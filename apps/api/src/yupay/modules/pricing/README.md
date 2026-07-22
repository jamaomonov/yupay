# `pricing` module

Amount-based pricing for SKUs the customer buys by dollar amount instead of
a fixed denomination (today: Steam wallet top-ups via Waxpeer). See
[ADR-0032](../../../../../../docs/decisions/0032-variable-amount-skus.md) for
why the amount lives on the order line and why the margin lives in the rate
rather than a percentage.

Owns no tables. Pure conversion functions plus one gate that reads
`fx_rates`, a table owned by `fx`.

## Public interface

```python
from yupay.modules.pricing.variable import (
    to_units,          # amount_usd -> supplier units, grossed up + rounded up
    display_rate,       # market rate * SKU multiplier = customer-facing rate
    price_in_quote,      # amount_usd * display_rate = price in quote currency
    validate_amount,     # bounds + at-most-two-decimals check
)
from yupay.modules.pricing.fx_guard import (
    check_rate,          # pure decision function, no I/O
    guarded_usd_rate,     # fetches + checks in one call
    RateRejected,         # raised on any failed check
    RejectReason,         # Literal of the five reasons
)
```

## The trust gate (`fx_guard`)

`fx` already retries providers, caches, and rejects non-positive numbers
inside its own chain. What it cannot judge is a rate that parses fine but is
simply **wrong** — half the real value, or six hours stale. Applying the
margin multiplier to a bad rate and continuing to sell is how a pricing bug
becomes a refund queue, so every variable-amount price — storefront display
and checkout alike — goes through `guarded_usd_rate` first.

Before `check_rate` even runs, `guarded_usd_rate` raises the fifth reason,
`unavailable`, itself — whenever `fx`'s entire provider chain returns
nothing (`FxUnavailableError`), meaning there is no rate at all to check,
not merely a bad one. This is the most operationally severe reason: a total
FX outage rather than a single wrong number. Once a rate is in hand,
`check_rate` runs four further checks, in this order, and raises
`RateRejected` on the first one that fails:

| #   | Reason         | Condition                                                                                                                 | Setting                                               | Default                        |
| --- | -------------- | ------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- | ------------------------------ |
| —   | `unavailable`  | `fx`'s entire provider chain failed (`FxUnavailableError`); raised by `guarded_usd_rate` itself, before `check_rate` runs | —                                                     | —                              |
| 1   | `non_positive` | `rate <= 0`                                                                                                               | —                                                     | —                              |
| 2   | `stale`        | older than `pricing_fx_max_age_seconds`                                                                                   | `pricing_fx_max_age_seconds`                          | `21600` (6 h)                  |
| 3   | `deviation`    | more than `pricing_fx_max_deviation_pct`% from the last known-good rate (skipped when there is no previous rate)          | `pricing_fx_max_deviation_pct`                        | `15` (%)                       |
| 4   | `out_of_band`  | outside `[pricing_fx_min_rate_uzs, pricing_fx_max_rate_uzs]`                                                              | `pricing_fx_min_rate_uzs` / `pricing_fx_max_rate_uzs` | `8000` / `25000` (UZS per USD) |

`non_positive` runs before `out_of_band` deliberately — a zero rate should
report as "not a number", not the coincidentally-also-true "out of band".
`deviation` runs before `out_of_band` because a previous-rate comparison is
the more specific, more actionable signal (a provider silently halving its
output); `out_of_band` is the last-resort backstop for a first-ever rate
with no history, and for any rate whose deviation from an already-bad
previous rate happens to look small.

All four settings live in `core/config.py` (`pricing_fx_*`) — read the
current defaults there, not from this file, if this README and the code
ever drift.

**Any rejection fails closed.** `catalog.service._resolve_variable_price`
turns it into a missing display price (never a silent fallback to the raw
market rate); `orders.service._variable_line_charge` turns it into a 502
(`UpstreamUnavailableError`) that blocks the order. Both log
`pricing.rate_rejected` at error level with the `reason` — that log line is
the "alert admin" half of "product unavailable to buy + alert admin" from
the design spec.

`guarded_usd_rate` compares against the most recent `fx_rates` row for the
same `(base, quote)` pair — the last row the `fx` module's periodic refresh
job wrote, **not** the last rate this gate itself approved. If a provider
starts returning a consistently wrong value across consecutive refreshes,
that baseline is bad too and the deviation check compares bad against bad
and passes; the absolute band is the only backstop left in that scenario
(see the docstring on `_previous_rate` in `fx_guard.py`).

## Amount → supplier units (`to_units`)

Waxpeer counts in **thousandths of a dollar** (`UNITS_PER_USD = 1000`, so a
cent is exactly 10 units — two-decimal dollar amounts convert without
rounding error). If the supplier charges a fee (`fee_rate`, currently
`waxpeer_fee_rate = 0`), the amount sent has to be grossed up so the
customer still receives what they asked for:

```
gross_usd = amount_usd / (1 - fee_rate)
units     = ceil(gross_usd * 1000)
```

Rounding is **always up** (`ROUND_CEILING`) — the most we ever overpay the
supplier by is a fraction of a cent, and the customer is never shown a
promise we then deliver less of. The alternative (round to what we send,
let the customer receive slightly less than they typed) was rejected in the
design spec as an arithmetic convenience that turns into "I paid for $10,
got $9.50" support tickets.

`to_units` raises `ValidationError` for a non-positive amount or a
`fee_rate` outside `[0, 1)`.

## Amount → price (`display_rate`, `price_in_quote`)

```
display_rate  = market_rate * sku.rate_multiplier
price_in_quote = amount_usd * display_rate
```

The margin is entirely inside `display_rate` — there is no separate fee
field shown anywhere. The storefront shows something like "1 $ = 14 025
сум" and no percentage, matching how this market already prices top-ups
(ADR-0032). `rate_multiplier` lives on the `Sku` row (`catalog.models`),
not in settings, so a new variable-amount product gets its own margin,
adjustable from the admin UI without a deploy.

`price_in_quote` returns six decimal places for intermediate precision;
rounding to the currency's smallest **chargeable** unit happens once, when
the full order total is assembled at checkout (`orders.service._round_to_payable`)
— not here, to avoid compounding rounding error across multiple lines. That
unit is whole so'm for UZS (tiyin coins are defunct, and acquirers reject a
sub-so'm remainder) and kopecks (two decimals) for RUB, so `total_charged` is
always an amount Payme/Octo can actually charge in minor units.

## Amount validation (`validate_amount`)

Rejects (raises `ValidationError`):

- more than two decimal places, or
- outside the closed interval `[sku.min_amount_usd, sku.max_amount_usd]`.

Both bounds are inclusive — an amount exactly equal to the minimum or
maximum is accepted.

## Callers

- `orders.service._resolve_line_unit_price` / `_variable_line_charge` —
  checkout: validates the customer's amount and prices the line. The
  client-sent price is never trusted; the server always recomputes. Checkout
  does **not** preflight the supplier balance — a short Waxpeer wallet is a
  soft failure at fulfilment, not a checkout refusal.
- `catalog.service._resolve_variable_price` — storefront display price for
  a variable-amount SKU, same computation as checkout, minus the actual
  charge.
- `fulfillment.suppliers.waxpeer` — `to_units` for the gross-up sent to
  Waxpeer, and its own reconciliation of `give_amount` against the promise
  (see the `fulfillment` module and `docs/runbooks/waxpeer-troubleshooting.md`).

## Tests

- `apps/api/tests/unit/test_variable_pricing.py` — rounding, gross-up,
  bounds, exact-boundary acceptance.
- `apps/api/tests/unit/test_fx_guard.py` — `check_rate`'s four reject
  reasons and the order they're checked in, as pure decision logic (no DB).
- `apps/api/tests/integration/test_fx_guard_db.py` — `guarded_usd_rate`
  against a real `fx_rates` table, including the fifth reason,
  `unavailable` (`FxUnavailableError` → `RateRejected("unavailable", ...)`).
- Checkout-level coverage (amount outside bounds rejected, price never
  taken from the client, FX rejection blocks the order) lives in the
  `orders` integration suite.

## What's deliberately not here

- **No cache of its own.** `guarded_usd_rate` calls into `fx`'s existing
  Redis-cached snapshot; the trust gate adds a check, not a second cache
  layer. See `docs/architecture/cache-keys.md` for `fx`'s keys.
- **No automatic supplier-fee detection.** A `give_amount` shortfall is
  logged and flagged, never used to auto-adjust `waxpeer_fee_rate` — that
  stays an operator decision (see the runbook).
