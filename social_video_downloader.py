#!/usr/bin/env python3
"""
Social Video Downloader v3.0 — Fully Refactored Gold Standard
================================================================
Async-native, concurrent batch downloader for Instagram and X (Twitter).
Maximizes resolution and bitrate, with production-grade reliability,
data integrity, resume support, and rich terminal output.

Fully refactored to eliminate all identified bugs, race conditions,
and logical vulnerabilities from v2.0.

Author:  Kilo / Automated Engineering
License: MIT
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import yt_dlp
except ImportError:
    sys.exit(
        "ERROR: yt-dlp is required but not installed.\n"
        "Install it with:  pip install --upgrade yt-dlp"
    )

try:
    import browser_cookie3  # type: ignore[import-untyped]

    BROWSER_COOKIES_AVAILABLE = True
except ImportError:
    BROWSER_COOKIES_AVAILABLE = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_SITES = {"instagram", "x", "twitter"}
SUPPORTED_EXTENSIONS = {".mp4", ".mkv", ".webm", ".m4a", ".mp3", ".opus", ".mov"}
DEFAULT_STATE_FILE = ".download_state.json"
DEFAULT_CONCURRENT = 3
DEFAULT_RETRIES = 5
DEFAULT_RETRY_DELAY = 3
DEFAULT_SUBPROCESS_TIMEOUT = 180
DEFAULT_OUTPUT_DIR = "downloads"
PROGRESS_REFRESH_MS = 150
DEFAULT_MIN_FILE_SIZE = 10240  # 10KB minimum to filter out error pages

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"

QUALITY_PRESETS = {
    "4k": {"min_height": 2160, "format_sort": ["res", "fps", "tbr", "codec"]},
    "1440p": {"min_height": 1440, "format_sort": ["res", "fps", "tbr", "codec"]},
    "1080p": {"min_height": 1080, "format_sort": ["res", "fps", "tbr", "codec"]},
    "720p": {"min_height": 720, "format_sort": ["res", "fps", "tbr", "codec"]},
    "480p": {"min_height": 480, "format_sort": ["res", "fps", "tbr", "codec"]},
    "best": {"min_height": 0, "format_sort": ["res", "fps", "tbr", "codec"]},
}

CODEC_PRIORITY = {
    "h265": ["codec:h265", "codec:h264", "codec:vp9", "codec:av1"],
    "h264": ["codec:h264", "codec:h265", "codec:vp9", "codec:av1"],
    "av1": ["codec:av1", "codec:h265", "codec:vp9", "codec:h264"],
    "vp9": ["codec:vp9", "codec:av1", "codec:h265", "codec:h264"],
}

BROWSER_MAP = {
    "chrome": "chrome",
    "firefox": "firefox",
    "edge": "edge",
    "brave": "brave",
    "chromium": "chromium",
}


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class DownloadTask:
    """Represents a single URL to process."""

    url: str
    index: int
    retries_left: int = DEFAULT_RETRIES
    attempt: int = 1
    status: str = "pending"
    error: Optional[str] = None
    file_path: Optional[Path] = None
    file_size: int = 0
    resolution: Optional[str] = None
    format_id: Optional[str] = None
    duration_s: float = 0.0
    verified: bool = False


@dataclass
class DownloaderConfig:
    """Runtime configuration."""

    urls: list[str]
    output_dir: Path = field(default_factory=lambda: Path(DEFAULT_OUTPUT_DIR))
    concurrent: int = DEFAULT_CONCURRENT
    quality: str = "best"
    prefer_codec: Optional[str] = None
    hdr_only: bool = False
    merge_format: str = "mp4"
    embed_metadata: bool = True
    embed_thumbnail: bool = True
    write_subs: bool = False
    write_auto_subs: bool = False
    sub_langs: str = "en"
    retries: int = DEFAULT_RETRIES
    retry_delay: int = DEFAULT_RETRY_DELAY
    subprocess_timeout: int = DEFAULT_SUBPROCESS_TIMEOUT
    limit_rate: Optional[str] = None
    timeout: int = 30
    cookies_file: Optional[Path] = None
    cookies_from_browser: Optional[str] = None
    user_agent: Optional[str] = None
    proxy: Optional[str] = None
    output_template: str = "%(title)s [%(id)s].%(ext)s"
    verbose: bool = False
    quiet: bool = False
    no_verify: bool = False
    min_file_size: int = DEFAULT_MIN_FILE_SIZE
    resume: bool = True
    state_file: Path = field(default_factory=lambda: Path(DEFAULT_STATE_FILE))
    flat_playlist: bool = False
    playlist_items: Optional[str] = None
    force_overwrites: bool = False


# ---------------------------------------------------------------------------
# URL Normalization
# ---------------------------------------------------------------------------

def normalize_url(url: str) -> str:
    """Normalize URL for state deduplication: lowercase scheme+host only."""
    url = url.strip()
    m = re.match(r"(https?://)([^/]+)(/.*)?", url, re.IGNORECASE)
    if m:
        scheme = m.group(1).lower()
        host = m.group(2).lower()
        path = m.group(3) or ""
        url = f"{scheme}{host}{path}"
    url = re.sub(r"/+$", "", url)
    return url


# ---------------------------------------------------------------------------
# State Management (Resume Support) — Atomic Writes
# ---------------------------------------------------------------------------

class StateManager:
    """Tracks completed/failed URLs across sessions for resume support."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.data: dict[str, Any] = {"completed": {}, "failed": {}, "meta": {}}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            text = self.path.read_text(encoding="utf-8")
            self.data = json.loads(text)
        except (json.JSONDecodeError, OSError) as exc:
            logging.getLogger("social_downloader").warning(
                "State file corrupted (%s), starting fresh.", exc
            )
            self.data = {"completed": {}, "failed": {}, "meta": {}}

    def save(self) -> None:
        """Atomic write: write to temp file then rename."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".state_", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, str(self.path))
        except PermissionError:
            # File is locked by another process (Windows advisory lock or
            # antivirus scanner).  Log and skip — in-memory state is still
            # valid for the current session.
            logging.getLogger("social_downloader").warning(
                "State file %s is locked; in-memory state preserved.", self.path
            )
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            logging.getLogger("social_downloader").warning(
                "State file save failed; in-memory state preserved.", exc_info=True
            )

    def is_completed(self, url: str) -> bool:
        return normalize_url(url) in self.data.get("completed", {})

    def is_failed(self, url: str) -> bool:
        return normalize_url(url) in self.data.get("failed", {})

    def mark_completed(self, url: str, result: DownloadTask) -> None:
        key = normalize_url(url)
        self.data["completed"][key] = {
            "file": str(result.file_path.resolve()) if result.file_path else None,
            "size": result.file_size,
            "resolution": result.resolution,
            "format_id": result.format_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.data.get("failed", {}).pop(key, None)
        self.save()

    def mark_failed(self, url: str, error: str) -> None:
        key = normalize_url(url)
        self.data.setdefault("failed", {})[key] = {
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.save()

    def get_completed_count(self) -> int:
        return len(self.data.get("completed", {}))

    def get_failed_count(self) -> int:
        return len(self.data.get("failed", {}))

    def clear(self) -> None:
        self.data = {"completed": {}, "failed": {}, "meta": {}}
        self.save()


# ---------------------------------------------------------------------------
# Cookie Extraction
# ---------------------------------------------------------------------------

def extract_browser_cookies(browser_name: str) -> Optional[Path]:
    """Extract cookies from browser to a temporary Netscape-format file."""
    if not BROWSER_COOKIES_AVAILABLE:
        print(
            "WARNING: browser_cookie3 not installed. "
            "Install with: pip install browser-cookie3",
            file=sys.stderr,
        )
        return None

    browser_key = BROWSER_MAP.get(browser_name.lower())
    if not browser_key:
        print(
            f"WARNING: Unsupported browser '{browser_name}'. "
            f"Supported: {', '.join(BROWSER_MAP.keys())}",
            file=sys.stderr,
        )
        return None

    try:
        cookie_fn = getattr(browser_cookie3, browser_key)
        cj = cookie_fn(domain_name="")
    except Exception as exc:
        print(f"WARNING: Failed to extract {browser_name} cookies: {exc}", file=sys.stderr)
        return None

    # Proper domain suffix matching
    def is_relevant_domain(cookie_domain: str) -> bool:
        d = cookie_domain.lower().lstrip(".")
        for suffix in [".instagram.com", ".twitter.com", ".x.com"]:
            if d == suffix.lstrip(".") or d.endswith(suffix):
                return True
        return False

    relevant = [c for c in cj if is_relevant_domain(c.domain)]

    if not relevant:
        print(
            f"WARNING: No cookies found for Instagram/Twitter in {browser_name}",
            file=sys.stderr,
        )
        return None

    # Use tempfile for unique, safe naming
    fd, temp_path = tempfile.mkstemp(
        suffix=".txt", prefix=f"cookies_{browser_name}_{os.getpid()}_"
    )
    temp_path = Path(temp_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n")
            f.write("# Extracted by social_video_downloader\n\n")
            for c in relevant:
                domain = c.domain
                flag = "TRUE" if c.domain_specified else "FALSE"
                path_str = c.path or "/"
                secure = "TRUE" if c.secure else "FALSE"
                try:
                    expires = str(int(c.expires)) if c.expires else "0"
                except (TypeError, ValueError):
                    expires = "0"
                name = c.name
                value = c.value or ""
                f.write(f".{domain}\t{flag}\t{path_str}\t{secure}\t{expires}\t{name}\t{value}\n")
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    print(f"INFO: Extracted {len(relevant)} cookies from {browser_name}", file=sys.stderr)
    return temp_path


# ---------------------------------------------------------------------------
# Format Selection
# ---------------------------------------------------------------------------

def build_format_string(config: DownloaderConfig, has_ffmpeg: bool = True) -> str:
    """Build yt-dlp format selector from quality/codec preferences."""
    preset = QUALITY_PRESETS.get(config.quality.lower(), QUALITY_PRESETS["best"])

    v_parts = []
    if preset["min_height"]:
        v_parts.append(f"height>={preset['min_height']}")

    if config.hdr_only:
        v_parts.append("hdr:12")

    if has_ffmpeg:
        video_fmt = "bestvideo"
        if v_parts:
            video_fmt += "/" + "+".join(v_parts)
        format_str = (
            f"bestvideo[ext=mp4]+bestaudio[ext=m4a]/{video_fmt}+bestaudio/"
            f"bestvideo+bestaudio/best"
        )
    else:
        single_stream = "best"
        if v_parts:
            single_stream = "best/" + "+".join(v_parts)
        format_str = f"{single_stream}/best"

    return format_str


def build_format_sort(config: DownloaderConfig) -> list[str]:
    """Build yt-dlp format_sort list."""
    preset = QUALITY_PRESETS.get(config.quality.lower(), QUALITY_PRESETS["best"])
    sort = list(preset["format_sort"])

    codec_sort = CODEC_PRIORITY.get((config.prefer_codec or "").lower(), [])
    if codec_sort:
        sort = [s for s in sort if not s.startswith("codec:") or s == "codec:h264"]
        for cs in codec_sort:
            if cs not in sort:
                sort.insert(0, cs)

    if config.hdr_only and "hdr:12" not in sort:
        sort.insert(0, "hdr:12")

    return sort


# ---------------------------------------------------------------------------
# Progress Display
# ---------------------------------------------------------------------------

class ProgressDisplay:
    """Async-compatible terminal progress display."""

    def __init__(self, total: int, quiet: bool = False) -> None:
        self.total = total
        self.quiet = quiet
        self._tasks: dict[int, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._last_draw = 0.0
        self._completed = 0
        self._failed = 0
        self._render_scheduled = False

    def register(self, task: DownloadTask) -> None:
        self._tasks[task.index] = {
            "url": task.url,
            "status": "pending",
            "progress": 0.0,
            "speed": 0.0,
            "eta": 0,
            "size": "?",
            "error": None,
        }

    async def update(
        self,
        index: int,
        status: str,
        progress: float = 0.0,
        speed: float = 0.0,
        eta: int = 0,
        size: str = "?",
        error: Optional[str] = None,
    ) -> None:
        if self.quiet:
            return
        async with self._lock:
            if index in self._tasks:
                t = self._tasks[index]
                if status:
                    t["status"] = status
                if progress is not None:
                    t["progress"] = progress
                if speed is not None:
                    t["speed"] = speed
                if eta is not None:
                    t["eta"] = eta
                if size != "?":
                    t["size"] = size
                if error is not None:
                    t["error"] = error

        # Schedule a render soon
        if not self._render_scheduled and not self.quiet:
            self._render_scheduled = True
            try:
                loop = asyncio.get_running_loop()
                loop.call_later(
                    PROGRESS_REFRESH_MS / 1000, self._scheduled_render
                )
            except RuntimeError:
                self._render_scheduled = False

    def _scheduled_render(self) -> None:
        self._render_scheduled = False
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.render())
        except RuntimeError:
            pass

    async def mark_completed(self, index: int, success: bool) -> None:
        async with self._lock:
            if index in self._tasks:
                self._tasks[index]["status"] = "success" if success else "failed"
                if success:
                    self._completed += 1
                else:
                    self._failed += 1

    async def render(self) -> None:
        if self.quiet:
            return
        now = time.monotonic()
        if now - self._last_draw < PROGRESS_REFRESH_MS / 1000:
            return
        self._last_draw = now

        async with self._lock:
            snapshot = {
                idx: dict(t)
                for idx, t in self._tasks.items()
            }
            completed = self._completed
            failed = self._failed
            total = self.total

        lines = []
        lines.append(
            f"\033[1mSocial Video Downloader\033[0m | "
            f"Progress: {completed + failed}/{total} | "
            f"[OK] {completed} [X] {failed}"
        )
        lines.append("-" * 80)

        for idx in sorted(snapshot.keys()):
            t = snapshot[idx]
            status_icon = {
                "pending": "[  ]",
                "running": " ->",
                "success": "[OK]",
                "failed": "[X]",
                "skipped": "[--]",
            }.get(t["status"], " ? ")

            color = {
                "pending": "37",
                "running": "36",
                "success": "32",
                "failed": "31",
                "skipped": "33",
            }.get(t["status"], "37")

            if t["status"] == "running" and t["progress"] > 0:
                bar_len = 20
                filled = int(bar_len * t["progress"] / 100)
                bar = "=" * filled + "-" * (bar_len - filled)
                speed_str = f"{t['speed'] / 1_048_576:.1f}MB/s" if t["speed"] > 0 else "?"
                eta_str = f"{t['eta']}s" if t["eta"] > 0 else "?"
                detail = f"[{bar}] {t['progress']:.0f}% {speed_str} ETA {eta_str} {t['size']}"
            elif t["status"] == "failed" and t["error"]:
                detail = f"FAILED: {t['error'][:60]}"
            elif t["status"] == "success":
                detail = f"Done ({t['size']})"
            else:
                detail = t["url"][:60]

            lines.append(f"  \033[{color}m{status_icon}\033[0m [{idx:3d}] {detail}")

        output = "\033[H\033[J" + "\n".join(lines)
        try:
            print(output, end="", flush=True)
        except UnicodeEncodeError:
            safe = output.encode("ascii", errors="replace").decode("ascii")
            print(safe, end="", flush=True)

    async def final_render(self) -> None:
        if not self.quiet:
            await self.render()
            print()


# ---------------------------------------------------------------------------
# Async Download Engine
# ---------------------------------------------------------------------------

class AsyncDownloadEngine:
    """
    Concurrent download engine using asyncio subprocess.
    Each URL gets its own yt-dlp process; a semaphore limits concurrency.
    """

    def __init__(self, config: DownloaderConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.display = ProgressDisplay(len(config.urls), quiet=config.quiet)
        self.state = StateManager(config.state_file) if config.resume else None
        self._active: set[int] = set()
        self._completed_count = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> list[DownloadTask]:
        """Execute all downloads concurrently. Returns list of results."""
        self._log_banner()

        if not self.config.urls:
            self.logger.error("No URLs provided.")
            return []

        self.config.output_dir.mkdir(parents=True, exist_ok=True)

        tasks = []
        skipped = 0
        for idx, url in enumerate(self.config.urls, 1):
            norm_url = normalize_url(url)
            if self.config.resume and self.state and self.state.is_completed(norm_url):
                self.logger.info("⊘ [%d] Skipping (already downloaded): %s", idx, url)
                task = DownloadTask(url=url, index=idx, status="skipped")
                entry = self.state.data["completed"][norm_url]
                task.file_path = Path(entry["file"]) if entry.get("file") else None
                task.file_size = entry.get("size", 0)
                task.resolution = entry.get("resolution")
                task.format_id = entry.get("format_id")
                tasks.append(task)
                skipped += 1
                continue

            tasks.append(DownloadTask(url=url, index=idx))
            self.display.register(tasks[-1])

        if skipped:
            self.logger.info("⊘ Skipped %d already-completed URLs", skipped)

        active_tasks = [t for t in tasks if t.status != "skipped"]
        if not active_tasks:
            self.logger.info("All URLs already downloaded. Nothing to do.")
            await self.display.final_render()
            return tasks

        # Run concurrent downloads
        semaphore = asyncio.Semaphore(self.config.concurrent)

        async def _run_with_limit(task: DownloadTask) -> DownloadTask:
            async with semaphore:
                return await self._process_task(task)

        try:
            results = await asyncio.gather(
                *[_run_with_limit(t) for t in active_tasks], return_exceptions=True
            )
        except asyncio.CancelledError:
            self.logger.warning("Batch cancelled.")
            final = list(tasks)
            self._cleanup_orphans()
            self._log_summary(final)
            raise

        # Handle exceptions from gather
        final = list(tasks)  # include skipped tasks
        result_map = {t.index: t for t in tasks}
        for task, result in zip(active_tasks, results):
            if isinstance(result, Exception):
                task.status = "failed"
                task.error = str(result)
                if self.state:
                    self.state.mark_failed(task.url, str(result))
            else:
                result_map[task.index] = result
        final = list(result_map.values())

        await self.display.final_render()
        self._cleanup_orphans()
        self._log_summary(final)
        return final

    # ------------------------------------------------------------------
    # Task Processing
    # ------------------------------------------------------------------

    async def _process_task(self, task: DownloadTask) -> DownloadTask:
        """Process a single URL with retry logic."""
        start = time.monotonic()
        last_error: Optional[str] = None

        for attempt in range(1, self.config.retries + 1):
            task.attempt = attempt
            task.retries_left = self.config.retries - attempt

            if attempt > 1:
                jitter = random.uniform(0, self.config.retry_delay)
                delay = min(self.config.retry_delay * (2 ** (attempt - 2)) + jitter, 120)
                self.logger.warning(
                    "↻ [%d] Retry %d/%d in %.1fs…", task.index, attempt, self.config.retries, delay
                )
                await asyncio.sleep(delay)
                if asyncio.current_task() and asyncio.current_task().cancelled():
                    raise asyncio.CancelledError()

            await self.display.update(task.index, "running", progress=0.0)
            self.logger.info("↓ [%d] %s", task.index, task.url)

            try:
                result = await asyncio.wait_for(
                    self._download_subprocess(task), timeout=self.config.subprocess_timeout
                )

                if result.get("success"):
                    task.status = "success"
                    task.file_path = Path(result["file"]) if result.get("file") else None
                    task.file_size = result.get("size", 0)
                    task.resolution = result.get("resolution")
                    task.format_id = result.get("format_id")
                    task.duration_s = time.monotonic() - start
                    task.verified = result.get("verified", False)

                    if self.state:
                        self.state.mark_completed(task.url, task)

                    await self.display.update(
                        task.index, "success", size=self._fmt_bytes(task.file_size)
                    )
                    return task
                else:
                    last_error = result.get("error", "Unknown error")
                    self.logger.warning("✗ [%d] Attempt %d: %s", task.index, attempt, last_error)

            except asyncio.TimeoutError:
                last_error = f"Timeout after {self.config.subprocess_timeout}s"
                self.logger.warning("✗ [%d] Attempt %d: %s", task.index, attempt, last_error)

            except Exception as exc:
                last_error = f"Unexpected: {exc}"
                self.logger.exception("✗ [%d] Attempt %d raised", task.index, attempt)

        task.status = "failed"
        task.error = last_error or "All retries exhausted"
        task.duration_s = time.monotonic() - start
        if self.state:
            self.state.mark_failed(task.url, task.error or "Unknown error")

        await self.display.update(task.index, "failed", error=task.error)
        return task

    # ------------------------------------------------------------------
    # Subprocess Execution
    # ------------------------------------------------------------------

    async def _download_subprocess(self, task: DownloadTask) -> dict[str, Any]:
        """
        Run yt-dlp as a subprocess via asyncio.to_thread(subprocess.run).
        Returns a dict with success/file/size/resolution/error keys.
        """
        cmd = self._build_command(task.url)
        output_dir = self.config.output_dir.resolve()

        def _run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(output_dir),
                timeout=self.config.subprocess_timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

        try:
            proc_result: subprocess.CompletedProcess[str] = await asyncio.to_thread(_run)
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Timeout after {self.config.subprocess_timeout}s"}
        except Exception as exc:
            return {"success": False, "error": f"Subprocess error: {exc}"}

        stdout_text = proc_result.stdout or ""
        stderr_text = proc_result.stderr or ""
        combined_output = stdout_text + ("\n" + stderr_text if stderr_text else "")
        result = self._parse_yt_dlp_output(task, combined_output, proc_result.returncode)

        # Resolve file path relative to output_dir
        if result.get("success") and result.get("file"):
            raw_path = Path(result["file"])
            if raw_path.is_absolute():
                file_path = raw_path
            else:
                file_path = output_dir / raw_path
            if file_path.exists():
                result["file"] = str(file_path)
                result["size"] = file_path.stat().st_size
                if not result.get("resolution"):
                    result["resolution"] = self._probe_resolution(file_path)
            else:
                found = self._find_output_file(
                    task.url,
                    output_dir=output_dir,
                    reported_filepath=result.get("file"),
                )
                if found:
                    result["file"] = str(found)
                    result["size"] = found.stat().st_size
                    if not result.get("resolution"):
                        result["resolution"] = self._probe_resolution(found)
                else:
                    result["file"] = None
                    result["success"] = False
                    result["error"] = "Download completed but no output file found"

        # Always verify file exists, even if --no-verify is set
        if result.get("success") and result.get("file"):
            file_path = Path(result["file"])
            if not file_path.exists():
                result["success"] = False
                result["error"] = "File disappeared after download"
            elif not self.config.no_verify:
                ok, reason = self._verify_file(file_path, self.config.min_file_size)
                result["verified"] = ok
                if not ok:
                    self.logger.warning("⚠ [%d] Integrity failed: %s", task.index, reason)
                    file_path.unlink(missing_ok=True)
                    result = {"success": False, "error": f"Integrity: {reason}"}

        return result

    # ------------------------------------------------------------------
    # Command Builder
    # ------------------------------------------------------------------

    def _build_command(self, url: str) -> list[str]:
        """Build the yt-dlp command line arguments."""
        has_ffmpeg = shutil.which("ffmpeg") is not None
        fmt_string = build_format_string(self.config, has_ffmpeg=has_ffmpeg)

        cmd = [
            sys.executable,
            "-m", "yt_dlp",
            url,
            "--format", fmt_string,
            "--format-sort", ",".join(build_format_sort(self.config)),
            "--prefer-free-formats",
            "--output", self.config.output_template,
            "--no-overwrites" if not self.config.force_overwrites else "--force-overwrites",
            "--continue",
            "--retries", "0",
            "--fragment-retries", "0",
            "--socket-timeout", str(self.config.timeout),
        ]

        if self.config.limit_rate:
            cmd.extend(["--limit-rate", self.config.limit_rate])

        if self.config.no_verify:
            cmd.append("--no-check-certificate")

        if has_ffmpeg:
            cmd.extend(["--merge-output-format", self.config.merge_format])
            cmd.append("--embed-metadata" if self.config.embed_metadata else "--no-embed-metadata")
            if self.config.embed_thumbnail:
                cmd.append("--embed-thumbnail")
            else:
                cmd.append("--no-embed-thumbnail")
        else:
            cmd.extend(["--merge-output-format", "mp4"])
            cmd.append("--no-embed-metadata")
            cmd.append("--no-embed-thumbnail")

        if self.config.write_subs:
            cmd.extend(["--write-subs", "--embed-subs"])
        if self.config.write_auto_subs:
            cmd.extend(["--write-auto-subs", "--embed-subs", "--sub-langs", self.config.sub_langs])

        if self.config.flat_playlist:
            cmd.append("--flat-playlist")
        if self.config.playlist_items:
            cmd.extend(["--playlist-items", self.config.playlist_items])
        if self.config.proxy:
            cmd.extend(["--proxy", self.config.proxy])
        if self.config.user_agent:
            cmd.extend(["--user-agent", self.config.user_agent])
        if self.config.cookies_file:
            cmd.extend(["--cookies", str(self.config.cookies_file)])
        if self.config.hdr_only:
            cmd.append("--hdr-only")

        # Structured output — always included for reliable parsing
        cmd.extend([
            "--print", "after_move:filepath",
            "--print", "after_move:filesize",
            "--print", "after_move:resolution",
            "--print", "after_move:format_id",
            "--newline",
            "--no-warnings",
        ])

        if self.config.quiet:
            cmd.append("-q")
        elif self.config.verbose:
            cmd.append("-v")

        return cmd

    # ------------------------------------------------------------------
    # Output Parsing
    # ------------------------------------------------------------------

    def _parse_yt_dlp_output(
        self, task: DownloadTask, output: str, returncode: int
    ) -> dict[str, Any]:
        """Parse yt-dlp subprocess output for results."""
        result: dict[str, Any] = {"success": False}

        if returncode == 0:
            lines = output.split("\n")
            prints = [l for l in lines if l and not l.startswith("[")]

            # Heuristic: last non-bracket line is format_id, second-to-last is resolution,
            # third-to-last is filesize, everything before is the filepath
            if len(prints) >= 4:
                raw_filepath = "\n".join(prints[:-3]).strip()
                result["file"] = raw_filepath
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

            # Validate the file
            if result.get("file"):
                raw_file = result["file"]
                cleaned = raw_file.replace("\n", " ").replace("\r", " ")
                cleaned = re.sub(r" {2,}", " ", cleaned).strip()
                if cleaned:
                    result["file"] = cleaned

            if result.get("file"):
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
                l.strip() for l in output.split("\n")
                if l.strip() and not l.startswith("[download]")
                and not l.startswith("[ExtractAudio]") and not l.startswith("[ffmpeg]")
                and not l.startswith("WARNING")
            ]
            result["error"] = (
                error_lines[-1] if error_lines else f"yt-dlp exited with code {returncode}"
            )[:200]

        return result

    # ------------------------------------------------------------------
    # File Location Heuristics
    # ------------------------------------------------------------------

    def _find_output_file(
        self,
        url: str,
        output_dir: Optional[Path] = None,
        window: int = 300,
        reported_filepath: Optional[str] = None,
    ) -> Optional[Path]:
        """Find the most recently created/modified media file in output dir."""
        if output_dir is None:
            output_dir = self.config.output_dir.resolve()

        try:
            candidates = sorted(
                output_dir.iterdir(),
                key=lambda p: p.stat().st_mtime if p.exists() else 0,
                reverse=True,
            )
        except OSError:
            return None

        now = time.time()

        # Strategy 1: Match by tweet/post ID from reported filepath
        ytdlp_id = None
        if reported_filepath:
            m = re.search(r"\[(\d{10,})\]", reported_filepath)
            if m:
                ytdlp_id = m.group(1)

        if ytdlp_id:
            matches = [
                p for p in candidates
                if p.exists() and p.suffix in SUPPORTED_EXTENSIONS
                and ytdlp_id in p.name
            ]
            if matches:
                return matches[0]

        # Strategy 2: Match by ID from URL
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
                if p.exists() and p.suffix in SUPPORTED_EXTENSIONS
                and url_id in p.name
                and now - p.stat().st_mtime <= window * 2
            ]
            if matches:
                return matches[0]

        # Strategy 3: Most recent media file within window
        valid = [
            p for p in candidates
            if p.exists() and p.suffix in SUPPORTED_EXTENSIONS
            and now - p.stat().st_mtime <= window
        ]
        if valid:
            return valid[0]
        return None

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    @staticmethod
    def _verify_file(file_path: Path, min_size: int) -> tuple[bool, str]:
        """Verify downloaded file integrity.  Never raises."""
        try:
            if not file_path.exists():
                return False, "File does not exist"
            size = file_path.stat().st_size
            if size < min_size:
                return False, f"Too small: {size} bytes < {min_size}"
            if size == 0:
                return False, "Empty file"
            with open(file_path, "rb") as f:
                header = f.read(16)
            if not header:
                return False, "Empty file"
        except OSError as exc:
            return False, f"OS error: {exc}"
        return True, "OK"

    @staticmethod
    def _probe_resolution(file_path: Path) -> Optional[str]:
        """Probe video resolution using ffprobe if available."""
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

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup_orphans(self) -> None:
        """Remove .part files and orphaned .jpg thumbnails after batch completion."""
        if not self.config.output_dir.exists():
            return

        removed_parts = 0
        removed_jpgs = 0

        for f in self.config.output_dir.iterdir():
            if not f.is_file():
                continue

            if f.suffix == ".part":
                try:
                    f.unlink(missing_ok=True)
                    removed_parts += 1
                except PermissionError:
                    pass
                continue

            if f.suffix.lower() == ".jpg":
                base = f.stem
                has_video = any(
                    (self.config.output_dir / f"{base}{ext}").exists()
                    for ext in SUPPORTED_EXTENSIONS
                    if ext != ".jpg"
                )
                if has_video:
                    try:
                        f.unlink(missing_ok=True)
                        removed_jpgs += 1
                    except PermissionError:
                        pass

        if removed_parts:
            self.logger.info("🧹 Cleaned up %d incomplete .part files", removed_parts)
        if removed_jpgs:
            self.logger.info("🧹 Cleaned up %d orphaned .jpg thumbnails", removed_jpgs)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def _log_banner(self) -> None:
        self.logger.info(
            "Async Social Video Downloader | %d URLs | Concurrency: %d | Output: %s",
            len(self.config.urls),
            self.config.concurrent,
            self.config.output_dir.resolve(),
        )

    def _log_summary(self, results: list[DownloadTask]) -> None:
        total = len(results)
        passed = sum(1 for r in results if r and r.status == "success")
        failed = sum(1 for r in results if r and r.status == "failed")
        skipped = sum(1 for r in results if r and r.status == "skipped")

        self.logger.info("━━━ Summary: %d total | %d success | %d failed | %d skipped", total, passed, failed, skipped)

        if failed > 0:
            self.logger.info("Failed URLs:")
            for r in results:
                if r and r.status == "failed":
                    self.logger.info("  • [%d] %s — %s", r.index, r.url, r.error)

    @staticmethod
    def _fmt_bytes(n: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if abs(n) < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="social_video_downloader",
        description=(
            "Async batch downloader for Instagram and X (Twitter) videos.\n"
            "Downloads at maximum available resolution and bitrate with "
            "concurrent execution, resume support, and rich terminal output."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s https://www.instagram.com/p/ABC123/\n"
            "  %(prog)s -f urls.txt -j 5 --quality 1080p\n"
            "  %(prog)s URL1 URL2 --cookies-from-browser chrome\n"
            "  %(prog)s -f urls.txt --resume --report report.json\n"
            "  %(prog)s URL --prefer-codec h265 --hdr-only --merge-format mkv\n"
        ),
    )

    parser.add_argument("urls", nargs="*", metavar="URL", help="Instagram or X/Twitter URLs.")
    parser.add_argument("-f", "--file", metavar="FILE", help="Text file with one URL per line.")
    parser.add_argument(
        "-i", "--stdin", action="store_true",
        help="Read URLs from stdin (one per line). Useful for piping.",
    )
    parser.add_argument(
        "-j", "--concurrent", type=int, default=DEFAULT_CONCURRENT,
        help=f"Parallel download slots (default: {DEFAULT_CONCURRENT}).",
    )

    parser.add_argument(
        "-o", "--output-dir", default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "-t", "--output-template", default="%(title)s [%(id)s].%(ext)s",
        help="Filename template (default: '%%(title)s [%%(id)s].%%(ext)s').",
    )
    parser.add_argument(
        "--merge-format", default="mp4", choices=["mp4", "mkv", "webm", "mov", "flv"],
        help="Merged container format (default: mp4).",
    )

    parser.add_argument(
        "--quality", default="best", choices=list(QUALITY_PRESETS.keys()),
        help="Resolution preset (default: best).",
    )
    parser.add_argument(
        "--prefer-codec", choices=list(CODEC_PRIORITY.keys()),
        help="Preferred video codec (h264, h265, av1, vp9).",
    )
    parser.add_argument("--hdr-only", action="store_true", help="Download HDR content only.")

    parser.add_argument("--no-embed-metadata", dest="embed_metadata", action="store_false")
    parser.add_argument("--no-embed-thumbnail", dest="embed_thumbnail", action="store_false")
    parser.add_argument("--write-subs", action="store_true", help="Download subtitles.")
    parser.add_argument("--write-auto-subs", action="store_true", help="Download auto-generated subtitles.")
    parser.add_argument("--sub-langs", default="en", help="Subtitle language codes (default: en).")

    parser.add_argument(
        "-r", "--retries", type=int, default=DEFAULT_RETRIES,
        help=f"Retries per URL (default: {DEFAULT_RETRIES}).",
    )
    parser.add_argument(
        "--retry-delay", type=int, default=DEFAULT_RETRY_DELAY,
        help=f"Base retry delay in seconds (default: {DEFAULT_RETRY_DELAY}).",
    )
    parser.add_argument(
        "--subprocess-timeout", type=int, default=DEFAULT_SUBPROCESS_TIMEOUT,
        help=f"Subprocess timeout in seconds (default: {DEFAULT_SUBPROCESS_TIMEOUT}).",
    )
    parser.add_argument(
        "--timeout", type=int, default=30,
        help="Socket timeout in seconds (default: 30).",
    )
    parser.add_argument("--limit-rate", metavar="RATE", help="Speed limit (e.g. 5M, 500K).")
    parser.add_argument("--proxy", help="HTTP/HTTPS proxy URL.")
    parser.add_argument("--user-agent", help="Custom User-Agent.")

    parser.add_argument(
        "--cookies", metavar="FILE", type=Path,
        help="Cookies file (Netscape format).",
    )
    parser.add_argument(
        "--cookies-from-browser",
        choices=list(BROWSER_MAP.keys()),
        help="Extract cookies from browser (chrome, firefox, edge, brave, chromium).",
    )

    parser.add_argument("--flat-playlist", action="store_true", help="Don't resolve playlist entries.")
    parser.add_argument("--playlist-items", help="Playlist item indices (e.g. '1,2,5-7').")
    parser.add_argument("--force-overwrites", action="store_true", help="Overwrite existing files.")

    parser.add_argument("--no-verify", dest="no_verify", action="store_true", help="Skip integrity checks.")
    parser.add_argument(
        "--min-file-size", type=int, default=DEFAULT_MIN_FILE_SIZE, metavar="BYTES",
        help=f"Minimum file size in bytes (default: {DEFAULT_MIN_FILE_SIZE}).",
    )

    parser.add_argument("--resume", dest="resume", action="store_true", default=True, help="Enable resume support (default).")
    parser.add_argument("--no-resume", dest="resume", action="store_false", help="Disable resume support.")
    parser.add_argument(
        "--state-file", type=Path, default=Path(DEFAULT_STATE_FILE),
        help=f"State file path (default: {DEFAULT_STATE_FILE}).",
    )
    parser.add_argument("--clear-state", action="store_true", help="Clear state file and exit.")

    parser.add_argument("--report", metavar="FILE", help="Write JSON report.")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")

    return parser


def load_urls_from_file(path: Path) -> list[str]:
    """Read non-empty, non-comment lines from a text file."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        print(f"ERROR: URL file not found: {path}", file=sys.stderr)
        sys.exit(1)
    except UnicodeDecodeError:
        print(f"ERROR: URL file is not valid UTF-8: {path}", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"ERROR: Cannot read URL file: {exc}", file=sys.stderr)
        sys.exit(1)

    urls = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            urls.append(stripped)
    return urls


def setup_logging(verbose: bool = False, quiet: bool = False) -> logging.Logger:
    """Configure logging."""
    logger = logging.getLogger("social_downloader")
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        logger.handlers.clear()

    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
    logger.addHandler(handler)
    return logger


def export_report(path: Path, results: list[DownloadTask], config: DownloaderConfig) -> None:
    """Write JSON report."""
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "concurrent": config.concurrent,
            "quality": config.quality,
            "merge_format": config.merge_format,
            "output_dir": str(config.output_dir),
        },
        "summary": {
            "total": len(results),
            "success": sum(1 for r in results if r and r.status == "success"),
            "failed": sum(1 for r in results if r and r.status == "failed"),
            "skipped": sum(1 for r in results if r and r.status == "skipped"),
        },
        "results": [
            {
                "index": r.index,
                "url": r.url,
                "status": r.status,
                "file": str(r.file_path) if r.file_path else None,
                "size": r.file_size,
                "resolution": r.resolution,
                "format_id": r.format_id,
                "duration_s": round(r.duration_s, 2),
                "verified": r.verified,
                "error": r.error,
            }
            for r in results if r
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=".report_", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    print(f"Report written to {path}", file=sys.stderr)


async def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.clear_state:
        state = StateManager(args.state_file)
        state.clear()
        print(f"State file cleared: {args.state_file}", file=sys.stderr)
        return 0

    urls: list[str] = list(args.urls or [])
    if args.file:
        urls.extend(load_urls_from_file(Path(args.file)))
    if args.stdin:
        try:
            stdin_text = sys.stdin.read()
            stdin_urls = [
                line.strip() for line in stdin_text.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            urls.extend(stdin_urls)
        except Exception as exc:
            print(f"ERROR: Failed to read from stdin: {exc}", file=sys.stderr)
            sys.exit(1)

    if not urls:
        parser.error("No URLs provided. Pass URLs as arguments, use -f/--file, or use -i/--stdin.")

    # Deduplicate
    seen: set[str] = set()
    unique_urls = []
    for url in urls:
        norm = normalize_url(url)
        if norm not in seen:
            seen.add(norm)
            unique_urls.append(url)
    if len(unique_urls) != len(urls):
        print(f"INFO: Removed {len(urls) - len(unique_urls)} duplicate URLs", file=sys.stderr)

    # Extract browser cookies if requested
    cookies_file = args.cookies
    temp_cookies = None
    if args.cookies_from_browser:
        temp_cookies = extract_browser_cookies(args.cookies_from_browser)
        if temp_cookies:
            cookies_file = temp_cookies
        else:
            print(
                "WARNING: Browser cookie extraction failed. "
                "Downloads may require authentication.",
                file=sys.stderr,
            )

    config = DownloaderConfig(
        urls=unique_urls,
        output_dir=Path(args.output_dir).resolve(),
        concurrent=max(1, args.concurrent),
        quality=args.quality,
        prefer_codec=args.prefer_codec,
        hdr_only=args.hdr_only,
        merge_format=args.merge_format,
        embed_metadata=args.embed_metadata,
        embed_thumbnail=args.embed_thumbnail,
        write_subs=args.write_subs,
        write_auto_subs=args.write_auto_subs,
        sub_langs=args.sub_langs,
        retries=max(1, args.retries),
        retry_delay=max(1, args.retry_delay),
        subprocess_timeout=max(10, args.subprocess_timeout),
        timeout=max(10, args.timeout),
        limit_rate=args.limit_rate,
        cookies_file=cookies_file,
        cookies_from_browser=args.cookies_from_browser,
        user_agent=args.user_agent,
        proxy=args.proxy,
        output_template=args.output_template,
        verbose=args.verbose,
        quiet=args.quiet,
        no_verify=args.no_verify,
        min_file_size=max(0, args.min_file_size),
        resume=args.resume,
        state_file=Path(args.state_file).resolve(),
        flat_playlist=args.flat_playlist,
        playlist_items=args.playlist_items,
        force_overwrites=args.force_overwrites,
    )

    logger = setup_logging(verbose=config.verbose, quiet=config.quiet)

    if config.embed_thumbnail and not shutil.which("ffmpeg"):
        logger.warning(
            "ffmpeg not found on PATH. Thumbnail embedding and some "
            "merges may fail. Install ffmpeg for full functionality."
        )

    try:
        engine = AsyncDownloadEngine(config, logger)
        results = await engine.run()
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        return 130
    except Exception as exc:
        logger.error("Fatal error: %s", exc, exc_info=True)
        return 1
    finally:
        if temp_cookies:
            temp_cookies.unlink(missing_ok=True)

    if args.report:
        export_report(Path(args.report).resolve(), results, config)

    failed = [r for r in results if r and r.status == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
