from __future__ import annotations

import asyncio
import html
import logging
import re
from pathlib import Path
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
    r"https?://(?:www\.)?(?:instagram\.com/(?:(?:share/)?(?:reel|reels|p|tv)/[^/\s?]+)|(?:x|twitter)\.com/(?:[^/\s]+/status/\d+|i/status/\d+))",
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


async def _reply_media(message: types.Message, path: Path, caption: str) -> None:
    input_file = FSInputFile(path)
    media_type = _get_media_type(path.name)
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


def _on_download_task_done(task: asyncio.Task[Any]) -> None:
    active_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Download task terminated unexpectedly", exc_info=exc)


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
    task.add_done_callback(_on_download_task_done)


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

            escaped_url = html.escape(url)
            caption = f"<code>{escaped_url}</code>\nTotal Size: {total_size_mb:.1f} MB" + (
                f"\nResolution: {html.escape(result.resolution)}" if result.resolution else ""
            )

            if len(valid_paths) == 1:
                await _reply_media(message, valid_paths[0], caption)
            else:
                # Telegram limit is 10 items per media group; batch into chunks of 10
                chunk_size = 10
                chunks = [
                    valid_paths[i : i + chunk_size] for i in range(0, len(valid_paths), chunk_size)
                ]

                for chunk_idx, chunk in enumerate(chunks):
                    chunk_caption = (
                        f"{caption} (Part {chunk_idx + 1}/{len(chunks)})"
                        if len(chunks) > 1
                        else caption
                    )

                    # A media group needs at least 2 items, so send leftovers on their own
                    if len(chunk) == 1:
                        await _reply_media(message, chunk[0], chunk_caption)
                        continue

                    media_group: list[Any] = []
                    for idx, p in enumerate(chunk):
                        media_type = _get_media_type(p.name)
                        fs_file = FSInputFile(p)
                        item_caption = chunk_caption if idx == 0 else None

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
                detail = html.escape(result.error or "Unknown error")
                await status_msg.edit_text(f"❌ Failed: {detail}")

    except Exception:
        # The exception text is for the log, not for the chat: str(exc) can carry the
        # container's absolute job paths or a fragment of the extractor's stderr, and a
        # chat is not a place to publish those. The user gets the outcome; the reason
        # is in the log line above, with the same correlation.
        logger.exception("Download failed for %s", url)
        if status_msg:
            await status_msg.edit_text(
                "❌ Something went wrong handling that link. The failure has been logged."
            )
    finally:
        if result:
            result.cleanup()


@router.message()
async def handle_fallback(message: types.Message) -> None:
    await message.reply(
        "👋 Send me an Instagram or Twitter/X link to download media, or /help for more info."
    )
