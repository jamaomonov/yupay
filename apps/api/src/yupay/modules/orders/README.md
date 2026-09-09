# `orders` module

Order aggregate with FSM, idempotent creation, and frozen price + FX snapshots.
See [ADR-0011](../../../../../docs/decisions/0011-order-fsm-and-snapshots.md).

## Responsibilities

- Own `orders`, `order_items`, `order_events`.
- Accept new orders from authenticated users, guest checkouts (by email), **and**
  B2B merchants ordering through `/merchant/v1` — one `Actor`, three arms.
- Validate `fulfillment_data` against the product's `required_fields` schema.
- Freeze `unit_price_usd` per item, plus the multiplier and market rate the
  line was priced at (ADR-0051), via the [`fx` trust gate](../pricing/fx_guard.py).
- Provide owner-scoped read endpoints and admin endpoints for ops.

## Tables

| Table          | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `orders`       | Exactly one of `user_id` / `guest_email` / `merchant_id` is set (`ck_orders_actor_exclusive`; the merchant arm is the B2B reseller channel — RESTRICT FK, merchants with orders get frozen, never deleted). `purpose` is `catalog` (storefront sale) or `wallet_topup` (1:1 deposit, no line items, ADR-0058). Customer `GET /orders` hides funding rows. Per-actor partial UNIQUE on `idempotency_key` — one per arm (`uq_orders_idem_user`, `uq_orders_idem_guest`, `uq_orders_idem_merchant`), so a replayed key resolves in the database and two actors may hold the same key. `total_charged` is the sum of the per-line charges, rounded to the currency's smallest chargeable unit (whole so'm for UZS, kopecks for RUB) so it is always an exact tiyin amount acquirers accept. It is **not** `total_usd × rate`: a variable-amount line is charged at `market_rate × sku.rate_multiplier`, and an override-priced line ignores the rate entirely. |
| `order_items`  | `unit_price_usd` frozen, `fulfillment_data` validated. `rate_multiplier` + `fx_rate` freeze what the line was priced at (ADR-0051) so its value in USD never depends on today's catalog config — see [`revenue.py`](revenue.py). `fulfillment_state` runs its own micro-FSM (`pending → reserved → in_progress → delivered`).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `order_events` | Append-only audit. Outbox reads from here when `payments` + `fulfillment` land.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |

## Public interface

```python
from yupay.modules.orders.api import (
    Order, OrderItem, OrderEvent,                # ORM
    OrderCreate, OrderOut, OrderListOut,         # DTOs
    OrderAdminOut, OrderAdminListOut,
    Actor,                                       # service value object (user | guest | merchant)
    create_order, get_order_for_actor,           # service fns
    list_orders_for_actor,
    cancel_order_admin, get_order_admin, list_orders_admin,
    mark_order_failed_admin,
    router, admin_router,                        # FastAPI
)
```

## HTTP surface

| Method | Path                               | Auth                      | Purpose                                                                                                                                                              |
| ------ | ---------------------------------- | ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POST` | `/api/v1/orders`                   | Bearer or Guest           | Create order. Requires `Idempotency-Key` (≥16 chars).                                                                                                                |
| `GET`  | `/api/v1/orders/{id}`              | Bearer or Guest+`?email=` | Owner-only detail. 404 on mismatch.                                                                                                                                  |
| `GET`  | `/api/v1/orders`                   | Bearer                    | List my orders (DESC, capped at 50).                                                                                                                                 |
| `GET`  | `/api/v1/admin/orders`             | admin role                | All orders, optional `status` filter.                                                                                                                                |
| `GET`  | `/api/v1/admin/orders/{id}`        | admin role                | Detail with full event log.                                                                                                                                          |
| `POST` | `/api/v1/admin/orders/{id}/cancel` | admin role                | Only valid from `pending_payment`.                                                                                                                                   |
| `POST` | `/api/v1/admin/orders/{id}/fail`   | admin role                | Close a paid-but-undeliverable order. Body `{reason}` (required). Only from `paid`/`fulfilling`/`fulfilled`; cascades open tasks + pending payments. Moves no money. |

## FSM

```
pending_payment → paid → fulfilling → fulfilled → delivered
       ↓                       ↓
   cancelled             failed → refunded
       ↓
    expired
```

Status transitions write an `order.<verb>` event. Illegal transitions return 409.

`failed` has **two** writers, and `FAILABLE_STATUSES` is the one list of states
either may close from (`paid`/`fulfilling`/`fulfilled` — never `delivered`,
which is a refund and moves real money):

- `mark_order_failed_admin` — support closing a paid-but-undeliverable order by
  hand, with a required reason;
- `fulfillment.service._end_a_refunded_merchant_order` — a **merchant** order
  whose whole deposit charge has come back automatically (M3c Task 6). Retail
  is untouched: a terminal fulfilment failure still leaves the order row alone,
  because an operator may still top up, retry or deliver by hand. For a
  refunded merchant order all three are already refused with `409
deposit_already_returned`, so the order really is over.

Both go through `on_order_status_changed`.

## Idempotency

`POST /orders` requires `Idempotency-Key: <≥16 chars>`. The unique
`(user_id|guest_email|merchant_id, idempotency_key)` constraint prevents double-create
even under concurrent retries; the second call returns the same order body.

The scope is **per actor**, not global: each arm has its own partial UNIQUE
(`uq_orders_idem_user`, `uq_orders_idem_guest` from migration 0006;
`uq_orders_idem_merchant` from 0069). Two merchants may legitimately pick the same
`merchant_order_id` — they cannot see each other's keys — and a merchant's key never
replays a retail order.

## Merchant (B2B) orders

An order placed through `POST /merchant/v1/orders` uses the same `create_order`
as the storefront, with three merchant-only differences, all guarded here:

- **`unit_price_usd_override`** — one USD price per line, carrying the wholesale
  price `merchants.pricing` computed. Passing it with a non-merchant actor is a
  `ValidationError`, not a silently-ignored argument: a client-supplied price
  reaching a retail order is the one thing this seam must never become.
- **`affiliate_code` is refused** on the merchant arm. `resolve_code` is called
  with `user_id=actor.user_id`, which is NULL for a merchant, so a code would
  resolve like a _guest's_ and take a retail discount off an already-wholesale
  price.
- **Fulfilment is always enqueued, never run inline.** The merchant path calls
  `start_for_order` with `fulfilment_async` forced on, whatever the deployment
  is configured with, so a supplier purchase can never sit inside the
  transaction that took the money — see `merchants/orders.py::_enqueue_only`.
  Retail is unchanged and still follows the flag.
- **`mark_merchant_order_paid`** moves the order `pending_payment → paid`
  without a `Payment` row: the deposit debit is the settlement (spec §9.5), so a
  merchant order never rests in `pending_payment` and is invisible to the expiry
  sweep. It records the machine API's replay fingerprint on the `order.paid`
  event, and publishes nothing to realtime — `user_id` is NULL by construction.
  It does call the status-change seam below, with `publish_realtime=False`: the
  webhook half is the point, the nudge half is the thing that sentence declines.

## The status-change seam

`on_order_status_changed(db, order, *, publish_realtime=True)` is the **one
place** where "the order's status just changed" has consequences. Every site
that writes `order.status` calls it — this module's four, `payments.service`'s
four, `fulfillment.service`'s two — so a fourth consequence is added once
rather than to three of the four sites somebody remembered. The three modules
used to keep a verbatim copy of the realtime nudge each; they now delegate.

Two consequences today, disjoint by construction: the realtime nudge reaches a
**retail owner**, and `merchants.webhooks` reaches a **merchant**. The webhook
needed a seam rather than the existing publish precisely because
`publish_order_event` is a no-op for a NULL `user_id`, which every merchant
order has — the branch is `order.merchant_id is not None`.

Call it after `status` and `updated_at` are set and, for the webhook half,
from inside the transaction that set them: the delivery row and its
`pg_notify` ride the caller's transaction.

`publish_realtime=False` at the two sites that deliberately have no
`order.status_changed` nudge — `mark_merchant_order_paid` (no owner to nudge)
and `fulfillment`'s settle, which publishes `order.delivered` instead and must
not start sending a connected storefront a second event for one transition.

Drawn in `docs/architecture/sequence-diagrams/merchant-webhook-emit.mmd`.

`source` stays `"unknown"` on a merchant order, and now carries a fourth
meaning: not "the client did not say" but "no storefront placed this". The
column's CHECK admits only `web` / `miniapp` / `bot` / `unknown`, so a
`merchant_api` value would need a migration and is out of M2's scope. **The
discriminator is `merchant_id IS NOT NULL`, not `source`** — reporting that
splits by surface should exclude merchant rows explicitly rather than let them
land in the `unknown` bucket beside genuinely unattributed retail orders.

`find_merchant_order` is the per-merchant replay lookup that path needs before
it prices anything. The rest of the flow — pricing, the deposit, fulfilment —
lives in `merchants/orders.py`; see
`docs/architecture/sequence-diagrams/merchant-order-create.mmd`.

## Guest auth

Guests pass `Authorization: Guest <jwt>` (JWT minted by `POST /auth/guest`). The body
**must** include the plain `email` so the server can verify it against the JWT's
`email_hash` claim — see ADR-0007 for the hash construction.

For order lookup, the guest must also pass `?email=…` in the query string (the JWT
alone only carries the hash).

## Tests

- `apps/api/tests/integration/test_orders_routes.py` — 9 cases:
  - mandatory `Idempotency-Key`
  - happy path, replay returns same id
  - missing required field / pattern violation / unknown `select` option
  - 404 for cross-user lookup
  - list orders for self
  - admin list + cancel (twice → 409)

## What's deliberately **not** here yet

- **Payment integration**: payments saga listens for `order.created` and pushes the
  order through `paid`. Lands with the `payments` module.
- **Fulfilment**: takes a `paid` order, calls suppliers/inventory, sets
  `order_items.fulfillment_state`. Lands with the `fulfillment` module.
- **Expiry sweeper**: a scheduled job will flip aged `pending_payment` rows to
  `expired`. Lands with `apps/scheduler`.
- **Guest order lookup link** (signed magic link in email) — once `notifications`
  ships.
