from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
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
    job_dir: Optional[Path] = None

    @property
    def file_path(self) -> Optional[Path]:
        return self.file_paths[0] if self.file_paths else None

    def cleanup(self) -> None:
        """Remove job directory and all downloaded files."""
        if self.job_dir and self.job_dir.exists():
            shutil.rmtree(self.job_dir, ignore_errors=True)
        for p in self.file_paths:
            p.unlink(missing_ok=True)


class DownloaderWrapper:
    def __init__(
        self,
        output_dir: Path,
        concurrent: int = 2,
        min_file_size: int = DEFAULT_MIN_FILE_SIZE,
        timeout: int = 30,
        subprocess_timeout: int = 180,
        ffprobe_timeout: int = 10,
    ):
        self.output_dir = output_dir
        self.concurrent = concurrent
        self.min_file_size = min_file_size
        self.timeout = timeout
        self.subprocess_timeout = subprocess_timeout
        self.ffprobe_timeout = ffprobe_timeout
        self.semaphore = asyncio.Semaphore(concurrent)
        self._shutdown = asyncio.Event()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def shutdown(self) -> None:
        self._shutdown.set()

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
            return await self._download_async(url, user_id)

    async def _download_async(self, url: str, user_id: int) -> DownloadResult:
        job_id = uuid.uuid4().hex[:12]
        job_dir = (self.output_dir / f"job_{job_id}").resolve()
        job_dir.mkdir(parents=True, exist_ok=True)

        max_retries = 2
        retry_delay = 1.0
        transient_errors = (TimeoutError, OSError, ConnectionError)
        last_error = ""

        try:
            for attempt in range(max_retries + 1):
                if self._shutdown.is_set():
                    shutil.rmtree(job_dir, ignore_errors=True)
                    return DownloadResult(success=False, error="Download cancelled by shutdown")

                cmd = self._build_command(url)
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=str(job_dir),
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    try:
                        stdout_bytes, stderr_bytes = await asyncio.wait_for(
                            proc.communicate(), timeout=self.subprocess_timeout
                        )
                    except TimeoutError:
                        proc.kill()
                        await proc.wait()
                        raise

                    stdout = stdout_bytes.decode(errors="replace")
                    stderr = stderr_bytes.decode(errors="replace")
                    returncode = proc.returncode or 0

                except transient_errors as exc:
                    last_error = str(exc)
                    if attempt < max_retries:
                        await asyncio.sleep(retry_delay * (2**attempt))
                        continue
                    shutil.rmtree(job_dir, ignore_errors=True)
                    return DownloadResult(
                        success=False,
                        error=f"Transient error after {max_retries + 1} attempts: {last_error}",
                    )
                except Exception as exc:
                    shutil.rmtree(job_dir, ignore_errors=True)
                    return DownloadResult(success=False, error=str(exc))

                combined = stdout + ("\n" + stderr if stderr else "")
                result = self._parse_output(combined, returncode)

                if result.get("success") and result.get("file"):
                    raw = Path(result["file"])
                    file_path = raw if raw.is_absolute() else job_dir / raw
                    if not file_path.exists():
                        found = self._find_output_file(url, job_dir, result.get("file"))
                        if found:
                            file_path = found
                        else:
                            result["success"] = False
                            result["error"] = "Download completed but no output file found"

                    if file_path.exists():
                        result["file"] = str(file_path)
                        result["size"] = file_path.stat().st_size
                        if not result.get("resolution"):
                            result["resolution"] = await self._probe_resolution(
                                file_path, self.ffprobe_timeout
                            )

                        if result["size"] < self.min_file_size:
                            file_path.unlink(missing_ok=True)
                            result["success"] = False
                            result["error"] = f"File too small: {result['size']} bytes"
                        else:
                            return DownloadResult(
                                success=True,
                                file_paths=[file_path],
                                size=result["size"],
                                resolution=result.get("resolution"),
                                format_id=result.get("format_id"),
                                verified=True,
                                job_dir=job_dir,
                            )

                last_error = result.get("error", "Unknown error")
                if attempt < max_retries:
                    await asyncio.sleep(retry_delay * (2**attempt))
                    continue

            # Fallback to gallery-dl if yt-dlp attempts fail
            g_result = await self._run_gallery_dl(url, job_dir)
            if g_result.success:
                g_result.job_dir = job_dir
                return g_result

            shutil.rmtree(job_dir, ignore_errors=True)
            return DownloadResult(
                success=False, error=last_error or g_result.error or "Download failed"
            )

        except Exception as exc:
            shutil.rmtree(job_dir, ignore_errors=True)
            return DownloadResult(success=False, error=str(exc))

    async def _run_gallery_dl(self, url: str, job_dir: Path) -> DownloadResult:
        cmd = [
            sys.executable,
            "-m",
            "gallery_dl",
            "--directory",
            str(job_dir),
            "-q",
            url,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(job_dir),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=self.subprocess_timeout
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                raise

            returncode = proc.returncode or 0
            stderr = stderr_bytes.decode(errors="replace")
            stdout = stdout_bytes.decode(errors="replace")

        except Exception as exc:
            return DownloadResult(success=False, error=f"gallery-dl error: {exc}")

        if returncode != 0:
            return DownloadResult(success=False, error=f"gallery-dl failed: {stderr or stdout}")

        downloaded_files: list[Path] = []
        for root, _, files in os.walk(job_dir):
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                    if file_path.parent != job_dir:
                        dest = job_dir / file_path.name
                        counter = 1
                        while dest.exists():
                            dest = job_dir / f"{file_path.stem}_{counter}{file_path.suffix}"
                            counter += 1
                        shutil.move(str(file_path), str(dest))
                        downloaded_files.append(dest)
                    else:
                        downloaded_files.append(file_path)

        if not downloaded_files:
            return DownloadResult(success=False, error="gallery-dl returned no supported files")

        total_size = sum(f.stat().st_size for f in downloaded_files if f.exists())

        return DownloadResult(
            success=True,
            file_paths=downloaded_files,
            size=total_size,
            verified=True,
            job_dir=job_dir,
        )

    def _build_command(self, url: str) -> list[str]:
        has_ffmpeg = shutil.which("ffmpeg") is not None
        fmt = (
            "bestvideo*[ext=mp4]+bestaudio[ext=m4a]/bestvideo*+bestaudio/best"
            if has_ffmpeg
            else "best"
        )

        sort = ["res", "size", "fps", "tbr", "codec"]

        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            url,
            "--extractor-args",
            "twitter:api=syndication",
            "--format",
            fmt,
            "--format-sort",
            ",".join(sort),
            "--prefer-free-formats",
            "--output",
            f"%(title)s [%(id)s]_{int(time.time())}.%(ext)s",
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
    async def _probe_resolution(file_path: Path, ffprobe_timeout: int = 10) -> Optional[str]:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
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
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                stdout_bytes, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=ffprobe_timeout
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                raise

            if proc.returncode == 0:
                res = stdout_bytes.decode(errors="replace").strip()
                if res and "x" in res:
                    return res
        except Exception:
            pass
        return None
