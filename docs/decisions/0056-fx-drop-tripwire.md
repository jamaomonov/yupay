# 0056. FX drop tripwire

- **Status**: Accepted
- **Date**: 2026-08-22
- **Deciders**: @jamaomonov
- **Tags**: backend | payments | pricing | ops

## Context and problem statement

A sudden dump of USD→UZS (or RUB) would let us keep selling at yesterday's
margin until someone notices. The pricing trust gate (`pricing_fx_max_deviation_pct`
= 15%, both directions) only hides Steam/variable FX prices — card and wallet
checkout keep working. Ops needed a kill-switch: if the market rate **falls**
more than 6%, stop every new payment and page the ops chat. Recovery is
manual: turn the providers back on.

Pay-from-balance was not on the same lever as Click/Payme/Uzum, so a
maintenance flag on the acquirers still left miniapp wallet checkout open.

## Decision drivers

- Drop-only, not a rise — a stronger soum is not an emergency.
- 6% is tighter than the 15% pricing gate on purpose: we want to freeze
  sales before we start selling at a loss, not after.
- Do not auto-enable. The operator looks at the rate and clicks «Включить».
- Do not overwrite a provider the operator already `disabled`.
- Wallet must stop with the acquirers.

## Considered options

1. **Reuse `pricing_fx_max_deviation_pct`** — bidirectional, 15%, only
   prices some SKUs.
2. **New drop-only tripwire on the `fx_refresh` job** + wallet as a logical
   provider.
3. **Hard-stop the API process** — too coarse, no in-flight settlement.

## Decision outcome

**Chosen option:** Option 2.

`detect_drops` compares the last `fx_rates` row to the just-fetched market
rate for `fx_drop_watched_quotes` (UZS, RUB). USDT is ignored — CoinGecko
noise around 1.0 is not a store emergency. A missing previous row (first
tick) does not trip.

On a drop, `trip_active_to_maintenance` puts every _active_ logical
provider — Click, Payme, Uzum, Octo, crypto, **wallet** — into
`maintenance`. The ops alert (`kind="fx_drop"`) is hooked on
`schedule_after_commit` so a later exception cannot roll back
`maintenance` _and_ leave a "payments stopped" message in the group.
`POST /admin/fx/refresh` commits the trip before listing quotes for the
same reason. Already-`disabled` rows stay disabled. A second tick while
everything is already in maintenance does not re-alert.

The same path runs from the 5-minute scheduler job and from
`POST /admin/fx/refresh`.

`wallet` is a logical provider. `GET /payments/providers` includes it.
Miniapp checkout checks that list; web does not offer wallet and ignores
the extra slug.

Manual FX (ADR-0055) is not the tripwire input: `refresh_all` reads the
market. A typed pin does not hide a real dump, and a typed typo does not
by itself trip this wire (the operator just typed it).

### Positive consequences

- One alert, one admin screen, one recovery action.
- In-flight acquirer payments still settle (ADR-0041).

### Negative consequences

- A provider-chain failover that jumps UZS by >6% will trip. Ops re-enable.
- First refresh after an empty `fx_rates` table never trips; the second
  tick (5 min later) will.

## Validation

- Unit: drop >6% trips, exact 6% does not, rise ignored, USDT ignored,
  first tick skipped.
- Integration: `trip_active_to_maintenance` skips `disabled` and already
  `maintenance`; wallet is in the admin list and in `GET /providers`.

## References

- [ADR-0008](./0008-fx-provider-chain.md)
- [ADR-0041](./0041-admin-payment-provider-controls.md)
- [ADR-0055](./0055-manual-fx-rates.md)
- `docs/runbooks/payment-provider-controls.md`
