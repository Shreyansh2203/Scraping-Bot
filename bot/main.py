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
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
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
    }
    return web.json_response(stats)


async def on_startup(bot: Bot) -> None:
    if settings.WEBHOOK_URL:
        logging.getLogger("bot.main").info("Setting webhook to %s", settings.WEBHOOK_URL)
        await bot.set_webhook(settings.WEBHOOK_URL, drop_pending_updates=True)
    else:
        logging.getLogger("bot.main").info("Deleting webhook for polling")
        await bot.delete_webhook(drop_pending_updates=True)


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
        concurrent=settings.CONCURRENT_DOWNLOADS,
        subprocess_timeout=settings.SUBPROCESS_TIMEOUT,
        ffprobe_timeout=settings.FFPROBE_TIMEOUT,
    )

    dp = Dispatcher()
    dp["downloader"] = downloader
    dp.startup.register(on_startup)
    dp.include_router(commands.router)
    dp.include_router(download.router)
    dp.message.middleware(throttle.ThrottleMiddleware())
    dp.message.middleware(throttle.AuthMiddleware())

    app = web.Application()
    app["downloader"] = downloader
    app.router.add_get("/health", health_handler)

    if settings.WEBHOOK_URL:
        webhook_requests_handler = SimpleRequestHandler(
            dispatcher=dp,
            bot=bot,
        )
        webhook_requests_handler.register(app, path="/webhook")
        setup_application(app, dp, bot=bot)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, settings.HEALTH_BIND, settings.HEALTH_PORT)
        await site.start()
        logging.getLogger("bot.main").info(
            "Webhook server started on %s:%d", settings.HEALTH_BIND, settings.HEALTH_PORT
        )

        # Keep running the aiohttp server until stopped
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            downloader.shutdown()
            await runner.cleanup()
            await bot.session.close()
            file_handler.close()

    else:
        # Long Polling fallback for local dev
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, settings.HEALTH_BIND, settings.HEALTH_PORT)
        await site.start()
        logging.getLogger("bot.main").info(
            "Health server (polling) started on %s:%d", settings.HEALTH_BIND, settings.HEALTH_PORT
        )

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
