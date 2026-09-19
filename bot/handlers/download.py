from __future__ import annotations

import logging
import re
from typing import Optional

from aiogram import Router, types
from aiogram.types import (
    FSInputFile,
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
)

from core.config import settings
from core.downloader_wrapper import DownloaderWrapper, DownloadResult

logger = logging.getLogger("bot.handlers.download")
router = Router()

_URL_RE = re.compile(
    r"https?://(www\.)?(instagram\.com/(reel|p)/[^/]+|x\.com/[^/]+/status/\d+|twitter\.com/[^/]+/status/\d+)",
    re.IGNORECASE,
)


def _get_media_type(path: str) -> str:
    ext = path.lower()
    if ext.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return "photo"
    elif ext.endswith((".mp4", ".mkv", ".webm", ".mov")):
        return "video"
    elif ext.endswith((".m4a", ".mp3", ".opus")):
        return "audio"
    return "document"


@router.message(lambda m: bool(_URL_RE.search((m.text or m.caption or ""))))
async def handle_url(message: types.Message, downloader: DownloaderWrapper) -> None:
    text: Optional[str] = message.text or message.caption
    match = _URL_RE.search(text or "")
    if not match:
        return
    url = match.group(0)
    user_id = message.from_user.id if message.from_user else message.chat.id

    import asyncio

    asyncio.create_task(_process_download(message, downloader, url, user_id))


async def _process_download(
    message: types.Message, downloader: DownloaderWrapper, url: str, user_id: int
) -> None:
    status_msg: Optional[types.Message] = None
    result: Optional[DownloadResult] = None
    try:
        status_msg = await message.reply("⏳ Downloading...")
        result = await downloader.download_url(url, user_id)

        if result.success and result.file_paths:
            # Verify total size
            total_size_mb = sum(p.stat().st_size for p in result.file_paths if p.exists()) / (
                1024 * 1024
            )
            if any(
                p.stat().st_size / (1024 * 1024) > settings.MAX_FILE_SIZE_MB
                for p in result.file_paths
                if p.exists()
            ):
                if status_msg:
                    await status_msg.edit_text(
                        "⚠️ Downloaded, but at least one file is too large for Telegram."
                    )
                for p in result.file_paths:
                    p.unlink(missing_ok=True)
                return

            caption = f"<code>{url}</code>\n" f"Total Size: {total_size_mb:.1f} MB" + (
                f"\nResolution: {result.resolution}" if result.resolution else ""
            )

            valid_paths = [p for p in result.file_paths if p.exists()]

            if len(valid_paths) == 1:
                media_type = _get_media_type(valid_paths[0].name)
                input_file = FSInputFile(valid_paths[0])
                if media_type == "photo":
                    await message.reply_photo(input_file, caption=caption)
                elif media_type == "video":
                    await message.reply_video(input_file, caption=caption)
                elif media_type == "audio":
                    await message.reply_audio(input_file, caption=caption)
                else:
                    await message.reply_document(
                        input_file,
                        caption=caption,
                        disable_content_type_detection=False,
                    )
            elif len(valid_paths) > 1:
                from typing import Any

                media_group: list[Any] = []
                for idx, p in enumerate(valid_paths[:10]):  # Telegram limit is 10 for media group
                    media_type = _get_media_type(p.name)
                    fs_file = FSInputFile(p)

                    media: Any
                    if media_type == "photo":
                        media = InputMediaPhoto(media=fs_file)
                    elif media_type == "video":
                        media = InputMediaVideo(media=fs_file)
                    elif media_type == "audio":
                        media = InputMediaAudio(media=fs_file)
                    else:
                        media = InputMediaDocument(media=fs_file)

                    if idx == 0:
                        media.caption = caption
                    media_group.append(media)
                await message.reply_media_group(media=media_group)

            if status_msg:
                await status_msg.edit_text(
                    f"✅ Done ({total_size_mb:.1f} MB, {len(valid_paths)} files)"
                )

            for p in valid_paths:
                p.unlink(missing_ok=True)
        else:
            if status_msg:
                await status_msg.edit_text(f"❌ Failed: {result.error or 'Unknown error'}")
    except Exception as exc:
        logger.exception("Download failed for %s", url)
        if status_msg:
            await status_msg.edit_text(f"❌ Error: {exc}")
        if result and result.file_paths:
            for p in result.file_paths:
                p.unlink(missing_ok=True)
