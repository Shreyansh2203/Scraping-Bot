from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.downloader_wrapper import SUPPORTED_EXTENSIONS, DownloaderWrapper, DownloadResult


@pytest.fixture
def tmp_dirs(tmp_path):
    output_dir = tmp_path / "downloads"
    output_dir.mkdir()
    return output_dir


def test_normalize_url():
    wrapper = DownloaderWrapper(output_dir=Path("downloads"))
    assert (
        wrapper._normalize("https://www.Instagram.com/reel/ABC123/")
        == "https://instagram.com/reel/ABC123"
    )
    assert (
        wrapper._normalize("HTTPS://X.COM/user/status/123456/")
        == "https://x.com/user/status/123456"
    )
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
    assert result.file_paths == []
    assert result.size == 0
    assert result.resolution is None
    assert result.error is None
    assert result.verified is False


def test_download_result_cleanup(tmp_path):
    job_dir = tmp_path / "job_123"
    job_dir.mkdir()
    test_file = job_dir / "video.mp4"
    test_file.write_bytes(b"content")

    result = DownloadResult(
        success=True,
        file_paths=[test_file],
        job_dir=job_dir,
    )
    assert test_file.exists()
    assert job_dir.exists()

    result.cleanup()

    assert not test_file.exists()
    assert not job_dir.exists()


def test_downloader_shutdown():
    wrapper = DownloaderWrapper(output_dir=Path("downloads"))
    assert not wrapper._shutdown.is_set()
    wrapper.shutdown()
    assert wrapper._shutdown.is_set()


def test_build_command():
    wrapper = DownloaderWrapper(output_dir=Path("downloads"))
    cmd = wrapper._build_command("https://instagram.com/reel/ABC123")
    assert "yt_dlp" in cmd
    assert "https://instagram.com/reel/ABC123" in cmd
    assert "--output" in cmd


def test_parse_output_success_variations():
    wrapper = DownloaderWrapper(output_dir=Path("downloads"))

    # 4 prints: file, size, res, format_id
    out4 = "video.mp4\n1048576\n1920x1080\n22"
    res4 = wrapper._parse_output(out4, 0)
    assert res4["success"] is True
    assert res4["file"] == "video.mp4"
    assert res4["size"] == 1048576
    assert res4["resolution"] == "1920x1080"
    assert res4["format_id"] == "22"

    # 3 prints: file, size, format_id
    out3 = "video.mp4\n1048576\n22"
    res3 = wrapper._parse_output(out3, 0)
    assert res3["success"] is True
    assert res3["file"] == "video.mp4"
    assert res3["size"] == 1048576

    # 2 prints: file, size
    out2 = "video.mp4\n1048576"
    res2 = wrapper._parse_output(out2, 0)
    assert res2["success"] is True
    assert res2["file"] == "video.mp4"
    assert res2["size"] == 1048576

    # 1 print: file
    out1 = "video.mp4"
    res1 = wrapper._parse_output(out1, 0)
    assert res1["success"] is True
    assert res1["file"] == "video.mp4"

    # Empty prints
    res0 = wrapper._parse_output("", 0)
    assert res0["success"] is False
    assert "no output file found" in res0["error"]


def test_parse_output_errors():
    wrapper = DownloaderWrapper(output_dir=Path("downloads"))

    # Returncode 1
    out_err1 = "[download] 10%\nERROR: Video unavailable"
    res_err1 = wrapper._parse_output(out_err1, 1)
    assert res_err1["success"] is False
    assert "Video unavailable" in res_err1["error"]

    # Returncode 2
    out_err2 = "Fatal failure"
    res_err2 = wrapper._parse_output(out_err2, 2)
    assert res_err2["success"] is False
    assert "Fatal failure" in res_err2["error"]


def test_find_output_file(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path)

    # 1. Matching ytdlp_id
    f1 = tmp_path / "video [12345678901].mp4"
    f1.write_bytes(b"data")
    found1 = wrapper._find_output_file(
        "https://x.com/user/status/123", tmp_path, reported_filepath="out [12345678901].mp4"
    )
    assert found1 == f1

    # 2. Matching url_id
    f2 = tmp_path / "post_999888777.mp4"
    f2.write_bytes(b"data")
    found2 = wrapper._find_output_file(
        "https://x.com/user/status/999888777", tmp_path, reported_filepath=None
    )
    assert found2 == f2

    # 3. Any recent file
    found3 = wrapper._find_output_file(
        "https://instagram.com/reel/XYZ", tmp_path, reported_filepath=None
    )
    assert found3 in (f1, f2)


def test_find_output_file_oserror(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path)
    mock_dir = MagicMock(spec=Path)
    mock_dir.iterdir.side_effect = OSError("Permission denied")
    assert wrapper._find_output_file("https://x.com/123", output_dir=mock_dir) is None


async def test_probe_resolution_success(tmp_path):
    video = tmp_path / "test.mp4"
    video.write_bytes(b"data")

    with (
        patch("shutil.which", return_value="/usr/bin/ffprobe"),
        patch("asyncio.create_subprocess_exec") as mock_exec,
    ):
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"1920x1080\n", b""))
        proc.returncode = 0
        mock_exec.return_value = proc

        res = await DownloaderWrapper._probe_resolution(video)
        assert res == "1920x1080"


async def test_probe_resolution_no_ffprobe(tmp_path):
    video = tmp_path / "test.mp4"
    with patch("shutil.which", return_value=None):
        res = await DownloaderWrapper._probe_resolution(video)
        assert res is None


async def test_run_gallery_dl_success(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path)
    job_dir = tmp_path / "job_test"
    job_dir.mkdir()

    # Pre-populate a file that gallery-dl will "download"
    sub_dir = job_dir / "instagram"
    sub_dir.mkdir()
    dl_file = sub_dir / "image.jpg"
    dl_file.write_bytes(b"image data")

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.returncode = 0
        mock_exec.return_value = proc

        res = await wrapper._run_gallery_dl("https://instagram.com/p/ABC", job_dir)
        assert res.success is True
        assert len(res.file_paths) == 1
        assert res.file_paths[0].name == "image.jpg"


async def test_run_gallery_dl_nonzero_exit(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path)
    job_dir = tmp_path / "job_test"
    job_dir.mkdir()

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"", b"404 Not Found"))
        proc.returncode = 1
        mock_exec.return_value = proc

        res = await wrapper._run_gallery_dl("https://instagram.com/p/ABC", job_dir)
        assert res.success is False
        assert "gallery-dl failed" in res.error


async def test_download_async_success(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path, min_file_size=10)

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = MagicMock()
        # Output says video.mp4 was written
        proc.communicate = AsyncMock(return_value=(b"video.mp4\n2048\n1920x1080\n22\n", b""))
        proc.returncode = 0
        mock_exec.return_value = proc

        # Intercept to create the actual file inside the job_dir
        async def side_effect(*args, **kwargs):
            cwd = Path(kwargs["cwd"])
            (cwd / "video.mp4").write_bytes(b"x" * 2048)
            return proc

        mock_exec.side_effect = side_effect

        res = await wrapper.download_url("https://x.com/user/status/123", 12345)
        assert res.success is True
        assert res.size == 2048
        assert res.resolution == "1920x1080"
        assert res.job_dir is not None

        res.cleanup()
        assert not res.job_dir.exists()


async def test_download_async_shutdown(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path)
    wrapper.shutdown()

    res = await wrapper.download_url("https://x.com/user/status/123", 12345)
    assert res.success is False
    assert "cancelled by shutdown" in res.error


async def test_download_async_file_too_small(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path, min_file_size=5000)

    with (
        patch("asyncio.create_subprocess_exec") as mock_exec,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"small.mp4\n100\n", b""))
        proc.returncode = 0

        async def side_effect(*args, **kwargs):
            cwd = Path(kwargs["cwd"])
            (cwd / "small.mp4").write_bytes(b"x" * 100)
            return proc

        mock_exec.side_effect = side_effect

        with patch.object(wrapper, "_run_gallery_dl", new_callable=AsyncMock) as mock_gdl:
            mock_gdl.return_value = DownloadResult(success=False, error="gdl failed")
            res = await wrapper.download_url("https://x.com/user/status/123", 12345)
            assert res.success is False


async def test_download_async_ytdlp_fail_gallery_dl_success(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path)

    with (
        patch("asyncio.create_subprocess_exec") as mock_exec,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"", b"ERROR: Private video"))
        proc.returncode = 1
        mock_exec.return_value = proc

        with patch.object(wrapper, "_run_gallery_dl", new_callable=AsyncMock) as mock_gdl:
            gdl_res = DownloadResult(success=True, file_paths=[tmp_path / "img.jpg"], size=1000)
            mock_gdl.return_value = gdl_res

            res = await wrapper.download_url("https://instagram.com/p/ABC", 12345)
            assert res.success is True
            assert res.size == 1000
