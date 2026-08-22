# 0057. Admin-ordered FX provider chain

- **Status**: Accepted
- **Date**: 2026-08-22
- **Deciders**: @jamaomonov
- **Tags**: backend | frontend | ops

## Context and problem statement

ADR-0008 fixed the adapter _order_ in code: exchangerate.host → Open Exchange
Rates → CoinGecko, later with exchangerate-api.com in front when a key exists.
Ops could not see what each adapter currently quotes, nor pick a primary
without a deploy. A fourth fiat source (FXRatesAPI) made a hardcoded order
worse.

## Decision drivers

- Compare live USD→UZS / RUB / USDT from every adapter on one screen.
- Change primary vs fallback without a restart.
- Do not commit API keys. Missing keys skip that adapter.

## Considered options

1. **Env-only order** (`FX_PRIMARY=...`) — needs a redeploy to swap.
2. **Per-quote primary** — more knobs than we will use.
3. **Global ordered chain in Postgres**, probed live for the admin page.

## Decision outcome

**Chosen option:** Option 3.

`fx_provider_settings(slug, sort_order, enabled)` is the source of truth.
Redis `fx:provider_chain` mirrors it. `FxService.get_market_rate` walks the
enabled slugs; the first adapter whose `supports` is true and whose fetch
succeeds wins. CoinGecko stays in the list but only answers crypto pairs.

`GET /admin/fx/providers` calls every adapter in parallel (no rate cache) so
the dashboard shows the raw quote. `PUT` replaces the whole permutation of
known slugs, then drops `fx:rate:{base}:{quote}` so the next customer read
hits the new primary.

Default seed: FXRatesAPI → ExchangeRate-API → exchangerate.host → Open
Exchange Rates → CoinGecko.

Manual quote toggle (ADR-0055) still wins over the whole chain.

## Validation

- Unit: FXRatesAPI adapter, chain validation, Redis reorder, probe roles.
- Admin: list shows per-provider rates; moving a row persists order.

## References

- [ADR-0008](./0008-fx-provider-chain.md)
- [ADR-0055](./0055-manual-fx-rates.md)
