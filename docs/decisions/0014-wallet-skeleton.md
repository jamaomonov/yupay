# 0014. Wallet skeleton: ledger tables, posting service, admin adjustment

- **Status**: Accepted
- **Date**: 2026-05-16
- **Builds on**: ADR-0004 (double-entry ledger), ADR-0011 (order FSM), ADR-0012 (payments skeleton)
- **Deciders**: founding team
- **Tags**: backend, wallet, ledger

## Context

ADR-0004 fixed the ledger model. Now we need a usable seam:

- Other modules (`payments`, `promotions`, `fulfillment`) will start posting to the
  ledger soon — they need a stable `wallet.api` to call.
- Admin needs a way to adjust balances by hand (operational realities: comp a customer,
  fix a misposted refund, seed cashback for staff testing).
- Customer needs to see their balances and history.
- We must NOT design the public surface around any single future caller — every caller
  posts through the same `post()` primitive.

## Decision

Ship a **functional, minimal** wallet that:

- Provides the ledger primitives (`ensure_account`, `post`, `balance`,
  `user_balances`) as the only way to move money.
- Enforces the invariant `SUM(D) = SUM(C)` per currency per transaction at the
  **service layer** with `ValidationError`. A deferred constraint trigger is left for
  ADR-0019; on the volumes we're at, the service check is sufficient and avoids
  surprise trigger interactions during migrations.
- Provides exactly one mutation entry point (`POST /admin/wallet/adjust`) for ops.
  Customer routes are read-only.
- Leaves cashback accrual, promo credits, refund reversal, FX-conversion postings,
  and outbox-fan-out **unwired** — they will land as ADRs when the corresponding
  modules (`promotions`, `payments` real adapters) are built.

### Tables (see migration `0009_wallet_init`)

```
wallet_accounts
  id              UUID PK
  owner_type      VARCHAR(16) NOT NULL   -- 'user' | 'house' | 'provider'
  owner_id        VARCHAR(64) NOT NULL   -- users.id | 'house' | provider slug
  kind            VARCHAR(48) NOT NULL   -- taxonomy below
  currency        CHAR(3)     NOT NULL   -- 'USD' | 'UZS' | 'RUB' | …
  status          VARCHAR(16) NOT NULL DEFAULT 'active'  -- 'active' | 'frozen'
  metadata        JSONB        NOT NULL DEFAULT '{}'::jsonb
  created_at      TIMESTAMPTZ
  UNIQUE (owner_type, owner_id, kind, currency)

wallet_transactions
  id              UUID PK
  kind            VARCHAR(48) NOT NULL   -- 'admin.adjust' | 'order.cashback' | …
  reference_type  VARCHAR(32)            -- 'order' | 'payment' | 'manual' | …
  reference_id    VARCHAR(64)
  idempotency_key VARCHAR(160) NOT NULL UNIQUE
  metadata        JSONB       NOT NULL DEFAULT '{}'::jsonb
  actor           VARCHAR(64)            -- 'system' | 'admin:<id>'
  created_at      TIMESTAMPTZ

wallet_postings
  id              UUID PK
  transaction_id  UUID NOT NULL REFERENCES wallet_transactions(id) ON DELETE CASCADE
  account_id      UUID NOT NULL REFERENCES wallet_accounts(id) ON DELETE RESTRICT
  direction       CHAR(1) NOT NULL CHECK (direction IN ('D','C'))
  amount          NUMERIC(20,6) NOT NULL CHECK (amount > 0)
  currency        CHAR(3) NOT NULL
  created_at      TIMESTAMPTZ
```

Indexes: `(account_id, created_at DESC)` on `wallet_postings` for history queries,
`(reference_type, reference_id)` on `wallet_transactions` for "find postings for
this order".

### Account taxonomy

| Kind | Normal side | Meaning |
|---|---|---|
| `user_wallet` | D | Spendable balance (top-ups, FX in) |
| `user_cashback` | D | Accrued cashback waiting for redemption |
| `user_promo_credit` | D | Promo/referral credit |
| `house_revenue` | C | Gross revenue |
| `house_cogs` | D | Cost of goods sold |
| `house_promo_expense` | D | Promo/cashback expense |
| `house_refunds` | D | Contra-revenue (refunds out) |
| `house_fx_pnl` | C | FX gain/loss bucket |
| `provider_clearing` | C | Clearing per acquirer (owner_id = provider slug) |

The "normal side" determines which direction increases the balance. `balance()`
returns `SUM(amount WHERE direction=normal_side) − SUM(amount WHERE direction≠normal_side)`.

### `post()` contract

```python
async def post(
    db,
    *,
    kind: str,
    legs: list[Leg],                # >= 2 postings
    idempotency_key: str,
    reference: Reference | None = None,
    actor: str = "system",
    metadata: dict[str, Any] | None = None,
) -> WalletTransaction:
    """All-or-nothing posting. Raises:
       - ValidationError on invariant break or invalid leg
       - ConflictError on idempotency collision with a *different* payload (TBD; for now
         same key returns the existing transaction)."""
```

`Leg = (account_id, direction: 'D'|'C', amount: Decimal, currency: str)`.

### Idempotency

- `idempotency_key` UNIQUE → reposting the same key returns the existing transaction
  (no second set of postings). The caller chooses keys that mirror the upstream event:
  `order:<id>:cashback`, `payment:<id>:capture`, `admin:adjust:<uuid>`.
- A future hardening: hash the legs and reject mismatched replays. Skeleton skips this.

### What's deferred

1. **Auto-cashback on `order.delivered`** — needs `promotions` rules table.
2. **Real provider settlement postings** — wired when the first real acquirer adapter
   lands. Mock-payment flow doesn't touch the ledger.
3. **Outbox events** (`wallet.transaction.posted`) — added when consumers exist.
4. **Materialized view of balances** — only build when an integration test shows the
   on-the-fly `SUM(...)` is hot.
5. **Deferred SQL trigger** for the invariant.
6. **Partitioning** `wallet_postings` by month — at ~50M rows per ADR-0004.

## Consequences

- Every future module that touches money posts through this one service. No SQL
  outside `wallet/` writes to the ledger tables.
- The skeleton's only mutation endpoint is admin-only. Customer surface is read-only.
- Tests must include the invariant: posting with `SUM(D) ≠ SUM(C)` is rejected.

## Alternatives considered

- **Signed-amount single-leg ledger** — rejected. Loses the audit trail that
  double-entry gives (you can't ask "where did this $5 come from?" mechanically).
- **Eager balance row on `wallet_accounts`** — rejected for the skeleton. Adds a hot
  row that needs `SELECT FOR UPDATE` on every post; we'll revisit when an integration
  test demonstrates the read pressure.
