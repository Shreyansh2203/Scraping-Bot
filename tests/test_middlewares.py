import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Dispatcher
from aiogram.types import Chat, Message, Update, User

from bot.handlers import commands, download
from bot.main import _build_dispatcher
from bot.middlewares.throttle import AuthMiddleware, ThrottleMiddleware
from core.config import settings
from core.downloader_wrapper import DownloaderWrapper


@pytest.fixture
def mock_message():
    msg = MagicMock(spec=Message)
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = 12345
    msg.reply = AsyncMock()
    return msg


async def test_throttle_middleware_allows_first_and_throttles_rapid(mock_message):
    middleware = ThrottleMiddleware(rate_limit=1.0)
    handler = AsyncMock(return_value="ok")

    # First request should succeed
    res1 = await middleware(handler, mock_message, {})
    assert res1 == "ok"
    assert handler.call_count == 1
    assert mock_message.reply.call_count == 0

    # Rapid second request should be throttled
    res2 = await middleware(handler, mock_message, {})
    assert res2 is None
    assert handler.call_count == 1  # Handler not called again
    mock_message.reply.assert_called_once_with("⚠️ Slow down! Please wait a moment.")


async def test_throttle_middleware_allows_after_interval(mock_message):
    middleware = ThrottleMiddleware(rate_limit=1.0)
    handler = AsyncMock(return_value="ok")

    await middleware(handler, mock_message, {})
    assert handler.call_count == 1

    middleware.last_request[12345] = time.monotonic() - 2.0

    res = await middleware(handler, mock_message, {})
    assert res == "ok"
    assert handler.call_count == 2


async def test_throttle_middleware_non_message_event():
    middleware = ThrottleMiddleware(rate_limit=1.0)
    handler = AsyncMock(return_value="passed")
    event = object()  # Not a Message

    res = await middleware(handler, event, {})
    assert res == "passed"
    handler.assert_called_once_with(event, {})


async def test_throttle_middleware_no_from_user(mock_message):
    mock_message.from_user = None
    middleware = ThrottleMiddleware(rate_limit=1.0)
    handler = AsyncMock(return_value="ok")

    res = await middleware(handler, mock_message, {})
    assert res == "ok"
    assert 0 in middleware.last_request


def test_throttle_cleanup_max_size():
    middleware = ThrottleMiddleware(rate_limit=10.0, max_size=3)
    now = time.monotonic()
    middleware.last_request = {
        1: now - 1,
        2: now - 2,
        3: now - 3,
        4: now - 4,
        5: now - 5,
    }

    middleware._cleanup(now)
    # Should be reduced to max_size 3
    assert len(middleware.last_request) <= 3
    # The oldest (4, 5) should have been removed
    assert 5 not in middleware.last_request
    assert 4 not in middleware.last_request


async def test_auth_middleware_empty_allow_list_denies_by_default(mock_message, monkeypatch):
    # An empty allow-list must deny everyone. It used to be treated as "no restriction",
    # which meant every value that failed to parse (a stray comma, a non-numeric ID,
    # whitespace) silently opened the bot to every caller.
    monkeypatch.setattr(settings, "ALLOWED_USERS", [])
    monkeypatch.setattr(settings, "ALLOW_PUBLIC", False)
    middleware = AuthMiddleware()
    handler = AsyncMock(return_value="allowed")

    res = await middleware(handler, mock_message, {})
    assert res is None
    handler.assert_not_called()
    mock_message.reply.assert_called_once_with("⛔ Unauthorized.")


async def test_auth_middleware_empty_list_allows_when_public_opted_in(
    mock_message,
    monkeypatch,
):
    monkeypatch.setattr(settings, "ALLOWED_USERS", [])
    monkeypatch.setattr(settings, "ALLOW_PUBLIC", True)
    middleware = AuthMiddleware()
    handler = AsyncMock(return_value="allowed")

    res = await middleware(handler, mock_message, {})
    assert res == "allowed"
    handler.assert_called_once()
    assert mock_message.reply.call_count == 0


async def test_auth_middleware_malformed_allow_list_never_reaches_the_handler(
    mock_message,
    monkeypatch,
):
    # The end-to-end shape of the original defect: config parsing yields an empty list
    # and the middleware must refuse rather than wave the caller through.
    monkeypatch.setattr(settings, "ALLOWED_USERS", [])
    monkeypatch.setattr(settings, "ALLOW_PUBLIC", False)
    middleware = AuthMiddleware()
    handler = AsyncMock(return_value="allowed")

    await middleware(handler, mock_message, {})
    handler.assert_not_called()


async def test_auth_middleware_authorized_user(mock_message, monkeypatch):
    monkeypatch.setattr(settings, "ALLOWED_USERS", [12345, 67890])
    middleware = AuthMiddleware()
    handler = AsyncMock(return_value="allowed")

    res = await middleware(handler, mock_message, {})
    assert res == "allowed"
    handler.assert_called_once()
    assert mock_message.reply.call_count == 0


async def test_auth_middleware_unauthorized_user(mock_message, monkeypatch):
    monkeypatch.setattr(settings, "ALLOWED_USERS", [99999])
    middleware = AuthMiddleware()
    handler = AsyncMock(return_value="allowed")

    res = await middleware(handler, mock_message, {})
    assert res is None
    handler.assert_not_called()
    mock_message.reply.assert_called_once_with("⛔ Unauthorized.")


async def test_auth_middleware_non_message_event():
    middleware = AuthMiddleware()
    handler = AsyncMock(return_value="passed")
    event = object()

    res = await middleware(handler, event, {})
    assert res == "passed"
    handler.assert_called_once_with(event, {})


def test_throttle_default_allows_about_one_request_per_second():
    """Pin the rate the bot is actually wired with, not just the one tests pass in.

    Every other test constructs ThrottleMiddleware with an explicit rate_limit, so a
    change to the default -- the value bot/main.py registers -- was invisible.
    """
    assert ThrottleMiddleware().rate_limit == 1.0


_CHAT = Chat(id=500, type="private")


class _EchoBot:
    """Stands in for aiogram's Bot: records the text of every reply the bot sends."""

    id = 777

    def __init__(self):
        self.sent: list[str] = []

    async def __call__(self, method, *args, **kwargs):
        self.sent.append(getattr(method, "text", ""))
        return MagicMock(
            message_id=1,
            date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            chat=_CHAT,
        )


def _dispatcher_like_main() -> Dispatcher:
    """The dispatcher bot/main.py actually serves updates with.

    Deliberately built by calling the production factory rather than by repeating its
    wiring here: a test that reassembles the dispatcher itself proves nothing about
    whether main() registers the middlewares. aiogram refuses to re-parent a router, so
    the shared module-level routers are detached first and left attached afterwards --
    detaching afterwards would sever the link the outer middlewares resolve through.
    """
    commands.router._parent_router = None
    download.router._parent_router = None
    return _build_dispatcher(MagicMock(spec=DownloaderWrapper), "test-only-webhook-secret")


async def _feed(texts_and_users, same_dispatcher: bool = False) -> list[list[str]]:
    """Push updates through a Dispatcher assembled exactly as bot/main.py assembles it.

    ``same_dispatcher`` keeps one Dispatcher across the updates, which is what the
    throttle test needs: its state lives on the middleware instance.
    """
    dp = _dispatcher_like_main()
    results: list[list[str]] = []
    for index, (text, user_id) in enumerate(texts_and_users, start=1):
        bot = _EchoBot()
        update = Update(
            update_id=index,
            message=Message(
                message_id=index,
                date=datetime(2026, 1, 1, tzinfo=timezone.utc),
                chat=_CHAT,
                from_user=User(id=user_id, is_bot=False, first_name="Tester"),
                text=text,
            ),
        )
        if not same_dispatcher:
            dp = _dispatcher_like_main()
        await dp.feed_update(bot, update)
        results.append(bot.sent)
    return results


async def test_auth_middleware_is_wired_onto_the_dispatcher(monkeypatch):
    """ALLOWED_USERS is the bot's only access control; prove it is actually registered.

    The middleware classes are unit tested, which says nothing about whether
    bot/main.py installs them. Deleting either registration line used to leave the
    whole suite green.
    """
    monkeypatch.setattr(settings, "ALLOWED_USERS", [999])

    blocked, allowed = await _feed([("/start", 12345), ("/start", 999)])

    assert blocked == ["⛔ Unauthorized."], "an unlisted user was not stopped by the dispatcher"
    assert allowed and allowed != ["⛔ Unauthorized."], "a listed user was blocked"


async def test_throttle_middleware_is_wired_onto_the_dispatcher(monkeypatch):
    # Auth denies by default on an empty allow-list, so opt in here: this test is about
    # the throttle being wired onto the dispatcher, not about who is allowed to call it.
    monkeypatch.setattr(settings, "ALLOWED_USERS", [])
    monkeypatch.setattr(settings, "ALLOW_PUBLIC", True)

    first, second = await _feed([("/help", 4242), ("/help", 4242)], same_dispatcher=True)

    assert len(first) == 1 and not first[0].startswith("⚠️")
    assert second == [
        "⚠️ Slow down! Please wait a moment."
    ], "the second rapid message from one user was not throttled by the dispatcher"
