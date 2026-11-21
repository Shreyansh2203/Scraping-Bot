# MIT License
#
# Copyright (c) 2026 Shreyansh Srivastava
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv
from pydantic import PrivateAttr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

logger = logging.getLogger(__name__)

_BOT_TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]+$")

_PENDING_MALFORMED: list[str] = []


def _parse_allowed_users_value(v: Any) -> list[int]:
    """Parse a comma-separated ALLOWED_USERS string into ints, tracking malformed entries.

    ``str`` type keeps pydantic-settings from JSON-decoding the value; we parse
    manually so a stray comma or non-numeric ID is recorded rather than silently
    shrinking the allow-list.
    """
    global _PENDING_MALFORMED
    if isinstance(v, list):
        _PENDING_MALFORMED = []
        return v
    users: list[int] = []
    malformed: list[str] = []
    if v:
        for uid in str(v).split(","):
            uid = uid.strip()
            if uid:
                try:
                    users.append(int(uid))
                except ValueError:
                    malformed.append(uid)
                    logger.warning("Invalid user ID '%s', skipping", uid)
    _PENDING_MALFORMED = malformed
    return users


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    BOT_TOKEN: str = ""
    DOWNLOAD_DIR: Path = Path("./downloads")
    CONCURRENT_DOWNLOADS: int = 2
    MAX_FILE_SIZE_MB: int = 50
    MAX_DURATION_SECONDS: int = 600
    ALLOWED_USERS: Any = []
    ALLOW_PUBLIC: bool = False
    HEALTH_PORT: int = 8080
    HEALTH_BIND: str = "127.0.0.1"
    SUBPROCESS_TIMEOUT: int = 180
    FFPROBE_TIMEOUT: int = 10
    REDIS_URL: str = ""
    MAX_DISK_USAGE_PERCENT: int = 0
    BOT_MODE: str = ""
    RENDER_EXTERNAL_HOSTNAME: str = ""
    WEBHOOK_URL: str = ""

    _malformed_user_ids: list[str] = PrivateAttr(default_factory=list)

    @field_validator("HEALTH_PORT", mode="before")
    @classmethod
    def _resolve_health_port(cls, value: Any) -> Any:
        port = os.getenv("PORT") or None
        if port is not None:
            return port
        return value

    @field_validator(
        "CONCURRENT_DOWNLOADS",
        "MAX_FILE_SIZE_MB",
        "MAX_DURATION_SECONDS",
        "SUBPROCESS_TIMEOUT",
        "FFPROBE_TIMEOUT",
        "MAX_DISK_USAGE_PERCENT",
        "HEALTH_PORT",
        mode="before",
    )
    @classmethod
    def _safe_int(cls, value: Any, info: Any) -> int:
        try:
            return int(value)
        except (ValueError, TypeError):
            default = cast(int, cls.model_fields[info.field_name].default)
            logger.warning("Invalid integer value '%s', using default %s", value, default)
            return default

    @field_validator("ALLOW_PUBLIC", mode="before")
    @classmethod
    def _parse_allow_public(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip() == "1"

    @field_validator("ALLOWED_USERS", mode="before")
    @classmethod
    def _parse_allowed_users(cls, value: Any) -> list[int]:
        return _parse_allowed_users_value(value)

    @model_validator(mode="after")
    def _capture_malformed_and_compute_webhook(self) -> "Settings":
        self._malformed_user_ids = list(_PENDING_MALFORMED)

        if self.BOT_MODE == "polling":
            self.WEBHOOK_URL = ""
        elif os.getenv("WEBHOOK_URL"):
            pass
        else:
            self.WEBHOOK_URL = (
                f"https://{self.RENDER_EXTERNAL_HOSTNAME}/webhook"
                if self.RENDER_EXTERNAL_HOSTNAME
                else ""
            )

        return self

    def validate(self) -> None:  # type: ignore[override]
        if not self.BOT_TOKEN:
            raise RuntimeError("BOT_TOKEN is not set")
        if not _BOT_TOKEN_RE.match(self.BOT_TOKEN):
            raise RuntimeError(
                "BOT_TOKEN is malformed; expected the '<bot_id>:<secret>' value from @BotFather"
            )
        if self.CONCURRENT_DOWNLOADS < 1:
            raise RuntimeError("CONCURRENT_DOWNLOADS must be >= 1")
        if self.MAX_FILE_SIZE_MB < 1:
            raise RuntimeError("MAX_FILE_SIZE_MB must be >= 1")
        if self.MAX_DURATION_SECONDS < 1:
            raise RuntimeError("MAX_DURATION_SECONDS must be >= 1")
        if not (1 <= self.HEALTH_PORT <= 65535):
            raise RuntimeError("HEALTH_PORT must be between 1 and 65535")
        if not (0 <= self.MAX_DISK_USAGE_PERCENT <= 100):
            raise RuntimeError("MAX_DISK_USAGE_PERCENT must be between 0 and 100")
        if self._malformed_user_ids:
            offenders = ", ".join(repr(uid) for uid in self._malformed_user_ids)
            raise RuntimeError(
                f"ALLOWED_USERS contains entries that are not Telegram user IDs: {offenders}; "
                "a typo must not silently leave the bot with fewer users than you meant"
            )
        if not self.ALLOWED_USERS and not self.ALLOW_PUBLIC:
            raise RuntimeError(
                "ALLOWED_USERS is empty; set it to a comma-separated list of Telegram user "
                "IDs, or set ALLOW_PUBLIC=1 to run a deliberately public bot"
            )
        if not self.ALLOWED_USERS:
            logger.warning("ALLOWED_USERS is empty and ALLOW_PUBLIC=1; bot is public")


settings = Settings()
