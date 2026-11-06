from __future__ import annotations

import time
from typing import Any, Optional

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from core.config import settings


class ThrottleMiddleware(BaseMiddleware):
    """Per-user rate limiting with an optional Redis backend for distributed deployments.

    When ``REDIS_URL`` is set and the ``redis`` package is installed, Redis is the
    authoritative store so multiple bot replicas share a single rate-limit namespace.
    Otherwise the in-memory ``last_request`` dict is used, which is correct for a
    single-replica deployment and keeps existing tests green.
    """

    def __init__(
        self,
        rate_limit: float = 1.0,
        max_size: int = 10000,
        redis_url: Optional[str] = None,
    ) -> None:
        self.rate_limit = rate_limit
        self.max_size = max_size
        self.last_request: dict[int, float] = {}
        self._redis_url = redis_url or settings.REDIS_URL
        self._redis: Any = None

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

    async def _get_redis(self) -> Any:
        if self._redis is not None:
            return self._redis
        if not self._redis_url:
            return None
        try:
            import redis.asyncio as redis  # type: ignore[import-not-found]

            self._redis = redis.from_url(self._redis_url)
            return self._redis
        except ImportError:
            return None

    async def _is_throttled(self, user_id: int, now: float) -> bool:
        redis_client = await self._get_redis()
        if redis_client is not None:
            key = f"scraping-bot:throttle:{user_id}"
            try:
                last = await redis_client.get(key)
                if last is not None:
                    try:
                        last_ts = float(last)
                        if now - last_ts < self.rate_limit:
                            return True
                    except ValueError:
                        pass
                await redis_client.setex(key, int(self.rate_limit) + 1, str(now))
                return False
            except Exception:
                # Redis misbehaved: fall through to in-memory below.
                self._redis = None

        self._cleanup(now)
        if user_id in self.last_request and now - self.last_request[user_id] < self.rate_limit:
            return True
        self.last_request[user_id] = now
        return False

    async def __call__(self, handler: Any, event: TelegramObject, data: dict[str, Any]) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        user_id = event.from_user.id if event.from_user else 0
        now = time.monotonic()

        if await self._is_throttled(user_id, now):
            await event.reply("⚠️ Slow down! Please wait a moment.")
            return
        return await handler(event, data)


class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler: Any, event: TelegramObject, data: dict[str, Any]) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        # An empty allow-list denies everyone unless an operator has explicitly opted in
        # to a public bot. Reading truthiness of ALLOWED_USERS alone made every malformed
        # value (an unparsable ID, a stray comma, whitespace) open the bot to everyone,
        # because the check was skipped rather than failed.
        if not settings.ALLOWED_USERS:
            if not settings.ALLOW_PUBLIC:
                await event.reply("⛔ Unauthorized.")
                return
            return await handler(event, data)

        user_id = event.from_user.id if event.from_user else 0
        if user_id not in settings.ALLOWED_USERS:
            await event.reply("⛔ Unauthorized.")
            return
        return await handler(event, data)
