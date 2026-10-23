"""Pure output parsing for the extractors.

These functions take everything they need as arguments and return plain dicts, so they
can be tested without constructing a DownloaderWrapper and without spawning a process.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .bounds import (
    _BOUND_PROBE_RE,
    SUPPORTED_EXTENSIONS,
    _probe_number,
    bound_refusal,
)

# What a --max-filesize abort looks like from here. yt-dlp says "File is larger than
# max-filesize ... Aborting" on stdout, which -q silences, and then exits 0 having
# transferred nothing. The probe line still printed, so the download did start; the
# after_move prints did not, so nothing came back. Retrying that is pointless -- the
# condition is deterministic, not transient -- and gallery-dl is handed no bound at all.
_TRANSFER_REFUSED_MSG = (
    "Refusing to download: the extractor declined to transfer this file, which is what "
    "yt-dlp does when --max-filesize is exceeded"
)


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
            import shutil as _shutil

            _shutil.rmtree(self.job_dir, ignore_errors=True)
        for p in self.file_paths:
            p.unlink(missing_ok=True)


def _parse_output(
    output: str,
    returncode: int,
    max_file_size_bytes: int,
    max_duration_seconds: int,
) -> dict[str, Any]:
    """Parse yt-dlp's stdout into a result dict, applying the size/duration bounds."""
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

    # Apply the bound refusal when the extractor already said the media is over the
    # limit. This is terminal: no retry, no unbounded gallery-dl fallback.
    refused = bound_refusal(result.get("bound"), max_file_size_bytes, max_duration_seconds)
    if refused is None and result.get("transfer_refused"):
        refused = _TRANSFER_REFUSED_MSG
    if refused:
        result["success"] = False
        result["error"] = refused

    return result


def _find_output_file(
    url: str,
    output_dir: Optional[Path] = None,
    reported_filepath: Optional[str] = None,
    window: int = 300,
    default_output_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Locate the file yt-dlp actually wrote when its reported path is unreliable."""
    if output_dir is None:
        output_dir = default_output_dir.resolve() if default_output_dir is not None else None
    if output_dir is None:
        return None

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


async def _probe_resolution(
    file_path: Path,
    ffprobe_timeout: int = 10,
) -> Optional[str]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    import asyncio

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
        )
        try:
            stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=ffprobe_timeout)
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


def gallery_dl_collect_files(
    target_dir: Path,
    min_file_size: int,
) -> tuple[list[Path], int, bool]:
    """Walk a gallery-dl target dir, flatten nested dirs, apply the min-file-size floor.

    Returns (files, total_size, had_any_supported). os.walk order differs between
    filesystems, so the caller should sort the result if a stable media-group order
    matters. `had_any_supported` is True when at least one supported-extension file
    was found before the min_file_size floor removed undersized ones, so the caller
    can distinguish "no supported files at all" from "all supported files too small".
    """
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

    had_any_supported = bool(downloaded_files)
    undersized = [
        path for path in downloaded_files if path.exists() and path.stat().st_size < min_file_size
    ]
    for path in undersized:
        path.unlink(missing_ok=True)
    downloaded_files = [path for path in downloaded_files if path not in undersized]

    total_size = sum(f.stat().st_size for f in downloaded_files if f.exists())
    downloaded_files.sort(key=lambda p: p.name)
    return downloaded_files, total_size, had_any_supported


__all__ = [
    "DownloadResult",
    "_parse_output",
    "_find_output_file",
    "_probe_resolution",
    "gallery_dl_collect_files",
]
