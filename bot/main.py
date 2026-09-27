from __future__ import annotations

import asyncio
import importlib.metadata
import json
import logging
import signal
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType
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


def _resolve_version() -> str:
    try:
        return importlib.metadata.version("scraping-bot")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0+unknown"


__version__ = _resolve_version()
_start_time = time.monotonic()

DOWNLOADER_KEY: web.AppKey[DownloaderWrapper] = web.AppKey("downloader")


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
    downloader = request.app[DOWNLOADER_KEY]
    stats = {
        "status": "ok",
        "version": __version__,
        "uptime_seconds": int(time.monotonic() - _start_time),
        "concurrent": downloader.concurrent,
        "active_downloads": len(download.active_tasks),
        "output_dir": str(downloader.output_dir),
    }
    return web.json_response(stats)


async def metrics_handler(request: web.Request) -> web.Response:
    """Prometheus-compatible plain text metrics endpoint."""
    downloader = request.app[DOWNLOADER_KEY]
    uptime = time.monotonic() - _start_time
    active = len(download.active_tasks)

    lines = [
        "# HELP scraping_bot_uptime_seconds Bot uptime in seconds.",
        "# TYPE scraping_bot_uptime_seconds gauge",
        f"scraping_bot_uptime_seconds {uptime:.2f}",
        "# HELP scraping_bot_active_downloads Currently active download tasks.",
        "# TYPE scraping_bot_active_downloads gauge",
        f"scraping_bot_active_downloads {active}",
        "# HELP scraping_bot_concurrent_limit Maximum concurrent downloads configured.",
        "# TYPE scraping_bot_concurrent_limit gauge",
        f"scraping_bot_concurrent_limit {downloader.concurrent}",
    ]
    return web.Response(text="\n".join(lines) + "\n", content_type="text/plain; version=0.0.4")


async def on_startup(bot: Bot) -> None:
    if settings.WEBHOOK_URL:
        logging.getLogger("bot.main").info("Setting webhook to %s", settings.WEBHOOK_URL)
        await bot.set_webhook(settings.WEBHOOK_URL, drop_pending_updates=False)
    else:
        logging.getLogger("bot.main").info("Deleting webhook for polling")
        await bot.delete_webhook(drop_pending_updates=False)


async def _shutdown(
    downloader: DownloaderWrapper,
    runner: web.AppRunner,
    bot: Bot,
    log_handlers: tuple[logging.Handler, ...],
) -> None:
    downloader.shutdown()
    if download.active_tasks:
        await asyncio.wait(download.active_tasks, timeout=5)
    await runner.cleanup()
    await bot.session.close()
    for log_handler in log_handlers:
        log_handler.close()
        logging.getLogger().removeHandler(log_handler)


def _raise_system_exit(signum: int, frame: FrameType | None) -> None:
    """Interpreter-level fallback for platforms without loop-level signal handlers."""
    raise SystemExit(0)


def _make_shutdown_handler(main_task: asyncio.Task[Any]) -> Callable[[signal.Signals], None]:
    """Build the one-shot callback that cancels the main task on SIGTERM/SIGINT.

    Cancelling unwinds ``main`` through its ``finally`` block, so the download drain
    and the resource cleanup always run. A signal raised from a ``signal.signal``
    handler instead jumps out of the event loop mid-step, which skips that block
    entirely. Repeat signals are ignored so a second one cannot abort a drain that is
    already under way; the platform SIGKILLs a process that overruns its grace period.
    """
    requested = False

    def request_shutdown(sig: signal.Signals) -> None:
        nonlocal requested
        if requested or main_task.done():
            return
        requested = True
        logging.getLogger("bot.main").info(
            "Received %s, draining active downloads before shutdown", sig.name
        )
        main_task.cancel()

    return request_shutdown


def _install_signal_handlers(
    loop: asyncio.AbstractEventLoop, main_task: asyncio.Task[Any] | None
) -> None:
    """Route SIGTERM/SIGINT through the loop so shutdown runs ``main``'s ``finally``.

    Loop-level signal handlers are POSIX-only. Elsewhere the interpreter-level handler
    is installed instead, which still stops the process, so the bot keeps running as
    before on platforms without ``add_signal_handler``.
    """
    if main_task is None:
        return

    logger = logging.getLogger("bot.main")
    request_shutdown = _make_shutdown_handler(main_task)
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, request_shutdown, sig)
        except NotImplementedError:
            with suppress(ValueError, OSError, RuntimeError):
                signal.signal(sig, _raise_system_exit)
        except (RuntimeError, ValueError) as exc:
            logger.warning("Could not install %s handler: %s", sig.name, exc)


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

    # Register Auth before Throttle
    dp.message.middleware(throttle.AuthMiddleware())
    dp.message.middleware(throttle.ThrottleMiddleware())

    app = web.Application()
    app[DOWNLOADER_KEY] = downloader
    app.router.add_get("/health", health_handler)
    app.router.add_get("/metrics", metrics_handler)

    use_webhook = bool(settings.WEBHOOK_URL)
    if use_webhook:
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
        "Health server started on %s:%d (%s mode)",
        settings.HEALTH_BIND,
        settings.HEALTH_PORT,
        "webhook" if use_webhook else "polling",
    )

    try:
        _install_signal_handlers(asyncio.get_running_loop(), asyncio.current_task())
        if use_webhook:
            with suppress(asyncio.CancelledError):
                while True:
                    await asyncio.sleep(3600)
        else:
            await dp.start_polling(bot)
    finally:
        await _shutdown(downloader, runner, bot, (handler, file_handler))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
        print("Bot stopped.")
