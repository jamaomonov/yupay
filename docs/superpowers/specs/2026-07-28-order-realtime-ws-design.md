# Order Realtime (WebSocket) + Delivered/Failed Modal — Design

**Date:** 2026-07-28
**Status:** Approved (brainstorming complete)
**Related ADR:** `docs/decisions/0040-order-realtime-ws.md` (to be written)
**Depends on:** the reviews feature (`feat/reviews-and-ratings`) — the delivered
modal deep-links to the brand review form / opens the reviews sheet.

## Goal

Replace HTTP polling of order status with a live WebSocket push so a logged-in
user sees status changes without reloading. When `order.delivered` arrives,
globally pop a modal ("top-up successful") that asks them to rate the brand; when
`order.failed` arrives, pop a modal pointing to support.

## Decisions (locked)

| Decision               | Choice                                                                                                              |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------- |
| "Rate us" target       | **Brand review** (reuse the reviews feature)                                                                        |
| Audience               | **Logged-in only** (guests keep polling; guest WS deferred)                                                         |
| Delivered/failed modal | **Global** (fires wherever the user is in the app)                                                                  |
| Both events            | **delivered** (→ rate) **and** **failed** (→ support) show a modal                                                  |
| Polling                | **Kept as fallback** — WS primary; polling re-enables when WS is down                                               |
| Fan-out                | **Redis pub/sub** (mandatory: transitions fire in worker/scheduler, WS lives in api — possibly different instances) |

## Architecture

### Backend — new `realtime` module

- `POST /realtime/handshake` (auth, `current_user`) → `{ token }`: a 60s ws-JWT via
  the existing `auth.jwt.mint_ws_handshake(sub=user.id, sid=…, channel="user:{id}")`.
  Rate-limited (global limiter). The client calls it before connecting and on every
  reconnect (`OrderSocket.getToken`).
- `WS /realtime/ws/orders?token=<ws-jwt>`:
  1. Verify the token (`authjwt.verify(token, expected_kind="ws")`) → `user_id` (sub) + `channel`.
     Reject (close 4401) on missing/invalid/expired/wrong-kind token.
  2. Subscribe to Redis channel `realtime:user:{user_id}`.
  3. Forward each published message JSON to the socket. Ignore inbound client
     `{type:"ping"}`. Send a server `{type:"ping", at}` every 25s so the client's
     60s alive-timer stays fresh even on a quiet channel.
  4. On disconnect/`WebSocketDisconnect`: unsubscribe + close cleanly.
- `realtime/service.py`:
  - `async publish_order_event(user_id: str | None, message: dict) -> None` — no-op
    when `user_id is None` (guest orders don't publish); else `redis.publish(
f"realtime:user:{user_id}", json.dumps(message))`.
  - the WS subscribe/forward loop.
- `realtime/api.py` re-exports `publish_order_event`, `router` (handshake), and the
  ws route registration.
- `core/redis.py`: add thin `publish` / `pubsub` helpers if not already present.

### Publishing at transition points

Call `realtime.api.publish_order_event(order.user_id, msg)` after each order status
transition (only when `order.user_id` is set):

| Where                     | Transition     | Message                |
| ------------------------- | -------------- | ---------------------- |
| `payments`/`orders`       | → `paid`       | `order.status_changed` |
| `fulfillment.service:183` | → `fulfilling` | `order.status_changed` |
| `fulfillment.service:897` | → `delivered`  | `order.delivered`      |
| `fulfillment` fail path   | → `failed`     | `order.failed`         |
| `orders.service:612`      | → `cancelled`  | `order.status_changed` |
| `orders.service:695`      | → `expired`    | `order.status_changed` |

Messages follow the existing `packages/api-client/src/realtime/messages.ts`
contract. **Extend `order.delivered`** to carry `brand_slug` (+ `brand_name`) so the
modal deep-links to the review form without an extra fetch; mirror the change in the
Pydantic model. Publishing is fire-and-forget (at-most-once) — acceptable because the
DB is the source of truth and the client re-fetches on reconnect.

### Frontend (web + miniapp)

- **`useOrderSocket()`** — fetches the handshake token, opens `OrderSocket`, and on
  each message updates the TanStack Query cache for the affected order
  (`setQueryData(["order", orderId], …)` / targeted invalidate) so the order screen
  updates live. Tracks a `wsConnected` flag.
- **Polling → fallback:** the existing `refetchInterval` on the order query becomes
  conditional — polls only while `!wsConnected`. WS up ⇒ polling off; WS closes ⇒
  polling resumes.
- **Global modal** via a Zustand store `useOrderResultModal` (mirrors `useLoginModal`):
  the app-wide socket hook (mounted only for logged-in users, high in the tree) opens
  it on `order.delivered` / `order.failed`.
  - **Delivered:** "Пополнение успешно ✓ / заказ доставлен" + **"Оценить покупку"**
    CTA → web: `/{locale}/store/{brand_slug}?order={orderId}#reviews`; miniapp: opens
    `ReviewsSheet` with `formOrderId`. Suppress the CTA if already reviewed (`getMyReviews`).
  - **Failed:** "Что-то пошло не так с заказом" + a support/contact CTA (link to the
    existing support entry) and the order id.
- Mount point: web — a `<RealtimeProvider>` client component inside the auth provider,
  active only when a user is logged in; miniapp — in `App.tsx` after auth bootstrap.

### Infra / security

- WS URL from env (`ws(s)://<api-host>/api/v1/realtime/ws/orders`) — web
  `NEXT_PUBLIC_WS_URL` (or derive from `NEXT_PUBLIC_API_BASE_URL` by swapping the
  scheme), miniapp `VITE_WS_URL`. Caddy already proxies the WS `Upgrade` on the api host.
- **CSP:** add `wss://api.yupay.uz` to `connect-src` in `Caddyfile.prod` (needs a
  `up -d --force-recreate caddy` on prod per the inode gotcha).
- Handshake token is 60s and its channel is bound to the caller's own `user_id`; the
  WS endpoint only ever subscribes to that user's channel — no cross-user leakage.
  Rate-limit the handshake endpoint.

## Out of scope (YAGNI)

Guest WS, presence / "who's online", WS for reviews or catalog, message history /
replay (a reconnecting client just re-fetches the order — the DB is the source of
truth), delivery receipts / read state.

## Testing

- **Backend:** integration test the WS endpoint — connect with a valid ws-token then
  publish an event and assert it's received; reject a missing/expired/wrong-kind
  token; a user never receives another user's channel. Assert `publish_order_event`
  fires at each transition (and is skipped for guest orders).
- **Frontend:** hook test with a mocked `OrderSocket` — a `status_changed` updates the
  order cache; a `delivered` opens the modal with the brand link; polling is disabled
  while connected and resumes on close.

## Docs (same PR)

- `apps/api/src/yupay/modules/realtime/README.md`
- `docs/architecture/module-map.md` (realtime node + edges: publishers → realtime,
  realtime → core/redis)
- `docs/architecture/sequence-diagrams/order-live-update.mmd` (transition → Redis →
  WS → cache update → delivered modal)
- ADR `docs/decisions/0040-order-realtime-ws.md` (WS gateway, Redis pub/sub fan-out,
  handshake-token auth, polling fallback)
- `docs/architecture/cache-keys.md` (the `realtime:user:{id}` pub/sub channel)
- `docs/security/threat-model.md` (WS auth / per-user isolation)
- `docs/api/README.md` + regenerated `docs/api/openapi.json` (handshake endpoint)
