"""Hold the reseller price on the nine Free Fire SKUs when their cost drops to NOVA.

Retail and B2B price from the same number but by opposite rules. Retail
``price_usd`` is a stored column that ADR-0083 deliberately refuses to lower, so
when ``cost_usdt`` drops from G2B's number to NOVA's the shelf price stays and
the saving becomes margin. The merchant price list is **cost-plus, computed
live** — ``merchants.pricing.merchant_unit_price(effective_cost(sku), markup)``
reads ``cost_usdt`` on every request — so the same cost drop cuts the reseller
price automatically, by the same 0.8-3.6 %.

Nobody decided that. The owner's decision, asked and answered on 2026-09-18, is
that the saving is kept on both channels: the reseller price stays where it is,
which means ``b2b_markup_pct`` has to rise by exactly what the cost fell.

**Run this AFTER the cost has actually moved**, which as of 2026-09-18 has not
happened and will not happen on its own: the nine SKUs below carry no sourcing
rule, so they route to G2B and G2B keeps writing their cost. NOVA is a reserve
and auto routing never picks it. Somebody has to switch them first — on the
brand screen, as ``force_supplier``, because a reserve cannot be reached any
other way — and then wait for the next hourly tick.
The script does not assume when that is — it computes each markup from the
SKU's *current* cost against a recorded target price, so:

* run too early, while ``cost_usdt`` is still G2B's, and every SKU comes out at
  its present 6 % and nothing is written. It tells you so and exits.
* run after the cost moved, and each markup rises to whatever holds that SKU's
  price to the sixth decimal.
* run twice, and the second run is a no-op.

The target prices below are what the nine SKUs list at today, measured on
production 2026-09-18 at ``cost_usdt * (1 + 6 %)`` with every SKU on the
platform-wide 6 % markup. They are the thing being preserved, so they are
carried as data rather than recomputed from a cost that will be gone.

Dry run by default, same shape as the other seeds in this directory:

    docker compose -f docker-compose.prod.yml exec -T api \\
        python - < scripts/seed/2026-09-18_free_fire_b2b_hold.py

Read the table, then commit it:

    docker compose -f docker-compose.prod.yml exec -T -e APPLY=1 api \\
        python - < scripts/seed/2026-09-18_free_fire_b2b_hold.py

**Money guard.** A markup outside 5-13 % is refused rather than written. The
arithmetic only makes sense while the cost moved by roughly what NOVA quoted;
if a SKU's cost has moved for some *other* reason — a NOVA price change, a
manual edit, a supplier swap — the markup this formula produces would hold a
price that no longer relates to anything, and that is a catalogue change for a
human to look at, not a number to seed past.
"""

from __future__ import annotations

import asyncio
import os
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Sku

# sku_code -> the B2B unit price to preserve, measured on prod 2026-09-18.
TARGET_B2B_PRICE: dict[str, Decimal] = {
    "freefire_cis-weekly-lite": Decimal("0.402800"),
    "freefire_cis-110": Decimal("0.869200"),
    "freefire_cis-weekly-membership": Decimal("1.706600"),
    "freefire_cis-341": Decimal("2.618200"),
    "freefire_cis-572": Decimal("4.261200"),
    "freefire_cis-monthly-membership": Decimal("6.158600"),
    "freefire_cis-1166": Decimal("8.554200"),
    "freefire_cis-2398": Decimal("17.108400"),
    "freefire_cis-6160": Decimal("43.354000"),
}

# Outside this band the cost moved for a reason this script does not model.
MARKUP_FLOOR = Decimal("5")
MARKUP_CEILING = Decimal("13")

APPLY = os.environ.get("APPLY") == "1"


def _markup_holding(target_price: Decimal, cost: Decimal) -> Decimal:
    """The markup percentage that reproduces ``target_price`` from ``cost``.

    Inverts ``merchant_unit_price``: ``price = cost * (1 + markup / 100)``.
    Quantized to the two decimals ``Sku.b2b_markup_pct`` stores, so the price it
    restores can sit a fraction of a cent either side of the target — the dry
    run prints both numbers so that residual is visible rather than assumed.

    Args:
        target_price: The unit price to hold, at six decimals.
        cost: The SKU's current ``cost_usdt``.

    Returns:
        The markup percentage to store, e.g. ``Decimal("9.94")`` for 9.94 %.
    """
    return ((target_price / cost - 1) * 100).quantize(Decimal("0.01"), ROUND_HALF_UP)


async def main() -> None:
    """Print what each markup would become, and write it when ``APPLY=1``."""
    async with get_session_factory()() as db:
        rows = (
            (await db.execute(select(Sku).where(Sku.sku_code.in_(sorted(TARGET_B2B_PRICE)))))
            .scalars()
            .all()
        )
        found = {sku.sku_code: sku for sku in rows}

        missing = sorted(set(TARGET_B2B_PRICE) - set(found))
        if missing:
            print(f"!! not in the catalogue, skipped: {', '.join(missing)}")

        print(
            f"{'sku':34} {'cost':>10} {'markup':>8} {'->':^4} {'markup':>8} "
            f"{'price now':>11} {'price after':>12}"
        )
        planned: list[tuple[Sku, Decimal]] = []
        for code in sorted(TARGET_B2B_PRICE):
            sku = found.get(code)
            if sku is None:
                continue
            target = TARGET_B2B_PRICE[code]
            if sku.cost_usdt is None:
                print(f"{code:34} {'no cost':>10}  refused — cost_usdt is NULL")
                continue
            new_markup = _markup_holding(target, sku.cost_usdt)
            price_now = sku.cost_usdt * (1 + sku.b2b_markup_pct / 100)
            price_after = sku.cost_usdt * (1 + new_markup / 100)
            flag = ""
            if new_markup == sku.b2b_markup_pct:
                flag = "  unchanged — cost has not moved yet"
            elif not MARKUP_FLOOR <= new_markup <= MARKUP_CEILING:
                flag = f"  REFUSED — outside {MARKUP_FLOOR}-{MARKUP_CEILING} %"
            else:
                planned.append((sku, new_markup))
            print(
                f"{code:34} {sku.cost_usdt:>10.6f} {sku.b2b_markup_pct:>7}% "
                f"{'->':^4} {new_markup:>7}% {price_now:>11.6f} {price_after:>12.6f}{flag}"
            )

        if not planned:
            print("\nnothing to write.")
            return

        if not APPLY:
            print(f"\ndry run — {len(planned)} SKUs would change. Re-run with APPLY=1.")
            return

        for sku, new_markup in planned:
            sku.b2b_markup_pct = new_markup
        await db.commit()
        print(f"\nwrote {len(planned)} markups.")


if __name__ == "__main__":
    asyncio.run(main())
