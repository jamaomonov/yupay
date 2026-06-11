# 0029. Promo codes credit `user_wallet` directly

- **Status**: Accepted
- **Date**: 2026-06-11
- **Deciders**: core team
- **Tags**: backend | payments | product

## Context and problem statement

The double-entry ledger has carried a `user_promo_credit` account kind since
the wallet skeleton, but nothing ever wrote to it from the product side: no
issuance, no redemption UI, and — critically — the wallet payment gateway
debits `user_wallet` only, so promo credit would be **unspendable** today (and
its balance chip is hidden in the miniapp UI). We want the cheapest promo
mechanic that uses the existing rails end to end.

## Decision drivers

- Money credited by a promo must be immediately visible and spendable.
- One redemption per user, a global cap, expiry — standard fraud guards.
- No new payment-path complexity (the wallet gateway stays untouched).

## Considered options

1. **Fixed-denomination code crediting `user_wallet`** — gift money lands in
   the spendable balance; ledger pair `D user_wallet / C house_promo_expense`.
2. **Credit `user_promo_credit`** — "correct" account semantically, but
   spending it requires teaching the wallet gateway (and balance maths,
   and the UI) about a second debit source first.
3. **Order-level percent discounts** — different mechanic entirely (price
   modifier at checkout), much wider blast radius.

## Decision outcome

**Chosen option:** Option 1. It closes the loop with zero changes to the
payment path: `promo.redeem` posts to the same accounts `admin.adjust`
already uses, the miniapp wallet hero updates instantly, and the existing
`house_promo_expense` reporting captures the spend. Options 2/3 stay open as
follow-ups (option 2 becomes worthwhile when cashback also needs spending
rules; option 3 is its own feature).

Mechanics: `promo_codes` (UPPERCASE unique code, amount+currency, optional
global cap and expiry, active flag) + `promo_redemptions`
(`UNIQUE(code,user)`, link to the ledger txn, client idempotency key for
timeout replay). Redemption takes the code row `FOR UPDATE` so the cap can't
be raced, books the ledger txn under the natural key
`promo:{code_id}:{user_id}`, and inserts the redemption under a SAVEPOINT.

### Positive consequences

- Ships in one module + one miniapp card; promo money is real money.
- Audit trail: every redemption references its ledger transaction.

### Negative consequences

- Promo money is indistinguishable from cash in the wallet (by design — but
  it also means no "promo-only" spending restrictions are possible without
  moving to option 2).
- Percent/discount campaigns still have no mechanism.

## Validation

`tests/integration/test_promo_routes.py`: redemption credits the balance and
pays for a real order via the wallet gateway; double-redeem 409 with
same-key replay; cap, expiry and deactivation guards; admin list usage.
Revisit when referral payouts or promo-only balances appear on the roadmap.
