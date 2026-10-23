from __future__ import annotations

import asyncio
import builtins
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from bot.main import DOWNLOADER_KEY, deep_health_handler
from core.downloader_wrapper import DownloaderWrapper


class _FakeDownloader:
    def __init__(self, tmp_path, max_disk_usage_percent=0):
        self.concurrent = 2
        self.output_dir = tmp_path / "downloads"
        self.max_disk_usage_percent = max_disk_usage_percent


class _FakeRequest:
    def __init__(self, app):
        self.app = app


async def test_deep_health_ok_when_everything_available(tmp_path):
    downloader = _FakeDownloader(tmp_path, max_disk_usage_percent=90)
    request = _FakeRequest({DOWNLOADER_KEY: downloader})

    with (
        patch("shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("shutil.disk_usage", return_value=(1000, 100, 900)),
    ):
        response = await deep_health_handler(request)

    assert response.status == 200
    data = json.loads(response.body.decode())
    assert data["status"] == "ok"
    assert data["problems"] == []


async def test_deep_health_degraded_when_ffmpeg_missing(tmp_path):
    downloader = _FakeDownloader(tmp_path)
    request = _FakeRequest({DOWNLOADER_KEY: downloader})

    with patch("shutil.which", return_value=None):
        response = await deep_health_handler(request)

    assert response.status == 503
    data = json.loads(response.body.decode())
    assert data["status"] == "degraded"
    assert "ffmpeg is not on PATH" in data["problems"]


async def test_deep_health_degraded_when_ytdlp_not_importable(tmp_path):
    downloader = _FakeDownloader(tmp_path)
    request = _FakeRequest({DOWNLOADER_KEY: downloader})

    with (
        patch("shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("importlib.util.find_spec", return_value=None),
    ):
        response = await deep_health_handler(request)

    assert response.status == 503
    data = json.loads(response.body.decode())
    assert data["status"] == "degraded"
    assert "yt_dlp is not importable" in data["problems"]


async def test_deep_health_degraded_when_disk_over_limit(tmp_path):
    downloader = _FakeDownloader(tmp_path, max_disk_usage_percent=50)
    request = _FakeRequest({DOWNLOADER_KEY: downloader})

    with (
        patch("shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("shutil.disk_usage", return_value=(1000, 900, 100)),
    ):
        response = await deep_health_handler(request)

    assert response.status == 503
    data = json.loads(response.body.decode())
    assert data["status"] == "degraded"
    assert "disk usage" in data["problems"][0]


async def test_deep_health_ignores_disk_when_limit_is_zero(tmp_path):
    downloader = _FakeDownloader(tmp_path, max_disk_usage_percent=0)
    request = _FakeRequest({DOWNLOADER_KEY: downloader})

    with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        response = await deep_health_handler(request)

    assert response.status == 200
    data = json.loads(response.body.decode())
    assert data["status"] == "ok"


async def test_check_disk_space_returns_none_when_disabled(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path, max_disk_usage_percent=0)
    assert wrapper._check_disk_space() is None


async def test_check_disk_space_refuses_over_limit(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path, max_disk_usage_percent=50)
    with patch("shutil.disk_usage", return_value=(1000, 900, 100)):
        refusal = wrapper._check_disk_space()
    assert refusal is not None
    assert "90%" in refusal


async def test_check_disk_space_allows_under_limit(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path, max_disk_usage_percent=90)
    with patch("shutil.disk_usage", return_value=(1000, 100, 900)):
        refusal = wrapper._check_disk_space()
    assert refusal is None


async def test_check_disk_space_returns_none_on_oserror(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path, max_disk_usage_percent=50)
    with patch("shutil.disk_usage", side_effect=OSError("no such device")):
        assert wrapper._check_disk_space() is None


async def test_download_url_refuses_when_disk_full(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path, max_disk_usage_percent=50)
    with patch.object(wrapper, "_check_disk_space", return_value="Disk full"):
        result = await wrapper.download_url("https://x.com/user/status/1", 1)
    assert result.success is False
    assert result.error == "Disk full"


def test_find_output_file_returns_none_when_output_dir_none():
    wrapper = DownloaderWrapper(output_dir=Path("/tmp/nonexistent"))
    assert wrapper._find_output_file("https://x.com/1", output_dir=None) is None


async def test_throttle_redis_cached_client_returned():
    from bot.middlewares.throttle import ThrottleMiddleware

    mw = ThrottleMiddleware(rate_limit=1.0, redis_url="redis://localhost:6379")
    cached = MagicMock()
    mw._redis = cached
    result = await mw._get_redis()
    assert result is cached


async def test_throttle_redis_import_error_returns_none(monkeypatch):
    from bot.middlewares.throttle import ThrottleMiddleware

    mw = ThrottleMiddleware(rate_limit=1.0, redis_url="redis://localhost:6379")
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "redis.asyncio":
            raise ImportError("no redis")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    result = await mw._get_redis()
    assert result is None


async def test_throttle_redis_user_throttled():
    from bot.middlewares.throttle import ThrottleMiddleware

    mw = ThrottleMiddleware(rate_limit=1.0, redis_url="redis://localhost:6379")
    redis_client = AsyncMock()
    redis_client.get = AsyncMock(return_value=b"1000.0")
    mw._redis = redis_client

    # now - last_ts = 0.5 < rate_limit 1.0 -> throttled
    assert await mw._is_throttled(42, 1000.5) is True


async def test_throttle_redis_user_not_throttled_records_now():
    from bot.middlewares.throttle import ThrottleMiddleware

    mw = ThrottleMiddleware(rate_limit=1.0, redis_url="redis://localhost:6379")
    redis_client = AsyncMock()
    redis_client.get = AsyncMock(return_value=None)
    redis_client.setex = AsyncMock()
    mw._redis = redis_client

    assert await mw._is_throttled(42, 1000.0) is False
    redis_client.setex.assert_awaited_once_with("scraping-bot:throttle:42", 2, "1000.0")


async def test_throttle_redis_exception_falls_back_to_memory():
    from bot.middlewares.throttle import ThrottleMiddleware

    mw = ThrottleMiddleware(rate_limit=1.0, redis_url="redis://localhost:6379")
    redis_client = AsyncMock()
    redis_client.get = AsyncMock(side_effect=OSError("redis down"))
    mw._redis = redis_client

    assert await mw._is_throttled(42, 1000.0) is False
    assert 42 in mw.last_request


async def test_throttle_redis_unparsable_value_falls_through():
    from bot.middlewares.throttle import ThrottleMiddleware

    mw = ThrottleMiddleware(rate_limit=1.0, redis_url="redis://localhost:6379")
    redis_client = AsyncMock()
    redis_client.get = AsyncMock(return_value=b"not-a-number")
    redis_client.setex = AsyncMock()
    mw._redis = redis_client

    assert await mw._is_throttled(42, 1000.0) is False


async def test_deep_health_degraded_when_disk_usage_raises(tmp_path):
    downloader = _FakeDownloader(tmp_path, max_disk_usage_percent=50)
    request = _FakeRequest({DOWNLOADER_KEY: downloader})

    with (
        patch("shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("shutil.disk_usage", side_effect=OSError("no disk")),
    ):
        response = await deep_health_handler(request)

    assert response.status == 503
    data = json.loads(response.body.decode())
    assert data["status"] == "degraded"
    assert "cannot probe disk usage" in data["problems"][0]


async def test_throttle_redis_creates_client_when_url_set(monkeypatch):
    import sys

    from bot.middlewares.throttle import ThrottleMiddleware

    mw = ThrottleMiddleware(rate_limit=1.0, redis_url="redis://localhost:6379")

    fake_asyncio = MagicMock()
    fake_asyncio.from_url = MagicMock(return_value="redis-client")
    fake_redis = MagicMock()
    fake_redis.asyncio = fake_asyncio

    monkeypatch.setitem(sys.modules, "redis", fake_redis)
    monkeypatch.setitem(sys.modules, "redis.asyncio", fake_asyncio)

    result = await mw._get_redis()
    assert result == "redis-client"
    assert mw._redis == "redis-client"


async def test_check_disk_space_returns_none_when_total_is_zero(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path, max_disk_usage_percent=50)
    with patch("shutil.disk_usage", return_value=(0, 0, 0)):
        assert wrapper._check_disk_space() is None


def test_find_output_file_impl_returns_none_when_both_dirs_none():
    from core.output_parser import _find_output_file as impl

    assert impl("https://x.com/1", output_dir=None, default_output_dir=None) is None


async def test_download_url_turns_away_when_saturated_with_disk_check(tmp_path):
    wrapper = DownloaderWrapper(output_dir=tmp_path, concurrent=1, max_disk_usage_percent=0)
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

    with patch("asyncio.create_subprocess_exec", side_effect=exec_blocking):
        first = asyncio.create_task(wrapper.download_url("https://x.com/user/status/1", 1))
        await asyncio.wait_for(in_flight.wait(), timeout=5)
        second = await asyncio.wait_for(
            wrapper.download_url("https://x.com/user/status/2", 2), timeout=5
        )
        release.set()
        await asyncio.wait_for(first, timeout=5)

    assert second.success is False
    assert "slots are busy" in second.error
