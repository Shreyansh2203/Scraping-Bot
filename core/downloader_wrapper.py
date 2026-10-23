from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from core.bounds import (
    _BOUND_PROBE_TEMPLATE,
    _TRANSFER_REFUSED,
    DEFAULT_MAX_DURATION_SECONDS,
    DEFAULT_MAX_FILE_SIZE_MB,
    DEFAULT_MIN_FILE_SIZE,
    SUPPORTED_EXTENSIONS,
    bound_refusal,
)
from core.output_parser import (
    DownloadResult,
)
from core.output_parser import (
    _find_output_file as _find_output_file_impl,
)
from core.output_parser import (
    _parse_output as _parse_output_impl,
)
from core.output_parser import (
    _probe_resolution as _probe_resolution_impl,
)

if importlib.util.find_spec("yt_dlp") is None:
    raise RuntimeError("yt-dlp is required. Install with: pip install yt-dlp")
if importlib.util.find_spec("gallery_dl") is None:
    raise RuntimeError("gallery-dl is required. Install with: pip install gallery-dl")

logger = logging.getLogger("downloader")


def _subprocess_kwargs() -> dict[str, Any]:
    """Isolate the child in its own process group so the whole tree can be killed."""
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        return {"creationflags": flags}
    return {"start_new_session": True}


async def _terminate_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill the downloader and the ffmpeg processes it spawned, then reap it."""
    if sys.platform == "win32":
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/F",
                "/T",
                "/PID",
                str(proc.pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
        except OSError:
            proc.kill()
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except OSError:
            proc.kill()
    await proc.wait()


def _is_safe_url(url: str) -> bool:
    """Untrusted user input must never reach the child process as a flag or a shell word."""
    if not url or any(char.isspace() for char in url):
        return False
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


class DownloaderWrapper:
    def __init__(
        self,
        output_dir: Path,
        concurrent: int = 2,
        min_file_size: int = DEFAULT_MIN_FILE_SIZE,
        timeout: int = 30,
        subprocess_timeout: int = 180,
        ffprobe_timeout: int = 10,
        max_file_size_mb: int = DEFAULT_MAX_FILE_SIZE_MB,
        max_duration_seconds: int = DEFAULT_MAX_DURATION_SECONDS,
        max_disk_usage_percent: int = 0,
    ):
        self.output_dir = output_dir
        self.concurrent = concurrent
        self.min_file_size = min_file_size
        self.timeout = timeout
        self.subprocess_timeout = subprocess_timeout
        self.ffprobe_timeout = ffprobe_timeout
        self.max_file_size_mb = max_file_size_mb
        self.max_file_size_bytes = int(max_file_size_mb * 1024 * 1024)
        self.max_duration_seconds = max_duration_seconds
        self.max_disk_usage_percent = max_disk_usage_percent
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

    def _check_disk_space(self) -> str | None:
        """Refuse downloads when the download partition is over the usage ceiling.

        Returns a refusal message or None when there is headroom. A MAX_DISK_USAGE_PERCENT
        of 0 disables the guard.
        """
        if self.max_disk_usage_percent <= 0:
            return None
        try:
            total, used, _ = shutil.disk_usage(self.output_dir)
        except OSError:
            return None
        if total == 0:
            return None
        usage_percent = used / total * 100
        if usage_percent >= self.max_disk_usage_percent:
            return (
                f"Download refused: disk usage at {usage_percent:.0f}% exceeds the "
                f"{self.max_disk_usage_percent}% limit"
            )
        return None

    async def download_url(self, url: str, user_id: int) -> DownloadResult:
        """Run one download, refusing outright when every slot is already taken.

        ``asyncio.Semaphore`` queues, and a request makes up to three ``yt-dlp``
        attempts plus one ``gallery-dl`` attempt, each bounded by ``subprocess_timeout``.
        On Render that timeout is 300 s, so one unlucky link can hold a slot for twenty
        minutes. Two of them park both slots and everyone else waits in a queue that
        grows without a timeout of its own. Turning the wait into an immediate answer
        costs the caller a retry and costs the bot its monopolisation.

        There is no await between the ``locked()`` check and the acquire below:
        ``Semaphore.acquire`` decrements and returns without yielding when the
        semaphore is free, so the check cannot be raced by another task.
        """
        if self.semaphore.locked():
            return DownloadResult(
                success=False,
                error=(
                    f"All {self.concurrent} download slots are busy; try again in a "
                    "moment rather than queueing behind the current requests"
                ),
            )

        disk_refusal = self._check_disk_space()
        if disk_refusal:
            return DownloadResult(success=False, error=disk_refusal)

        async with self.semaphore:
            return await self._download_async(url, user_id)

    async def _download_async(self, url: str, user_id: int) -> DownloadResult:
        if not _is_safe_url(url):
            return DownloadResult(
                success=False, error=f"Refusing to fetch non-http(s) URL: {url[:200]!r}"
            )

        import uuid

        job_id = uuid.uuid4().hex[:12]
        job_dir = (self.output_dir / f"job_{job_id}").resolve()
        job_dir.mkdir(parents=True, exist_ok=True)

        max_retries = 2
        retry_delay = 1.0
        transient_errors = (TimeoutError, OSError, ConnectionError)
        last_error = ""

        live_proc: asyncio.subprocess.Process | None = None
        keep_job_dir = False

        try:
            for attempt in range(max_retries + 1):
                if self._shutdown.is_set():
                    return DownloadResult(success=False, error="Download cancelled by shutdown")

                cmd = self._build_command(url)
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=str(job_dir),
                        **_subprocess_kwargs(),
                    )
                    live_proc = proc
                    try:
                        stdout_bytes, stderr_bytes = await asyncio.wait_for(
                            proc.communicate(), timeout=self.subprocess_timeout
                        )
                    except TimeoutError:
                        await _terminate_tree(proc)
                        raise

                    stdout = stdout_bytes.decode(errors="replace")
                    stderr = stderr_bytes.decode(errors="replace")
                    returncode = proc.returncode or 0

                except transient_errors as exc:
                    # A bare TimeoutError has an empty str(), which left the user
                    # looking at "Transient error after 4 attempts: " with nothing
                    # after the colon. The exception name says what happened.
                    last_error = str(exc) or type(exc).__name__
                    if attempt < max_retries:
                        await asyncio.sleep(retry_delay * (2**attempt))
                        continue
                    return DownloadResult(
                        success=False,
                        error=f"Transient error after {max_retries + 1} attempts: {last_error}",
                    )
                except Exception as exc:
                    return DownloadResult(success=False, error=str(exc))

                combined = stdout + ("\n" + stderr if stderr else "")
                result = self._parse_output(combined, returncode)

                if not result.get("success"):
                    # A failed attempt is not the place for the size verdict: a file that
                    # did download stays on the success path, where the handler's
                    # post-download MAX_FILE_SIZE_MB check still reports it to the user.
                    refused = self._bound_refusal(result.get("bound"))
                    if refused is None and result.get("transfer_refused"):
                        refused = _TRANSFER_REFUSED
                    if refused:
                        return DownloadResult(success=False, error=refused)

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
                            keep_job_dir = True
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
                keep_job_dir = True
                return g_result

            return DownloadResult(
                success=False, error=last_error or g_result.error or "Download failed"
            )

        except Exception as exc:
            return DownloadResult(success=False, error=str(exc))

        finally:
            # An extractor that is still running has to die before the directory goes:
            # on Windows the open handle keeps rmtree from deleting the partial file, and
            # on POSIX the ffmpeg it spawned keeps writing to a path that no longer means
            # anything. returncode is only set once the child has been reaped, so a
            # process that finished normally -- or was already killed by the timeout
            # handler above -- is left alone.
            if live_proc is not None and live_proc.returncode is None:
                try:
                    await _terminate_tree(live_proc)
                except Exception:
                    logger.warning("Could not terminate the extractor process tree", exc_info=True)
            if not keep_job_dir:
                shutil.rmtree(job_dir, ignore_errors=True)

    async def _run_gallery_dl(self, url: str, job_dir: Path) -> DownloadResult:
        from .output_parser import gallery_dl_collect_files

        target_dir = job_dir / "gallery_dl"
        target_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable,
            "-m",
            "gallery_dl",
            "--directory",
            str(target_dir),
            # The same byte ceiling the yt-dlp path gets from --max-filesize. Without
            # it, a link that fails yt-dlp three times and then resolves to a large
            # gallery-dl target writes to disk until subprocess_timeout fires, and the
            # size floor in bot/handlers/download.py only runs once the bytes are
            # already there. gallery-dl reads a plain byte count here, like yt-dlp.
            "--filesize-max",
            str(self.max_file_size_bytes),
            "-q",
            url,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(target_dir),
                **_subprocess_kwargs(),
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=self.subprocess_timeout
                )
            except TimeoutError:
                await _terminate_tree(proc)
                raise

            returncode = proc.returncode or 0
            stderr = stderr_bytes.decode(errors="replace")
            stdout = stdout_bytes.decode(errors="replace")

        except Exception as exc:
            return DownloadResult(success=False, error=f"gallery-dl error: {exc}")

        if returncode != 0:
            return DownloadResult(success=False, error=f"gallery-dl failed: {stderr or stdout}")

        downloaded_files, total_size, had_any_supported = gallery_dl_collect_files(
            target_dir, self.min_file_size
        )

        if not downloaded_files:
            if had_any_supported:
                return DownloadResult(
                    success=False,
                    error=(
                        "File too small: every file gallery-dl returned was under "
                        f"{self.min_file_size} bytes"
                    ),
                )
            return DownloadResult(success=False, error="gallery-dl returned no supported files")

        return DownloadResult(
            success=True,
            file_paths=downloaded_files,
            size=total_size,
            verified=True,
            job_dir=job_dir,
        )

    def _bound_refusal(self, bound: object) -> str | None:
        return bound_refusal(bound, self.max_file_size_bytes, self.max_duration_seconds)

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
            # The byte ceiling. --max-filesize aborts the transfer as soon as the
            # response advertises more than this, which is the case the size floor in
            # bot/handlers/download.py cannot help with: it only runs once the file is
            # already on disk, so without this a multi-gigabyte 4K stream writes until
            # subprocess_timeout fires.
            "--max-filesize",
            str(self.max_file_size_bytes),
            "--print",
            _BOUND_PROBE_TEMPLATE,
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
        return _parse_output_impl(
            output,
            returncode,
            self.max_file_size_bytes,
            self.max_duration_seconds,
        )

    def _find_output_file(
        self,
        url: str,
        output_dir: Path | None = None,
        reported_filepath: str | None = None,
        window: int = 300,
    ) -> Optional[Path]:
        return _find_output_file_impl(
            url,
            output_dir=output_dir,
            reported_filepath=reported_filepath,
            window=window,
            default_output_dir=self.output_dir,
        )

    @staticmethod
    async def _probe_resolution(file_path: Path, ffprobe_timeout: int = 10) -> Optional[str]:
        return await _probe_resolution_impl(file_path, ffprobe_timeout)


__all__ = [
    "SUPPORTED_EXTENSIONS",
    "DownloaderWrapper",
    "DownloadResult",
    "_is_safe_url",
    "_subprocess_kwargs",
    "_terminate_tree",
]
