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

## Pricing

The wholesale price formula — the **one home**, per
`docs/superpowers/plans/2026-09-06-merchant-b2b-m1.md` Task 5 — lives in
`pricing.py` and nowhere else:

```
price = ceil_to_cent(
    effective_cost(sku) * (1 + (sku.b2b_markup_pct + (merchant.markup_adjustment_pp ?? 0)) / 100)
)
```

Four pure functions, all `Decimal`, no DB access:

- `effective_cost(sku) -> Decimal | None` reads `sku.cost_usdt`. `None`
  means the SKU is **not sellable B2B** — excluded from the merchant
  catalog, orders for it rejected. It never falls back to `price_usd` or
  any other retail figure (spec §8.2).
- `merchant_markup_pct(sku, merchant)` adds the dormant per-merchant
  `markup_adjustment_pp` (spec §8.3, `None` for every merchant in v1) to
  the SKU's uniform `b2b_markup_pct`.
- `merchant_price(cost, markup_pct)` rounds up to the cent
  (`ROUND_CEILING`) — rounding down would erase margin on cheap SKUs
  invisibly, a cent at a time.
- `violates_margin_floor(cost, price, floor_pct)` is the only global
  pricing control (spec §8.3): it catches a fat-fingered per-SKU markup
  (including one that goes negative — Task 4 deliberately added no DB
  `CHECK` on `b2b_markup_pct`) and cost spikes a stale markup no longer
  covers. Callers read `settings.merchant_margin_floor_pct` (default `2`)
  and pass it in; the pure functions never read settings themselves.

**Nothing else in the codebase may reimplement this formula.** The one
sanctioned exception is the admin SPA's client-side price _preview_ next to
the markup field (Task 8, labelled «предварительно») — display-only, never
authoritative; the server always recomputes and is the source of truth for
what a merchant is actually charged.

Import these from `api`, not from `pricing` directly — the same rule as
every other symbol in this module.

## Admin surface

Everything support needs to run a pilot merchant by hand (Task 6), all
admin-gated (`require_admin`), business logic imported through the `api`
facade only. Two routers in `admin_routes.py` (mounted by `api/v1` directly
from that file — the facade never exports a router, or it would close a
cycle back through the route stack, same rule as `affiliate.routes`):

- `POST`/`GET /admin/merchants` — create a reseller; list every merchant
  with its USD deposit balance joined in **one grouped query**
  (`admin.list_merchants_with_balances`, the batch variant of
  `deposit_balance` — no per-merchant balance read).
- `POST /admin/merchants/{id}/freeze|unfreeze` — persists `status` only in
  M1; ordering is what M2 will block.
- `POST /admin/merchants/{id}/deposit-credits` — posts via
  `service.credit_deposit`. **Requires** `Idempotency-Key`; the ledger key
  is namespaced `merchant-credit:{merchant_id}:{client_key}` so one
  client's key can never replay another merchant's transaction. The ledger
  replays by key **without comparing parameters**, so the response's
  `amount` is the transaction's actual (original) amount — a mismatched
  replay is visible to the admin UI, and `balance` rides along. See
  `docs/architecture/sequence-diagrams/merchant-deposit-credit.mmd`.
- `PATCH /admin/catalog/skus/{id}/b2b` (`markup_pct?`, `visible_b2b?`),
  `POST /admin/catalog/b2b/bulk-markup` (`brand_slug | category`,
  `markup_pct` — one UPDATE, returns the affected count) and
  `PATCH /admin/catalog/brands/{id}/b2b` (`visible_b2b`) — the catalog B2B
  knobs. No pricing math in routes; the markup is stored verbatim and the
  order-time margin floor is the guard (spec §8.3).

The non-ledger writes accept an optional `Idempotency-Key` and replay
through the generic `(scope, key)` store (`core.idempotency`), like the
other admin write endpoints.

## Status

Schema (Task 1), the deposit service (Task 3), wholesale pricing (Task 5)
and the admin endpoints (Task 6) are in place. Cabinet auth, the machine
API, and API-key issuance land in later tasks.
