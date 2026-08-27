# `affiliate`

Partner program: a partner promotes a code, buyers get 3–10% off their first
order and are permanently attributed to that partner, and the partner earns
1–2% of every subsequent order.

**Spec:** `docs/superpowers/specs/2026-08-27-affiliate-program-design.md`
**ADR:** `docs/decisions/0061-affiliate-commission-by-sweep.md`

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

The last three rows are not implemented yet — they land with the payout API.

**"Available to withdraw" is the balance of `partner_balance`** — not a sum
computed over `affiliate_commissions`. One source of truth, and a payout
request that reserves its money cannot be raced into an overdraft.

There is no posting for the discount, and there must not be one. The buyer
simply pays less; cost of goods is unchanged, so our margin is genuinely lower.
That is a fact about revenue, not an expense.

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
```

`void_commission` deliberately refuses a matured commission — it may already
sit inside a payout request, and clawing back money a partner can see is an
admin's decision.

Internally this module reaches into `wallet.service` rather than `wallet.api`.
The wallet facade imports its router, which pulls in the whole v1 route stack
and circles back — an `ImportError` for any caller not already inside the app,
and dead weight in the scheduler process. The existing `purge_sessions` and
`purge_evidence` jobs reach past their facades for the same reason.

## Test coverage note

`accrual.py` sits at 96%. The uncovered lines are the `except IntegrityError`
branch taken when two sweeps race for the same order. That path cannot be
produced by a black-box test in one session — the loser's `INSERT` blocks on
the unique index until the winner commits, so any attempt to interleave them in
one test hangs rather than exercising the branch. Its correctness rests on
`uq_affiliate_commissions_order`, which is tested directly, and on the sweep not
double-paying, which `test_accrual_is_idempotent` asserts. Mocking the failure
would test the mock.
