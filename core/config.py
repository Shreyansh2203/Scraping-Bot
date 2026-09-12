from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Settings:
    __version__: str = "0.1.0"

    def __init__(self) -> None:
        self.BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
        self.DOWNLOAD_DIR: Path = Path(os.getenv("DOWNLOAD_DIR", "./downloads"))
        self.STATE_FILE: Path = Path(os.getenv("STATE_FILE", "./state/bot_state.json"))
        self.CONCURRENT_DOWNLOADS: int = int(os.getenv("CONCURRENT_DOWNLOADS", "2"))
        self.MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
        self.ALLOWED_USERS: list[int] = [
            int(uid.strip()) for uid in os.getenv("ALLOWED_USERS", "").split(",") if uid.strip()
        ]
        self.HEALTH_PORT: int = int(os.getenv("HEALTH_PORT", "8080"))

    def validate(self) -> None:
        if not self.BOT_TOKEN:
            raise RuntimeError("BOT_TOKEN is not set")


settings = Settings()
