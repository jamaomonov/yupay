# `affiliate`

Partner program: a partner promotes a code, buyers get 3–10% off their first
order and are permanently attributed to that partner, and the partner earns
1–2% of every subsequent order.

**Spec:** `docs/superpowers/specs/2026-08-27-affiliate-program-design.md`
**ADR:** `docs/decisions/0061-affiliate-commission-by-sweep.md`
**Plans:** `docs/superpowers/plans/2026-08-27-affiliate-core.md` (schema, ledger, sweep),
`docs/superpowers/plans/2026-08-28-affiliate-discount.md` (the discount on the order path)

## Why this is not part of `promo`

`promo` credits a fixed gift **to the buyer's wallet, after payment**
(`D user_wallet / C house_promo_expense`). An affiliate code **reduces what the
buyer pays, before payment**, and binds them to a partner. Different moment,
different postings, different ownership.

## Money

| Event                                    | Posting                                          |
| ---------------------------------------- | ------------------------------------------------ |
| Commission accrued                       | `D partner_pending / C house_affiliate_expense`  |
| Hold period expired                      | `D partner_balance / C partner_pending`          |
| Payout requested                         | `D partner_payout_hold / C partner_balance`      |
| Payout transferred                       | `D house_affiliate_paid / C partner_payout_hold` |
| Payout rejected                          | `D partner_balance / C partner_payout_hold`      |
| Commission voided (refund, pre-maturity) | `D house_affiliate_expense / C partner_pending`  |

All six are implemented. The three payout postings are driven by
`payouts.py`; the admin side that calls `mark_paid` / `reject_payout`
arrives with the admin screens.

**"Available to withdraw" is the balance of `partner_balance`** — not a sum
computed over `affiliate_commissions`. One source of truth, and a payout
request that reserves its money cannot be raced into an overdraft.

There is no posting for the discount, and there must not be one. The buyer
simply pays less; cost of goods is unchanged, so our margin is genuinely lower.
That is a fact about revenue, not an expense.

It does have to reach the **reports**, though, and that is subtler than it
sounds. Dashboard revenue comes from the order total, so it drops on its own.
Margin is computed per line in `orders/revenue.py` and does not — which left two
figures on one card disagreeing about cost, on exactly the orders with the least
margin to spare. Both expressions now subtract `order_items.discount_usd`;
`gross - margin == cost` survives because a discount lowers what we received and
what we kept by the same amount.

## Adding an account kind takes three edits, not one

The set of kinds lives in three places and only one of them gives a readable
error:

1. `wallet.service.NORMAL_SIDE` — the Python check, raises `unknown account kind`.
2. `wallet.schemas.AccountKind` — the published literal type.
3. `ck_wallet_accounts_kind` — the CHECK constraint that actually stops the
   INSERT, with a constraint name and nothing else.

`USER_VISIBLE_KINDS` is deliberately **not** extended: it is the allow-list for
what a customer sees in their own wallet, and partner money must never appear
there.

## Partner authentication

A partner is not a user: separate table, separate sessions, and **a separate
JWT kind**. `auth.jwt.verify` rejects a kind mismatch, so a `partner_access`
token cannot be presented to a buyer endpoint and a buyer's token cannot be
presented to the panel. Reusing `"access"` would work today only because a
partner id is not found in `users` — an accident, not a boundary.

No cryptography is reimplemented. Passwords go through `auth.security`
(argon2id, tuned, capacity-limited) and tokens through `auth.jwt`.

Three behaviours have tests that fail if they are undone:

- **Sign-in answers identically** for a wrong password, an unknown address and
  a suspended account, and runs argon2 against a dummy hash either way. Neither
  wording nor timing may say which.
- **The approval link is single-use** (Redis `SET NX` on the token's `jti`) and
  re-checks status at redemption, so an account approved and then suspended is
  not still openable by the email sent in between.
- **Refresh tokens rotate.** Presented twice, the second fails — it is either a
  bug or a theft.

**No panel endpoint takes a `partner_id`.** Every one reads it from the token.
`list commissions for partner X` is the natural signature and the wrong one.

## Payout safety needs both halves

A row lock on the partner **and** the ledger reservation. The lock serialises
concurrent requests, so the second reads after the first has written; the
reservation is what it then sees, because the money has already left
`partner_balance`. Reserving without locking still races. Locking without
reserving lets a partner queue two requests against one balance.

Card numbers are stored (the transfer is manual) and are PII of the worst kind
here. They never reach a log line, and `PayoutOut` masks to the last four —
a full PAN in a JSON response is a PAN in a browser cache, a proxy log and a
screenshot.

## Statistics are rolling windows, not calendar periods

`month` is the last 30 days. This project has no display-timezone convention,
so a calendar month would silently be a UTC month and read wrong for a partner
in Tashkent every evening; and a rolling figure has no cliff on the 1st. Any UI
must label them "30 days", not "this month", so the wording matches the
arithmetic.

## Measuring coverage

Run it so the **root** `pyproject.toml` is picked up, or export
`COVERAGE_CORE=sysmon`. That file explains why: the default tracer loses the
trace after the first `await db.execute(...)` in a frame, because SQLAlchemy's
async engine hops through greenlets. Measured from inside `apps/api` without
it, this module reported 79% on `routes.py` where the real figure is 100%.

## The two constraints that carry the design

- `UNIQUE(user_id)` on `affiliate_attributions` — a buyer belongs to one
  partner, forever, guaranteed by the database.
- `UNIQUE(order_id)` on `affiliate_commissions` — the accrual sweep's entire
  idempotency. Overlapping ticks cannot pay twice; a missed order is picked up
  next pass; nothing needs reconciling by hand.

## Public interface

Import from `api`, never from `accrual` or `ledger`:

```python
from yupay.modules.affiliate import api as affiliate_api

await affiliate_api.accrue_commissions(db, hold_days=14, limit=500)  # -> int
await affiliate_api.mature_commissions(db, limit=500)                # -> int
await affiliate_api.void_commission(db, order_id=order_id)           # -> bool
await affiliate_api.resolve_code(db, code=..., user_id=..., purpose="catalog")
affiliate_api.discount_amount(total, percent, currency)              # -> Decimal
affiliate_api.distribute_discount_usd(line_totals, discount)         # -> list
```

Two things are deliberately **not** on the facade:

- `routes.router` — `api/v1` imports it from `affiliate.routes` directly.
  Re-exporting it here would close an import cycle, because `orders.service`
  and `payments.service` both import this module.
- `attribution.bind_attribution` — same reason; `payments.service` imports
  `affiliate.attribution` directly.

`void_commission` deliberately refuses a matured commission — it may already
sit inside a payout request, and clawing back money a partner can see is an
admin's decision.

Internally this module reaches into `wallet.service` rather than `wallet.api`.
The wallet facade imports its router, which pulls in the whole v1 route stack
and circles back — an `ImportError` for any caller not already inside the app,
and dead weight in the scheduler process. The existing `purge_sessions` and
`purge_evidence` jobs reach past their facades for the same reason.

## SAVEPOINT, and the order of two lines

Both `accrual` and `attribution` insert a row that a `UNIQUE` may reject, and
both wrap it in `db.begin_nested()`. The row must be added **inside** that
block. Added before it, a failed flush leaves the doomed object in
`session.new` and SQLAlchemy poisons the whole session with
`PendingRollbackError` — so losing one race would abandon the entire sweep pass,
or roll back the payment settlement that owns the outer transaction. This was
shipped wrong once and caught by the second-coded-order test.

## Test coverage note

`accrual.py` sits at 96%. The uncovered lines are the `except IntegrityError`
branch taken when two sweeps race for the same order. That path cannot be
produced by a black-box test in one session — the loser's `INSERT` blocks on
the unique index until the winner commits, so any attempt to interleave them in
one test hangs rather than exercising the branch. Its correctness rests on
`uq_affiliate_commissions_order`, which is tested directly, and on the sweep not
double-paying, which `test_accrual_is_idempotent` asserts. Mocking the failure
would test the mock.
