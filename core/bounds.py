"""Constants and pure helpers for the size/duration bound probe.

yt-dlp is asked to print the size and duration it already knows, on its own line,
before it starts transferring anything. That lets the bot refuse an oversized or
over-long file without writing a single byte -- and without retrying a condition that
is deterministic, not transient.
"""

from __future__ import annotations

import re
from typing import Optional

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


def _probe_number(raw: str) -> Optional[int]:
    """Read one field of the bound probe, or None when yt-dlp did not report it."""
    raw = raw.strip()
    if not raw or raw == "NA":
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def bound_refusal(
    bound: object,
    max_file_size_bytes: int,
    max_duration_seconds: int,
) -> Optional[str]:
    """The user-facing reason to give up, when the extractor already said the media is
    over the limit, or None when it did not.

    Returning a reason here is what makes the refusal terminal: the caller does not
    retry a request that is going to be refused identically every time, and does not
    hand it to gallery-dl, which is not given either bound.
    """
    if not isinstance(bound, dict):
        return None
    size = bound.get("size")
    duration = bound.get("duration")
    if isinstance(size, int) and size > max_file_size_bytes:
        return (
            "Refusing to download: the file is larger than the "
            f"{max_file_size_bytes // BYTES_PER_MB} MB limit"
        )
    if isinstance(duration, int) and duration > max_duration_seconds:
        return f"Refusing to download: the media is longer than the {max_duration_seconds}s limit"
    return None


__all__ = [
    "SUPPORTED_EXTENSIONS",
    "DEFAULT_MIN_FILE_SIZE",
    "DEFAULT_MAX_FILE_SIZE_MB",
    "DEFAULT_MAX_DURATION_SECONDS",
    "BYTES_PER_MB",
    "_BOUND_PROBE_TAG",
    "_BOUND_PROBE_TEMPLATE",
    "_BOUND_PROBE_RE",
    "_TRANSFER_REFUSED",
    "_probe_number",
    "bound_refusal",
]
