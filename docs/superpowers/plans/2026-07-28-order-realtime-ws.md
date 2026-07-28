# Order Realtime (WebSocket) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push order-status changes to logged-in users over a WebSocket (polling kept as fallback); on `order.delivered` pop a global modal that asks them to rate the brand, on `order.failed` a modal pointing to support.

**Architecture:** A new `realtime` FastAPI module exposes a handshake endpoint + a WS gateway that subscribes each connection to a Redis pub/sub channel `realtime:user:{id}`. Order-status transitions (in api / worker / scheduler processes) publish to that channel via `realtime.publish_order_event`. Web + miniapp open the shared `OrderSocket` client, update the TanStack Query order cache on each message, gate polling on WS-disconnected, and show a global delivered/failed modal.

**Tech Stack:** FastAPI WebSocket, `redis.asyncio` pub/sub, EdDSA ws-handshake JWT; Next.js 15 (web), Vite+React+wouter (miniapp); `@yupay/api-client` `OrderSocket`.

**Spec:** `docs/superpowers/specs/2026-07-28-order-realtime-ws-design.md`. **Depends on** the reviews feature branch (modal links to the brand review form).

## Global Constraints

- **Logged-in only.** Publish only when `order.user_id` is set; guests keep polling. The WS endpoint authenticates a 60s ws-handshake JWT (`kind="ws"`) whose `channel` is bound to the caller's own `user_id`; a connection only ever subscribes to `realtime:user:{sub}` — no cross-user data.
- **Redis pub/sub is the fan-out** (transitions fire in worker/scheduler, WS lives in api — possibly different instances). `get_redis()` returns a `decode_responses=True` `redis.asyncio.Redis`.
- **Immediate publish at the transition point** (after the status is set + flushed). The client treats every message as a nudge and does an authoritative `GET /orders/{id}` refetch (HTTP round-trip ≫ the µs to commit, so no practical race); a rare rollback-after-publish self-corrects on that refetch. Publishing is fire-and-forget (at-most-once) — the DB is the source of truth.
- **Message contract is fixed:** `packages/api-client/src/realtime/messages.ts` (`order.status_changed` / `order.delivered` / `order.failed` / `ping`). Do not add fields — the client resolves `brand_slug` from the refetched order (`items[0].display.brand_slug`).
- **Polling is fallback, not removed:** the order query's `refetchInterval` becomes conditional on `!wsConnected`.
- **CSP already allows `wss://api.yupay.uz`** (Caddyfile.prod connect-src) — no Caddy change.
- Errors: raise typed `yupay.core.errors.*`; `mypy --strict`, `ruff` (line 100), Google docstrings (Python); `strict` TS, no `any`. All new user-facing strings in `ru/en/uz` in the same task. Regenerate OpenAPI (`make gen-api`) when routes change. Run `make lint typecheck test` before the branch is done.

---

### Task 1: `realtime` backend — service + WS gateway + handshake

**Files:**
- Create: `apps/api/src/yupay/modules/realtime/service.py`, `routes.py`, `api.py`
- Modify: `apps/api/src/yupay/modules/realtime/__init__.py` (keep docstring)
- Modify: `apps/api/src/yupay/api/v1/__init__.py` (mount, alphabetical — after `promo`/`reviews`)
- Test: `apps/api/tests/integration/test_realtime_ws.py`
- Docs: `make gen-api` (handshake endpoint)

**Interfaces:**
- Consumes: `get_redis` (`yupay.core.redis`), `auth.jwt.{mint_ws_handshake, verify}`, `auth.deps.current_user`, `db_session`, `yupay.core.ids.new_id`, `yupay.core.clock.now`.
- Produces: `realtime.api.publish_order_event(user_id, message)`, `router` (handshake), the WS route.

- [ ] **Step 1: `service.py`**

```python
"""Realtime order updates: publish domain messages to per-user Redis channels
and forward them to a connected WebSocket. Fan-out is Redis pub/sub so a
transition in the worker/scheduler reaches a socket held by any api instance."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from yupay.core.logging import get_logger
from yupay.core.redis import get_redis

log = get_logger("yupay.realtime.service")

_PING_INTERVAL_SECONDS = 25


def channel_for(user_id: str) -> str:
    return f"realtime:user:{user_id}"


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
        await pubsub.unsubscribe(channel_for(user_id))
        await pubsub.aclose()


async def _ping(websocket: WebSocket) -> None:
    """Server-side keepalive so the client's 60s alive-timer never lapses."""
    from yupay.core.clock import now

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
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks:
            t.cancel()


__all__ = ["channel_for", "publish_order_event", "run_order_socket"]
```

- [ ] **Step 2: `routes.py`**

```python
"""HTTP + WebSocket routes for realtime order updates."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket
from pydantic import BaseModel

from yupay.core.errors import UnauthorizedError
from yupay.core.ids import new_id
from yupay.modules.auth import jwt as authjwt
from yupay.modules.auth.deps import current_user
from yupay.modules.realtime.service import run_order_socket
from yupay.modules.users.models import User

router = APIRouter(prefix="/realtime", tags=["realtime"])


class HandshakeOut(BaseModel):
    token: str


@router.post("/handshake", response_model=HandshakeOut, summary="Mint a 60s WS handshake token")
async def handshake(user: Annotated[User, Depends(current_user)]) -> HandshakeOut:
    token = authjwt.mint_ws_handshake(
        sub=user.id, sid=new_id(), channel=f"user:{user.id}"
    )
    return HandshakeOut(token=token)


@router.websocket("/ws/orders")
async def ws_orders(websocket: WebSocket, token: str) -> None:
    try:
        claims = authjwt.verify(token, expected_kind="ws")
    except Exception:  # noqa: BLE001 -- any verify failure closes the handshake
        await websocket.close(code=4401)
        return
    await run_order_socket(websocket, claims.sub)
```

(`token` is a required query param — FastAPI reads `?token=` for WS. A missing/invalid token closes with 4401, matching `OrderSocket`'s reconnect.)

- [ ] **Step 3: `api.py`**

```python
"""Public surface of the ``realtime`` module."""

from yupay.modules.realtime.routes import router
from yupay.modules.realtime.service import publish_order_event

__all__ = ["publish_order_event", "router"]
```

- [ ] **Step 4: Mount** in `apps/api/src/yupay/api/v1/__init__.py` — `from yupay.modules.realtime.api import router as realtime_router` (alphabetical slot) + `router.include_router(realtime_router)`.

- [ ] **Step 5: Failing test** `apps/api/tests/integration/test_realtime_ws.py`

Use the `integration_client` app with `httpx`/Starlette's WS test transport, or FastAPI `TestClient` websocket. Mint a ws token with `mint_ws_handshake`. Tests:
```python
import pytest

pytestmark = pytest.mark.asyncio


async def test_ws_receives_published_event(integration_client, ws_token_for):
    token = ws_token_for("user-abc")
    async with integration_client.websocket_connect(f"/api/v1/realtime/ws/orders?token={token}") as ws:
        from yupay.modules.realtime.service import publish_order_event
        await publish_order_event("user-abc", {"type": "order.status_changed", "orderId": "o1", "status": "paid", "at": "t"})
        msg = await ws.receive_json()
        assert msg["type"] == "order.status_changed" and msg["orderId"] == "o1"


async def test_ws_rejects_bad_token(integration_client):
    with pytest.raises(Exception):
        async with integration_client.websocket_connect("/api/v1/realtime/ws/orders?token=garbage"):
            ...


async def test_publish_is_noop_for_guest():
    from yupay.modules.realtime.service import publish_order_event
    await publish_order_event(None, {"type": "x"})  # must not raise
```
(Adapt to the project's WS test helper — if `integration_client` (httpx ASGITransport) can't do WS, use `starlette.testclient.TestClient(app).websocket_connect`. Discover the working approach; a helper `ws_token_for` mints via `mint_ws_handshake`. Real Redis (dev) is used by the integration harness.)

- [ ] **Step 6: Run + regen + commit** — `pytest apps/api/tests/integration/test_realtime_ws.py -v` PASS; `make gen-api`; commit `feat(api/realtime): WS gateway + handshake + Redis fan-out`.

---

### Task 2: Publish at order-status transitions

**Files:**
- Modify: `apps/api/src/yupay/modules/fulfillment/service.py` (`_try_settle_order` → delivered; fail paths → failed; the `paid → fulfilling` block ~line 183)
- Modify: `apps/api/src/yupay/modules/orders/service.py` (cancel ~612, expire ~695)
- Modify: `apps/api/src/yupay/modules/payments/service.py` (the `paid` transition — `order.status = "paid"` at line 255)
- Test: `apps/api/tests/integration/test_realtime_publish.py`

**Interfaces:**
- Consumes: `realtime.api.publish_order_event`. Import lazily inside the function (`from yupay.modules.realtime import api as realtime`) to avoid pulling the WS route stack at module import (same trap as the scheduler jobs / catalog↔reviews).

- [ ] **Step 1: A small helper** in each touched service (or a shared one) to publish a status_changed:
```python
async def _publish_status(order) -> None:
    from yupay.modules.realtime import api as realtime
    await realtime.publish_order_event(
        order.user_id,
        {"type": "order.status_changed", "orderId": order.id, "status": order.status,
         "at": order.updated_at.isoformat()},
    )
```
For the terminal cases in `_try_settle_order`, publish `order.delivered`:
```python
await realtime.publish_order_event(order.user_id,
    {"type": "order.delivered", "orderId": order.id, "payload": {"kind": "order", "data": None}})
```
and for the fail path, `order.failed` with a generic reason (never PII).

- [ ] **Step 2: Wire the call sites** — after each `order.status = …; order.updated_at = now()` (+ its `db.flush()`), call the publish helper. Only fires for logged-in orders (helper passes `order.user_id`, which `publish_order_event` no-ops on None). Confirm the transitions covered: `paid`, `fulfilling`, `delivered`, `failed`, `cancelled`, `expired`.

- [ ] **Step 3: Failing test** — drive an order to delivered through the fulfillment service (reuse the fulfillment test factories) with a real Redis SUBSCRIBE on `realtime:user:{uid}`; assert an `order.delivered` message lands. A guest order (`user_id=None`) publishes nothing. Assert the `paid`/`cancelled` transitions publish `order.status_changed`.

- [ ] **Step 4: Run + commit** — `feat(api): publish order status transitions to realtime`.

---

### Task 3: Web — `useOrderSocket` hook + polling gate

**Files:**
- Modify: `apps/web/package.json` (add `"@yupay/api-client": "workspace:*"`)
- Create: `apps/web/src/lib/realtime.ts` (handshake fetch + a `connectOrderSocket` factory)
- Create: `apps/web/src/hooks/useOrderSocket.ts`
- Modify: `apps/web/src/components/order/OrderStatus.tsx` (gate `refetchInterval` on WS state)
- Modify: `apps/web/src/app/[locale]/Providers.tsx` (mount a `<RealtimeProvider>` for logged-in users)
- Test: `apps/web/src/hooks/useOrderSocket.test.tsx`

**Interfaces:**
- Consumes: `OrderSocket`, `OrderUpdateMessage` from `@yupay/api-client`; `apiFetch` (`@/lib/client`); `useAuth`; `useQueryClient`.

- [ ] **Step 1: `lib/realtime.ts`**
```ts
import { OrderSocket } from "@yupay/api-client";
import { apiFetch } from "./client";

const WS_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000")
  .replace(/^http/, "ws")
  .replace(/\/$/, "") + "/api/v1/realtime/ws/orders";

export function createOrderSocket(handlers: {
  onMessage: (m: import("@yupay/api-client").OrderUpdateMessage) => void;
  onOpen?: () => void;
  onClose?: () => void;
}): OrderSocket {
  return new OrderSocket({
    url: WS_URL,
    getToken: async () => (await apiFetch<{ token: string }>("/realtime/handshake", { method: "POST" })).token,
    onMessage: handlers.onMessage,
    onOpen: handlers.onOpen,
    onClose: handlers.onClose,
  });
}
```

- [ ] **Step 2: `useOrderSocket` + RealtimeProvider** — a client component that, when `useAuth().user` is set, creates one `OrderSocket`, tracks `wsConnected` in a Zustand store (`useRealtimeStatus`), and on each message: `qc.invalidateQueries({ queryKey: ["order", m.orderId] })` (authoritative refetch) and dispatches delivered/failed to the modal store (Task 4). Closes the socket on logout/unmount. Mount `<RealtimeProvider>` in `Providers.tsx`.

- [ ] **Step 3: Gate polling** — in `OrderStatus.tsx`, read `useRealtimeStatus().connected` and change `refetchInterval` to `(q) => (!connected && q.state.data && IN_MOTION.has(q.state.data.status) ? 4000 : false)`.

- [ ] **Step 4: Test** — mock `@yupay/api-client` `OrderSocket` (capture the `onMessage`), render the hook with a QueryClient, fire a `status_changed` → assert `invalidateQueries` called for `["order", id]`; fire `delivered` → assert the modal store opened. Verify polling is disabled while `connected`.

- [ ] **Step 5: Run + commit** — `pnpm --filter web typecheck test`; commit `feat(web): live order updates over WebSocket with polling fallback`.

---

### Task 4: Web — global delivered/failed modal

**Files:**
- Create: `apps/web/src/store/useOrderResultModal.ts` (Zustand — mirror `useLoginModal`)
- Create: `apps/web/src/components/order/OrderResultModal.tsx`
- Modify: `apps/web/src/app/[locale]/layout.tsx` (mount the modal once, like the login modal)
- Modify: `packages/i18n/locales/{ru,en,uz}/web.json` (new `orderResult` keys)
- Test: `apps/web/src/components/order/OrderResultModal.test.tsx`

**Interfaces:**
- Consumes: `useOrderResultModal` (holds `{ kind: "delivered" | "failed"; orderId }`), `getMyReviews` (`@/lib/reviews`), `apiFetch` (to fetch the order for `brand_slug`).

- [ ] **Step 1: Store** `useOrderResultModal` — `{ open(kind, orderId), close(), state }`. Task 3's hook calls `open("delivered", orderId)` / `open("failed", orderId)`.
- [ ] **Step 2: Modal** — on open, fetch `GET /orders/{orderId}` for `items[0].display.{brand_slug,brand_name}`. **Delivered:** title `orderResult.deliveredTitle` ("Пополнение успешно"), body, and a **"Оценить покупку"** button → `/{locale}/store/{brand_slug}?order={orderId}#reviews` (hidden if `getMyReviews()` already contains the order). **Failed:** title `orderResult.failedTitle`, body, a support link. Reuse the app's dialog styling (mirror the login modal).
- [ ] **Step 3: i18n** — `orderResult.{deliveredTitle,deliveredBody,rateCta,failedTitle,failedBody,supportCta,close}` in ru/en/uz.
- [ ] **Step 4: Test** — render with the store opened `delivered` + a mocked order fetch → asserts the rate link href; opened `failed` → asserts the support CTA.
- [ ] **Step 5: Run + commit** — `feat(web): global delivered/failed order modal with rate CTA`.

---

### Task 5: Mini App — live updates + delivered/failed modal

**Files:**
- Modify: `apps/miniapp/package.json` (add `@yupay/api-client`)
- Create: `apps/miniapp/src/lib/realtime.ts`, `apps/miniapp/src/hooks/useOrderSocket.ts`
- Create: `apps/miniapp/src/components/OrderResultDialog.tsx` (uses `components/ui/dialog.tsx`)
- Modify: `apps/miniapp/src/lib/orders.ts` (`useOrder` — gate `refetchInterval` on WS state)
- Modify: `apps/miniapp/src/App.tsx` (mount the socket hook + dialog for a signed-in user, after `BootstrapGate`)
- Modify: `packages/i18n/locales/{ru,en,uz}/miniapp.json` (flat `orderResult.*` keys)
- Test: a hook/component test if the miniapp suite supports it

**Interfaces:**
- Consumes: `OrderSocket` from `@yupay/api-client`; `apiGet`/`apiPost` (`@/lib/api`); `useMe`; the existing `ReviewsSheet` (open with `formOrderId` on the delivered "rate" CTA).

- [ ] **Step 1: `lib/realtime.ts`** — derive the WS URL from `apiBase` (swap `http`→`ws`); `getToken` via `apiPost("/api/v1/realtime/handshake", {})`.
- [ ] **Step 2: `useOrderSocket`** — mounted for a signed-in user (`useMe().data`), one `OrderSocket`, tracks `connected` in a small store, invalidates `["order", orderId]` on message, and opens the `OrderResultDialog` on delivered/failed.
- [ ] **Step 3: Gate polling** — `useOrder` refetchInterval also returns `false` when the socket is connected.
- [ ] **Step 4: `OrderResultDialog`** — delivered: "Пополнение успешно" + "Оценить" → opens `ReviewsSheet` with `formOrderId`; failed: support message. Fetch the order for `brand_slug`.
- [ ] **Step 5: i18n** — `orderResult.*` flat keys in ru/en/uz (parity test must stay green).
- [ ] **Step 6: Run + commit** — `pnpm --filter miniapp typecheck`; commit `feat(miniapp): live order updates + delivered/failed dialog`.

---

### Task 6: Docs

**Files:**
- Create: `apps/api/src/yupay/modules/realtime/README.md`
- Modify: `docs/architecture/module-map.md` (realtime row + edges: publishers → realtime, realtime → core/redis)
- Create: `docs/architecture/sequence-diagrams/order-live-update.mmd`
- Create: `docs/decisions/0040-order-realtime-ws.md` (MADR — WS gateway, Redis pub/sub fan-out, ws-handshake auth, immediate-publish + client-refetch, polling fallback)
- Modify: `docs/architecture/cache-keys.md` (the `realtime:user:{id}` pub/sub channel — note it's a transient channel, not a cached key)
- Modify: `docs/security/threat-model.md` (WS auth: 60s handshake, per-user channel isolation)
- Modify: `docs/api/README.md` (handshake + ws endpoint) + verify `docs/api/openapi.json` current

- [ ] Steps: write each doc; note CSP already permits `wss://api.yupay.uz` (no Caddy change); commit `docs(realtime): module map, ADR-0040, sequence diagram, security notes`.

---

## Final verification (before opening the PR)

- [ ] `make lint typecheck test` green (Python + all TS workspaces).
- [ ] `make gen-api` no diff (handshake endpoint committed).
- [ ] WS verified end-to-end locally (a status change pushes without reload; delivered modal appears; killing the socket re-enables polling).
- [ ] All three locales updated for every new key.
- [ ] No PII in messages/logs; a connection only receives its own user's channel.
- [ ] PR notes: depends on the reviews branch; rollback = feature is additive (drop the module + revert publish calls); CSP already allows wss.
