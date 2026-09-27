from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

_BOT_TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]+$")


class Settings:
    def __init__(self) -> None:
        self.BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
        self.DOWNLOAD_DIR: Path = Path(os.getenv("DOWNLOAD_DIR", "./downloads"))
        self.CONCURRENT_DOWNLOADS: int = self._safe_int(os.getenv("CONCURRENT_DOWNLOADS", "2"), 2)
        self.MAX_FILE_SIZE_MB: int = self._safe_int(os.getenv("MAX_FILE_SIZE_MB", "50"), 50)
        self.MAX_DURATION_SECONDS: int = self._safe_int(
            os.getenv("MAX_DURATION_SECONDS", "600"), 600
        )
        # The entries ALLOWED_USERS carried that are not Telegram user IDs. Kept so
        # validate() can refuse to start rather than start with a shorter list.
        self._malformed_user_ids: list[str] = []
        self.ALLOWED_USERS: list[int] = self._parse_allowed_users(os.getenv("ALLOWED_USERS", ""))
        # A public bot is a deliberate choice, so it has to be spelled out.
        self.ALLOW_PUBLIC: bool = os.getenv("ALLOW_PUBLIC", "").strip() == "1"
        self.HEALTH_PORT: int = self._safe_int(
            os.getenv("PORT", os.getenv("HEALTH_PORT", "8080")), 8080
        )
        self.HEALTH_BIND: str = os.getenv("HEALTH_BIND", "127.0.0.1")
        self.SUBPROCESS_TIMEOUT: int = self._safe_int(os.getenv("SUBPROCESS_TIMEOUT", "180"), 180)
        self.FFPROBE_TIMEOUT: int = self._safe_int(os.getenv("FFPROBE_TIMEOUT", "10"), 10)

        self.BOT_MODE: str = os.getenv("BOT_MODE", "").lower()
        self.RENDER_EXTERNAL_HOSTNAME: str = os.getenv("RENDER_EXTERNAL_HOSTNAME", "")
        if self.BOT_MODE == "polling":
            self.WEBHOOK_URL: str = ""
        else:
            self.WEBHOOK_URL = os.getenv("WEBHOOK_URL") or (
                f"https://{self.RENDER_EXTERNAL_HOSTNAME}/webhook"
                if self.RENDER_EXTERNAL_HOSTNAME
                else ""
            )

    @staticmethod
    def _safe_int(value: str, default: int) -> int:
        try:
            return int(value)
        except (ValueError, TypeError):
            logger.warning("Invalid integer value '%s', using default %s", value, default)
            return default

    def _parse_allowed_users(self, value: str) -> list[int]:
        """Split ALLOWED_USERS into ids, recording anything that is not one.

        The dropped entries are remembered so validate() can refuse to start. Silently
        shrinking the list is what made a typo invisible: "" , "   " and "," all yield an
        empty list, and AuthMiddleware reads an empty list as "no restriction".
        """
        users: list[int] = []
        for uid in value.split(","):
            uid = uid.strip()
            if uid:
                try:
                    users.append(int(uid))
                except ValueError:
                    self._malformed_user_ids.append(uid)
                    logger.warning("Invalid user ID '%s', skipping", uid)
        return users

    def validate(self) -> None:
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
