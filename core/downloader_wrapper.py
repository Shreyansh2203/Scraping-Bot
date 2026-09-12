from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import yt_dlp
except ImportError:
    raise RuntimeError("yt-dlp is required. Install with: pip install yt-dlp")

__version__ = "0.1.0"

SUPPORTED_EXTENSIONS = {".mp4", ".mkv", ".webm", ".m4a", ".mp3", ".opus", ".mov"}
DEFAULT_MIN_FILE_SIZE = 10240  # 10KB


logger = logging.getLogger("downloader")


@dataclass
class DownloadResult:
    success: bool
    file_path: Optional[Path] = None
    size: int = 0
    resolution: Optional[str] = None
    format_id: Optional[str] = None
    error: Optional[str] = None
    verified: bool = False


class DownloaderWrapper:
    def __init__(
        self,
        output_dir: Path,
        state_file: Path,
        concurrent: int = 2,
        min_file_size: int = DEFAULT_MIN_FILE_SIZE,
        timeout: int = 30,
        subprocess_timeout: int = 180,
    ):
        self.output_dir = output_dir
        self.state_file = state_file
        self.concurrent = concurrent
        self.min_file_size = min_file_size
        self.timeout = timeout
        self.subprocess_timeout = subprocess_timeout
        self.semaphore = asyncio.Semaphore(concurrent)
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
            logger.warning("State file corrupted (%s), starting fresh.", exc)
            self._state = {"completed": {}, "failed": {}, "meta": {}}

    def _save_state(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.state_file.parent), prefix=".state_", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, str(self.state_file))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def is_completed(self, url: str) -> bool:
        key = self._normalize(url)
        return key in self._state.get("completed", {})

    def mark_completed(self, url: str, result: DownloadResult) -> None:
        key = self._normalize(url)
        self._state["completed"][key] = {
            "file": str(result.file_path.resolve()) if result.file_path else None,
            "size": result.size,
            "resolution": result.resolution,
            "format_id": result.format_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._state.get("failed", {}).pop(key, None)
        self._save_state()

    def mark_failed(self, url: str, error: str) -> None:
        key = self._normalize(url)
        self._state.setdefault("failed", {})[key] = {
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._save_state()

    @staticmethod
    def _normalize(url: str) -> str:
        url = url.strip()
        m = re.match(r"(https?://)([^/]+)(/.*)?", url, re.IGNORECASE)
        if m:
            scheme = m.group(1).lower()
            host = m.group(2).lower()
            path = m.group(3) or ""
            url = f"{scheme}{host}{path}"
        return re.sub(r"/+$", "", url)

    async def download_url(self, url: str, user_id: int) -> DownloadResult:
        async with self.semaphore:
            return await asyncio.to_thread(self._download_sync, url, user_id)

    def _download_sync(self, url: str, user_id: int) -> DownloadResult:
        if self.is_completed(url):
            return DownloadResult(success=True, error="Already downloaded")

        cmd = self._build_command(url)
        output_dir = self.output_dir.resolve()

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(output_dir),
                timeout=self.subprocess_timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            self.mark_failed(url, f"Timeout after {self.subprocess_timeout}s")
            return DownloadResult(success=False, error=f"Timeout after {self.subprocess_timeout}s")
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
                    result["resolution"] = self._probe_resolution(file_path)
            else:
                found = self._find_output_file(url, output_dir, result.get("file"))
                if found:
                    result["file"] = str(found)
                    result["size"] = found.stat().st_size
                    if not result.get("resolution"):
                        result["resolution"] = self._probe_resolution(found)
                else:
                    result["success"] = False
                    result["error"] = "Download completed but no output file found"

        if result.get("success") and result.get("file"):
            file_path = Path(result["file"])
            if not file_path.exists():
                result["success"] = False
                result["error"] = "File disappeared after download"
            elif file_path.stat().st_size < self.min_file_size:
                file_path.unlink(missing_ok=True)
                result["success"] = False
                result["error"] = f"File too small: {file_path.stat().st_size} bytes"
            else:
                dl_result = DownloadResult(
                    success=True,
                    file_path=file_path,
                    size=result.get("size", 0),
                    resolution=result.get("resolution"),
                    format_id=result.get("format_id"),
                    verified=True,
                )
                self.mark_completed(url, dl_result)
                return dl_result

        error_msg = result.get("error", "Unknown error")
        self.mark_failed(url, error_msg)
        return DownloadResult(success=False, error=error_msg)

    def _build_command(self, url: str) -> list[str]:
        has_ffmpeg = shutil.which("ffmpeg") is not None
        fmt = (
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
            if has_ffmpeg else "best"
        )
        sort = ["res", "fps", "tbr", "codec"]

        cmd = [
            sys.executable, "-m", "yt_dlp",
            url,
            "--format", fmt,
            "--format-sort", ",".join(sort),
            "--prefer-free-formats",
            "--output", "%(title)s [%(id)s].%(ext)s",
            "--no-overwrites",
            "--continue",
            "--retries", "0",
            "--fragment-retries", "0",
            "--socket-timeout", str(self.timeout),
            "--print", "after_move:filepath",
            "--print", "after_move:filesize",
            "--print", "after_move:resolution",
            "--print", "after_move:format_id",
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
            prints = [l for l in lines if l and not l.startswith("[")]

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
                try:
                    result["size"] = int(prints[1].strip())
                except (ValueError, IndexError):
                    result["resolution"] = prints[1].strip()
                result["format_id"] = prints[2].strip()
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
                l for l in output.split("\n") if l.strip() and not l.startswith("[download]")
            ]
            result["error"] = (error_lines[-1] if error_lines else "yt-dlp reported failure")[:200]
        else:
            error_lines = [
                l.strip()
                for l in output.split("\n")
                if l.strip()
                and not l.startswith(("[download]", "[ExtractAudio]", "[ffmpeg]", "WARNING"))
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

        try:
            candidates = sorted(
                output_dir.iterdir(),
                key=lambda p: p.stat().st_mtime if p.exists() else 0,
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
                p for p in candidates
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
                p for p in candidates
                if p.exists()
                and p.suffix in SUPPORTED_EXTENSIONS
                and url_id in p.name
                and now - p.stat().st_mtime <= window * 2
            ]
            if matches:
                return matches[0]

        valid = [
            p for p in candidates
            if p.exists() and p.suffix in SUPPORTED_EXTENSIONS and now - p.stat().st_mtime <= window
        ]
        if valid:
            return valid[0]
        return None

    @staticmethod
    def _probe_resolution(file_path: Path) -> Optional[str]:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return None
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=width,height",
                    "-of", "csv=s=x:p=0",
                    str(file_path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                res = result.stdout.strip()
                if res and "x" in res:
                    return res
        except Exception:
            pass
        return None
