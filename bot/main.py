from __future__ import annotations

import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from core.config import settings
from core.downloader_wrapper import DownloaderWrapper
from bot.handlers import commands, download

async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
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

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        import asyncio
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped.")
