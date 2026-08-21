# Runbook — Telegram Stars onto a single unit SKU

> **Do not run this against prod until the image with Tasks 1–8 is live.**
> Checkout, G-Engine fulfilment, the orders display and both storefronts dual-read:
> a SKU with `min_qty` set goes down the qty path, everything else keeps the old
> variable-amount path. Flip the row first and every Stars checkout 422s for the
> length of the deploy.

The seed is `scripts/seed/2026-08-21_telegram_stars_unit_sku.py`. It is the **only**
data change of this rollout. Migration `0049_sku_min_max_qty` is schema-only on
purpose — a failed deploy must not be able to leave Stars with the packs switched
off and code that still expects them. **Never put this DML in an Alembic `upgrade()`.**

## What changes

| Row                             | Before                                                                 | After                                                                                                                 |
| ------------------------------- | ---------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `tg-stars-any`                  | `variable_amount=true`, `units_per_usd` set, `price_usd=1` placeholder | `variable_amount=false`, `amount_unit='Stars'`, `min_qty=50`, `max_qty=2500`, `price_usd` = the price of **one** star |
| `tg-stars-any` G-Engine mapping | `quantity` = whatever it carried                                       | `quantity=1`, service `72`, `is_active=true`                                                                          |
| `tg-stars-50` … `tg-stars-2500` | `active=true`                                                          | `active=false` — **not deleted**                                                                                      |
| historical `order_items`        | —                                                                      | untouched                                                                                                             |

An in-flight pack order still fulfils correctly after the flip: it stored `qty=1`
against a mapping with `quantity=N`, and the adapter sends `qty × mapping.quantity`
either way.

## Rollout — five steps, in this order

1. **Deploy code + migration `0049` first.** Columns land nullable; every existing
   row keeps `min_qty=NULL`. The new code dual-reads: unit SKU (`min_qty` set) →
   qty path; variable → old path. **Stars still sells the old way.** Steam is
   unchanged.
2. **Confirm `/store/telegram-stars` still sells on prod** — pack grid and
   free-amount field both render, and a pack tile still reaches payment. If it
   does not, stop and roll the image back; do not run the seed.
3. **Run the seed** (command below). Not in `alembic upgrade`. Never add it to one.
4. **Buy 50★ twice** — once from a tile, once by typing `50`. Each must create
   **one** G-Engine order with `Quantity = 50`.
5. **Revert, if needed, in this order:** seed `--revert` first, then roll the
   image back, and only then `alembic downgrade` past 0049. The downgrade drops
   `min_qty`/`max_qty`; running it while the row still relies on them takes the
   catalog with it.

## Running the seed

Always `--dry-run` first. It prints the same before/after table and rolls back.

```bash
# prod — dry run, writes nothing
docker compose -f docker-compose.prod.yml exec -T api python - --dry-run \
    < scripts/seed/2026-08-21_telegram_stars_unit_sku.py

# prod — for real
docker compose -f docker-compose.prod.yml exec -T api python - \
    < scripts/seed/2026-08-21_telegram_stars_unit_sku.py
```

On a local docker stack, migrate first (`make migrate` — 0049 is schema-only),
then the same stdin form. `scripts/` is not in the api image; piping the file
from the host is required.

```bash
make migrate
docker compose exec -T api python - --dry-run \
    < scripts/seed/2026-08-21_telegram_stars_unit_sku.py
docker compose exec -T api python - \
    < scripts/seed/2026-08-21_telegram_stars_unit_sku.py
```

The script is idempotent: a second forward run reports
`committed (nothing had changed)` and leaves every row alone.

## The cost guard — what an abort means

`price_usd` on a unit SKU is the price of **one star**, so the numbers that were
harmless on the variable-amount line are dangerous on this one. The script refuses
to guess and exits 1, printing the offending row plus (when `GENGINE_API_KEY` is
configured) what G-Engine quotes for service 72 right now.

| Abort                                               | What it means                                                                                                                                                                                                    | What to do                                                                                                                                                                    |
| --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cost_usdt is NULL`                                 | The variable-amount line never carried a cost. This is the case prod is most likely to hit.                                                                                                                      | Set the per-star cost — `1 / unfixed_details.rate` from G-Engine service 72, around `$0.0155` — and `margin_percent` on the SKU in the admin, then re-run.                    |
| `cost_usdt=… is above 0.5`                          | That is a pack-sized cost that was never divided by the star count.                                                                                                                                              | Fix the row (or check you are pointed at the right SKU). **Do not divide it by 50 and do not ask the script to** — it will not, because picking a sale price is not its call. |
| `cost_usdt=… is below 0.001`                        | Too small to be a star; something rounded to nothing.                                                                                                                                                            | Fix the row and re-run.                                                                                                                                                       |
| `price_usd=… is above 0.5`                          | The resulting per-star price would sell 50 Stars for more than $25. The usual cause is the `price_usd=1` placeholder the variable line carried — on a unit SKU that is a dollar per star, i.e. $50 for 50 Stars. | Set `margin_percent` on the SKU so the price is re-derived from `cost_usdt`, or set `price_usd` by hand, then re-run.                                                         |
| `price_usd=… is below cost_usdt=…`                  | Every star would sell at a loss.                                                                                                                                                                                 | Set `margin_percent` and re-run.                                                                                                                                              |
| `the gengine mapping … points at service …, not 72` | The mapping this script would rewrite is not the Stars one.                                                                                                                                                      | Fix the mapping in the admin. The script will not edit a row it does not recognise.                                                                                           |

When `margin_percent` is set, `price_usd = cost_usdt × (1 + margin_percent/100)` at
six decimals — the same rule as the hourly supplier price refresh, except it keeps
six decimals instead of rounding to cents. Cents would take $0.018546 to $0.02 and
hand the SKU a fifth more margin than anyone asked for.

## The qty mapping guard

`sku_supplier_mapping.quantity` for `tg-stars-any` must end at **1**. The G-Engine
adapter sends `Quantity = order_items.qty × mapping.quantity`, and after this flip
the star count rides on `qty`. A leftover pack-era `500` there would order
500 × whatever the customer asked for. The script prints the old → new line before
it touches anything:

```text
mapping.quantity: 500 -> 1 — G-Engine Quantity is qty × mapping.quantity, so
leaving it at 500 would order 500 × the stars the customer asked for
```

## Verifying

After the seed, the public catalog must return **one** SKU. The brand page
`GET /api/v1/catalog/brands/telegram-stars` lists product summaries, not SKUs —
confirm the product is still there, then count SKUs on the product payload.

```bash
# Brand page (what /store/telegram-stars hits first)
curl -s https://api.yupay.io/api/v1/catalog/brands/telegram-stars \
  | jq '{products: (.products | length), starting_price_usd: .products[0].starting_price_usd}'
# expected: products=1, starting_price_usd ≈ 0.0185 (per star, not a pack)

# The SKU list — must be exactly one row
curl -s https://api.yupay.io/api/v1/catalog/products/telegram-stars \
  | jq '{count: (.skus | length), skus: [.skus[] | {sku_code, price_usd, variable_amount, amount_unit, units_per_usd, min_qty, max_qty}]}'
# expected: count=1, sku_code=tg-stars-any, variable_amount=false,
#           amount_unit="Stars", units_per_usd=null, min_qty=50, max_qty=2500
```

The package grid the customer sees is now built on the storefront from that rate
(`STAR_PACKAGES` in web and miniapp), which is why the packs can be off in the
database and still on screen.

**One G-Engine order per purchase.** After a 50★ purchase, the order line should
read `qty=50`, `unit_price_usd` = the per-star price, `display.denomination`
`"50 Stars"`, and exactly one G-Engine task with `Quantity=50`.

## Revert

```bash
docker compose -f docker-compose.prod.yml exec -T api python - --revert \
    --units-per-usd 64.705882 \
    < scripts/seed/2026-08-21_telegram_stars_unit_sku.py
```

`--units-per-usd` defaults to the live G-Engine rate for service 72; pass it
explicitly when `GENGINE_API_KEY` is not reachable from the container, otherwise
the script exits rather than invent one.

**Revert is "packs back on, `tg-stars-any` variable again" — not a row-level time
machine.** It restores the shape `scripts/seed/2026-08-18_telegram_stars_any_amount.py`
created: 50…5 000 stars in USD bounds off the given rate, `rate_multiplier=1.2000`,
`price_usd` back to its `1` placeholder. It does not restore whatever each row held
five minutes before the forward run. `cost_usdt` and `margin_percent` are left
alone on purpose — a true per-star cost stays true, and the next forward run needs
it.

By default it reactivates **every** inactive SKU under `telegram-stars`. The
forward run prints the exact list it switched off, so to put back only those:

```bash
… python - --revert --packs tg-stars-50,tg-stars-75,… < scripts/seed/…
```

`mapping.quantity` stays at 1 through a revert: the variable path re-derives the
star count from what was actually charged and never reads it, and a pack-era number
left there would be a trap for the next forward run.

## Related

- ADR-0054 — `docs/decisions/0054-telegram-stars-unit-sku.md`.
- `scripts/seed/2026-08-18_telegram_stars_any_amount.py` — created the row this seed converts.
- `apps/api/migrations/versions/0049_sku_min_max_qty.py` — the schema half (columns + relaxed `ck_skus_amount_unit_complete`).
- `apps/api/tests/unit/test_stars_seed_guards.py` — the guards above, as tests.
- `docs/runbooks/supplier-api-down.md` — if G-Engine is the thing that is broken.
