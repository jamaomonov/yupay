# realtime

WebSocket gateway that pushes order-status changes to logged-in users, replacing
tight HTTP polling with a live push (polling stays as a fallback on the frontend).
Fan-out is Redis pub/sub because the transition that triggers a push can happen in
the `api`, `worker`, or `scheduler` process, while the socket itself is held by one
`api` instance — possibly a different one. See
[`docs/decisions/0040-order-realtime-ws.md`](../../../../../docs/decisions/0040-order-realtime-ws.md).

## Endpoints

```
POST /api/v1/realtime/handshake        — auth (current_user); mints a 60s ws token
WS   /api/v1/realtime/ws/orders?token=… — verifies the token, runs the socket
```

- **`POST /realtime/handshake`** requires the normal `Authorization: Bearer
<access-jwt>` and mints a single-purpose token via
  `auth.jwt.mint_ws_handshake(sub=user.id, sid=new_id(), channel=f"user:{user.id}")`:
  `kind="ws"`, 60-second TTL, `channel` always the caller's **own** id — never
  client-supplied. The client calls this once per session and again on every
  reconnect (`OrderSocket.getToken`).
- **`WS /realtime/ws/orders?token=…`** — the browser `WebSocket` API cannot set
  request headers, so the handshake token rides the query string instead of an
  `Authorization` header (accepted tradeoff: `wss://` encrypts it in transit, the
  TTL is 60s, and the only residual exposure is the token appearing in server
  access logs for that window). `routes.ws_orders` verifies the token
  (`authjwt.verify(token, expected_kind="ws")`), closing with code `4401` on any
  failure (missing/expired/wrong-kind/bad-signature — logged as `error=str(exc)`,
  never the token itself), then hands off to `service.run_order_socket`, which:
  1. Accepts the socket.
  2. Subscribes to the Redis channel `channel_for(user_id)` and forwards every
     published message verbatim as a text frame (`_forward`).
  3. Sends a `{"type": "ping", "at": …}` frame every 25 seconds so the client's
     60s alive-timer never lapses on a quiet channel (`_ping`).
  4. Reads and discards client frames until the socket closes (`_drain`) —
     inbound `{"type": "ping"}` from the client's own heartbeat is not acted on.
  5. On whichever task finishes first (usually `_drain` raising on disconnect),
     cancels the others and awaits them with `return_exceptions=True` so a
     teardown error (e.g. `pubsub.unsubscribe`/`aclose` failing) is retrieved
     instead of surfacing as an untraceable "Task exception was never
     retrieved".

## Publish surface

The module's only write API is one function, re-exported from `api.py`:

```python
async def publish_order_event(user_id: str | None, message: dict[str, Any]) -> None
```

- **No-op for guest orders** (`user_id is None`) — guests never had a socket to
  begin with (`useOrderSocket` only mounts for a logged-in user), so this simply
  short-circuits rather than publishing to nobody.
- Otherwise `redis.publish(channel_for(user_id), json.dumps(message))` —
  fire-and-forget, at-most-once. Callers (`orders.service`, `payments.service`,
  `fulfillment.service`) invoke it **immediately, in-transaction**, right after
  setting the new status and flushing — not after commit. The client treats
  every message as a _nudge_, not a payload of record, and does an authoritative
  `GET /orders/{id}` refetch on receipt; an HTTP round-trip vastly outlasts the
  microseconds to commit, so a message published just before a rare rollback
  self-corrects on that refetch rather than requiring an outbox/after-commit
  hook.
- `message` is an open discriminated-union envelope mirrored in
  `packages/api-client/src/realtime/messages.ts` (kept as `dict[str, Any]` here
  rather than a Pydantic model for that reason — the wire contract is owned by
  the TS side).

## Redis channel

`channel_for(user_id) -> f"realtime:user:{user_id}"` — one pub/sub channel per
user, documented in `docs/architecture/cache-keys.md`. It is **not** a cached
value: nothing is ever `GET`, there is no TTL, and a message that finds no
subscriber is simply dropped (Redis pub/sub, not a stream/queue). A socket
subscribes to exactly one channel, derived server-side from the verified
token's `sub` — never from anything the client can set — so one connection can
never observe another user's events.

## Domain rule: no `order.failed`

**A fulfillment failure is not an order failure.** A paid order sits at
`fulfilling` while fulfillment works internally; if a supplier errors or our
internal balance is empty, the order **stays at `fulfilling`** — only an
internal task/attempt row reflects the failure — while an admin resolves it
(top up + retry, or deliver manually). Consequently:

- `order.failed` is defined in the wire contract (for forward-compatibility)
  but is **never emitted** by any publish call site in this codebase.
- There is **no customer-facing "failed" modal** — the frontends' message
  routers group `order.failed` with `ping` as an explicit no-op, not an
  oversight.
- Terminal-but-not-fulfillment outcomes the customer _does_ see —
  `cancelled`, `expired` — still publish a normal `order.status_changed` and
  surface on the order-status page, same as before this feature existed.

**"The order only ever leaves `fulfilling` by reaching `delivered`" used to
stand here and no longer does.** Two writers move a paid order to `failed`:
`orders.service.mark_order_failed_admin` (support closing an undeliverable order
by hand) and, since M3c Task 6, `fulfillment.service` closing a **merchant**
order whose whole deposit charge has already been refunded automatically
(ADR-0071 decision 12). Neither reaches this module: the first is a deliberate
human decision, the second is a merchant order — `user_id IS NULL` by the actor
CHECK — so `publish_order_event` no-ops for it, and both go to the merchant
webhook instead. The rule above is about a **retail** buyer being shown an
internal remediation state as their own final outcome, and it is unchanged.

## Publishers (call sites)

| Module        | Transition                                | Message                |
| ------------- | ----------------------------------------- | ---------------------- |
| `payments`    | → `paid`                                  | `order.status_changed` |
| `fulfillment` | → `fulfilling`                            | `order.status_changed` |
| `fulfillment` | → `delivered`                             | `order.delivered`      |
| `orders`      | → `cancelled` (admin cancel)              | `order.status_changed` |
| `orders`      | → `expired` (TTL, lazy or scheduler bulk) | `order.status_changed` |

Each call site imports `yupay.modules.realtime.api` **lazily, inside the
function** (`from yupay.modules.realtime import api as realtime`) rather than
at module scope — pulling in `realtime.routes` at import time would drag the
whole `api/v1` router stack into every `orders`/`payments`/`fulfillment`
import, the same trap the scheduler jobs and the `catalog`↔`reviews` cycle
avoid (see `docs/architecture/module-map.md`).

## Frontend contract

Web and Mini App both open the shared `@yupay/api-client` `OrderSocket`
(reconnecting, exponential backoff, 25s client heartbeat, closes itself after
60s of silence) via a `useOrderSocket` hook that:

- Invalidates `["order", orderId]` on every message carrying an `orderId` —
  never writes the payload straight into the cache.
- Gates the order query's `refetchInterval` on the socket's `connected` flag —
  polling is the fallback, not removed.
- Opens a global "delivered → rate the brand" modal/dialog on
  `order.delivered`.
