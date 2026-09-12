import time
from collections import defaultdict
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from core.config import settings


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self, rate_limit: float = 1.0) -> None:
        self.rate_limit = rate_limit
        self.last_request: dict[int, float] = defaultdict(float)

    async def __call__(self, handler: Any, event: TelegramObject, data: dict[str, Any]) -> Any:
        message = event if isinstance(event, Message) else None
        user_id = message.from_user.id if message and message.from_user else 0
        now = time.monotonic()
        if now - self.last_request[user_id] < self.rate_limit:
            if message:
                await message.reply("⚠️ Slow down! Please wait a moment.")
            return
        self.last_request[user_id] = now
        return await handler(event, data)


class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler: Any, event: TelegramObject, data: dict[str, Any]) -> Any:
        message = event if isinstance(event, Message) else None
        if settings.ALLOWED_USERS:
            user_id = message.from_user.id if message and message.from_user else 0
            if user_id not in settings.ALLOWED_USERS:
                if message:
                    await message.reply("⛔ Unauthorized.")
                return
        return await handler(event, data)
