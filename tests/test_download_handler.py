import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import (
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
    User,
)

from bot.handlers.download import (
    _URL_RE,
    _get_media_type,
    _on_download_task_done,
    _process_download,
    active_tasks,
    handle_fallback,
    handle_url,
)
from core.config import settings
from core.downloader_wrapper import DownloaderWrapper, DownloadResult


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/reel/ABC123/",
        "https://www.instagram.com/reels/ABC123/",
        "https://instagram.com/p/ABC123/",
        "https://www.instagram.com/reel/ABC123",
        "https://www.instagram.com/share/reel/ABC123/",
        "https://www.instagram.com/tv/ABC123/",
        "https://x.com/user/status/1234567890",
        "https://twitter.com/user/status/1234567890",
        "https://x.com/user/status/1234567890/",
        "https://x.com/i/status/1234567890",
    ],
)
def test_url_regex_valid(url):
    assert _URL_RE.search(url) is not None


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/profile/user/",
        "https://x.com/user",
        "https://twitter.com/user",
        "not a url",
        "https://example.com",
    ],
)
def test_url_regex_invalid(url):
    assert _URL_RE.search(url) is None


def test_url_regex_extract():
    text = (
        "Check this: https://www.instagram.com/reel/ABC123/ and this https://x.com/user/status/123/"
    )
    matches = [m.group(0) for m in _URL_RE.finditer(text)]
    assert len(matches) == 2
    assert matches[0] == "https://www.instagram.com/reel/ABC123"
    assert matches[1] == "https://x.com/user/status/123"


def test_get_media_type():
    assert _get_media_type("photo.jpg") == "photo"
    assert _get_media_type("photo.png") == "photo"
    assert _get_media_type("video.mp4") == "video"
    assert _get_media_type("video.mkv") == "video"
    assert _get_media_type("audio.mp3") == "audio"
    assert _get_media_type("audio.m4a") == "audio"
    assert _get_media_type("image.webp") == "document"
    assert _get_media_type("file.txt") == "document"


@pytest.fixture
def mock_message():
    msg = MagicMock(spec=Message)
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = 12345
    msg.text = "https://www.instagram.com/reel/ABC123/"
    msg.caption = None
    msg.reply = AsyncMock()
    msg.reply_photo = AsyncMock()
    msg.reply_video = AsyncMock()
    msg.reply_audio = AsyncMock()
    msg.reply_document = AsyncMock()
    msg.reply_media_group = AsyncMock()
    return msg


async def test_handle_url_spawns_task(mock_message):
    mock_downloader = MagicMock(spec=DownloaderWrapper)
    initial_tasks = len(active_tasks)

    with patch("bot.handlers.download._process_download", new_callable=AsyncMock):
        await handle_url(mock_message, mock_downloader)
        assert len(active_tasks) == initial_tasks + 1

    # Task completes and cleans itself up
    tasks = [t for t in active_tasks if not t.done()]
    if tasks:
        await asyncio.gather(*tasks)
    await asyncio.sleep(0)
    assert len(active_tasks) == initial_tasks


async def test_handle_url_no_match(mock_message):
    mock_message.text = "Just a message without URL"
    mock_downloader = MagicMock(spec=DownloaderWrapper)
    initial_tasks = len(active_tasks)

    await handle_url(mock_message, mock_downloader)
    assert len(active_tasks) == initial_tasks


async def test_handle_url_logs_unexpected_task_failure(mock_message, caplog):
    mock_downloader = MagicMock(spec=DownloaderWrapper)

    with patch(
        "bot.handlers.download._process_download", new_callable=AsyncMock, side_effect=OSError
    ):
        await handle_url(mock_message, mock_downloader)
        tasks = list(active_tasks)
        for task in tasks:
            await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

    assert "Download task terminated unexpectedly" in caplog.text
    assert not active_tasks


async def test_process_download_single_video(mock_message, tmp_path):
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"x" * 1024)

    status_msg = MagicMock(spec=Message)
    status_msg.edit_text = AsyncMock()
    mock_message.reply.return_value = status_msg

    downloader = MagicMock(spec=DownloaderWrapper)
    res = DownloadResult(
        success=True,
        file_paths=[video_file],
        size=1024,
        resolution="1920x1080",
        verified=True,
    )
    downloader.download_url = AsyncMock(return_value=res)

    await _process_download(mock_message, downloader, "https://x.com/user/status/123", 12345)

    mock_message.reply_video.assert_called_once()
    status_msg.edit_text.assert_called_once()
    assert "Done" in status_msg.edit_text.call_args[0][0]


async def test_process_download_single_photo(mock_message, tmp_path):
    photo_file = tmp_path / "photo.jpg"
    photo_file.write_bytes(b"x" * 1024)

    status_msg = MagicMock(spec=Message)
    status_msg.edit_text = AsyncMock()
    mock_message.reply.return_value = status_msg

    downloader = MagicMock(spec=DownloaderWrapper)
    res = DownloadResult(success=True, file_paths=[photo_file], size=1024, verified=True)
    downloader.download_url = AsyncMock(return_value=res)

    await _process_download(mock_message, downloader, "https://x.com/user/status/123", 12345)

    mock_message.reply_photo.assert_called_once()


async def test_process_download_single_audio(mock_message, tmp_path):
    audio_file = tmp_path / "sound.mp3"
    audio_file.write_bytes(b"x" * 1024)

    status_msg = MagicMock(spec=Message)
    status_msg.edit_text = AsyncMock()
    mock_message.reply.return_value = status_msg

    downloader = MagicMock(spec=DownloaderWrapper)
    res = DownloadResult(success=True, file_paths=[audio_file], size=1024, verified=True)
    downloader.download_url = AsyncMock(return_value=res)

    await _process_download(mock_message, downloader, "https://x.com/user/status/123", 12345)

    mock_message.reply_audio.assert_called_once()


async def test_process_download_single_document(mock_message, tmp_path):
    doc_file = tmp_path / "image.webp"
    doc_file.write_bytes(b"x" * 1024)

    status_msg = MagicMock(spec=Message)
    status_msg.edit_text = AsyncMock()
    mock_message.reply.return_value = status_msg

    downloader = MagicMock(spec=DownloaderWrapper)
    res = DownloadResult(success=True, file_paths=[doc_file], size=1024, verified=True)
    downloader.download_url = AsyncMock(return_value=res)

    await _process_download(mock_message, downloader, "https://x.com/user/status/123", 12345)

    mock_message.reply_document.assert_called_once()


async def test_process_download_media_group_chunked(mock_message, tmp_path):
    files = []
    for i in range(12):  # 12 files -> 2 chunks (10 and 2)
        f = tmp_path / f"img_{i}.jpg"
        f.write_bytes(b"x" * 500)
        files.append(f)

    status_msg = MagicMock(spec=Message)
    status_msg.edit_text = AsyncMock()
    mock_message.reply.return_value = status_msg

    downloader = MagicMock(spec=DownloaderWrapper)
    res = DownloadResult(success=True, file_paths=files, size=6000, verified=True)
    downloader.download_url = AsyncMock(return_value=res)

    await _process_download(mock_message, downloader, "https://x.com/user/status/123", 12345)

    assert mock_message.reply_media_group.call_count == 2
    assert all(
        2 <= len(call.kwargs["media"]) <= 10
        for call in mock_message.reply_media_group.call_args_list
    )
    status_msg.edit_text.assert_called_once()
    assert "Done" in status_msg.edit_text.call_args[0][0]


async def test_process_download_trailing_single_item_chunk(mock_message, tmp_path):
    files = []
    for i in range(11):  # 11 files -> chunks of 10 and 1
        f = tmp_path / f"img_{i}.jpg"
        f.write_bytes(b"x" * 500)
        files.append(f)

    status_msg = MagicMock(spec=Message)
    status_msg.edit_text = AsyncMock()
    mock_message.reply.return_value = status_msg

    downloader = MagicMock(spec=DownloaderWrapper)
    res = DownloadResult(success=True, file_paths=files, size=5500, verified=True)
    downloader.download_url = AsyncMock(return_value=res)

    await _process_download(mock_message, downloader, "https://x.com/user/status/123", 12345)

    # Telegram rejects media groups with a single item, so the 11th file is sent on its own
    assert mock_message.reply_media_group.call_count == 1
    mock_message.reply_photo.assert_called_once()
    assert "Part 2/2" in mock_message.reply_photo.call_args.kwargs["caption"]


async def test_process_download_escapes_html_in_error_caption(mock_message):
    status_msg = MagicMock(spec=Message)
    status_msg.edit_text = AsyncMock()
    mock_message.reply.return_value = status_msg

    downloader = MagicMock(spec=DownloaderWrapper)
    res = DownloadResult(success=False, error="<b>ERROR</b>: video unavailable & private")
    downloader.download_url = AsyncMock(return_value=res)

    await _process_download(mock_message, downloader, "https://x.com/user/status/123", 12345)

    text = status_msg.edit_text.call_args[0][0]
    assert "<b>" not in text
    assert "&lt;b&gt;ERROR&lt;/b&gt;" in text
    assert "unavailable &amp; private" in text


async def test_process_download_escapes_html_in_exception_caption(mock_message):
    status_msg = MagicMock(spec=Message)
    status_msg.edit_text = AsyncMock()
    mock_message.reply.return_value = status_msg

    downloader = MagicMock(spec=DownloaderWrapper)
    downloader.download_url = AsyncMock(side_effect=RuntimeError("<tg-send>bad request</tg-send>"))

    await _process_download(mock_message, downloader, "https://x.com/user/status/123", 12345)

    text = status_msg.edit_text.call_args[0][0]
    assert "<tg-send>" not in text
    assert "&lt;tg-send&gt;" in text


async def test_process_download_escapes_html_in_url_caption(mock_message, tmp_path):
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"x" * 1024)

    status_msg = MagicMock(spec=Message)
    status_msg.edit_text = AsyncMock()
    mock_message.reply.return_value = status_msg

    downloader = MagicMock(spec=DownloaderWrapper)
    res = DownloadResult(
        success=True,
        file_paths=[video_file],
        size=1024,
        resolution="1920x1080 <hdr>",
        verified=True,
    )
    downloader.download_url = AsyncMock(return_value=res)

    await _process_download(mock_message, downloader, "https://x.com/user/status/123", 12345)

    caption = mock_message.reply_video.call_args.kwargs["caption"]
    assert "<hdr>" not in caption
    assert "1920x1080 &lt;hdr&gt;" in caption


async def test_process_download_mixed_media_album(mock_message, tmp_path):
    files = []
    for name in ("img.jpg", "clip.mp4", "sound.mp3", "sticker.webp"):
        f = tmp_path / name
        f.write_bytes(b"x" * 500)
        files.append(f)

    status_msg = MagicMock(spec=Message)
    status_msg.edit_text = AsyncMock()
    mock_message.reply.return_value = status_msg

    downloader = MagicMock(spec=DownloaderWrapper)
    res = DownloadResult(success=True, file_paths=files, size=2000, verified=True)
    downloader.download_url = AsyncMock(return_value=res)

    await _process_download(mock_message, downloader, "https://x.com/user/status/123", 12345)

    mock_message.reply_media_group.assert_called_once()
    media = mock_message.reply_media_group.call_args.kwargs["media"]
    assert [type(item) for item in media] == [
        InputMediaPhoto,
        InputMediaVideo,
        InputMediaAudio,
        InputMediaDocument,
    ]
    assert media[0].caption and "Total Size" in media[0].caption
    assert all(item.caption is None for item in media[1:])


async def test_on_download_task_done_ignores_cancelled_tasks():
    task = asyncio.create_task(asyncio.sleep(30))
    active_tasks.add(task)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

    _on_download_task_done(task)

    assert task not in active_tasks


async def test_process_download_oversized(mock_message, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 0)
    big_file = tmp_path / "big.mp4"
    big_file.write_bytes(b"x" * 100)

    status_msg = MagicMock(spec=Message)
    status_msg.edit_text = AsyncMock()
    mock_message.reply.return_value = status_msg

    downloader = MagicMock(spec=DownloaderWrapper)
    res = DownloadResult(success=True, file_paths=[big_file], size=100, verified=True)
    downloader.download_url = AsyncMock(return_value=res)

    await _process_download(mock_message, downloader, "https://x.com/user/status/123", 12345)

    status_msg.edit_text.assert_called_once()
    assert "maximum allowed size" in status_msg.edit_text.call_args[0][0]


async def test_process_download_failure(mock_message):
    status_msg = MagicMock(spec=Message)
    status_msg.edit_text = AsyncMock()
    mock_message.reply.return_value = status_msg

    downloader = MagicMock(spec=DownloaderWrapper)
    res = DownloadResult(success=False, error="Post is private")
    downloader.download_url = AsyncMock(return_value=res)

    await _process_download(mock_message, downloader, "https://x.com/user/status/123", 12345)

    status_msg.edit_text.assert_called_once_with("❌ Failed: Post is private")


async def test_process_download_exception(mock_message):
    status_msg = MagicMock(spec=Message)
    status_msg.edit_text = AsyncMock()
    mock_message.reply.return_value = status_msg

    downloader = MagicMock(spec=DownloaderWrapper)
    downloader.download_url = AsyncMock(side_effect=RuntimeError("Subprocess crashed"))

    await _process_download(mock_message, downloader, "https://x.com/user/status/123", 12345)

    status_msg.edit_text.assert_called_once_with("❌ Error: Subprocess crashed")


async def test_process_download_missing_files_on_disk(mock_message, tmp_path):
    missing_file = tmp_path / "non_existent.mp4"
    status_msg = MagicMock(spec=Message)
    status_msg.edit_text = AsyncMock()
    mock_message.reply.return_value = status_msg

    downloader = MagicMock(spec=DownloaderWrapper)
    res = DownloadResult(success=True, file_paths=[missing_file], size=1024, verified=True)
    downloader.download_url = AsyncMock(return_value=res)

    await _process_download(mock_message, downloader, "https://x.com/user/status/123", 12345)

    status_msg.edit_text.assert_called_once_with("❌ Downloaded file could not be found on disk.")


async def test_handle_fallback(mock_message):
    await handle_fallback(mock_message)
    mock_message.reply.assert_called_once()
    assert "Send me an Instagram or Twitter/X link" in mock_message.reply.call_args[0][0]
