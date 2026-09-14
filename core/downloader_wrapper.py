from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

if importlib.util.find_spec("yt_dlp") is None:
    raise RuntimeError("yt-dlp is required. Install with: pip install yt-dlp")
if importlib.util.find_spec("gallery_dl") is None:
    raise RuntimeError("gallery-dl is required. Install with: pip install gallery-dl")

__version__ = "0.1.0"

SUPPORTED_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".webm",
    ".m4a",
    ".mp3",
    ".opus",
    ".mov",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}
DEFAULT_MIN_FILE_SIZE = 1024  # 1KB for images

logger = logging.getLogger("downloader")


@dataclass
class DownloadResult:
    success: bool
    file_paths: list[Path] = field(default_factory=list)
    size: int = 0
    resolution: Optional[str] = None
    format_id: Optional[str] = None
    error: Optional[str] = None
    verified: bool = False

    @property
    def file_path(self) -> Optional[Path]:
        return self.file_paths[0] if self.file_paths else None


class DownloaderWrapper:
    def __init__(
        self,
        output_dir: Path,
        state_file: Path,
        concurrent: int = 2,
        min_file_size: int = DEFAULT_MIN_FILE_SIZE,
        timeout: int = 30,
        subprocess_timeout: int = 180,
        ffprobe_timeout: int = 10,
    ):
        self.output_dir = output_dir
        self.state_file = state_file
        self.concurrent = concurrent
        self.min_file_size = min_file_size
        self.timeout = timeout
        self.subprocess_timeout = subprocess_timeout
        self.ffprobe_timeout = ffprobe_timeout
        self.semaphore = asyncio.Semaphore(concurrent)
        self._lock = threading.Lock()
        self._shutdown = threading.Event()
        self._state: dict[str, Any] = {"completed": {}, "failed": {}, "meta": {}}
        self._load_state()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _load_state(self) -> None:
        if not self.state_file.exists():
            return
        try:
            text = self.state_file.read_text(encoding="utf-8")
            self._state = json.loads(text)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("State file corrupted (%s), attempting partial recovery.", exc)
            try:
                text = self.state_file.read_text(encoding="utf-8")
                for i in range(len(text) - 1, -1, -1):
                    if text[i] == "}":
                        try:
                            self._state = json.loads(text[: i + 1])
                            logger.warning("Recovered partial state from %d bytes.", i + 1)
                            return
                        except json.JSONDecodeError:
                            continue
            except OSError:
                pass
            logger.warning("State file unrecoverable, starting fresh.")
            self._state = {"completed": {}, "failed": {}, "meta": {}}

    def is_completed(self, url: str) -> bool:
        key = self._normalize(url)
        with self._lock:
            return key in self._state.get("completed", {})

    def shutdown(self) -> None:
        self._shutdown.set()

    def mark_completed(self, url: str, result: DownloadResult) -> None:
        key = self._normalize(url)
        with self._lock:
            self._state["completed"][key] = {
                "files": [str(p.resolve()) for p in result.file_paths] if result.file_paths else [],
                "size": result.size,
                "resolution": result.resolution,
                "format_id": result.format_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._state.get("failed", {}).pop(key, None)
            state_snapshot = self._state.copy()

        self._save_state_snapshot(state_snapshot)

    def mark_failed(self, url: str, error: str) -> None:
        key = self._normalize(url)
        with self._lock:
            self._state.setdefault("failed", {})[key] = {
                "error": error,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            state_snapshot = self._state.copy()

        self._save_state_snapshot(state_snapshot)

    def _save_state_snapshot(self, state: dict[str, Any]) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.state_file.parent), prefix=".state_", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, str(self.state_file))
        except (OSError, TypeError, ValueError):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    @staticmethod
    def _normalize(url: str) -> str:
        url = url.strip()
        m = re.match(r"(https?://)([^/]+)(/.*)?", url, re.IGNORECASE)
        if m:
            scheme = m.group(1).lower()
            host = m.group(2).lower()
            if host.startswith("www."):
                host = host[4:]
            path = m.group(3) or ""
            url = f"{scheme}{host}{path}"
        return re.sub(r"/+$", "", url)

    async def download_url(self, url: str, user_id: int) -> DownloadResult:
        async with self.semaphore:
            return await asyncio.to_thread(self._download_sync, url, user_id)

    def _download_sync(self, url: str, user_id: int) -> DownloadResult:
        if self.is_completed(url):
            return DownloadResult(success=False, error="Already downloaded")

        cmd = self._build_command(url)
        output_dir = self.output_dir.resolve()

        max_retries = 2
        retry_delay = 1.0
        transient_errors = (TimeoutError, OSError, ConnectionError)

        last_error = ""
        for attempt in range(max_retries + 1):
            if self._shutdown.is_set():
                self.mark_failed(url, "Download cancelled by shutdown")
                return DownloadResult(success=False, error="Download cancelled by shutdown")
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    cwd=str(output_dir),
                    timeout=self.subprocess_timeout,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except transient_errors as exc:
                last_error = str(exc)
                if attempt < max_retries:
                    time.sleep(retry_delay * (2**attempt))
                    continue
                self.mark_failed(
                    url, f"Transient error after {max_retries + 1} attempts: {last_error}"
                )
                return DownloadResult(
                    success=False,
                    error=f"Transient error after {max_retries + 1} attempts: {last_error}",
                )
            except subprocess.TimeoutExpired:
                last_error = f"Timeout after {self.subprocess_timeout}s"
                if attempt < max_retries:
                    time.sleep(retry_delay * (2**attempt))
                    continue
                self.mark_failed(url, last_error)
                return DownloadResult(success=False, error=last_error)
            except Exception as exc:
                self.mark_failed(url, str(exc))
                return DownloadResult(success=False, error=str(exc))

            combined = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
            result = self._parse_output(combined, proc.returncode)

            if result.get("success") and result.get("file"):
                raw = Path(result["file"])
                file_path = raw if raw.is_absolute() else output_dir / raw
                if file_path.exists():
                    result["file"] = str(file_path)
                    result["size"] = file_path.stat().st_size
                    if not result.get("resolution"):
                        result["resolution"] = self._probe_resolution(
                            file_path, self.ffprobe_timeout
                        )
                else:
                    found = self._find_output_file(url, output_dir, result.get("file"))
                    if found:
                        result["file"] = str(found)
                        result["size"] = found.stat().st_size
                        if not result.get("resolution"):
                            result["resolution"] = self._probe_resolution(
                                found, self.ffprobe_timeout
                            )
                    else:
                        result["success"] = False
                        result["error"] = "Download completed but no output file found"

            if result.get("success") and result.get("file"):
                file_path = Path(result["file"])
                if not file_path.exists():
                    result["success"] = False
                    result["error"] = "File disappeared after download"
                elif file_path.stat().st_size < self.min_file_size:
                    size = file_path.stat().st_size
                    file_path.unlink(missing_ok=True)
                    result["success"] = False
                    result["error"] = f"File too small: {size} bytes"
                else:
                    dl_result = DownloadResult(
                        success=True,
                        file_paths=[file_path],
                        size=result.get("size", 0),
                        resolution=result.get("resolution"),
                        format_id=result.get("format_id"),
                        verified=True,
                    )
                    self.mark_completed(url, dl_result)
                    return dl_result

            error_msg = result.get("error", "Unknown error")

            # Fallback to gallery-dl if yt-dlp fails
            g_result = self._run_gallery_dl(url)
            if g_result.success:
                self.mark_completed(url, g_result)
                return g_result

            self.mark_failed(url, error_msg)
            return DownloadResult(success=False, error=error_msg)

        self.mark_failed(url, last_error or "Unknown error")
        return DownloadResult(success=False, error=last_error or "Unknown error")

    def _run_gallery_dl(self, url: str) -> DownloadResult:
        output_dir = self.output_dir.resolve()
        with tempfile.TemporaryDirectory(dir=output_dir) as temp_dir:
            cmd = [
                sys.executable,
                "-m",
                "gallery_dl",
                "--directory",
                temp_dir,
                "-q",
                url,
            ]
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    cwd=str(output_dir),
                    timeout=self.subprocess_timeout,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception as exc:
                return DownloadResult(success=False, error=f"gallery-dl error: {exc}")

            if proc.returncode != 0:
                return DownloadResult(
                    success=False, error=f"gallery-dl failed: {proc.stderr or proc.stdout}"
                )

            downloaded_files = []
            for root, _, files in os.walk(temp_dir):
                for file in files:
                    file_path = Path(root) / file
                    if file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                        dest = output_dir / file_path.name
                        counter = 1
                        while dest.exists():
                            dest = output_dir / f"{file_path.stem}_{counter}{file_path.suffix}"
                            counter += 1
                        shutil.move(str(file_path), str(dest))
                        downloaded_files.append(dest)

            if not downloaded_files:
                return DownloadResult(success=False, error="gallery-dl returned no supported files")

            total_size = sum(f.stat().st_size for f in downloaded_files if f.exists())

            return DownloadResult(
                success=True, file_paths=downloaded_files, size=total_size, verified=True
            )

    def _build_command(self, url: str) -> list[str]:
        has_ffmpeg = shutil.which("ffmpeg") is not None
        fmt = (
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
            if has_ffmpeg
            else "best"
        )
        sort = ["res", "fps", "tbr", "codec"]

        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            url,
            "--format",
            fmt,
            "--format-sort",
            ",".join(sort),
            "--prefer-free-formats",
            "--output",
            "%(title)s [%(id)s].%(ext)s",
            "--no-overwrites",
            "--continue",
            "--retries",
            "0",
            "--fragment-retries",
            "0",
            "--socket-timeout",
            str(self.timeout),
            "--print",
            "after_move:filepath",
            "--print",
            "after_move:filesize",
            "--print",
            "after_move:resolution",
            "--print",
            "after_move:format_id",
            "--newline",
            "--no-warnings",
            "-q",
        ]

        if has_ffmpeg:
            cmd.extend(["--merge-output-format", "mp4"])
            cmd.extend(["--embed-metadata", "--embed-thumbnail"])

        return cmd

    def _parse_output(self, output: str, returncode: int) -> dict[str, Any]:
        result: dict[str, Any] = {"success": False}

        if returncode == 0:
            lines = output.split("\n")
            prints = [
                line
                for line in lines
                if line.strip()
                and not line.startswith(
                    (
                        "[download]",
                        "[ExtractAudio]",
                        "[ffmpeg]",
                        "[Merger]",
                        "[info]",
                        "[error]",
                        "[warning]",
                    )
                )
            ]

            if len(prints) >= 4:
                result["file"] = "\n".join(prints[:-3]).strip()
                try:
                    result["size"] = int(prints[-3].strip())
                except (ValueError, IndexError):
                    pass
                result["resolution"] = prints[-2].strip()
                result["format_id"] = prints[-1].strip()
            elif len(prints) == 3:
                result["file"] = prints[0].strip()
                result["format_id"] = prints[2].strip()
                middle = prints[1].strip()
                try:
                    result["size"] = int(middle)
                except (ValueError, IndexError):
                    result["resolution"] = middle
            elif len(prints) == 2:
                result["file"] = prints[0].strip()
                try:
                    result["size"] = int(prints[1].strip())
                except (ValueError, IndexError):
                    result["resolution"] = prints[1].strip()
            elif prints:
                result["file"] = prints[-1].strip()

            if result.get("file"):
                cleaned = re.sub(r"\s+", " ", result["file"].replace("\n", " ")).strip()
                result["file"] = cleaned
                result["success"] = True
            else:
                result["error"] = "Download completed but no output file found"

        elif returncode == 1:
            error_lines = [
                line
                for line in output.split("\n")
                if line.strip() and not line.startswith("[download]")
            ]
            result["error"] = (error_lines[-1] if error_lines else "yt-dlp reported failure")[:200]
        else:
            error_lines = [
                line.strip()
                for line in output.split("\n")
                if line.strip()
                and not line.startswith(("[download]", "[ExtractAudio]", "[ffmpeg]", "WARNING"))
            ]
            result["error"] = (
                error_lines[-1] if error_lines else f"yt-dlp exited with code {returncode}"
            )[:200]

        return result

    def _find_output_file(
        self,
        url: str,
        output_dir: Optional[Path] = None,
        reported_filepath: Optional[str] = None,
        window: int = 300,
    ) -> Optional[Path]:
        if output_dir is None:
            output_dir = self.output_dir.resolve()

        def _mtime(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except OSError:
                return 0.0

        try:
            candidates = sorted(
                output_dir.iterdir(),
                key=lambda p: _mtime(p) if p.exists() else 0.0,
                reverse=True,
            )
        except OSError:
            return None

        now = time.time()

        ytdlp_id = None
        if reported_filepath:
            m = re.search(r"\[(\d{10,})\]", reported_filepath)
            if m:
                ytdlp_id = m.group(1)

        if ytdlp_id:
            matches = [
                p
                for p in candidates
                if p.exists() and p.suffix in SUPPORTED_EXTENSIONS and ytdlp_id in p.name
            ]
            if matches:
                return matches[0]

        url_id = None
        try:
            path = url.split("?")[0].rstrip("/")
            parts = path.split("/")
            if parts and parts[-1].isdigit():
                url_id = parts[-1]
        except Exception:
            pass

        if url_id:
            matches = [
                p
                for p in candidates
                if p.exists()
                and p.suffix in SUPPORTED_EXTENSIONS
                and url_id in p.name
                and now - _mtime(p) <= window * 2
            ]
            if matches:
                return matches[0]

        valid = [
            p
            for p in candidates
            if p.exists() and p.suffix in SUPPORTED_EXTENSIONS and now - _mtime(p) <= window
        ]
        if valid:
            return valid[0]
        return None

    @staticmethod
    def _probe_resolution(file_path: Path, ffprobe_timeout: int = 10) -> Optional[str]:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return None
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=width,height",
                    "-of",
                    "csv=s=x:p=0",
                    str(file_path),
                ],
                capture_output=True,
                text=True,
                timeout=ffprobe_timeout,
            )
            if result.returncode == 0:
                res = result.stdout.strip()
                if res and "x" in res:
                    return res
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        return None
