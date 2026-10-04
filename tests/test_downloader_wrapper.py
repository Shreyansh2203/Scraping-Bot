import asyncio
import importlib.util
import logging
import os
import shutil
import signal
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import core.downloader_wrapper
from core.downloader_wrapper import (
    SUPPORTED_EXTENSIONS,
    DownloaderWrapper,
    DownloadResult,
    _is_safe_url,
    _subprocess_kwargs,
    _terminate_tree,
)


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


def _gallery_dl_stub(files):
    async def side_effect(*args, **kwargs):
        target = Path(args[args.index("--directory") + 1])
        for rel, data in files.items():
            path = target / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.returncode = 0
        return proc

    return side_effect


async def test_run_gallery_dl_success(tmp_path):
    # min_file_size=0 keeps this test about collection; the floor has its own tests.
    wrapper = DownloaderWrapper(output_dir=tmp_path, min_file_size=0)
    job_dir = tmp_path / "job_test"
    job_dir.mkdir()

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.side_effect = _gallery_dl_stub({"instagram/image.jpg": b"image data"})

        res = await wrapper._run_gallery_dl("https://instagram.com/p/ABC", job_dir)
        assert res.success is True
        assert len(res.file_paths) == 1
        assert res.file_paths[0].name == "image.jpg"


async def test_run_gallery_dl_ignores_artifacts_of_previous_attempt(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path, min_file_size=0)
    job_dir = tmp_path / "job_test"
    job_dir.mkdir()
    stale = job_dir / "yt_dlp_partial.mp4"
    stale.write_bytes(b"x" * 4096)

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.side_effect = _gallery_dl_stub({"post/photo.jpg": b"image data"})

        res = await wrapper._run_gallery_dl("https://instagram.com/p/ABC", job_dir)

    assert [p.name for p in res.file_paths] == ["photo.jpg"]
    assert res.file_paths[0].parent == job_dir / "gallery_dl"
    assert stale.read_bytes() == b"x" * 4096
    assert res.job_dir == job_dir


async def test_run_gallery_dl_timeout_terminates_tree(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path, subprocess_timeout=0.01)
    job_dir = tmp_path / "job_test"
    job_dir.mkdir()

    with (
        patch("asyncio.create_subprocess_exec") as mock_exec,
        patch("core.downloader_wrapper._terminate_tree", new_callable=AsyncMock) as mock_term,
    ):
        proc = MagicMock()
        proc.communicate = AsyncMock(side_effect=TimeoutError)
        mock_exec.return_value = proc

        res = await wrapper._run_gallery_dl("https://instagram.com/p/ABC", job_dir)

    assert res.success is False
    mock_term.assert_awaited_once_with(proc)
    proc.kill.assert_not_called()


async def test_gallery_dl_command_is_bounded_by_the_same_ceiling_as_yt_dlp(tmp_path):
    """The fallback is the unbounded path, which is how a big target gets through.

    --max-filesize stops yt-dlp mid-transfer, but nothing stopped gallery-dl: a link
    that fails yt-dlp three times and then resolved to a large gallery target wrote
    to disk until SUBPROCESS_TIMEOUT fired, because the size check in
    bot/handlers/download.py only runs once the bytes are already there.
    """
    wrapper = DownloaderWrapper(output_dir=tmp_path, max_file_size_mb=50, min_file_size=0)
    job_dir = tmp_path / "job_test"
    job_dir.mkdir()

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.side_effect = _gallery_dl_stub({"instagram/image.jpg": b"image data"})

        res = await wrapper._run_gallery_dl("https://instagram.com/p/ABC", job_dir)

    assert res.success is True
    cmd = list(mock_exec.call_args.args)
    assert cmd[cmd.index("--filesize-max") + 1] == str(50 * 1024 * 1024)


async def test_a_timeout_that_exhausts_its_retries_says_so(tmp_path):
    """The reason the user is shown must not be a blank.

    TimeoutError has an empty str(), so str(exc) produced "" and the message ended
    at the colon: "Transient error after 4 attempts: ". The exception name is what
    the user needs to see.
    """
    wrapper = DownloaderWrapper(output_dir=tmp_path, subprocess_timeout=0.01)
    job_dir = tmp_path / "job_test"
    job_dir.mkdir()

    with (
        patch("asyncio.create_subprocess_exec") as mock_exec,
        patch("core.downloader_wrapper._terminate_tree", new_callable=AsyncMock),
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(wrapper, "_run_gallery_dl", new_callable=AsyncMock) as mock_gdl,
    ):
        proc = MagicMock()
        proc.communicate = AsyncMock(side_effect=TimeoutError)
        mock_exec.return_value = proc

        res = await wrapper.download_url("https://x.com/user/status/1", 1)

    assert res.success is False
    assert res.error.endswith("TimeoutError"), res.error
    assert not res.error.endswith(": "), "the reason is blank after the colon"
    mock_gdl.assert_not_awaited()


async def test_run_gallery_dl_no_supported_files(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path)
    job_dir = tmp_path / "job_test"
    job_dir.mkdir()

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.side_effect = _gallery_dl_stub({"post/notes.txt": b"nope"})

        res = await wrapper._run_gallery_dl("https://instagram.com/p/ABC", job_dir)

    assert res.success is False
    assert res.error == "gallery-dl returned no supported files"


async def test_run_gallery_dl_flattens_nested_dirs(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path, min_file_size=0)
    job_dir = tmp_path / "job_test"
    job_dir.mkdir()

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.side_effect = _gallery_dl_stub({"post1/img1.jpg": b"a", "post2/img1.jpg": b"b"})

        res = await wrapper._run_gallery_dl("https://instagram.com/p/ABC", job_dir)

    assert res.success is True
    assert [p.name for p in res.file_paths] == ["img1.jpg", "img1_1.jpg"]
    assert res.size == 2


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


async def test_run_gallery_dl_applies_the_same_min_file_size_floor_as_yt_dlp(tmp_path):
    """The yt-dlp path refuses a file under min_file_size; the fallback used to accept it.

    A post whose only download is a 10-byte stub is a failed download, and reporting it
    as a success sends an unusable file to Telegram.
    """
    wrapper = DownloaderWrapper(output_dir=tmp_path, min_file_size=5000)
    job_dir = tmp_path / "job_test"
    job_dir.mkdir()

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.side_effect = _gallery_dl_stub({"post/tiny.jpg": b"0123456789"})

        res = await wrapper._run_gallery_dl("https://instagram.com/p/ABC", job_dir)

    assert res.success is False
    assert res.file_paths == []
    assert res.size == 0
    assert "File too small" in res.error
    assert not (job_dir / "gallery_dl" / "tiny.jpg").exists()


async def test_run_gallery_dl_keeps_the_pages_of_a_mixed_post_that_meet_the_floor(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path, min_file_size=1000)
    job_dir = tmp_path / "job_test"
    job_dir.mkdir()

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.side_effect = _gallery_dl_stub(
            {
                "post/real1.jpg": b"x" * 2048,
                "post/stub.jpg": b"x" * 10,
                "post/real2.jpg": b"y" * 4096,
            }
        )

        res = await wrapper._run_gallery_dl("https://instagram.com/p/ABC", job_dir)

    assert res.success is True
    assert [p.name for p in res.file_paths] == ["real1.jpg", "real2.jpg"]
    assert res.size == 2048 + 4096
    assert not (job_dir / "gallery_dl" / "stub.jpg").exists()


async def test_download_url_fails_the_whole_job_when_the_fallback_returns_only_a_stub(tmp_path):
    """End to end: yt-dlp fails, gallery-dl yields 10 bytes, min_file_size is 5000."""
    wrapper = DownloaderWrapper(output_dir=tmp_path, min_file_size=5000)

    async def exec_stub(*args, **kwargs):
        proc = MagicMock()
        if "gallery_dl" in args:
            target = Path(args[args.index("--directory") + 1])
            (target / "tiny.jpg").write_bytes(b"0123456789")
            proc.communicate = AsyncMock(return_value=(b"", b""))
            proc.returncode = 0
        else:
            proc.communicate = AsyncMock(return_value=(b"", b"ERROR: Private video"))
            proc.returncode = 1
        return proc

    with (
        patch("asyncio.create_subprocess_exec", side_effect=exec_stub),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        res = await wrapper.download_url("https://instagram.com/p/ABC", 1)

    assert res.success is False
    assert res.file_paths == []
    assert res.size == 0
    # The job must not report success. Which message survives is a separate matter:
    # _download_async prefers the yt-dlp error over the fallback's, so the reason the
    # fallback gave is discarded whenever yt-dlp also failed.
    assert res.error


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


async def test_download_async_timeout_kills_process_tree(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path, subprocess_timeout=0.01)

    with (
        patch("asyncio.create_subprocess_exec") as mock_exec,
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("core.downloader_wrapper._terminate_tree", new_callable=AsyncMock) as mock_term,
        patch.object(wrapper, "_run_gallery_dl", new_callable=AsyncMock) as mock_gdl,
    ):
        proc = MagicMock()
        proc.communicate = AsyncMock(side_effect=TimeoutError)
        mock_exec.return_value = proc
        mock_gdl.return_value = DownloadResult(success=False, error="gdl failed")

        res = await wrapper.download_url("https://x.com/user/status/123", 12345)

    assert res.success is False
    assert mock_term.await_count == 3
    proc.kill.assert_not_called()


async def test_download_async_recovers_file_when_reported_path_is_wrong(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path)

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"video.mp4\n2048\n1920x1080\n22\n", b""))
        proc.returncode = 0

        async def side_effect(*args, **kwargs):
            cwd = Path(kwargs["cwd"])
            (cwd / "clip [18051999501].mp4").write_bytes(b"x" * 2048)
            return proc

        mock_exec.side_effect = side_effect

        res = await wrapper.download_url("https://x.com/user/status/123", 12345)

    assert res.success is True
    assert res.file_path is not None
    assert res.file_path.name == "clip [18051999501].mp4"
    assert res.size == 2048
    res.cleanup()


async def test_download_async_cleans_up_job_dir_when_the_subprocess_cannot_start(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path)

    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("python missing")):
        res = await wrapper.download_url("https://x.com/user/status/123", 12345)

    assert res.success is False
    assert "python missing" in res.error
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "url",
    [
        "https://x.com/user/status/123",
        "http://instagram.com/p/ABC123",
        "https://www.instagram.com/reel/ABC/?utm_source=tg",
        "https://example.com/path/to/file?a=1&b=2",
    ],
)
def test_is_safe_url_accepts_http_urls(url):
    assert _is_safe_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "--exec=touch /tmp/pwned",
        "-o/tmp/pwned",
        "file:///etc/passwd",
        "ftp://example.com/x",
        "javascript:alert(1)",
        "https://",
        "https://x.com/user status/1",
        "not-a-url",
        "",
    ],
)
def test_is_safe_url_rejects_everything_else(url):
    assert _is_safe_url(url) is False


@pytest.mark.parametrize("url", ["--exec=touch /tmp/pwned", "file:///etc/passwd", "  "])
async def test_download_url_never_spawns_a_process_for_unsafe_input(tmp_path, url):
    wrapper = DownloaderWrapper(output_dir=tmp_path)

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        res = await wrapper.download_url(url, 12345)

    assert res.success is False
    assert "Refusing to fetch" in res.error
    mock_exec.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_subprocess_kwargs_isolates_process_group():
    if sys.platform == "win32":
        new_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        kwargs = _subprocess_kwargs()
        assert kwargs["creationflags"] != 0
        assert kwargs["creationflags"] & new_group
    else:
        assert _subprocess_kwargs() == {"start_new_session": True}


async def test_terminate_tree_kills_process_group_on_posix(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    proc = MagicMock()
    proc.pid = 4242
    proc.wait = AsyncMock()
    killpg = MagicMock()
    monkeypatch.setattr(signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(os, "getpgid", MagicMock(return_value=4242), raising=False)
    monkeypatch.setattr(os, "killpg", killpg, raising=False)

    await _terminate_tree(proc)

    killpg.assert_called_once_with(4242, 9)
    proc.kill.assert_not_called()
    proc.wait.assert_awaited_once()


async def test_terminate_tree_uses_taskkill_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    proc = MagicMock()
    proc.pid = 1234
    proc.wait = AsyncMock()
    killer = MagicMock()
    killer.wait = AsyncMock()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = killer
        await _terminate_tree(proc)

    args = mock_exec.call_args[0]
    assert args[0] == "taskkill"
    assert "/T" in args and "/PID" in args and "1234" in args
    killer.wait.assert_awaited_once()
    proc.wait.assert_awaited_once()


async def test_terminate_tree_falls_back_to_kill(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    proc = MagicMock()
    proc.pid = 77
    proc.wait = AsyncMock()
    monkeypatch.setattr(signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(os, "getpgid", MagicMock(return_value=77), raising=False)
    monkeypatch.setattr(os, "killpg", MagicMock(side_effect=ProcessLookupError), raising=False)

    await _terminate_tree(proc)

    proc.kill.assert_called_once()
    proc.wait.assert_awaited_once()


async def test_terminate_tree_falls_back_to_kill_when_taskkill_is_unavailable(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    proc = MagicMock()
    proc.pid = 88
    proc.wait = AsyncMock()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.side_effect = OSError("taskkill is not on PATH")
        await _terminate_tree(proc)

    proc.kill.assert_called_once()
    proc.wait.assert_awaited_once()


def test_subprocess_kwargs_starts_a_new_session_on_posix(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert _subprocess_kwargs() == {"start_new_session": True}


def test_is_safe_url_rejects_a_url_the_parser_refuses_to_split():
    # urlsplit raises ValueError on an unterminated IPv6 literal, which must not
    # escape as an exception from a value a Telegram user typed.
    assert _is_safe_url("https://[oops") is False


def _exec_downloader_module_with(missing_module: str, expected_message: str) -> None:
    """Run the real module source with one extractor reported as not installed."""
    source = Path(core.downloader_wrapper.__file__).read_text(encoding="utf-8")
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name, *args, **kwargs):
        if name == missing_module:
            return None
        return real_find_spec(name, *args, **kwargs)

    module = types.ModuleType("guarded_downloader")
    with (
        patch("importlib.util.find_spec", side_effect=fake_find_spec),
        pytest.raises(RuntimeError, match=expected_message),
    ):
        exec(compile(source, core.downloader_wrapper.__file__, "exec"), module.__dict__)


def test_module_refuses_to_import_without_yt_dlp():
    _exec_downloader_module_with("yt_dlp", r"yt-dlp is required")


def test_module_refuses_to_import_without_gallery_dl():
    _exec_downloader_module_with("gallery_dl", r"gallery-dl is required")


def test_build_command_asks_for_merged_streams_when_ffmpeg_is_available():
    wrapper = DownloaderWrapper(output_dir=Path("downloads"))
    with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        cmd = wrapper._build_command("https://instagram.com/reel/ABC123")

    assert cmd[cmd.index("--format") + 1].startswith("bestvideo*[ext=mp4]+bestaudio[ext=m4a]")
    assert cmd[cmd.index("--merge-output-format") + 1] == "mp4"
    assert "--embed-metadata" in cmd
    assert "--embed-thumbnail" in cmd


def test_build_command_falls_back_to_a_premerged_format_without_ffmpeg():
    wrapper = DownloaderWrapper(output_dir=Path("downloads"))
    with patch("shutil.which", return_value=None):
        cmd = wrapper._build_command("https://instagram.com/reel/ABC123")

    assert cmd[cmd.index("--format") + 1] == "best"
    assert "--merge-output-format" not in cmd
    assert "--embed-metadata" not in cmd


def test_parse_output_leaves_size_unknown_when_it_is_not_a_number():
    wrapper = DownloaderWrapper(output_dir=Path("downloads"))

    res = wrapper._parse_output("video.mp4\nunknown\n1920x1080\n22", 0)

    assert res["success"] is True
    assert res["file"] == "video.mp4"
    assert "size" not in res
    assert res["resolution"] == "1920x1080"
    assert res["format_id"] == "22"


def test_parse_output_reads_a_three_print_resolution_out_of_the_middle_line():
    wrapper = DownloaderWrapper(output_dir=Path("downloads"))

    res = wrapper._parse_output("video.mp4\n1920x1080\n22", 0)

    assert res["file"] == "video.mp4"
    assert res["format_id"] == "22"
    assert res["resolution"] == "1920x1080"
    assert "size" not in res


def test_parse_output_reads_a_two_print_resolution():
    wrapper = DownloaderWrapper(output_dir=Path("downloads"))

    res = wrapper._parse_output("video.mp4\n1920x1080", 0)

    assert res["file"] == "video.mp4"
    assert res["resolution"] == "1920x1080"
    assert "size" not in res


def test_find_output_file_defaults_to_the_wrapper_output_dir(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x" * 2048)

    assert wrapper._find_output_file("https://instagram.com/reel/XYZ") == clip


def test_find_output_file_returns_none_for_an_empty_directory(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path)
    assert wrapper._find_output_file("https://instagram.com/reel/XYZ", output_dir=tmp_path) is None


def test_find_output_file_tolerates_a_candidate_whose_stat_fails(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path)

    unreadable = MagicMock(spec=Path)
    unreadable.suffix = ".mp4"
    unreadable.name = "clip.mp4"
    unreadable.exists.return_value = True
    unreadable.stat.side_effect = OSError("stale handle")

    directory = MagicMock(spec=Path)
    directory.iterdir.return_value = [unreadable]

    assert wrapper._find_output_file("https://x.com/user/status/1", output_dir=directory) is None


def test_find_output_file_survives_a_url_it_cannot_parse(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path)

    hostile = MagicMock()
    hostile.split.side_effect = ValueError("not a string")

    assert wrapper._find_output_file(hostile, output_dir=tmp_path) is None


async def test_probe_resolution_kills_ffprobe_when_it_times_out(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"data")

    with (
        patch("shutil.which", return_value="/usr/bin/ffprobe"),
        patch("asyncio.create_subprocess_exec") as mock_exec,
    ):
        proc = MagicMock()
        proc.communicate = AsyncMock(side_effect=TimeoutError)
        proc.wait = AsyncMock()
        mock_exec.return_value = proc

        res = await DownloaderWrapper._probe_resolution(video)

    assert res is None
    proc.kill.assert_called_once()
    proc.wait.assert_awaited_once()


async def test_probe_resolution_swallows_a_probe_that_cannot_start(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"data")

    with (
        patch("shutil.which", return_value="/usr/bin/ffprobe"),
        patch("asyncio.create_subprocess_exec", side_effect=OSError("ffprobe is missing")),
    ):
        res = await DownloaderWrapper._probe_resolution(video)

    assert res is None


async def test_run_gallery_dl_keeps_files_already_in_the_target_directory(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path, min_file_size=0)
    job_dir = tmp_path / "job_test"
    job_dir.mkdir()

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.side_effect = _gallery_dl_stub({"image.jpg": b"image data"})

        res = await wrapper._run_gallery_dl("https://instagram.com/p/ABC", job_dir)

    assert res.success is True
    assert [p.name for p in res.file_paths] == ["image.jpg"]
    assert res.file_paths[0].parent == job_dir / "gallery_dl"
    assert res.size == len(b"image data")


async def test_download_async_reports_a_non_transient_subprocess_error(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path)

    with patch("asyncio.create_subprocess_exec", side_effect=ValueError("bad argument")):
        res = await wrapper.download_url("https://x.com/user/status/1", 1)

    assert res.success is False
    assert "bad argument" in res.error
    assert list(tmp_path.iterdir()) == []


async def test_download_async_reports_when_the_reported_file_is_missing(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path)

    with (
        patch("asyncio.create_subprocess_exec") as mock_exec,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"ghost.mp4\n2048\n1920x1080\n22\n", b""))
        proc.returncode = 0
        mock_exec.return_value = proc

        with patch.object(wrapper, "_run_gallery_dl", new_callable=AsyncMock) as mock_gdl:
            mock_gdl.return_value = DownloadResult(success=False, error="gdl failed")
            res = await wrapper.download_url("https://x.com/user/status/1", 1)

    assert res.success is False
    assert res.error == "Download completed but no output file found"


async def test_download_async_cleans_up_when_the_fallback_itself_raises(tmp_path):
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
            mock_gdl.side_effect = RuntimeError("gallery-dl exploded")
            res = await wrapper.download_url("https://x.com/user/status/1", 1)

    assert res.success is False
    assert "gallery-dl exploded" in res.error
    assert list(tmp_path.iterdir()) == []


async def test_download_async_removes_the_job_directory_when_shutdown_cancels_it(tmp_path):
    """Shutdown drains by cancelling the in-flight task, and CancelledError is not an
    Exception, so the `except Exception` cleanup never ran and the directory survived.

    The container is torn down after the process exits, so the directory only really
    leaks on a long-lived local or Render deployment that restarts in place.
    """
    wrapper = DownloaderWrapper(output_dir=tmp_path)

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = MagicMock()
        proc.communicate = AsyncMock(side_effect=asyncio.CancelledError())
        mock_exec.return_value = proc

        with pytest.raises(asyncio.CancelledError):
            await wrapper.download_url("https://x.com/user/status/1", 1)

    assert list(tmp_path.iterdir()) == [], "a cancelled job left its directory behind"


def test_build_command_bounds_the_transfer_before_a_byte_is_written():
    """--max-filesize is the ceiling; the size floor in the handler only runs afterwards.

    Without it, yt-dlp has no reason to stop: MAX_FILE_SIZE_MB was consulted once the
    file was already on disk, so a multi-gigabyte stream filled the disk until
    subprocess_timeout fired.
    """
    wrapper = DownloaderWrapper(output_dir=Path("downloads"), max_file_size_mb=50)
    cmd = wrapper._build_command("https://instagram.com/reel/ABC123")

    assert cmd[cmd.index("--max-filesize") + 1] == str(50 * 1024 * 1024)


def test_build_command_asks_yt_dlp_to_report_the_size_and_duration_up_front():
    """The bound is only actionable if the bot learns the extractor already knew the size.

    yt-dlp's own "File is larger than max-filesize" line goes to stdout, which -q
    silences, so without this probe the refusal is invisible and the request is retried
    three times and then handed to the unbounded gallery-dl fallback.
    """
    wrapper = DownloaderWrapper(output_dir=Path("downloads"))
    cmd = wrapper._build_command("https://instagram.com/reel/ABC123")

    probe_templates = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--print"]
    probe = [tpl for tpl in probe_templates if "scraping-bot-bound:" in tpl]
    assert len(probe) == 1, probe_templates
    assert probe[0].startswith("before_dl:"), (
        "the probe has to be printed before the transfer starts"
    )
    assert "%(filesize)j" in probe[0] and "%(duration)j" in probe[0]


def test_the_probe_pattern_matches_what_yt_dlp_actually_prints():
    """yt-dlp eats the "before_dl:" print selector, so the tag has to be matched without it.

    Captured from yt-dlp 2026.8.19 run against a local HTTP server with --max-filesize in
    force: the only line it emitted was the tag and the three fields, the refusal itself
    having gone to stdout where -q swallows it. A pattern that expected the selector would
    match nothing and the oversize case would silently fall through to the retry loop.
    """
    wrapper = DownloaderWrapper(output_dir=Path("downloads"))

    result = wrapper._parse_output("scraping-bot-bound:NA|NA|NA\n", 0)

    assert result["bound"] == {"size": None, "duration": None}
    assert result.get("transfer_refused") is True


async def test_an_oversized_file_is_refused_without_a_retry_or_the_fallback(tmp_path):
    """The oversize verdict is terminal, so it must not be retried or handed to gallery-dl."""
    wrapper = DownloaderWrapper(output_dir=tmp_path, max_file_size_mb=1)

    async def exec_oversized(*args, **kwargs):
        proc = MagicMock()
        proc.pid = 1
        proc.returncode = 0
        # What yt-dlp actually emits with -q: the probe line, and nothing else, because
        # the downloader aborts before any after_move print happens.
        proc.communicate = AsyncMock(return_value=(b"scraping-bot-bound:9000000|NA|NA\n", b""))
        return proc

    with (
        patch("asyncio.create_subprocess_exec", side_effect=exec_oversized) as mock_exec,
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch.object(wrapper, "_run_gallery_dl", new_callable=AsyncMock) as mock_gdl,
    ):
        res = await wrapper.download_url("https://x.com/user/status/1", 1)

    assert res.success is False
    assert "larger than the 1 MB limit" in res.error
    assert mock_exec.await_count == 1, "an oversize link was retried"
    mock_sleep.assert_not_awaited()
    mock_gdl.assert_not_awaited()
    assert list(tmp_path.iterdir()) == []


async def test_media_longer_than_the_duration_limit_is_refused_without_the_fallback(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path, max_duration_seconds=90)

    async def exec_too_long(*args, **kwargs):
        proc = MagicMock()
        proc.pid = 1
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"scraping-bot-bound:NA|NA|14400\n", b""))
        return proc

    with (
        patch("asyncio.create_subprocess_exec", side_effect=exec_too_long) as mock_exec,
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(wrapper, "_run_gallery_dl", new_callable=AsyncMock) as mock_gdl,
    ):
        res = await wrapper.download_url("https://x.com/user/status/1", 1)

    assert res.success is False
    assert "longer than the 90s limit" in res.error
    assert mock_exec.await_count == 1
    mock_gdl.assert_not_awaited()


async def test_a_transfer_the_extractor_refuses_to_make_is_terminal(tmp_path):
    """The shape a --max-filesize abort actually has, reproduced from real yt-dlp.

    The extractor reports no size in the format dict -- many do not -- so the only place
    the size is known is the HTTP response, and the abort happens inside the downloader.
    Verified against yt-dlp 2026.8.19 with the real flag set: exit 0, the probe line,
    and nothing else, because the refusal is a stdout line that -q swallows. That is
    the common case, so it is the one that must not be retried or handed to gallery-dl.
    """
    wrapper = DownloaderWrapper(output_dir=tmp_path, max_file_size_mb=1)

    async def exec_aborted(*args, **kwargs):
        proc = MagicMock()
        proc.pid = 1
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"scraping-bot-bound:NA|NA|NA\n", b""))
        return proc

    with (
        patch("asyncio.create_subprocess_exec", side_effect=exec_aborted) as mock_exec,
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch.object(wrapper, "_run_gallery_dl", new_callable=AsyncMock) as mock_gdl,
    ):
        res = await wrapper.download_url("https://x.com/user/status/1", 1)

    assert res.success is False
    assert "--max-filesize" in res.error
    assert mock_exec.await_count == 1, "a refused transfer was retried"
    mock_sleep.assert_not_awaited()
    mock_gdl.assert_not_awaited(), "an unbounded fallback was allowed to fetch the same file"
    assert list(tmp_path.iterdir()) == []


async def test_a_silent_failure_with_no_transfer_started_is_still_retried(tmp_path):
    """The refusal is only terminal when a transfer actually began.

    Without a probe line there is no evidence anything was started, so the existing
    retry-then-gallery-dl behaviour has to stay: that is the path a flaky origin takes.
    """
    wrapper = DownloaderWrapper(output_dir=tmp_path, min_file_size=0)

    with (
        patch("asyncio.create_subprocess_exec") as mock_exec,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        proc = MagicMock()
        proc.pid = 1
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_exec.return_value = proc

        with patch.object(wrapper, "_run_gallery_dl", new_callable=AsyncMock) as mock_gdl:
            mock_gdl.return_value = DownloadResult(success=False, error="gdl failed")
            res = await wrapper.download_url("https://x.com/user/status/1", 1)

    assert res.success is False
    assert "max-filesize" not in (res.error or "")
    assert mock_exec.await_count == 3
    mock_gdl.assert_awaited_once()


async def test_media_inside_both_bounds_is_downloaded_and_parsed_as_usual(tmp_path):
    """The probe line must not disturb the positional parse of the after_move prints."""
    wrapper = DownloaderWrapper(output_dir=tmp_path, min_file_size=10, max_duration_seconds=600)

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = MagicMock()
        proc.pid = 1
        proc.returncode = 0

        async def side_effect(*args, **kwargs):
            cwd = Path(kwargs["cwd"])
            (cwd / "clip.mp4").write_bytes(b"x" * 2048)
            proc.communicate = AsyncMock(
                return_value=(
                    b"scraping-bot-bound:2000000|NA|95\nclip.mp4\n2048\n1920x1080\n22\n",
                    b"",
                )
            )
            return proc

        mock_exec.side_effect = side_effect

        res = await wrapper.download_url("https://x.com/user/status/123", 12345)

    assert res.success is True
    assert res.file_path is not None and res.file_path.name == "clip.mp4"
    assert res.size == 2048
    assert res.resolution == "1920x1080"
    res.cleanup()


async def test_an_extractor_that_reports_no_size_is_left_to_the_byte_ceiling(tmp_path):
    """NA everywhere must not be read as zero bytes and refuse every unknown stream."""
    wrapper = DownloaderWrapper(output_dir=tmp_path, min_file_size=10)

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = MagicMock()
        proc.pid = 1
        proc.returncode = 0

        async def side_effect(*args, **kwargs):
            cwd = Path(kwargs["cwd"])
            (cwd / "clip.mp4").write_bytes(b"x" * 2048)
            proc.communicate = AsyncMock(
                return_value=(
                    b"scraping-bot-bound:NA|NA|NA\nclip.mp4\n2048\n1920x1080\n",
                    b"",
                )
            )
            return proc

        mock_exec.side_effect = side_effect

        res = await wrapper.download_url("https://x.com/user/status/123", 12345)

    assert res.success is True
    res.cleanup()


def test_the_bound_probe_takes_the_worst_value_across_a_merged_download():
    """A video+audio merge prints the probe once per format, so all of them are read."""
    wrapper = DownloaderWrapper(output_dir=Path("downloads"), max_file_size_mb=1)

    result = wrapper._parse_output(
        "scraping-bot-bound:100|NA|30\nscraping-bot-bound:5000000|NA|30\n",
        0,
    )

    assert result["bound"] == {"size": 5000000, "duration": 30}
    assert wrapper._bound_refusal(result["bound"]) is not None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("NA|NA|NA", {"size": None, "duration": None}),
        ("", {"size": None, "duration": None}),
        ("2000000.0|NA|95.4", {"size": 2000000, "duration": 95}),
        ("NA|4000000|NA", {"size": 4000000, "duration": None}),
        ('"1GiB"|NA|NA', {"size": None, "duration": None}),
    ],
)
def test_the_bound_probe_reads_the_shapes_yt_dlp_prints(raw, expected):
    wrapper = DownloaderWrapper(output_dir=Path("downloads"))
    result = wrapper._parse_output(f"scraping-bot-bound:{raw}", 0)
    assert result["bound"] == expected


def test_a_download_within_the_bounds_is_not_refused():
    wrapper = DownloaderWrapper(output_dir=Path("downloads"), max_file_size_mb=50)
    assert wrapper._bound_refusal({"size": 49 * 1024 * 1024, "duration": 599}) is None
    assert wrapper._bound_refusal({"size": None, "duration": None}) is None
    assert wrapper._bound_refusal("not a dict") is None
    assert wrapper._bound_refusal(None) is None


async def test_download_url_turns_a_saturated_bot_away_instead_of_queueing(tmp_path):
    """A queued request has no timeout of its own, so two slow links park the bot.

    Each request can spend up to three SUBPROCESS_TIMEOUTs on yt-dlp plus one on
    gallery-dl; at the 300 s Render sets, one link holds a slot for twenty minutes and
    two of them hold both. Queueing behind them means the third user waits with nothing
    to bound the wait, so the answer comes back immediately instead.
    """
    wrapper = DownloaderWrapper(output_dir=tmp_path, concurrent=1)
    in_flight = asyncio.Event()
    release = asyncio.Event()

    async def exec_blocking(*args, **kwargs):
        in_flight.set()
        await release.wait()
        proc = MagicMock()
        proc.pid = 1
        proc.returncode = 1
        proc.communicate = AsyncMock(return_value=(b"", b"ERROR: nope"))
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=exec_blocking) as mock_exec:
        first = asyncio.create_task(wrapper.download_url("https://x.com/user/status/1", 1))
        await asyncio.wait_for(in_flight.wait(), timeout=5)

        second = await asyncio.wait_for(
            wrapper.download_url("https://x.com/user/status/2", 2), timeout=5
        )
        calls_while_saturated = mock_exec.await_count

        release.set()
        assert (await asyncio.wait_for(first, timeout=5)).success is False

    assert second.success is False
    assert "slots are busy" in second.error
    assert calls_while_saturated == 1, "a saturated request was queued behind the first"


async def test_a_request_is_admitted_as_soon_as_a_slot_frees_up(tmp_path):
    """The counterpart: shedding is not a permanent closed door."""
    wrapper = DownloaderWrapper(output_dir=tmp_path, concurrent=1)

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("asyncio.create_subprocess_exec") as mock_exec,
    ):
        proc = MagicMock()
        proc.pid = 1
        proc.returncode = 1
        proc.communicate = AsyncMock(return_value=(b"", b"ERROR: nope"))
        mock_exec.return_value = proc

        first = await wrapper.download_url("https://x.com/user/status/1", 1)
        second = await wrapper.download_url("https://x.com/user/status/2", 2)

    assert first.success is False and "slots are busy" not in (first.error or "")
    assert second.success is False and "slots are busy" not in (second.error or "")
    # Three yt-dlp attempts plus one gallery-dl fallback, twice over.
    assert mock_exec.await_count == 8, "the second request did not reach the extractor"


async def test_cancellation_kills_the_extractor_tree_before_removing_the_job_dir(tmp_path):
    """Order is the whole fix: kill first, then delete.

    CancelledError is a BaseException, so no `except Exception` runs when the loop
    cancels a task, and nothing removed the directory or killed the child. The orphaned
    yt-dlp keeps writing, and on Windows its open handle is what stops rmtree from
    deleting the partial file.
    """
    wrapper = DownloaderWrapper(output_dir=tmp_path)
    order = []
    job_dirs = []
    real_rmtree = shutil.rmtree

    async def exec_hanging(*args, **kwargs):
        job_dir = Path(kwargs["cwd"])
        job_dirs.append(job_dir)
        (job_dir / "partial.mp4").write_bytes(b"x" * 4096)
        proc = MagicMock()
        proc.pid = 4242
        proc.returncode = None
        proc.communicate = AsyncMock(side_effect=asyncio.CancelledError())
        return proc

    def record_rmtree(path, **kwargs):
        order.append("rmtree")
        real_rmtree(path, **kwargs)

    with (
        patch("asyncio.create_subprocess_exec", side_effect=exec_hanging),
        patch(
            "core.downloader_wrapper._terminate_tree",
            new_callable=AsyncMock,
            side_effect=lambda proc: order.append("kill"),
        ) as mock_term,
        patch("core.downloader_wrapper.shutil.rmtree", side_effect=record_rmtree),
    ):
        with pytest.raises(asyncio.CancelledError):
            await wrapper.download_url("https://x.com/user/status/1", 1)

    assert order == ["kill", "rmtree"], "the extractor outlived the directory it was writing to"
    mock_term.assert_awaited_once()
    assert not job_dirs[0].exists(), "the partial file survived the cancelled job"


async def test_an_extractor_that_will_not_die_still_leaves_no_directory_behind(tmp_path, caplog):
    """A kill that fails must not take the cleanup with it, and must be visible."""
    wrapper = DownloaderWrapper(output_dir=tmp_path)
    job_dirs = []

    async def exec_hanging(*args, **kwargs):
        job_dir = Path(kwargs["cwd"])
        job_dirs.append(job_dir)
        (job_dir / "partial.mp4").write_bytes(b"x" * 4096)
        proc = MagicMock()
        proc.pid = 4242
        proc.returncode = None
        proc.communicate = AsyncMock(side_effect=asyncio.CancelledError())
        return proc

    with (
        patch("asyncio.create_subprocess_exec", side_effect=exec_hanging),
        patch(
            "core.downloader_wrapper._terminate_tree",
            new_callable=AsyncMock,
            side_effect=OSError("taskkill is not on PATH"),
        ),
        caplog.at_level(logging.WARNING),
    ):
        with pytest.raises(asyncio.CancelledError):
            await wrapper.download_url("https://x.com/user/status/1", 1)

    assert "Could not terminate the extractor process tree" in caplog.text
    assert not job_dirs[0].exists(), "an undeletable kill also stranded the job directory"


async def test_a_finished_extractor_is_not_killed_again_by_the_cleanup(tmp_path):
    """The finally must not re-kill a child that already exited and was reaped."""
    wrapper = DownloaderWrapper(output_dir=tmp_path)

    with (
        patch("asyncio.create_subprocess_exec") as mock_exec,
        patch("core.downloader_wrapper._terminate_tree", new_callable=AsyncMock) as mock_term,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        proc = MagicMock()
        proc.pid = 7
        proc.returncode = 1
        proc.communicate = AsyncMock(return_value=(b"", b"ERROR: nope"))
        mock_exec.return_value = proc

        res = await wrapper.download_url("https://x.com/user/status/1", 1)

    assert res.success is False
    mock_term.assert_not_awaited()
