# 0004. Use a double-entry ledger for the internal wallet

- **Status**: Accepted
- **Date**: 2026-05-15
- **Deciders**: founding team
- **Tags**: backend, payments, data

## Context

YuPay's wallet supports: balance top-ups, purchases from balance, cashback accrual, promo
credits, refunds, referral payouts, and FX between currencies. Single-entry models with
mutable balance rows are notoriously hard to audit, hard to refund correctly, and easy to
break under concurrency. Regulators (and our own future accountants) will expect a real
ledger.

## Decision

We implement a **double-entry, append-only ledger**:

- `wallet_accounts(id, owner_type, owner_id, kind, currency)` — accounts.
- `wallet_postings(id, transaction_id, account_id, direction CHECK IN ('D','C'), amount NUMERIC(20,6), currency, created_at)` — postings; **never updated, never deleted**.
- `wallet_transactions(id, reason, ref_type, ref_id, created_at)` — the atomic unit that
  groups postings.
- Invariant: `SUM(D) = SUM(C)` per currency per transaction, enforced by service-level
  check (and optionally a deferred constraint trigger).
- **Multi-currency**: each account has a currency; FX is recorded as explicit postings, not
  as implicit conversion. We never mix currencies inside a single account.
- **Balances are a projection** of postings, cached in Redis (`wallet:balance:...`) and
  rebuildable from the source of truth.

### Account kinds (initial)

`user_wallet`, `user_cashback`, `user_promo_credit`, `house_revenue`, `house_cogs`,
`house_promo_expense`, `house_payments_received`, `provider_clearing:<provider>`,
`house_refunds`, `house_fx_pnl`.

**Pairing convention.** Postings always come in `D`/`C` pairs (`SUM(D) = SUM(C)`),
so every move needs partner accounts of opposite `NORMAL_SIDE`. The most common pairs:

| Action                                           | Debit (D)                           | Credit (C)            |
| ------------------------------------------------ | ----------------------------------- | --------------------- |
| Promo grant (admin tops up the user)             | `user_wallet`                       | `house_promo_expense` |
| Customer pays out of their YuPay balance         | `house_payments_received`           | `user_wallet`         |
| FX conversion inside a user's wallet (USD → UZS) | `user_wallet[UZS]` + `house_fx_pnl` | `user_wallet[USD]`    |
| Refund (return funds to the user)                | `user_wallet`                       | `house_refunds`       |

`house_payments_received` (D-normal) was added in migration 0018 as the dedicated
partner for the wallet payment gateway. It also receives the bookkeeping side of
future card / Click / Payme / crypto adapters once they're online — keeping the
"money customers paid us" total separate from `house_promo_expense` (which is the
flip side of promo grants, **not** payments).

`house_revenue` (C-normal) is the longer-term P&L bucket for actual recognised
revenue. The transition `house_payments_received → house_revenue` will be a
separate settlement step once accounting cycles are formalised; for now we keep
the money in `house_payments_received` and don't recognise it as revenue until
the order is delivered, which keeps refund accounting simple (refund moves money
back out of `house_payments_received`, not out of recognised revenue).

## Consequences

- Refunds and corrections are reversal postings, never edits.
- Auditing is trivial: every cent has a paper trail.
- Slightly more storage and more rows per operation. Partitioning `wallet_postings` by
  month is on the roadmap once volume warrants it.

## Alternatives considered

- **Single-entry mutable balance** — rejected: poor auditability, concurrency hazards.
- **Off-the-shelf ledger DB** (TigerBeetle, Formance) — promising, but adds an unfamiliar
  data store on day one. Revisit at ≥ 50K transactions/day.

## References

- Martin Kleppmann, "Designing Data-Intensive Applications", ch. 11
- [TigerBeetle docs](https://docs.tigerbeetle.com/)
