import importlib.metadata
import json
import logging
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import Bot

from bot.main import (
    DOWNLOADER_KEY,
    JsonFormatter,
    __version__,
    _raise_system_exit,
    _resolve_version,
    health_handler,
    metrics_handler,
    on_startup,
)
from core.config import settings


@pytest.fixture
def mock_downloader(tmp_path):
    class FakeDownloader:
        concurrent = 2
        output_dir = tmp_path / "downloads"

    return FakeDownloader()


@pytest.fixture
def mock_request(mock_downloader):
    request = type("Request", (), {})()
    request.app = {DOWNLOADER_KEY: mock_downloader}
    return request


async def test_health_handler(mock_request):
    response = await health_handler(mock_request)
    assert response.status == 200

    data = json.loads(response.body.decode())
    assert data["status"] == "ok"
    assert data["version"] == __version__
    assert data["concurrent"] == 2
    assert "downloads" in data["output_dir"]
    assert "uptime_seconds" in data
    assert "active_downloads" in data


async def test_metrics_handler(mock_request):
    response = await metrics_handler(mock_request)
    assert response.status == 200
    text = response.text
    # Strip the # HELP / # TYPE comment lines: a substring check against the whole body
    # is satisfied by the comment alone, so a renamed or deleted sample was invisible.
    samples = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, _, value = line.partition(" ")
        samples[name] = value.strip()
    assert sorted(samples) == [
        "scraping_bot_active_downloads",
        "scraping_bot_concurrent_limit",
        "scraping_bot_uptime_seconds",
    ], f"unexpected /metrics sample names: {sorted(samples)}"
    for name, value in samples.items():
        assert re.fullmatch(r"-?\d+(\.\d+)?([eE][-+]?\d+)?", value), (name, value)
    for name in samples:
        assert f"# HELP {name} " in text, f"no HELP line for {name}"
        assert f"# TYPE {name} gauge" in text, f"{name} is not declared a gauge"


async def test_uptime_is_measured_with_a_monotonic_clock(mock_request, monkeypatch):
    monkeypatch.setattr("bot.main._start_time", 500.0)

    with patch("bot.main.time.monotonic", return_value=560.0):
        health_data = json.loads((await health_handler(mock_request)).body.decode())
        metrics_text = (await metrics_handler(mock_request)).text

    assert health_data["uptime_seconds"] == 60
    assert "scraping_bot_uptime_seconds 60.00" in metrics_text


def test_version_is_read_from_package_metadata():
    with patch("importlib.metadata.version", return_value="9.9.9") as mock_version:
        assert _resolve_version() == "9.9.9"
    mock_version.assert_called_once_with("scraping-bot")

    with patch(
        "importlib.metadata.version",
        side_effect=importlib.metadata.PackageNotFoundError("scraping-bot"),
    ):
        assert _resolve_version() == "0.0.0+unknown"

    assert __version__ == _resolve_version()


def test_json_formatter():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Hello %s",
        args=("world",),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert data["level"] == "INFO"
    assert data["logger"] == "test_logger"
    assert data["message"] == "Hello world"
    assert "timestamp" in data


def test_json_formatter_with_exc():
    formatter = JsonFormatter()
    try:
        raise ValueError("Something broke")
    except ValueError:
        import sys

        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="test_logger",
        level=logging.ERROR,
        pathname="test.py",
        lineno=20,
        msg="Error occurred",
        args=(),
        exc_info=exc_info,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert data["level"] == "ERROR"
    assert "exc_info" in data
    assert "ValueError: Something broke" in data["exc_info"]


async def test_on_startup_webhook(monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_URL", "https://example.com/webhook")
    bot = MagicMock(spec=Bot)
    bot.set_webhook = AsyncMock()

    await on_startup(bot, secret_token="per-process-secret")
    bot.set_webhook.assert_called_once_with(
        "https://example.com/webhook",
        secret_token="per-process-secret",
        drop_pending_updates=False,
    )


async def test_on_startup_polling(monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_URL", "")
    bot = MagicMock(spec=Bot)
    bot.delete_webhook = AsyncMock()

    await on_startup(bot, secret_token="per-process-secret")
    bot.delete_webhook.assert_called_once_with(drop_pending_updates=False)


def test_signal_fallback_exits_without_loop_support():
    with pytest.raises(SystemExit):
        _raise_system_exit(15, None)
