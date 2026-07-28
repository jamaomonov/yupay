"""Realtime order updates: publish domain messages to per-user Redis channels
and forward them to a connected WebSocket. Fan-out is Redis pub/sub so a
transition in the worker/scheduler reaches a socket held by any api instance."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from starlette.websockets import WebSocket

from yupay.core.clock import now
from yupay.core.logging import get_logger
from yupay.core.redis import get_redis

log = get_logger("yupay.realtime.service")

_PING_INTERVAL_SECONDS = 25


def channel_for(user_id: str) -> str:
    """Return the Redis pub/sub channel name a given user's order events publish to."""
    return f"realtime:user:{user_id}"


# ``message`` is an open discriminated-union envelope mirrored in
# packages/api-client/src/realtime/messages.ts, hence dict[str, Any] rather than a model.
async def publish_order_event(user_id: str | None, message: dict[str, Any]) -> None:
    """Publish an order message to the user's channel. No-op for guest orders."""
    if user_id is None:
        return
    await get_redis().publish(channel_for(user_id), json.dumps(message))


async def _forward(websocket: WebSocket, user_id: str) -> None:
    """Subscribe to the user's channel and forward each message to the socket."""
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(channel_for(user_id))
    try:
        async for msg in pubsub.listen():
            if msg.get("type") == "message":
                await websocket.send_text(msg["data"])
    finally:
        # Ensure the pooled connection is always released: if unsubscribe() raises
        # (e.g. a transient Redis error), aclose() must still run.
        try:
            await pubsub.unsubscribe(channel_for(user_id))
        finally:
            await pubsub.aclose()  # type: ignore[no-untyped-call]  # redis-py: unannotated


async def _ping(websocket: WebSocket) -> None:
    """Server-side keepalive so the client's 60s alive-timer never lapses."""
    while True:
        await asyncio.sleep(_PING_INTERVAL_SECONDS)
        await websocket.send_text(json.dumps({"type": "ping", "at": now().isoformat()}))


async def _drain(websocket: WebSocket) -> None:
    """Read (and ignore) client frames; raises WebSocketDisconnect on close."""
    while True:
        await websocket.receive_text()


async def run_order_socket(websocket: WebSocket, user_id: str) -> None:
    """Accept the socket and run forward/ping/drain until the client disconnects."""
    await websocket.accept()
    tasks = [
        asyncio.create_task(_forward(websocket, user_id)),
        asyncio.create_task(_ping(websocket)),
        asyncio.create_task(_drain(websocket)),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        # Wait for cancellation to complete and retrieve each task's exception (if
        # any) so a teardown error (e.g. _forward's unsubscribe/aclose) is never
        # dumped to stderr as an untraceable "Task exception was never retrieved".
        await asyncio.gather(*tasks, return_exceptions=True)


__all__ = ["channel_for", "publish_order_event", "run_order_socket"]
