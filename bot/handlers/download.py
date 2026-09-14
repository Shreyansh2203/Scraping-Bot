from __future__ import annotations

import logging
import re
from typing import Optional

from aiogram import Router, types
from aiogram.types import FSInputFile

from core.config import settings
from core.downloader_wrapper import DownloadResult, DownloaderWrapper

logger = logging.getLogger("bot.handlers.download")
router = Router()

_URL_RE = re.compile(
    r"https?://(www\.)?(instagram\.com/(reel|p)/[^/]+|x\.com/[^/]+/status/\d+|twitter\.com/[^/]+/status/\d+)",
    re.IGNORECASE,
)


@router.message(lambda m: bool(_URL_RE.search((m.text or m.caption or ""))))
async def handle_url(message: types.Message, downloader: DownloaderWrapper) -> None:
    text: Optional[str] = message.text or message.caption
    match = _URL_RE.search(text or "")
    if not match:
        return
    url = match.group(0)
    status_msg: Optional[types.Message] = None
    result: Optional[DownloadResult] = None
    try:
        status_msg = await message.reply("⏳ Downloading...")
        user_id = message.from_user.id if message.from_user else message.chat.id
        result = await downloader.download_url(url, user_id)

        if result.success and result.file_path and result.file_path.exists():
            size_mb = result.file_path.stat().st_size / (1024 * 1024)
            if size_mb > settings.MAX_FILE_SIZE_MB:
                if status_msg:
                    await status_msg.edit_text(
                        f"⚠️ Downloaded, but file is too large for Telegram: {size_mb:.1f} MB"
                    )
                result.file_path.unlink(missing_ok=True)
                return

            caption = f"<code>{url}</code>\n" f"Size: {size_mb:.1f} MB" + (
                f"\nResolution: {result.resolution}" if result.resolution else ""
            )

            await message.reply_document(
                FSInputFile(result.file_path),
                caption=caption,
                disable_content_type_detection=False,
            )
            if status_msg:
                await status_msg.edit_text(f"✅ Done ({size_mb:.1f} MB)")
            result.file_path.unlink(missing_ok=True)
        else:
            if status_msg:
                await status_msg.edit_text(f"❌ Failed: {result.error or 'Unknown error'}")
    except Exception as exc:
        logger.exception("Download failed for %s", url)
        if status_msg:
            await status_msg.edit_text(f"❌ Error: {exc}")
        if result and result.file_path and result.file_path.exists():
            result.file_path.unlink(missing_ok=True)
