import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

from bot.handlers import commands, download
from bot.main import main
from core.config import settings


@pytest.fixture(autouse=True)
def reset_routers_and_settings(monkeypatch):
    monkeypatch.setattr(settings, "BOT_TOKEN", "123:MOCK_TOKEN")
    commands.router._parent_router = None
    download.router._parent_router = None
    yield
    commands.router._parent_router = None
    download.router._parent_router = None


async def test_main_polling_flow(monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_URL", "")

    with (
        patch("bot.main.Bot") as mock_bot_cls,
        patch("bot.main.Dispatcher.start_polling", new_callable=AsyncMock) as mock_polling,
        patch("bot.main.web.TCPSite") as mock_site_cls,
        patch.object(web.AppRunner, "setup", new_callable=AsyncMock),
        patch.object(web.AppRunner, "cleanup", new_callable=AsyncMock),
    ):
        mock_site = MagicMock()
        mock_site.start = AsyncMock()
        mock_site_cls.return_value = mock_site

        mock_bot = MagicMock()
        mock_bot.session.close = AsyncMock()
        mock_bot_cls.return_value = mock_bot

        await main()

        mock_polling.assert_called_once()
        mock_bot.session.close.assert_called_once()


async def test_main_webhook_flow(monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_URL", "https://example.com/webhook")

    with (
        patch("bot.main.Bot") as mock_bot_cls,
        patch("bot.main.web.TCPSite") as mock_site_cls,
        patch.object(web.AppRunner, "setup", new_callable=AsyncMock),
        patch.object(web.AppRunner, "cleanup", new_callable=AsyncMock),
        patch("bot.main.setup_application"),
        patch("asyncio.sleep", side_effect=asyncio.CancelledError),
    ):
        mock_site = MagicMock()
        mock_site.start = AsyncMock()
        mock_site_cls.return_value = mock_site

        mock_bot = MagicMock()
        mock_bot.session.close = AsyncMock()
        mock_bot_cls.return_value = mock_bot

        await main()

        mock_bot.session.close.assert_called_once()
