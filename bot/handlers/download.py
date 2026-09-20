from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Optional

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

# Strong references to active background tasks to prevent garbage collection
active_tasks: set[asyncio.Task[Any]] = set()

_URL_RE = re.compile(
    r"https?://(www\.)?(instagram\.com/(reel|p)/[^/\s?]+|x\.com/[^/\s]+/status/\d+|twitter\.com/[^/\s]+/status/\d+)",
    re.IGNORECASE,
)


def _get_media_type(path: str) -> str:
    ext = path.lower()
    if ext.endswith((".jpg", ".jpeg", ".png")):
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

    task = asyncio.create_task(_process_download(message, downloader, url, user_id))
    active_tasks.add(task)
    task.add_done_callback(active_tasks.discard)


async def _process_download(
    message: types.Message, downloader: DownloaderWrapper, url: str, user_id: int
) -> None:
    status_msg: Optional[types.Message] = None
    result: Optional[DownloadResult] = None
    try:
        status_msg = await message.reply("⏳ Downloading...")
        result = await downloader.download_url(url, user_id)

        if result.success and result.file_paths:
            valid_paths = [p for p in result.file_paths if p.exists()]
            if not valid_paths:
                if status_msg:
                    await status_msg.edit_text("❌ Downloaded file could not be found on disk.")
                return

            total_size_mb = sum(p.stat().st_size for p in valid_paths) / (1024 * 1024)

            # Check if any single file exceeds Telegram limit
            if any(
                p.stat().st_size / (1024 * 1024) > settings.MAX_FILE_SIZE_MB for p in valid_paths
            ):
                if status_msg:
                    await status_msg.edit_text(
                        f"⚠️ File exceeds maximum allowed size of {settings.MAX_FILE_SIZE_MB} MB."
                    )
                return

            caption = f"<code>{url}</code>\n" f"Total Size: {total_size_mb:.1f} MB" + (
                f"\nResolution: {result.resolution}" if result.resolution else ""
            )

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
            else:
                # Telegram limit is 10 items per media group; batch into chunks of 10
                chunk_size = 10
                chunks = [
                    valid_paths[i : i + chunk_size] for i in range(0, len(valid_paths), chunk_size)
                ]

                for chunk_idx, chunk in enumerate(chunks):
                    media_group: list[Any] = []
                    for idx, p in enumerate(chunk):
                        media_type = _get_media_type(p.name)
                        fs_file = FSInputFile(p)

                        item_caption = (
                            f"{caption} (Part {chunk_idx + 1}/{len(chunks)})"
                            if (idx == 0 and len(chunks) > 1)
                            else (caption if idx == 0 else None)
                        )

                        media: Any
                        if media_type == "photo":
                            media = InputMediaPhoto(media=fs_file, caption=item_caption)
                        elif media_type == "video":
                            media = InputMediaVideo(media=fs_file, caption=item_caption)
                        elif media_type == "audio":
                            media = InputMediaAudio(media=fs_file, caption=item_caption)
                        else:
                            media = InputMediaDocument(media=fs_file, caption=item_caption)

                        media_group.append(media)

                    await message.reply_media_group(media=media_group)

            if status_msg:
                await status_msg.edit_text(
                    f"✅ Done ({total_size_mb:.1f} MB, {len(valid_paths)} files)"
                )

        else:
            if status_msg:
                await status_msg.edit_text(f"❌ Failed: {result.error or 'Unknown error'}")

    except Exception as exc:
        logger.exception("Download failed for %s", url)
        if status_msg:
            await status_msg.edit_text(f"❌ Error: {exc}")
    finally:
        if result:
            result.cleanup()
