import importlib.util
import os
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
    wrapper = DownloaderWrapper(output_dir=tmp_path)
    job_dir = tmp_path / "job_test"
    job_dir.mkdir()

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.side_effect = _gallery_dl_stub({"instagram/image.jpg": b"image data"})

        res = await wrapper._run_gallery_dl("https://instagram.com/p/ABC", job_dir)
        assert res.success is True
        assert len(res.file_paths) == 1
        assert res.file_paths[0].name == "image.jpg"


async def test_run_gallery_dl_ignores_artifacts_of_previous_attempt(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path)
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
    wrapper = DownloaderWrapper(output_dir=tmp_path)
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
    wrapper = DownloaderWrapper(output_dir=tmp_path)
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
