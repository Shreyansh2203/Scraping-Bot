from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from core.config import settings
from core.downloader_wrapper import DownloaderWrapper
from bot.handlers import commands, download

__version__ = "0.1.0"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


async def health_handler(request: web.Request) -> web.Response:
    downloader: DownloaderWrapper = request.app["downloader"]
    stats = {
        "status": "ok",
        "version": __version__,
        "concurrent": downloader.concurrent,
        "output_dir": str(downloader.output_dir),
        "state_file": str(downloader.state_file),
    }
    return web.json_response(stats)


async def start_health_server(bot: Bot, downloader: DownloaderWrapper, port: int = 8080) -> None:
    app = web.Application()
    app["downloader"] = downloader
    app.router.add_get("/health", health_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.getLogger("bot.main").info("Health server started on :%d", port)


async def main() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler],
    )

    settings.validate()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    downloader = DownloaderWrapper(
        output_dir=settings.DOWNLOAD_DIR,
        state_file=settings.STATE_FILE,
        concurrent=settings.CONCURRENT_DOWNLOADS,
    )

    dp = Dispatcher()
    dp["downloader"] = downloader
    dp.include_router(commands.router)
    dp.include_router(download.router)

    await start_health_server(bot, downloader, settings.HEALTH_PORT)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped.")

