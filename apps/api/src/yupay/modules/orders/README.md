# `orders` module

Order aggregate with FSM, idempotent creation, and frozen price + FX snapshots.
See [ADR-0011](../../../../../docs/decisions/0011-order-fsm-and-snapshots.md).

## Responsibilities

- Own `orders`, `order_items`, `order_events`.
- Accept new orders from authenticated users **and** guest checkouts (by email).
- Validate `fulfillment_data` against the product's `required_fields` schema.
- Freeze `unit_price_usd` per item and lock the FX rate via
  [`fx.snapshot`](../fx/service.py).
- Provide owner-scoped read endpoints and admin endpoints for ops.

## Tables

| Table          | Notes                                                                                                                                                                                                                                                                                                               |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `orders`       | Either `user_id` or `guest_email` is set (CHECK enforced). Per-actor partial UNIQUE on `idempotency_key`. `total_charged = total_usd × fx_snapshot.rate` (frozen), rounded to the currency's smallest chargeable unit (whole so'm for UZS, kopecks for RUB) so it is always an exact tiyin amount acquirers accept. |
| `order_items`  | `unit_price_usd` frozen, `fulfillment_data` validated. `fulfillment_state` runs its own micro-FSM (`pending → reserved → in_progress → delivered`).                                                                                                                                                                 |
| `order_events` | Append-only audit. Outbox reads from here when `payments` + `fulfillment` land.                                                                                                                                                                                                                                     |

## Public interface

```python
from yupay.modules.orders.api import (
    Order, OrderItem, OrderEvent,                # ORM
    OrderCreate, OrderOut, OrderListOut,         # DTOs
    OrderAdminOut, OrderAdminListOut,
    Actor,                                       # service value object
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

## Idempotency

`POST /orders` requires `Idempotency-Key: <≥16 chars>`. The unique
`(user_id|guest_email, idempotency_key)` constraint prevents double-create even under
concurrent retries; the second call returns the same order body.

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
