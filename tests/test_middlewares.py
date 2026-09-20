import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Message, User

from bot.middlewares.throttle import AuthMiddleware, ThrottleMiddleware
from core.config import settings


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
    middleware = ThrottleMiddleware(rate_limit=0.05)
    handler = AsyncMock(return_value="ok")

    await middleware(handler, mock_message, {})
    assert handler.call_count == 1

    time.sleep(0.06)

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


async def test_auth_middleware_public_mode(mock_message, monkeypatch):
    monkeypatch.setattr(settings, "ALLOWED_USERS", [])
    middleware = AuthMiddleware()
    handler = AsyncMock(return_value="allowed")

    res = await middleware(handler, mock_message, {})
    assert res == "allowed"
    handler.assert_called_once()
    assert mock_message.reply.call_count == 0


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
