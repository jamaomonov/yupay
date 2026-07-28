"""Integration tests for the ``realtime`` WS gateway + handshake.

``integration_client`` (httpx over ``ASGITransport``) has no ``websocket_connect`` —
the WS-shaped tests here build their own app and drive it with Starlette's
``TestClient``, which runs the ASGI app on a dedicated thread/event loop via an
anyio blocking portal. Publishing is done through a brand-new ``redis.asyncio``
connection (never the process-wide ``get_redis()`` singleton) so the publish side
never touches the app's event loop — mixing the two would raise "Future attached
to a different loop" (see the caching comment in ``integration_client``).
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from httpx import AsyncClient
from redis.asyncio import from_url
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from yupay.bootstrap import create_app
from yupay.core.config import get_settings
from yupay.core.ids import new_id
from yupay.modules.auth import jwt as authjwt
from yupay.modules.users.models import User

# No module-level ``pytestmark = pytest.mark.asyncio``: two of the three tests here
# are synchronous (they drive Starlette's ``TestClient``, which manages its own
# event loop on a dedicated thread). ``asyncio_mode = "auto"`` (pyproject.toml)
# already marks the one ``async def`` test below without it.

_WS_PATH = "/api/v1/realtime/ws/orders"


def _publish_repeatedly(channel: str, message: dict[str, object], stop: threading.Event) -> None:
    """Publish ``message`` on ``channel`` every 50ms until ``stop`` is set.

    Redis pub/sub never queues for a subscriber that hasn't registered yet, so a
    single publish right after the WS connects is a race against the server-side
    ``pubsub.subscribe()`` call. Repeating the publish on its own connection (a
    fresh one, not the cached ``get_redis()`` singleton) sidesteps that race
    without coupling this test to internal timing.
    """

    async def _run() -> None:
        redis = from_url(get_settings().redis_url, decode_responses=True)
        try:
            payload = json.dumps(message)
            while not stop.is_set():
                await redis.publish(channel, payload)
                await asyncio.sleep(0.05)
        finally:
            await redis.aclose()

    asyncio.run(_run())


def test_ws_receives_published_event() -> None:
    """A message published on the user's channel is forwarded over the socket."""
    app = create_app()
    token = authjwt.mint_ws_handshake(sub="user-abc", sid=new_id(), channel="user:user-abc")
    stop = threading.Event()

    with TestClient(app) as client, client.websocket_connect(f"{_WS_PATH}?token={token}") as ws:
        publisher = threading.Thread(
            target=_publish_repeatedly,
            args=(
                "realtime:user:user-abc",
                {"type": "order.status_changed", "orderId": "o1", "status": "paid", "at": "t"},
                stop,
            ),
            daemon=True,
        )
        publisher.start()
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                msg = pool.submit(ws.receive_json).result(timeout=10)
        finally:
            stop.set()
            publisher.join(timeout=2)

    assert msg["type"] == "order.status_changed"
    assert msg["orderId"] == "o1"


def test_ws_rejects_bad_token() -> None:
    """A garbage token closes the handshake instead of ever accepting."""
    app = create_app()
    with (
        pytest.raises(WebSocketDisconnect),
        TestClient(app) as client,
        client.websocket_connect(f"{_WS_PATH}?token=garbage"),
    ):
        pass


async def test_publish_is_noop_for_guest() -> None:
    """Guest orders (``user_id=None``) must not raise or touch Redis."""
    from yupay.modules.realtime.service import publish_order_event

    await publish_order_event(None, {"type": "x"})


async def test_handshake_mints_ws_token(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """``POST /realtime/handshake`` mints a 60s ``ws`` token bound to the caller."""
    user_id = str(uuid.uuid4())
    db_session.add(User(id=user_id, roles=[]))
    await db_session.flush()
    await db_session.commit()
    access_token = authjwt.mint_access(sub=user_id, sid=str(uuid.uuid4()))

    resp = await integration_client.post(
        "/api/v1/realtime/handshake",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert resp.status_code == 200, resp.text
    ws_token = resp.json()["token"]
    claims = authjwt.verify(ws_token, expected_kind="ws")
    assert claims.sub == user_id
    assert claims.channel == f"user:{user_id}"


async def test_handshake_requires_auth(integration_client: AsyncClient) -> None:
    """No/invalid ``Authorization`` header is rejected before minting anything."""
    resp = await integration_client.post("/api/v1/realtime/handshake")
    assert resp.status_code == 401
