import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Bot

from bot.main import (
    JsonFormatter,
    __version__,
    _handle_sigterm,
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


async def test_health_handler(mock_downloader):
    request = type("Request", (), {})()
    request.app = {"downloader": mock_downloader}

    response = await health_handler(request)
    assert response.status == 200

    data = json.loads(response.body.decode())
    assert data["status"] == "ok"
    assert data["version"] == __version__
    assert data["concurrent"] == 2
    assert "downloads" in data["output_dir"]
    assert "uptime_seconds" in data
    assert "active_downloads" in data


async def test_metrics_handler(mock_downloader):
    request = type("Request", (), {})()
    request.app = {"downloader": mock_downloader}

    response = await metrics_handler(request)
    assert response.status == 200
    text = response.text
    assert "scraping_bot_uptime_seconds" in text
    assert "scraping_bot_active_downloads" in text
    assert "scraping_bot_concurrent_limit 2" in text


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

    await on_startup(bot)
    bot.set_webhook.assert_called_once_with(
        "https://example.com/webhook", drop_pending_updates=False
    )


async def test_on_startup_polling(monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_URL", "")
    bot = MagicMock(spec=Bot)
    bot.delete_webhook = AsyncMock()

    await on_startup(bot)
    bot.delete_webhook.assert_called_once_with(drop_pending_updates=False)


def test_handle_sigterm():
    with pytest.raises(SystemExit):
        _handle_sigterm(15, None)
