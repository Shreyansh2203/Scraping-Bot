import asyncio
import json
import logging
import re
import signal
from collections.abc import Callable
from functools import partial
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiohttp import web

import bot.main
from bot.handlers import commands, download
from bot.main import (
    _generate_webhook_secret,
    _install_signal_handlers,
    _make_shutdown_handler,
    _raise_system_exit,
    _shutdown,
    main,
)
from core.config import settings
from core.downloader_wrapper import DownloaderWrapper


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


SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


class _WebhookRequest:
    """The slice of aiohttp's Request that SimpleRequestHandler.handle reads.

    Built by hand rather than driven through a live server so the test can hand the
    handler a header of its choosing, which is the entire point: the request has to be
    able to arrive from something that is not Telegram.
    """

    def __init__(self, secret_token, payload=None):
        self.headers = {} if secret_token is None else {SECRET_HEADER: secret_token}
        self._payload = {"update_id": 1} if payload is None else payload

    async def json(self, loads=None):
        return self._payload


async def _run_webhook_main(monkeypatch, secret):
    """Run main() in webhook mode and hand back what it actually wired up.

    Returns the real SimpleRequestHandler it constructed rather than a mock of one: the
    secret check under test lives inside aiogram, so a stand-in would pass whatever the
    test asserted about it.
    """
    monkeypatch.setattr(settings, "WEBHOOK_URL", "https://example.com/webhook")
    monkeypatch.setattr(bot.main, "_generate_webhook_secret", lambda: secret)

    handlers = []
    dispatchers = []
    real_handler_cls = SimpleRequestHandler

    def recording_handler(**kwargs):
        dispatchers.append(kwargs["dispatcher"])
        handler = real_handler_cls(**kwargs)
        handlers.append(handler)
        return handler

    tg_bot = MagicMock()
    tg_bot.session.close = AsyncMock()
    tg_bot.set_webhook = AsyncMock()
    tg_bot.delete_webhook = AsyncMock()
    tg_bot.session.json_loads = json.loads
    tg_bot.session.json_dumps = json.dumps

    site = MagicMock()
    site.start = AsyncMock()

    monkeypatch.setattr(bot.main, "SimpleRequestHandler", recording_handler)
    monkeypatch.setattr(bot.main, "Bot", MagicMock(return_value=tg_bot))
    monkeypatch.setattr(bot.main, "setup_application", MagicMock())
    monkeypatch.setattr(web, "TCPSite", MagicMock(return_value=site))
    monkeypatch.setattr(web.AppRunner, "setup", AsyncMock())
    monkeypatch.setattr(web.AppRunner, "cleanup", AsyncMock())

    with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
        await main()

    assert len(handlers) == 1, "main() built more or fewer than one webhook request handler"
    return handlers[0], tg_bot, dispatchers[0]


async def test_webhook_secret_is_shared_by_set_webhook_and_the_request_handler(monkeypatch):
    """Both ends of the exchange must be given the same value or the bot rejects itself.

    set_webhook registers the secret with Telegram; the request handler is what checks
    the header on the way back in. Two independently generated values -- or one call
    site that quietly drops the argument -- means every legitimate delivery is refused.
    """
    handler, tg_bot, dp = await _run_webhook_main(monkeypatch, "the-one-secret")

    assert handler.secret_token == "the-one-secret"

    await dp.startup.trigger(bot=tg_bot)

    tg_bot.set_webhook.assert_awaited_once()
    assert tg_bot.set_webhook.await_args.kwargs["secret_token"] == "the-one-secret"


async def test_webhook_rejects_an_update_carrying_the_wrong_secret(monkeypatch):
    """A hand-written POST must not reach the dispatcher.

    AuthMiddleware reads the sender id off the update, so an update the attacker
    composed carries an attacker-chosen id: a permissive webhook is a public
    subprocess spawner, not merely a spam surface.
    """
    handler, _, _ = await _run_webhook_main(monkeypatch, "the-one-secret")
    feed = AsyncMock()
    monkeypatch.setattr(handler.dispatcher, "feed_raw_update", feed)

    response = await handler.handle(_WebhookRequest("not-the-secret"))

    assert response.status == 401, "a webhook update with a wrong secret was not refused"
    feed.assert_not_awaited()


async def test_webhook_rejects_an_update_carrying_no_secret_at_all(monkeypatch):
    """A missing header must be refused, not treated as an empty secret to match."""
    handler, _, _ = await _run_webhook_main(monkeypatch, "the-one-secret")
    feed = AsyncMock()
    monkeypatch.setattr(handler.dispatcher, "feed_raw_update", feed)

    response = await handler.handle(_WebhookRequest(None))

    assert response.status == 401
    feed.assert_not_awaited()


async def test_webhook_accepts_an_update_carrying_the_right_secret(monkeypatch):
    """The counterpart to the rejection: the fix must not be 'refuse everything'."""
    handler, _, _ = await _run_webhook_main(monkeypatch, "the-one-secret")
    feed = AsyncMock()
    monkeypatch.setattr(handler.dispatcher, "feed_raw_update", feed)

    response = await handler.handle(_WebhookRequest("the-one-secret"))
    await asyncio.sleep(0)

    assert response.status == 200
    feed.assert_awaited_once()
    assert feed.await_args.kwargs["update"] == {"update_id": 1}


def test_generated_webhook_secret_is_fresh_each_time_and_url_safe():
    first = _generate_webhook_secret()
    second = _generate_webhook_secret()

    assert first != second, "the secret is not random per process start"
    # Telegram allows 1-256 characters from A-Z a-z 0-9 _ - for this header.
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,256}", first), f"unusable secret: {first!r}"


async def test_webhook_secret_is_never_logged(monkeypatch, caplog):
    """A secret in the log is a secret in whatever aggregates the log."""
    marker = "SENTINEL-SECRET-MUST-NOT-LEAK"
    handler, tg_bot, dp = await _run_webhook_main(monkeypatch, marker)
    monkeypatch.setattr(handler.dispatcher, "feed_raw_update", AsyncMock())

    with caplog.at_level(logging.DEBUG):
        await dp.startup.trigger(bot=tg_bot)
        await handler.handle(_WebhookRequest(marker))

    assert marker in handler.secret_token, "the sentinel never reached the handler"
    assert marker not in caplog.text, "the webhook secret reached a log record"


async def test_shutdown_drains_tasks_and_releases_resources():
    downloader = MagicMock(spec=DownloaderWrapper)
    runner = MagicMock(spec=web.AppRunner)
    runner.cleanup = AsyncMock()
    bot = MagicMock()
    bot.session.close = AsyncMock()
    file_handler = MagicMock(spec=logging.Handler)
    stream_handler = MagicMock(spec=logging.Handler)
    root_logger = MagicMock()
    pending = {asyncio.create_task(asyncio.sleep(0))}

    with (
        patch.object(download, "active_tasks", pending),
        patch("logging.getLogger", return_value=root_logger),
    ):
        await _shutdown(downloader, runner, bot, (stream_handler, file_handler))

    downloader.shutdown.assert_called_once()
    assert all(task.done() for task in pending)
    runner.cleanup.assert_awaited_once()
    bot.session.close.assert_awaited_once()
    stream_handler.close.assert_called_once()
    file_handler.close.assert_called_once()
    assert root_logger.removeHandler.call_count == 2


def test_shutdown_handler_cancels_main_task_only_once():
    main_task = MagicMock(spec=asyncio.Task)
    main_task.done.return_value = False
    handler = _make_shutdown_handler(main_task)

    handler(signal.SIGTERM)
    handler(signal.SIGINT)

    main_task.cancel.assert_called_once_with()


def test_shutdown_handler_ignores_finished_task():
    main_task = MagicMock(spec=asyncio.Task)
    main_task.done.return_value = True

    _make_shutdown_handler(main_task)(signal.SIGTERM)

    main_task.cancel.assert_not_called()


def test_install_signal_handlers_registers_termination_signals():
    loop = MagicMock(spec=asyncio.AbstractEventLoop)
    main_task = MagicMock(spec=asyncio.Task)

    _install_signal_handlers(loop, main_task)

    assert [call.args[0] for call in loop.add_signal_handler.call_args_list] == [
        signal.SIGTERM,
        signal.SIGINT,
    ]


def test_install_signal_handlers_falls_back_without_loop_support():
    loop = MagicMock(spec=asyncio.AbstractEventLoop)
    loop.add_signal_handler.side_effect = NotImplementedError
    main_task = MagicMock(spec=asyncio.Task)

    with patch("signal.signal") as mock_signal:
        _install_signal_handlers(loop, main_task)

    assert [call.args[0] for call in mock_signal.call_args_list] == [
        signal.SIGTERM,
        signal.SIGINT,
    ]
    assert all(call.args[1] is _raise_system_exit for call in mock_signal.call_args_list)


def test_install_signal_handlers_swallows_registration_error():
    loop = MagicMock(spec=asyncio.AbstractEventLoop)
    loop.add_signal_handler.side_effect = RuntimeError("not in main thread")

    _install_signal_handlers(loop, MagicMock(spec=asyncio.Task))


def test_install_signal_handlers_without_a_current_task():
    loop = MagicMock(spec=asyncio.AbstractEventLoop)

    _install_signal_handlers(loop, None)

    loop.add_signal_handler.assert_not_called()


async def test_termination_signal_cancels_main_task_and_drains(monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_URL", "")

    handlers: dict[signal.Signals, Callable[..., object]] = {}
    handlers_ready = asyncio.Event()
    cleanup = AsyncMock()

    def fake_add_signal_handler(self, sig, callback, *args):
        handlers[sig] = partial(callback, *args)
        handlers_ready.set()

    async def block_forever(*_args, **_kwargs):
        await asyncio.Event().wait()

    site = MagicMock()
    site.start = AsyncMock()
    downloader = MagicMock()
    bot = MagicMock()
    bot.session.close = AsyncMock()

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(type(loop), "add_signal_handler", fake_add_signal_handler, raising=False)
    monkeypatch.setattr(web.AppRunner, "setup", AsyncMock())
    monkeypatch.setattr(web.AppRunner, "cleanup", cleanup)

    with (
        patch("bot.main.Bot", return_value=bot),
        patch("bot.main.DownloaderWrapper", return_value=downloader),
        patch("bot.main.Dispatcher.start_polling", new=block_forever),
        patch("bot.main.web.TCPSite", return_value=site),
    ):
        main_task = asyncio.create_task(main())
        await asyncio.wait_for(handlers_ready.wait(), timeout=5)

        in_flight = asyncio.create_task(asyncio.sleep(0.01))
        monkeypatch.setattr(download, "active_tasks", {in_flight})

        handlers[signal.SIGTERM]()

        with pytest.raises(asyncio.CancelledError):
            await main_task

    assert in_flight.done()
    downloader.shutdown.assert_called_once()
    cleanup.assert_awaited_once()
    bot.session.close.assert_awaited_once()
