from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()


class Settings:
    __version__: str = "0.1.0"

    def __init__(self) -> None:
        self.BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
        self.DOWNLOAD_DIR: Path = Path(os.getenv("DOWNLOAD_DIR", "./downloads"))
        self.CONCURRENT_DOWNLOADS: int = self._safe_int(os.getenv("CONCURRENT_DOWNLOADS", "2"), 2)
        self.MAX_FILE_SIZE_MB: int = self._safe_int(os.getenv("MAX_FILE_SIZE_MB", "50"), 50)
        self.ALLOWED_USERS: list[int] = self._parse_allowed_users(os.getenv("ALLOWED_USERS", ""))
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

    @staticmethod
    def _parse_allowed_users(value: str) -> list[int]:
        users: list[int] = []
        for uid in value.split(","):
            uid = uid.strip()
            if uid:
                try:
                    users.append(int(uid))
                except ValueError:
                    logger.warning("Invalid user ID '%s', skipping", uid)
        return users

    def validate(self) -> None:
        if not self.BOT_TOKEN:
            raise RuntimeError("BOT_TOKEN is not set")
        if self.CONCURRENT_DOWNLOADS < 1:
            raise RuntimeError("CONCURRENT_DOWNLOADS must be >= 1")
        if self.MAX_FILE_SIZE_MB < 1:
            raise RuntimeError("MAX_FILE_SIZE_MB must be >= 1")
        if not (1 <= self.HEALTH_PORT <= 65535):
            raise RuntimeError("HEALTH_PORT must be between 1 and 65535")
        if not self.ALLOWED_USERS:
            logger.warning("ALLOWED_USERS is empty; bot is public")


settings = Settings()
