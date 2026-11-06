from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Message

from bot.handlers.commands import cmd_help, cmd_start


@pytest.fixture
def mock_message():
    msg = MagicMock(spec=Message)
    msg.reply = AsyncMock()
    return msg


async def test_cmd_start(mock_message):
    await cmd_start(mock_message)
    mock_message.reply.assert_called_once()
    args, _ = mock_message.reply.call_args
    assert "Send me an Instagram or Twitter/X video URL" in args[0]


async def test_cmd_help(mock_message):
    await cmd_help(mock_message)
    mock_message.reply.assert_called_once()
    args, _ = mock_message.reply.call_args
    assert "Just paste a video URL" in args[0]
