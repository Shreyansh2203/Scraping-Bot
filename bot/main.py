from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web

from bot.handlers import commands, download
from bot.middlewares import throttle
from core.config import settings
from core.downloader_wrapper import DownloaderWrapper

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


async def start_health_server(
    bot: Bot, downloader: DownloaderWrapper, port: int = 8080, bind: str = "0.0.0.0"
) -> web.AppRunner:
    app = web.Application()
    app["downloader"] = downloader
    app.router.add_get("/health", health_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, bind, port)
    await site.start()
    logging.getLogger("bot.main").info("Health server started on %s:%d", bind, port)
    return runner


async def main() -> None:
    log_path = Path("bot.log").resolve()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    file_handler = logging.FileHandler(log_path)
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler, file_handler],
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
        subprocess_timeout=settings.SUBPROCESS_TIMEOUT,
        ffprobe_timeout=settings.FFPROBE_TIMEOUT,
    )

    dp = Dispatcher()
    dp["downloader"] = downloader
    dp.include_router(commands.router)
    dp.include_router(download.router)
    dp.update.middleware(throttle.ThrottleMiddleware())
    dp.update.middleware(throttle.AuthMiddleware())

    runner = await start_health_server(bot, downloader, settings.HEALTH_PORT, settings.HEALTH_BIND)
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        downloader.shutdown()
        await runner.cleanup()
        await bot.session.close()
        file_handler.close()


def _handle_sigterm(signum: int, frame: Any) -> None:
    raise SystemExit(0)


if __name__ == "__main__":
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_sigterm)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped.")
