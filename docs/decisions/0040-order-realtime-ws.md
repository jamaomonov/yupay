# 0040. Order realtime updates over WebSocket

- **Status**: Accepted
- **Date**: 2026-07-28
- **Deciders**: @jamaomonov
- **Tags**: backend | frontend | infra

## Context and problem statement

The order-status page (web and Mini App) polled `GET /orders/{id}` on a fixed
interval to notice `paid → fulfilling → delivered` transitions. That means a
lag of several seconds between the DB flipping the status and the customer
seeing it, plus load that scales with concurrently-open order pages rather
than with actual events. It also builds on the reviews feature (ADR-0039): we
want a "your order was delivered — rate the brand" moment that fires the
instant delivery happens, not on the next poll tick.

The forces at play:

- Order-status transitions happen in **three different processes** — the
  `api` request path (`payments`, most `orders` transitions), the
  `fulfillment` saga (still synchronous in-process per ADR-0013, so also
  `api`), and the `apps/scheduler` bulk-expiry job. A live connection, by
  contrast, is held by exactly one `api` instance. Any push mechanism has to
  bridge across process/instance boundaries.
- The deployment target is a single VPS today but must stay horizontally
  splittable (§1 of `AGENTS.md`) — a design that only works with sticky
  routing to "the" api instance would violate that.
- The browser's native `WebSocket` API cannot set custom request headers, so
  bearer-token auth (as used for every REST call) doesn't transfer directly.
- Guests are a large share of orders (no login) and were explicitly kept out
  of scope for this iteration (see the design spec).

## Decision drivers

- Sub-second UX for the delivered/rate-the-brand moment, without hammering
  Postgres with tighter polling.
- Must work across multiple `api` instances without sticky sessions (staying
  splittable, per `AGENTS.md` §1 scale targets).
- Minimal blast radius: additive, easy to roll back, doesn't touch the order
  FSM or existing polling path.
- No new infra dependency — Redis is already deployed and used elsewhere
  (`fx`, `stats`, rate limiting).
- Preserve the existing security posture: short-lived, single-purpose tokens
  (mirrors `guest`/`email_verify`/`password_reset` JWT kinds already in
  `auth.jwt`), no PII in the socket payload.

## Considered options

1. **WebSocket gateway in `api` + Redis pub/sub fan-out** — a new `realtime`
   module; publishers call `publish_order_event`, subscribers are WS
   connections in any `api` instance.
2. **Tighter HTTP polling only** — reduce the interval (e.g. 2s) instead of
   building push infrastructure.
3. **Server-Sent Events (SSE) instead of WebSocket** — one-way push is all
   this needs (client never sends order data over the channel).
4. **In-process pub/sub (no Redis), sticky routing to the instance holding
   the socket** — skip the extra hop through Redis.

## Decision outcome

**Chosen option: 1.** A new `realtime` module exposes `POST
/realtime/handshake` (mints a 60-second `kind="ws"` JWT scoped to
`channel="user:{id}"`) and `WS /realtime/ws/orders?token=…`. On accept, the
socket subscribes to the Redis channel `realtime:user:{id}`. Order-status
transitions in `payments.service`, `fulfillment.service`, and `orders.service`
call `realtime.api.publish_order_event(order.user_id, message)` **immediately,
in-transaction** (right after setting the status and flushing, not after
commit) — fire-and-forget, at-most-once. The client treats every message as a
nudge and does an authoritative `GET /orders/{id}` refetch
(`invalidateQueries(["order", orderId])`) rather than trusting the payload, so
the microsecond window between publish and commit is a non-issue: an HTTP
round-trip dwarfs it, and a rare rollback-after-publish just self-corrects on
that refetch. Frontend polling (`refetchInterval`) is **kept as a fallback**,
gated on the socket's `connected` flag — it resumes the instant the socket
drops and never runs while connected.

**Auth tradeoff (accepted):** the browser `WebSocket` API cannot set request
headers, so the handshake token rides the URL
(`?token=<jwt>`) instead of an `Authorization` header. This is accepted
because: `wss://` (TLS) protects the token in transit; the token is
single-purpose and expires in 60 seconds; it carries no PII (just `sub` and
`channel`, both already the user's own id); and the WS route re-derives the
subscribed channel from the verified token server-side, never from anything
client-supplied. The residual exposure is the token appearing in server/proxy
access logs for that 60-second window — judged acceptable given the short TTL
and narrow scope, same tradeoff class as the existing `guest`/`email_verify`
token kinds. `Caddyfile.prod`'s CSP already allows `connect-src wss://api.yupay.uz`,
so no infra change was needed.

**Domain rule (decided during execution, not in the original spec): a
fulfillment failure is not an order failure.** A paid order sits at
`fulfilling` while fulfillment works internally; if a supplier errors or our
internal code-warehouse balance is empty, the order **stays at `fulfilling`**
— only an internal `FulfillmentTask`/`FulfillmentAttempt` row reflects the
failure — while an admin resolves it out of band (top up + retry, or deliver
manually). The order only ever leaves `fulfilling` by reaching `delivered`.
The original design spec called for an `order.failed` message and a
customer-facing "failed → contact support" modal; during Task 2 (wiring the
publish call sites) it became clear no such customer-visible transition
exists in the FSM to hang that message off — inventing one would mean
surfacing an internal remediation state as if it were a final, customer-owned
failure, which is not true and would generate needless support tickets for
something an admin is already actively fixing. **`order.failed` stays defined
in the wire contract** (`packages/api-client/src/realtime/messages.ts`) for
forward compatibility, but no call site emits it, and both frontends'
message routers group it with `ping` as an explicit no-op (with an
exhaustive-switch `never` guard so a future variant can't silently fall
through unhandled). `cancelled`/`expired` are real customer-visible terminal
states and do publish a normal `order.status_changed`.

### Positive consequences

- Order-status page updates in near real time for logged-in users; the
  delivered → rate-the-brand modal fires the moment fulfillment finishes.
- Works unchanged across any number of `api` instances — Redis pub/sub is the
  fan-out, not in-process memory, so there is no sticky-session requirement.
- Additive and low-risk: nothing about the order FSM, the polling path, or
  guest checkout changed. Rollback is "drop the module + revert the publish
  call sites" with no data migration.
- Guests are unaffected (`publish_order_event` no-ops on `user_id=None`) and
  keep the exact polling behavior that existed before this feature.

### Negative consequences

- A message can theoretically be published just before a transaction rolls
  back (in-transaction, not after-commit). Accepted: the client-side refetch
  model makes this self-correcting, and the alternative (after-commit/outbox)
  adds latency and complexity disproportionate to a UX nudge.
- The `?token=` query-string tradeoff means the handshake token can appear in
  access logs for its 60-second lifetime — narrower than a leaked bearer
  token, but not zero.
- One more moving part in the deploy topology (WS upgrade proxied by Caddy);
  mitigated by Caddy already terminating `wss://` for other paths, and by the
  fallback: if the WS tier misbehaves, polling silently takes back over.
- Guest orders and the failed/support-modal case from the original spec are
  out of scope for this iteration — guests keep polling only, and there is no
  failure modal at all (see the domain rule above).

## Validation

Integration tests (`apps/api/tests/integration/test_realtime_ws.py`,
`test_realtime_publish.py`) cover: a valid handshake token can subscribe and
receive a published event; an invalid/expired/wrong-kind token is rejected
(close 4401); a guest order publish is a no-op; each of the `paid` /
`fulfilling` / `delivered` / `cancelled` / `expired` transitions publishes the
expected message shape. Frontend hook tests (`useOrderSocket.test.tsx` /
`.test.ts`) assert the message-to-side-effect mapping, including that
`order.failed` is a deliberate no-op. Success = the delivered modal appears
without a page reload in manual verification, and killing the socket
re-enables polling within one interval.

## Alternatives considered (detail)

### Option 2 — tighter polling only

Simpler (zero new infra), but a 2s interval on every open order-status page
scales linearly with concurrent viewers rather than with actual status
changes, working against the 200 RPS peak / single-VPS target, and still
leaves multi-second lag rather than the near-instant push the delivered-modal
UX wants. Rejected.

### Option 3 — SSE instead of WebSocket

SSE is a reasonable one-way-push alternative and would sidestep the
"WebSocket API can't set headers" auth wrinkle only partially (`EventSource`
also can't set custom headers, so the same `?token=` tradeoff would apply
anyway). It doesn't need the client-heartbeat/ping machinery a WS needs, but
offers no material advantage here since the payload direction is already
one-way in practice (the client's own `{"type":"ping"}` frames are the only
thing sent upstream, and are ignored). Not chosen because the `@yupay/api-client`
`OrderSocket` abstraction (reconnect/backoff/heartbeat) was already the
shape the design spec settled on, and a plain WS keeps the door open for a
genuinely bidirectional use case later without a second migration. Not
revisited unless connection-count overhead becomes a measured problem.

### Option 4 — in-process pub/sub, no Redis

Cheaper (no extra hop) but only works if the transition and the socket are
guaranteed to be handled by the same process — false today (fulfillment saga
and scheduler bulk-expiry can run on any instance) and permanently false once
horizontally split. Rejected as directly contradicting the "must remain
horizontally splittable without rewrites" scale target.

## References

- `docs/superpowers/specs/2026-07-28-order-realtime-ws-design.md` — approved
  design spec this ADR formalizes.
- `docs/superpowers/plans/2026-07-28-order-realtime-ws.md` — task-by-task
  implementation plan (the domain rule is called out as "decided during
  execution" in Task 2/3).
- `apps/api/src/yupay/modules/realtime/README.md` — module reference.
- `docs/architecture/module-map.md` — `realtime` row + dependency edges.
- `docs/architecture/sequence-diagrams/order-live-update.mmd`.
- `docs/architecture/cache-keys.md` — `realtime:user:{id}` pub/sub channel.
- `docs/security/threat-model.md` — WebSocket section.
- [ADR-0007](./0007-jwt-format-and-rotation.md) — JWT kinds this handshake
  token follows the same pattern as.
- [ADR-0039](./0039-reviews-and-ratings.md) — the reviews feature the
  delivered modal deep-links into.
