from __future__ import annotations

import time
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from core.config import settings


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self, rate_limit: float = 1.0, max_size: int = 10000) -> None:
        self.rate_limit = rate_limit
        self.max_size = max_size
        self.last_request: dict[int, float] = {}

    def _cleanup(self, now: float) -> None:
        """Evict timestamps older than rate_limit window to prevent memory leaks."""
        expired = [uid for uid, ts in self.last_request.items() if now - ts > self.rate_limit]
        for uid in expired:
            del self.last_request[uid]
        if len(self.last_request) > self.max_size:
            oldest_keys = sorted(self.last_request, key=lambda k: self.last_request[k])[
                : len(self.last_request) - self.max_size
            ]
            for uid in oldest_keys:
                del self.last_request[uid]

    async def __call__(self, handler: Any, event: TelegramObject, data: dict[str, Any]) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        user_id = event.from_user.id if event.from_user else 0
        now = time.monotonic()
        self._cleanup(now)

        if user_id in self.last_request and (now - self.last_request[user_id] < self.rate_limit):
            await event.reply("⚠️ Slow down! Please wait a moment.")
            return
        self.last_request[user_id] = now
        return await handler(event, data)


class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler: Any, event: TelegramObject, data: dict[str, Any]) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        if settings.ALLOWED_USERS:
            user_id = event.from_user.id if event.from_user else 0
            if user_id not in settings.ALLOWED_USERS:
                await event.reply("⛔ Unauthorized.")
                return
        return await handler(event, data)
