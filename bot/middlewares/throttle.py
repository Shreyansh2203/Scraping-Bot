from aiogram import BaseMiddleware
from aiogram.types import Message
from collections import defaultdict
import time

from core.config import settings


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self, rate_limit: float = 1.0):
        self.rate_limit = rate_limit
        self.last_request: dict[int, float] = defaultdict(float)

    async def __call__(self, handler, event: Message, data):
        user_id = event.from_user.id if event.from_user else 0
        now = time.monotonic()
        if now - self.last_request[user_id] < self.rate_limit:
            await event.reply("⚠️ Slow down! Please wait a moment.")
            return
        self.last_request[user_id] = now
        return await handler(event, data)


class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message, data):
        if settings.ALLOWED_USERS:
            user_id = event.from_user.id if event.from_user else 0
            if user_id not in settings.ALLOWED_USERS:
                await event.reply("⛔ Unauthorized.")
                return
        return await handler(event, data)
