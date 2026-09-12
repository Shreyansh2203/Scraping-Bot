from pathlib import Path

import pytest

from core.downloader_wrapper import SUPPORTED_EXTENSIONS, DownloaderWrapper, DownloadResult


@pytest.fixture
def tmp_dirs(tmp_path):
    output_dir = tmp_path / "downloads"
    output_dir.mkdir()
    state_file = tmp_path / "state.json"
    return output_dir, state_file


def test_normalize_url():
    wrapper = DownloaderWrapper(
        output_dir=Path("downloads"),
        state_file=Path("state.json"),
    )

    assert wrapper._normalize("https://www.Instagram.com/reel/ABC123/") == "https://instagram.com/reel/ABC123"
    assert wrapper._normalize("HTTPS://X.COM/user/status/123456/") == "https://x.com/user/status/123456"
    assert wrapper._normalize("https://example.com/") == "https://example.com"


def test_supported_extensions():
    assert ".mp4" in SUPPORTED_EXTENSIONS
    assert ".mkv" in SUPPORTED_EXTENSIONS
    assert ".webm" in SUPPORTED_EXTENSIONS
    assert ".txt" not in SUPPORTED_EXTENSIONS


def test_download_result_defaults():
    result = DownloadResult(success=False)
    assert result.success is False
    assert result.file_path is None
    assert result.size == 0
    assert result.resolution is None
    assert result.error is None
    assert result.verified is False


def test_download_result_success():
    result = DownloadResult(
        success=True,
        file_path=Path("/tmp/test.mp4"),
        size=1024,
        resolution="1920x1080",
        format_id="best[ext=mp4]",
        verified=True,
    )
    assert result.success is True
    assert result.file_path == Path("/tmp/test.mp4")
    assert result.size == 1024
    assert result.resolution == "1920x1080"
    assert result.verified is True


def test_state_persistence(tmp_dirs):
    output_dir, state_file = tmp_dirs
    wrapper = DownloaderWrapper(
        output_dir=output_dir,
        state_file=state_file,
        concurrent=1,
    )

    url = "https://instagram.com/reel/ABC123"
    wrapper._save_state()

    wrapper2 = DownloaderWrapper(
        output_dir=output_dir,
        state_file=state_file,
        concurrent=1,
    )
    assert wrapper2.is_completed(url) is False
