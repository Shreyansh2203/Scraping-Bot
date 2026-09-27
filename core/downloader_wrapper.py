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
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

if importlib.util.find_spec("yt_dlp") is None:
    raise RuntimeError("yt-dlp is required. Install with: pip install yt-dlp")
if importlib.util.find_spec("gallery_dl") is None:
    raise RuntimeError("gallery-dl is required. Install with: pip install gallery-dl")

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
DEFAULT_MAX_FILE_SIZE_MB = 50
DEFAULT_MAX_DURATION_SECONDS = 600
BYTES_PER_MB = 1024 * 1024

# yt-dlp's own skip messages for a rejected download go to stdout, which -q silences, so
# the request would be retried three times and then handed to gallery-dl -- a fallback
# with no such bound, which would then download the same oversized file. Instead the
# bot asks yt-dlp to print the size and duration it already knows, on its own line,
# before it starts.
#
# The tag is what comes back on stdout: yt-dlp treats the leading "before_dl:" as the
# print-time selector and strips it, so the template and the pattern cannot share a
# prefix. The fields are JSON-encoded individually and pipe-delimited so a value can
# never be confused with a filename, and "NA" is how yt-dlp renders a field it did not
# report.
_BOUND_PROBE_TAG = "scraping-bot-bound:"
_BOUND_PROBE_TEMPLATE = f"before_dl:{_BOUND_PROBE_TAG}%(filesize)j|%(filesize_approx)j|%(duration)j"
_BOUND_PROBE_RE = re.compile(re.escape(_BOUND_PROBE_TAG) + r"([^|\n]*)\|([^|\n]*)\|([^|\n]*)")

# What a --max-filesize abort looks like from here. yt-dlp says "File is larger than
# max-filesize ... Aborting" on stdout, which -q silences, and then exits 0 having
# transferred nothing. The probe line still printed, so the download did start; the
# after_move prints did not, so nothing came back. Retrying that is pointless -- the
# condition is deterministic, not transient -- and gallery-dl is handed no bound at all.
_TRANSFER_REFUSED = (
    "Refusing to download: the extractor declined to transfer this file, which is what "
    "yt-dlp does when --max-filesize is exceeded"
)

logger = logging.getLogger("downloader")


def _probe_number(raw: str) -> Optional[int]:
    """Read one field of the bound probe, or None when yt-dlp did not report it."""
    raw = raw.strip()
    if not raw or raw == "NA":
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


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
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


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
        max_file_size_mb: int = DEFAULT_MAX_FILE_SIZE_MB,
        max_duration_seconds: int = DEFAULT_MAX_DURATION_SECONDS,
    ):
        self.output_dir = output_dir
        self.concurrent = concurrent
        self.min_file_size = min_file_size
        self.timeout = timeout
        self.subprocess_timeout = subprocess_timeout
        self.ffprobe_timeout = ffprobe_timeout
        self.max_file_size_mb = max_file_size_mb
        self.max_file_size_bytes = int(max_file_size_mb * BYTES_PER_MB)
        self.max_duration_seconds = max_duration_seconds
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
        async with self.semaphore:
            return await self._download_async(url, user_id)

    async def _download_async(self, url: str, user_id: int) -> DownloadResult:
        if not _is_safe_url(url):
            return DownloadResult(
                success=False, error=f"Refusing to fetch non-http(s) URL: {url[:200]!r}"
            )

        job_id = uuid.uuid4().hex[:12]
        job_dir = (self.output_dir / f"job_{job_id}").resolve()
        job_dir.mkdir(parents=True, exist_ok=True)

        max_retries = 2
        retry_delay = 1.0
        transient_errors = (TimeoutError, OSError, ConnectionError)
        last_error = ""

        # The extractor that is still running, if any, and whether the job directory has
        # to outlive this frame. Both exist so the finally below is the single place
        # that kills a child and deletes a directory: an except clause is skipped by
        # every BaseException the loop can raise at us, and CancelledError is one.
        live_proc: Optional[asyncio.subprocess.Process] = None
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
                    last_error = str(exc)
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
        target_dir = job_dir / "gallery_dl"
        target_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable,
            "-m",
            "gallery_dl",
            "--directory",
            str(target_dir),
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

        downloaded_files: list[Path] = []
        for root, _, files in os.walk(target_dir):
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                    if file_path.parent != target_dir:
                        dest = target_dir / file_path.name
                        counter = 1
                        while dest.exists():
                            dest = target_dir / f"{file_path.stem}_{counter}{file_path.suffix}"
                            counter += 1
                        shutil.move(str(file_path), str(dest))
                        downloaded_files.append(dest)
                    else:
                        downloaded_files.append(file_path)

        if not downloaded_files:
            return DownloadResult(success=False, error="gallery-dl returned no supported files")

        # The yt-dlp path rejects a file under min_file_size, so the fallback has to
        # apply the same floor: a post whose only download is a truncated stub is a
        # failed download, not a successful one. A post that mixes a stub with real
        # pages keeps the real ones.
        undersized = [
            path
            for path in downloaded_files
            if path.exists() and path.stat().st_size < self.min_file_size
        ]
        for path in undersized:
            path.unlink(missing_ok=True)
        downloaded_files = [path for path in downloaded_files if path not in undersized]

        if not downloaded_files:
            return DownloadResult(
                success=False,
                error=(
                    "File too small: every file gallery-dl returned was under "
                    f"{self.min_file_size} bytes"
                ),
            )

        total_size = sum(f.stat().st_size for f in downloaded_files if f.exists())

        # os.walk yields in filesystem order, which differs between NTFS and ext4. These
        # paths become the media group the user receives, so sort them rather than let
        # the ordering be a property of the filesystem the bot happens to run on.
        downloaded_files.sort(key=lambda p: p.name)

        return DownloadResult(
            success=True,
            file_paths=downloaded_files,
            size=total_size,
            verified=True,
            job_dir=job_dir,
        )

    def _bound_refusal(self, bound: Any) -> Optional[str]:
        """The user-facing reason to give up, when the extractor already said the media
        is over the limit, or None when it did not.

        Returning a reason here is what makes the refusal terminal: the caller does not
        retry a request that is going to be refused identically every time, and does not
        hand it to gallery-dl, which is not given either bound.
        """
        if not isinstance(bound, dict):
            return None
        size = bound.get("size")
        duration = bound.get("duration")
        if isinstance(size, int) and size > self.max_file_size_bytes:
            return (
                "Refusing to download: the file is larger than the "
                f"{self.max_file_size_mb} MB limit"
            )
        if isinstance(duration, int) and duration > self.max_duration_seconds:
            return (
                "Refusing to download: the media is longer than the "
                f"{self.max_duration_seconds}s limit"
            )
        return None

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
        result: dict[str, Any] = {"success": False, "bound": {"size": None, "duration": None}}

        # Lift the bound probe out of the stream before anything else looks at it, or it
        # is counted as one of the fields the success path reads positionally.
        lines: list[str] = []
        probe_seen = False
        for raw in output.split("\n"):
            probe = _BOUND_PROBE_RE.match(raw.strip())
            if probe is None:
                lines.append(raw)
                continue
            probe_seen = True
            size, approx, duration = (_probe_number(field) for field in probe.groups())
            known_size = next((v for v in (size, approx) if v is not None), None)
            known_duration = duration
            for key, value in (("size", known_size), ("duration", known_duration)):
                current = result["bound"][key]
                if value is not None and (current is None or value > current):
                    result["bound"][key] = value
        output = "\n".join(lines)

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

        if probe_seen and not result.get("success") and returncode == 0:
            # The probe printed, so a transfer was about to start, and no after_move
            # filepath followed, so nothing came back. That is the --max-filesize abort.
            result["transfer_refused"] = True

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
                **_subprocess_kwargs(),
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
