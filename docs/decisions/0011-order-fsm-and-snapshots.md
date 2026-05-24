# 0011. Order FSM, idempotency, and price/FX snapshots

- **Status**: Accepted
- **Date**: 2026-05-16
- **Deciders**: founding team
- **Tags**: backend, orders, money

## Context

Orders are the central transactional entity. The flow:

1. Customer selects a SKU, fills the product's `required_fields`, hits "pay".
2. We need a stable order record with a frozen total **before** redirecting to the
   payment gateway. Without that, every refund / dispute / audit reopens "what did
   they actually owe us?"
3. We must accept the same request twice without double-charging (network blips,
   client retries, browser back-button → resubmit).
4. We must support **anonymous (guest) checkout** by email as well as logged-in
   Telegram users.
5. Once paid, the order travels through fulfilment + delivery (later modules read
   from the same table).

This ADR fixes the schema, state machine, and the price/FX snapshot rules. The
saga that drives the order through fulfilment + payment is mostly described
here too, even though the actual orchestration code ships in later PRs.

## Decision

### Schema

```
orders
  id                  UUID PK
  user_id             UUID NULL  → users.id            (NULL for guest checkout)
  guest_email         CITEXT NULL                       (NOT NULL when user_id IS NULL)
  status              VARCHAR(24) NOT NULL              (see FSM below)
  currency            VARCHAR(8) NOT NULL               (display currency, e.g. RUB)
  total_usd           NUMERIC(20,6) NOT NULL            (Σ items, frozen at creation)
  total_charged       NUMERIC(20,6) NOT NULL            (total_usd × fx_snapshot.rate)
  fx_snapshot_id      UUID NULL → fx_snapshots.id       (NULL when currency == USD)
  expires_at          TIMESTAMPTZ NOT NULL              (now() + 30 min on insert)
  idempotency_key     VARCHAR(128) NULL                 (client-supplied)
  ip_hash             CHAR(64) NULL
  ua_hash             CHAR(64) NULL
  created_at, updated_at, paid_at, fulfilled_at, cancelled_at  -- timestamps for audit

  -- exactly one of user_id / guest_email is set:
  CHECK ((user_id IS NULL) <> (guest_email IS NULL))
  -- idempotency is scoped per actor:
  UNIQUE (user_id, idempotency_key)    WHERE user_id IS NOT NULL
  UNIQUE (guest_email, idempotency_key) WHERE guest_email IS NOT NULL

order_items
  id                  UUID PK
  order_id            UUID NOT NULL → orders.id ON DELETE CASCADE
  sku_id              UUID NOT NULL → catalog.skus.id ON DELETE RESTRICT
  qty                 INTEGER NOT NULL CHECK (qty > 0)
  unit_price_usd      NUMERIC(20,6) NOT NULL            (sku.price_usd at creation)
  fulfillment_data    JSONB NOT NULL DEFAULT '{}'        (player_id, server, ...)
  fulfillment_state   VARCHAR(24) NOT NULL DEFAULT 'pending'
  supplier_order_id   VARCHAR(128) NULL                 (filled by fulfilment)

order_events
  id            UUID PK
  order_id      UUID NOT NULL → orders.id ON DELETE CASCADE
  kind          VARCHAR(48) NOT NULL    (order.created, order.paid, ...)
  payload       JSONB NOT NULL DEFAULT '{}'
  actor         VARCHAR(64) NULL        ('user:<id>', 'admin:<id>', 'system')
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
```

`order_events` is append-only; it carries the audit trail and is the source the
outbox relay reads from when `payments` and `fulfillment` land.

### FSM

```
       ┌─────────────────────────── pending_payment ──────────────────────────┐
       │                                  │                                   │
       │                                  ▼                                   ▼
   cancelled                            paid                              expired
       ▲                                  │
       │                                  ▼
       │                              fulfilling
       │                                  │
       │                       ┌──────────┴────────┐
       │                       ▼                   ▼
       │                  fulfilled            failed
       │                       │                   │
       │                       ▼                   ▼
       └──────── refunded ◄── delivered           refunded
```

Allowed transitions:

| From              | To                                | Actor             |
| ----------------- | --------------------------------- | ----------------- |
| `pending_payment` | `paid`                            | payments saga     |
| `pending_payment` | `cancelled`                       | user / admin      |
| `pending_payment` | `expired`                         | scheduled job     |
| `paid`            | `fulfilling`                      | fulfillment saga  |
| `fulfilling`      | `fulfilled`                       | fulfillment saga  |
| `fulfilling`      | `failed`                          | fulfillment saga  |
| `fulfilled`       | `delivered`                       | delivery          |
| `delivered`       | `refunded` / `partially_refunded` | admin             |
| `failed`          | `refunded`                        | automatic / admin |

Every transition writes an `order_events` row with the kind matching the verb
(`order.paid`, `order.fulfilled`, ...). Illegal transitions raise `ConflictError`.

### Idempotency

- `POST /api/v1/orders` **requires** `Idempotency-Key` (24-char minimum).
- Scope: `(user_id, key)` for authenticated, `(guest_email, key)` for guests.
- On replay we re-read the existing order and return the **same JSON** the first
  call returned. We deliberately do not re-process the body — replays whose
  body differs are still rejected with 409 (`idempotency conflict`).

### Price snapshot

- At order creation, for each item:
  - Read `sku.price_usd` once and copy into `order_items.unit_price_usd`.
  - SKU stays referenced so admin tools can still resolve "what was this item?"
  - The SKU's `required_fields` schema is read once and `fulfillment_data` is
    validated against it. Validation errors → 422 with the offending key.
- `total_usd = Σ qty × unit_price_usd`.

### FX snapshot

- If the requested `currency` is **USD**, `fx_snapshot_id = NULL`,
  `total_charged = total_usd`.
- Otherwise the service calls `fx.snapshot(base="USD", quote=<currency>)`. The FX
  module returns either a fresh snapshot (≤ 5 min old) or creates a new one. We
  store its id in `orders.fx_snapshot_id` and compute
  `total_charged = total_usd × snapshot.rate`.
- The locked rate **never updates**. Customer disputes can replay the math with
  a single SQL join.

### Expiry

`orders.expires_at = created_at + 30 min`. A scheduled job
(`orders.sweep_expired`) flips `pending_payment` rows whose `expires_at <= now()`
to `expired`. Implementation lands with `apps/scheduler`.

### Auth model

- `POST /orders` accepts **both** `Authorization: Bearer <user>` and
  `Authorization: Guest <jwt>`. The guest token carries `email_hash` (see
  ADR-0007); the request body must include the matching plain `email` so the
  order has a contactable address.
- `GET /orders/{id}` requires the same auth flavour as the order's owner:
  guest token (with matching `email`) for guest orders; user Bearer for user
  orders. 404 on mismatch (deliberately, to avoid leaking existence).
- Admin endpoints under `/admin/orders/*` use `require_admin`.

## Consequences

- **Refunds and disputes are trivial**: every order carries its frozen USD total
  and the exact FX rate it was charged at.
- **Idempotency is enforced by the DB**, not the application. Concurrency wars
  cannot create two orders for the same `(actor, key)`.
- The `order_events` table is the spine the saga reads from once `payments` and
  `fulfillment` land. No retrofitting needed.
- We add three tables now; later modules **extend**, not **rewrite**.

## Alternatives considered

- **No FX snapshot, recompute at refund** — rejected: race against rate changes
  produces ambiguous numbers in disputes.
- **Embed `required_fields` into `order_items` as a copy of the schema** —
  considered, but the schema is already immutable per-product (admin edits create
  a new version); for v1 we store only the _filled_ data, not the schema.
- **Soft-delete orders** — rejected: orders never disappear; we use `cancelled`
  / `refunded` statuses instead.

## References

- [ADR-0004 — double-entry ledger](./0004-double-entry-ledger.md)
- [ADR-0007 — JWT format](./0007-jwt-format-and-rotation.md)
- [ADR-0008 — FX provider chain](./0008-fx-provider-chain.md)
- [ADR-0009 — catalog levels](./0009-catalog-three-level-plus-form-schema.md)
