# 0055. Per-quote manual FX rate

- **Status**: Accepted
- **Date**: 2026-08-22
- **Deciders**: @jamaomonov
- **Tags**: backend | frontend | pricing | admin

## Context and problem statement

The admin «Курсы» page only showed the live provider rate. Ops sometimes need to
pin USD→UZS / USD→RUB / USD→USDT to a number they chose (a bank rate, a
rounded figure, a temporary freeze) and have **every** conversion use that
number — catalog, checkout, public `GET /fx/rates` — until they flip back to FX.

## Decision drivers

- One toggle per quote, not a global switch.
- The typed rate must win in one place, not be re-implemented at each caller.
- Flipping back to FX must not lose the last typed number.
- A provider refresh must not overwrite or disable the toggle.
- A typed rate must not be rejected by the pricing trust gate (stale / deviation
  / UZS band) — otherwise a deliberate 12 500 UZS pin would take the catalog
  offline.

## Considered options

1. **Override inside `FxService.get_rate`** — Redis + `fx_quote_settings` row.
2. **Per-SKU `SkuPrice` only** — already exists; does not set a currency-wide rate.
3. **Env / settings JSON** — no audit, no per-quote API, restart to change.

## Decision outcome

**Chosen option:** Option 1.

`FxService.get_rate` checks the admin override before the provider cache.
`source="manual"` is the signal. `get_market_rate` stays the live FX path for
the dashboard and for `refresh_all` history.

`guarded_usd_rate` skips stale / deviation / out-of-band when `source` is
`manual`. A non-positive typed rate is still rejected.

Per-SKU `SkuPrice` overrides still win over FX, manual or not: they are a
price, not a rate.

### Positive consequences

- Catalog display, checkout, snapshots, and the public rates endpoint stay in
  lockstep.
- The last typed rate survives a toggle-off.

### Negative consequences

- A 5-minute `fx_snapshots` reuse now also compares `rate` and `source`, so a
  just-flipped toggle does not keep selling at the previous snapshot.
- USDT→UZS (`bulk-set-uzs-prices`) is a different pair and is unchanged.

## Validation

- Unit tests: manual wins over a warm provider cache; toggle-off uses FX;
  `get_market_rate` ignores the toggle.
- Integration: `PATCH /admin/fx/rates/{quote}` changes `GET /fx/rates`; the
  guard accepts a manual rate that would fail the UZS band.

## References

- [ADR-0008](./0008-fx-provider-chain.md)
- [ADR-0032](./0032-variable-amount-skus.md)
- `docs/runbooks` — no dedicated FX runbook; the admin page is the operator UI.
