"""Async Redis client singleton."""

from __future__ import annotations

from redis.asyncio import Redis, from_url

from yupay.core.config import get_settings

_client: Redis | None = None


def get_redis() -> Redis:
    """Return the lazily-initialised async Redis client."""
    global _client
    if _client is None:
        _client = from_url(
            get_settings().redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _client


async def close_redis() -> None:
    """Close the Redis client on shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
