# `merchants`

B2B reseller accounts: a merchant, its cabinet operator(s), and the API keys
its server uses against `/merchant/v1`. This is the schema module that every
other part of the merchant B2B feature (the machine API, the cabinet BFF, the
deposit ledger, admin) builds on.

**Spec:** `docs/superpowers/specs/2026-09-06-merchant-b2b-design.md`

## Terminology note

Acquirers call **us** the merchant (Click/Payme `merchant_id` credentials);
in this module the merchant is the reseller.

## Tables

- `merchants` — the reseller account: `title`, `status` (`active`/`frozen`),
  and a dormant `markup_adjustment_pp` reserved for a future per-merchant
  pricing override (spec §8.3).
- `merchant_users` — cabinet operators. One user per merchant in v1; the FK
  already permits more.
- `merchant_api_keys` — machine credentials for `/merchant/v1`: a public
  `key_id` (`ypm_`-prefixed) and a SHA-256 `secret_hash`, with an optional
  IP allowlist.

## Deposit ledger

The merchant's prepaid balance is a **ledger balance**, never a column.
`merchant_deposit` is a debit-normal account kind (like `user_wallet`),
owned by `owner_type="merchant", owner_id=<merchant_id>, currency="USD"`
— USD-only in v1 (spec §7). Every movement posts through
`wallet.service.post`, so idempotency-by-key and all-or-nothing legs are
inherited from the ledger, not rebuilt here.

The posting table is authoritative — M2 must not re-derive directions:

| Event                       | Legs                                             |
| --------------------------- | ------------------------------------------------ |
| Support credits top-up (M1) | `D merchant_deposit / C house_payments_received` |
| (M2) order charge           | `C merchant_deposit / D house_payments_received` |
| (M2) refund on failure      | `D merchant_deposit / C house_payments_received` |

Only the first row is implemented in M1: `service.credit_deposit` posts it
with `kind="merchant_deposit_credit"` and the caller's idempotency key, so a
replay returns the original transaction. `service.deposit_balance` reads the
balance (`Decimal("0")` when no account exists yet — the read creates
nothing). Freezing a merchant (`service.set_status`) blocks orders (M2),
never money in: support can always credit a frozen merchant.

## Status

Schema (Task 1) and the deposit service (Task 3) are in place. Routes, auth,
and API-key issuance land in later tasks.
