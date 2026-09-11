from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


class Settings:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    DOWNLOAD_DIR: Path = Path(os.getenv("DOWNLOAD_DIR", "./downloads"))
    STATE_FILE: Path = Path(os.getenv("STATE_FILE", "./state/bot_state.json"))
    CONCURRENT_DOWNLOADS: int = int(os.getenv("CONCURRENT_DOWNLOADS", "2"))
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
    ALLOWED_USERS: list[int] = [
        int(uid.strip())
        for uid in os.getenv("ALLOWED_USERS", "").split(",")
        if uid.strip()
    ]

    def validate(self) -> None:
        if not self.BOT_TOKEN:
            raise RuntimeError("BOT_TOKEN is not set")


settings = Settings()
