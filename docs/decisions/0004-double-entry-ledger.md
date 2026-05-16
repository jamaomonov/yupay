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
`house_promo_expense`, `provider_clearing:<provider>`, `house_refunds`, `house_fx_pnl`.

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
