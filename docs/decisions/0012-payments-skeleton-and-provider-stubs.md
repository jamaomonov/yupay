# 0012. Payments skeleton: mock provider + region-specific stubs

- **Status**: Accepted
- **Date**: 2026-05-16
- **Builds on**: ADR-0005 (gateway abstraction), ADR-0011 (order FSM)
- **Deciders**: founding team
- **Tags**: backend, payments, integrations

## Context

We need the **payments seam** in place before fulfilment can be wired up — order
must traverse `pending_payment → paid` for downstream code to fire. At the same
time, no real acquirer is contracted yet:

- International gateways (Stripe / PayPal) are **out of scope** per business
  decision — global cards are not the target market.
- Uzbek acquirers (Click, Payme, Uzum) and Russian acquirers (YooKassa, Tinkoff) are
  the actual targets, but contracts and sandbox credentials aren't in hand.
- A crypto acquirer (USDT) is planned but specific provider not chosen.

We don't want to:

1. Block other modules behind "waiting for the merchant agreement".
2. Bake assumptions about a specific provider's webhook shape into the database.
3. Ship to staging without any way to flip an order to `paid` for testing.

## Decision

Land a **mock-end-to-end provider** that completes the payments flow, plus
explicit **stubs** for every region/acquirer we will integrate later.

### Tables (see migration `0007_payments_init`)

```
payments
  id                UUID PK
  order_id          UUID NOT NULL → orders.id
  provider          VARCHAR(32) NOT NULL    -- 'mock' | 'click' | 'payme' | ...
  status            VARCHAR(24) NOT NULL    -- pending | requires_action | succeeded | failed | cancelled | refunded
  amount            NUMERIC(20,6) NOT NULL
  currency          VARCHAR(8)  NOT NULL
  intent_url        VARCHAR(2048) NULL      -- where the customer is redirected
  external_id       VARCHAR(128) NULL       -- provider's intent id
  metadata          JSONB NOT NULL DEFAULT '{}'
  created_at, updated_at, succeeded_at NULL, failed_at NULL

  UNIQUE (provider, external_id)            -- partial; external_id may be NULL while pending

payment_attempts
  id                UUID PK
  payment_id        UUID NOT NULL → payments.id
  kind              VARCHAR(24) NOT NULL    -- create_intent | webhook | refund | cancel
  status            VARCHAR(16) NOT NULL    -- ok | error
  payload           JSONB NOT NULL DEFAULT '{}'
  error             TEXT NULL
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()

payment_webhooks
  id                UUID PK
  provider          VARCHAR(32) NOT NULL
  external_event_id VARCHAR(255) NOT NULL    -- provider's event id
  received_at, processed_at NULL
  payload           JSONB NOT NULL
  signature_ok      BOOLEAN NOT NULL
  UNIQUE (provider, external_event_id)       -- dedup
```

### `PaymentGateway` protocol

```python
class PaymentGateway(Protocol):
    provider: str
    available: bool                     # False for stubs in non-dev environments

    async def create_intent(
        self, *, order, return_url: str
    ) -> PaymentIntent: ...

    async def verify_webhook(
        self, *, headers: Mapping[str, str], body: bytes
    ) -> WebhookEvent: ...

    async def refund(
        self, *, payment, amount: Decimal
    ) -> RefundResult: ...
```

Implementations live in `apps/api/src/yupay/modules/payments/gateways/`. The
registry resolves a provider slug to its gateway.

### Provider matrix

| Slug       | State                                         | Module                 |
| ---------- | --------------------------------------------- | ---------------------- |
| `mock`     | **functional** (dev/test only)                | `gateways/mock.py`     |
| `click`    | stub — raises `NotImplementedError` with TODO | `gateways/click.py`    |
| `payme`    | stub                                          | `gateways/payme.py`    |
| `uzum`     | stub                                          | `gateways/uzum.py`     |
| `yookassa` | stub                                          | `gateways/yookassa.py` |
| `tinkoff`  | stub                                          | `gateways/tinkoff.py`  |
| `crypto`   | stub                                          | `gateways/crypto.py`   |

Each stub:

- Reports itself via `provider: str` and `available: bool`. The `available`
  property is `False` outside dev and is checked by the service before calling
  any RPC method.
- Reserves the **webhook URL slug** (`/webhooks/payments/<slug>`) so the eventual
  real impl just fills in `verify_webhook` and `create_intent` without route
  churn.
- Raises `NotImplementedError("<provider> not integrated yet")` from
  `create_intent` / `refund`.

The **mock** provider:

- `create_intent` returns a `PaymentIntent` with `intent_url` pointing at
  `https://mock.local/pay/<payment_id>` (the SPA renders a "Simulate payment"
  button against `/admin/payments/{id}/simulate-webhook`).
- `verify_webhook` accepts any payload as long as it contains the matching
  `payment_id` (no signature check — it's mock).
- `refund` instant-succeeds.

### Order FSM transitions

Triggered exclusively by `handle_webhook`:

| Webhook outcome            | Payment status | Order status (was → now) | Event               |
| -------------------------- | -------------- | ------------------------ | ------------------- |
| signature OK + `succeeded` | `succeeded`    | `pending_payment → paid` | `order.paid`        |
| signature OK + `failed`    | `failed`       | unchanged                | `payment.failed`    |
| signature OK + `cancelled` | `cancelled`    | unchanged                | `payment.cancelled` |

Re-deliveries of the same `external_event_id` short-circuit on the partial UNIQUE
in `payment_webhooks` and do not produce duplicate `order.paid` events.

### Routes

```
POST /api/v1/payments/intents                # user|guest creates an intent
GET  /api/v1/payments/{id}                   # owner-only lookup
POST /webhooks/payments/{provider}           # raw body, no auth, signature-verified

# admin
GET  /api/v1/admin/payments                  # list with filters
POST /api/v1/admin/payments/{id}/simulate    # dev/staging — fires a synthetic webhook
```

### Idempotency

- `POST /payments/intents` accepts `Idempotency-Key`. Two intents from the same
  actor with the same key return the same payment. **One** intent per order at a
  time; subsequent calls for an order with an active payment return the existing
  one.
- Webhooks dedup by `(provider, external_event_id)`. Replay → 200 with the same
  body the first call produced (idempotent observer).

### Refunds

Out of scope for the skeleton. The `refund()` protocol method exists so the
shape is right; implementations will land alongside their providers.

## Consequences

- Every module that depends on `paid` (fulfilment, notifications, ledger) can be
  built and tested today using the mock provider.
- Onboarding a new acquirer is: implement two methods + register the gateway, no
  schema or route changes.
- A staging env stuck without merchant agreements can still process orders end-to-end.
- Webhook signature verification is the **first** thing each real gateway must
  implement — the route already calls it before parsing the body.

## Alternatives considered

- **Skip payments until first real gateway** — rejected: blocks fulfilment and
  ledger work behind external partnerships.
- **Stripe-first** — rejected per business decision (no global card market).
- **Single "generic" provider with config table** — rejected: provider webhook
  shapes diverge wildly; abstraction without code per provider is fiction.

## References

- [ADR-0005 — payment gateway abstraction](./0005-payment-gateway-abstraction.md)
- [ADR-0011 — order FSM and snapshots](./0011-order-fsm-and-snapshots.md)
- [`apps/api/src/yupay/modules/payments/`](../../apps/api/src/yupay/modules/payments)
