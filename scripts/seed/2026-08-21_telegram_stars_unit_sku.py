"""Move Telegram Stars onto a single unit SKU priced per star.

**Read ``docs/runbooks/telegram-stars-unit-sku.md`` before running this against
prod.** It is the only data change of the unit-SKU rollout, and it must not run
until the image carrying the new code is live and Stars still sells the old way:
until then checkout, fulfilment and both storefronts dual-read, and flipping the
row first would 422 every Stars sale for the length of the deploy.

Run inside the api container:

    docker compose exec -T api python - \
        < scripts/seed/2026-08-21_telegram_stars_unit_sku.py

and on prod (after ``--dry-run``):

    docker compose -f docker-compose.prod.yml exec -T api python - --dry-run \
        < scripts/seed/2026-08-21_telegram_stars_unit_sku.py
    docker compose -f docker-compose.prod.yml exec -T api python - \
        < scripts/seed/2026-08-21_telegram_stars_unit_sku.py

What it does, forward:

* ``tg-stars-any`` stops being a variable-amount line and becomes a unit SKU —
  ``price_usd`` is the price of **one** star, the customer buys ``qty`` of them.
* The G-Engine mapping ends at ``quantity=1``. The adapter sends
  ``Quantity = item.qty × mapping.quantity``; leaving a pack-era 500 there would
  order 500 × what the customer asked for.
* The pack SKUs go ``active=false``. They are **not** deleted, and no historical
  ``order_items`` row is touched — a pack bought before the flip still fulfils
  as ``qty=1 × mapping.quantity``.

It aborts (exit 1) if any ``tg-stars-any`` order is still ``pending_payment`` /
``paid`` / ``fulfilling``, or a fulfillment task for that SKU is still open.
Those free-amount lines stored ``qty=1``; after the flip G-Engine would be told
to send 1 star. Pack SKUs in-flight are OK — this script does not rewrite their
mappings.

Two things it refuses to guess. ``cost_usdt`` must already look like a per-star
cost, and the resulting ``price_usd`` must sit between that cost and half a
dollar. A pack-sized number in either column means somebody has to look at the
row — dividing it by 50 here would be this script inventing a sale price.

Idempotent: a second forward run finds nothing to change and says so. ``--revert``
puts the packs back on and makes the unit SKU variable again; it is not a
row-level time machine (see the runbook).
"""

from __future__ import annotations

import argparse
import asyncio
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import NoReturn

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Product, Sku
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.fulfillment.suppliers.gengine_client import GEngineClient
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.integrations.service import MappingUpsert, get_mapping, upsert_mapping
from yupay.modules.orders.models import Order, OrderItem

PRODUCT_SLUG = "telegram-stars"
UNIT_SKU_CODE = "tg-stars-any"
SUPPLIER_SLUG = "gengine"
STARS_SERVICE_ID = 72
ADMIN_ID = "00000000-0000-7000-8000-000000000001"

AMOUNT_UNIT = "Stars"
#: Telegram's own floor, and a ceiling that is a business limit rather than a
#: supplier one: a single order past it is more likely a typo than a sale.
MIN_QTY = 50
MAX_QTY = 2500
#: One mapping unit per star. ``Quantity = item.qty × mapping.quantity``.
MAPPING_QUANTITY = 1

#: A per-star cost lives around $0.0155. Anything above the ceiling is a pack
#: price that was never divided; anything below the floor is a rounding
#: accident. Both stop the run.
COST_FLOOR = Decimal("0.001")
COST_CEILING = Decimal("0.5")

#: What ``--revert`` restores: the shape scripts/seed/2026-08-18_telegram_stars
#: _any_amount.py created — 50..5 000 stars, 20% on the guarded FX rate, and the
#: placeholder price every variable SKU carries.
REVERT_MIN_STARS = 50
REVERT_MAX_STARS = 5_000
REVERT_RATE_MULTIPLIER = Decimal("1.2000")
REVERT_PRICE_USD = Decimal("1")


# --------------------------------------------------------------------------- #
# Guards — pure, and unit-tested in apps/api/tests/unit/test_stars_seed_guards.py
# --------------------------------------------------------------------------- #


def cost_guard(cost: Decimal | None) -> str | None:
    """Return why ``cost_usdt`` cannot be read as a per-star cost, or ``None``.

    Args:
        cost: ``tg-stars-any.cost_usdt`` as stored.

    Returns:
        A message for the operator, or ``None`` when the cost is per-star.
    """
    if cost is None:
        return (
            "cost_usdt is NULL — the variable-amount line never carried one. "
            "Set the per-star cost (G-Engine service 72: 1 / unfixed_details.rate) "
            "and margin_percent on the SKU, then re-run."
        )
    if cost > COST_CEILING:
        return (
            f"cost_usdt={cost} is above {COST_CEILING} — that is a pack cost, not the "
            "cost of one star. This script will not divide it for you: fix the row "
            "(or point it at the right SKU) and re-run."
        )
    if cost < COST_FLOOR:
        return (
            f"cost_usdt={cost} is below {COST_FLOOR} — too small to be a star. "
            "Fix the row and re-run."
        )
    return None


def price_guard(price: Decimal, cost: Decimal) -> str | None:
    """Return why ``price_usd`` cannot be the price of one star, or ``None``.

    The variable-amount line carried ``price_usd=1`` as a placeholder — on a unit
    SKU that same 1 means **one dollar per star**, and 50 Stars would ring up at
    $50. Nothing here rescales it; an operator sets the margin and re-runs.

    Args:
        price: The ``price_usd`` the row would end up with.
        cost: The per-star cost the row already passed :func:`cost_guard` with.

    Returns:
        A message for the operator, or ``None`` when the price is per-star.
    """
    if price > COST_CEILING:
        return (
            f"price_usd={price} is above {COST_CEILING} — on a unit SKU that is the price "
            "of ONE star, so this would sell 50 Stars for "
            f"${(price * MIN_QTY).quantize(Decimal('0.01'))}. Set margin_percent on the "
            "SKU (price is then re-derived from cost_usdt) or fix price_usd, then re-run."
        )
    if price < cost:
        return (
            f"price_usd={price} is below cost_usdt={cost} — every star would sell at a "
            "loss. Set margin_percent on the SKU and re-run."
        )
    return None


def mapping_service_guard(external_product_id: str | None) -> str | None:
    """Return why the mapping is not the Stars one, or ``None``.

    Args:
        external_product_id: ``sku_supplier_mapping.external_product_id``.

    Returns:
        A message for the operator, or ``None`` when it points at service 72.
    """
    if (external_product_id or "").strip() != str(STARS_SERVICE_ID):
        return (
            f"the {SUPPLIER_SLUG} mapping for {UNIT_SKU_CODE} points at service "
            f"{external_product_id!r}, not {STARS_SERVICE_ID} — refusing to rewrite a "
            "mapping this script does not recognise."
        )
    return None


def quantity_plan(current: int) -> tuple[int, str]:
    """Return the mapping quantity to write and the old → new line to print first.

    Args:
        current: ``sku_supplier_mapping.quantity`` as stored.

    Returns:
        ``(1, line)``. Always 1: the star count now rides on ``order_items.qty``,
        and the adapter multiplies the two.
    """
    if current == MAPPING_QUANTITY:
        return MAPPING_QUANTITY, f"mapping.quantity: {current} (already 1 — unchanged)"
    return MAPPING_QUANTITY, (
        f"mapping.quantity: {current} -> {MAPPING_QUANTITY} — G-Engine Quantity is "
        f"qty × mapping.quantity, so leaving it at {current} would order {current} × "
        "the stars the customer asked for"
    )


def price_from_margin(cost: Decimal, margin_percent: Decimal) -> Decimal:
    """Return ``cost × (1 + margin/100)`` at the six decimals ``price_usd`` stores.

    The hourly refresh rounds the same product to cents because it prices packs.
    A per-star price rounded to cents is $0.0186 → $0.02: a third of the margin
    invented by rounding, and one rate move away from selling under cost.

    Args:
        cost: Per-star cost in USDT.
        margin_percent: The margin on file for the SKU.

    Returns:
        The per-star sale price.
    """
    return (cost * (Decimal(1) + margin_percent / Decimal(100))).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )


def usd_for_stars(stars: int, rate: Decimal) -> Decimal:
    """Return the USD bound for ``stars`` at ``rate`` stars per USD (revert path)."""
    return (Decimal(stars) / rate).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


# Orders whose ``tg-stars-any`` line would fulfill as Quantity=1 after the
# catalog flip. Names match ``OrderStatus`` / ``ck_orders_status``.
IN_FLIGHT_ORDER_STATUSES: frozenset[str] = frozenset({"pending_payment", "paid", "fulfilling"})
# Non-terminal fulfillment tasks (CHECK ``ck_fulfillment_tasks_status``).
# ``failed`` is retryable — a retry after the seed would also send Quantity=1.
OPEN_FULFILLMENT_TASK_STATUSES: frozenset[str] = frozenset({"pending", "in_progress", "failed"})


def is_in_flight_order_status(status: str) -> bool:
    """True when flipping ``tg-stars-any`` would mis-fulfill this order."""
    return status in IN_FLIGHT_ORDER_STATUSES


def is_open_fulfillment_task_status(status: str) -> bool:
    """True when the task can still send Quantity to G-Engine (including retry)."""
    return status in OPEN_FULFILLMENT_TASK_STATUSES


def in_flight_abort_reason(*, order_ids: list[str], task_ids: list[str]) -> str | None:
    """Return the abort text listing ids, or ``None`` when the catalog is safe to flip.

    Args:
        order_ids: ``orders.id`` for ``tg-stars-any`` lines still in
            :data:`IN_FLIGHT_ORDER_STATUSES`.
        task_ids: ``fulfillment_tasks.id`` for that SKU still in
            :data:`OPEN_FULFILLMENT_TASK_STATUSES`.

    Returns:
        A multi-line operator message, or ``None``.
    """
    if not order_ids and not task_ids:
        return None
    parts: list[str] = [
        "in-flight tg-stars-any orders or fulfillment tasks — flipping the SKU "
        "would fulfill a pre-seed qty=1 line as Quantity=1. Drain them "
        "(pending_payment expires ~10 min) and re-run. Pack SKUs in-flight are OK."
    ]
    if order_ids:
        parts.append("orders: " + ", ".join(order_ids))
    if task_ids:
        parts.append("fulfillment_tasks: " + ", ".join(task_ids))
    return "\n".join(parts)


async def find_in_flight_unit_sku(
    session: AsyncSession, *, sku_id: str
) -> tuple[list[str], list[str]]:
    """Return in-flight ``tg-stars-any`` order ids and open fulfillment task ids.

    Pack SKUs are not queried: this seed does not rewrite their mappings.

    Args:
        session: Open catalog/orders session.
        sku_id: ``skus.id`` of ``tg-stars-any``.

    Returns:
        ``(order_ids, task_ids)``, each sorted.
    """
    order_ids = list(
        (
            await session.execute(
                select(Order.id)
                .join(OrderItem, OrderItem.order_id == Order.id)
                .where(
                    OrderItem.sku_id == sku_id,
                    Order.status.in_(tuple(IN_FLIGHT_ORDER_STATUSES)),
                )
                .distinct()
                .order_by(Order.id)
            )
        )
        .scalars()
        .all()
    )
    task_ids = list(
        (
            await session.execute(
                select(FulfillmentTask.id)
                .join(OrderItem, OrderItem.id == FulfillmentTask.order_item_id)
                .where(
                    OrderItem.sku_id == sku_id,
                    FulfillmentTask.status.in_(tuple(OPEN_FULFILLMENT_TASK_STATUSES)),
                )
                .order_by(FulfillmentTask.id)
            )
        )
        .scalars()
        .all()
    )
    return order_ids, task_ids


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def _snapshot(sku: Sku, mapping: SkuSupplierMapping) -> dict[str, str]:
    """Every field either path writes, as printable strings."""
    return {
        "variable_amount": str(sku.variable_amount),
        "price_usd": str(sku.price_usd),
        "cost_usdt": str(sku.cost_usdt),
        "margin_percent": str(sku.margin_percent),
        "min_amount_usd": str(sku.min_amount_usd),
        "max_amount_usd": str(sku.max_amount_usd),
        "rate_multiplier": str(sku.rate_multiplier),
        "amount_unit": str(sku.amount_unit),
        "units_per_usd": str(sku.units_per_usd),
        "units": str(sku.units),
        "min_qty": str(sku.min_qty),
        "max_qty": str(sku.max_qty),
        "active": str(sku.active),
        "mapping.external_product_id": str(mapping.external_product_id),
        "mapping.external_variant_id": str(mapping.external_variant_id),
        "mapping.quantity": str(mapping.quantity),
        "mapping.is_active": str(mapping.is_active),
    }


def _print_diff(before: dict[str, str], after: dict[str, str]) -> bool:
    """Print the before/after table. Returns whether anything moved."""
    width = max(len(key) for key in before)
    changed = False
    print(f"\n  {'field'.ljust(width)}  {'before'.ljust(22)}  after")
    print(f"  {'-' * width}  {'-' * 22}  {'-' * 22}")
    for key, old in before.items():
        new = after[key]
        changed = changed or old != new
        print(
            f"  {key.ljust(width)}  {old.ljust(22)}  {new}{'' if old == new else '   <-- changed'}"
        )
    return changed


async def _finish(session: AsyncSession, *, dry_run: bool, changed: bool) -> None:
    """Commit, or roll back and say so."""
    if dry_run:
        await session.rollback()
        print("\ndry run — rolled back, nothing was written")
        return
    await session.commit()
    print("\ncommitted" if changed else "\ncommitted (nothing had changed)")


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


async def _load(session: AsyncSession) -> tuple[Sku, list[Sku], SkuSupplierMapping]:
    """Return the unit SKU, its sibling pack SKUs and the G-Engine mapping.

    Raises:
        SystemExit: When the product, the SKU or the mapping is missing.
    """
    product = (
        await session.execute(select(Product).where(Product.slug == PRODUCT_SLUG))
    ).scalar_one_or_none()
    if product is None:
        raise SystemExit(f"product {PRODUCT_SLUG} does not exist — nothing to convert")

    rows = list(
        (
            await session.execute(
                select(Sku).where(Sku.product_id == product.id).order_by(Sku.sort_order)
            )
        )
        .scalars()
        .all()
    )
    unit = next((row for row in rows if row.sku_code == UNIT_SKU_CODE), None)
    if unit is None:
        raise SystemExit(
            f"{UNIT_SKU_CODE} does not exist under {PRODUCT_SLUG} — run "
            "scripts/seed/2026-08-18_telegram_stars_any_amount.py first"
        )

    mapping = await get_mapping(session, sku_id=unit.id, supplier_slug=SUPPLIER_SLUG)
    if mapping is None:
        raise SystemExit(
            f"{UNIT_SKU_CODE} has no {SUPPLIER_SLUG} mapping — a unit SKU with no "
            "mapping cannot be fulfilled; fix the mapping in the admin and re-run"
        )
    print(f"{PRODUCT_SLUG}: {UNIT_SKU_CODE} + {len(rows) - 1} pack SKUs")
    return unit, [row for row in rows if row.sku_code != UNIT_SKU_CODE], mapping


async def gengine_star_rate() -> Decimal | None:
    """Return the live Stars-per-USD rate, or ``None`` when it cannot be read.

    Advisory only: it prices nothing here. Forward, it tells an operator what a
    per-star cost should look like; on revert it is the default ``units_per_usd``.
    """
    settings = get_settings()
    if not settings.gengine_api_key:
        return None
    client = GEngineClient(
        api_key=settings.gengine_api_key,
        base_url=settings.gengine_base_url,
        timeout_seconds=settings.gengine_request_timeout_seconds,
    )
    try:
        for offset in (0, 100, 200):
            page = await client.list_recharge_services(limit=100, offset=offset)
            if not page:
                break
            for service in page:
                if service.get("id") == STARS_SERVICE_ID:
                    rate = Decimal(str((service.get("unfixed_details") or {}).get("rate") or 0))
                    return rate if rate > 0 else None
    except Exception as exc:  # noqa: BLE001 -- advisory; a live rate is never required
        print(f"  G-Engine lookup failed ({exc!s}) — continuing without a live rate")
    return None


async def _abort_on_cost(sku: Sku, reason: str) -> NoReturn:
    """Print the offending row plus what G-Engine currently quotes, then exit 1."""
    print(f"\nABORT: {reason}")
    print(
        f"  {sku.sku_code}: cost_usdt={sku.cost_usdt} price_usd={sku.price_usd} "
        f"margin_percent={sku.margin_percent} variable_amount={sku.variable_amount} "
        f"units_per_usd={sku.units_per_usd} active={sku.active}"
    )
    rate = await gengine_star_rate()
    if rate is not None:
        print(
            f"  G-Engine service {STARS_SERVICE_ID} quotes {rate} Stars per USD right now "
            f"— one star costs ${usd_for_stars(1, rate)}"
        )
    raise SystemExit(1)


# --------------------------------------------------------------------------- #
# Forward
# --------------------------------------------------------------------------- #


def _apply_unit_fields(sku: Sku) -> None:
    """Turn the variable-amount row into a unit SKU. Sets no price."""
    sku.variable_amount = False
    sku.min_amount_usd = None
    sku.max_amount_usd = None
    sku.rate_multiplier = None
    sku.units_per_usd = None
    sku.units = None
    sku.amount_unit = AMOUNT_UNIT
    sku.min_qty = MIN_QTY
    sku.max_qty = MAX_QTY
    sku.active = True
    sku.updated_at = now()


def _deactivate_packs(packs: list[Sku]) -> list[str]:
    """Switch the pack SKUs off, printing each. Returns the codes this run turned off."""
    turned_off: list[str] = []
    for sku in packs:
        if sku.active:
            sku.active = False
            sku.updated_at = now()
            turned_off.append(sku.sku_code)
            print(f"  {sku.sku_code}: active true -> false")
        else:
            print(f"  {sku.sku_code}: already inactive — left as it was")
    if turned_off:
        print(f"  to put exactly these back: --revert --packs {','.join(turned_off)}")
    return turned_off


async def convert(session: AsyncSession, *, dry_run: bool) -> None:
    """Forward path: one unit SKU, packs off, mapping at quantity 1."""
    unit, packs, mapping = await _load(session)

    order_ids, task_ids = await find_in_flight_unit_sku(session, sku_id=unit.id)
    in_flight_reason = in_flight_abort_reason(order_ids=order_ids, task_ids=task_ids)
    if in_flight_reason is not None:
        print(f"\nABORT: {in_flight_reason}")
        raise SystemExit(1)

    service_reason = mapping_service_guard(mapping.external_product_id)
    if service_reason is not None:
        raise SystemExit(f"ABORT: {service_reason}")
    cost = unit.cost_usdt
    cost_reason = cost_guard(cost)
    if cost_reason is not None or cost is None:
        await _abort_on_cost(unit, cost_reason or "cost_usdt is NULL")

    before = _snapshot(unit, mapping)
    quantity, line = quantity_plan(mapping.quantity)
    print(f"  {line}")

    _apply_unit_fields(unit)
    if unit.margin_percent is not None:
        unit.price_usd = price_from_margin(cost, unit.margin_percent)
    else:
        print(
            f"  margin_percent is NULL — price_usd stays at {unit.price_usd}; "
            "it is now the price of one star"
        )
    price_reason = price_guard(unit.price_usd, cost)
    if price_reason is not None:
        await session.rollback()
        print(f"\nABORT: {price_reason}")
        print(
            f"  {unit.sku_code}: cost_usdt={unit.cost_usdt} price_usd={unit.price_usd} "
            f"margin_percent={unit.margin_percent}"
        )
        raise SystemExit(1)

    await upsert_mapping(
        session,
        MappingUpsert(
            sku_id=unit.id,
            supplier_slug=SUPPLIER_SLUG,
            kind="game",
            external_product_id=str(STARS_SERVICE_ID),
            external_variant_id=None,
            quantity=quantity,
            extra=mapping.extra or {},
            is_active=True,
            updated_by=ADMIN_ID,
        ),
    )
    _deactivate_packs(packs)
    await session.flush()

    changed = _print_diff(before, _snapshot(unit, mapping))
    await _finish(session, dry_run=dry_run, changed=changed)


# --------------------------------------------------------------------------- #
# Revert
# --------------------------------------------------------------------------- #


def _reactivate_packs(packs: list[Sku], codes: list[str] | None) -> None:
    """Switch pack SKUs back on: the named ones, or every inactive one."""
    wanted = [sku for sku in packs if codes is None or sku.sku_code in codes]
    missing = set(codes or []) - {sku.sku_code for sku in packs}
    if missing:
        raise SystemExit(f"--packs names SKUs that are not under {PRODUCT_SLUG}: {sorted(missing)}")
    for sku in wanted:
        if sku.active:
            print(f"  {sku.sku_code}: already active — left as it was")
            continue
        sku.active = True
        sku.updated_at = now()
        print(f"  {sku.sku_code}: active false -> true")


async def revert(
    session: AsyncSession,
    *,
    units_per_usd: Decimal | None,
    packs: list[str] | None,
    dry_run: bool,
) -> None:
    """Revert path: packs back on, ``tg-stars-any`` variable again.

    Not a row-level time machine. It restores the shape the 2026-08-18 seed
    created — 50..5 000 stars at ``REVERT_RATE_MULTIPLIER`` on the given rate,
    ``price_usd`` back to its placeholder — not whatever each row held five
    minutes before the forward run. ``cost_usdt`` and ``margin_percent`` are left
    alone: a true per-star cost stays true.
    """
    unit, pack_rows, mapping = await _load(session)
    rate = units_per_usd if units_per_usd is not None else await gengine_star_rate()
    if rate is None or rate <= 0:
        raise SystemExit(
            "no Stars-per-USD rate available — re-run with --units-per-usd <rate> "
            f"(G-Engine service {STARS_SERVICE_ID}, unfixed_details.rate)"
        )
    print(f"  rate: {rate} Stars per USD (${usd_for_stars(1, rate)} each)")

    before = _snapshot(unit, mapping)
    unit.variable_amount = True
    unit.min_amount_usd = usd_for_stars(REVERT_MIN_STARS, rate)
    unit.max_amount_usd = usd_for_stars(REVERT_MAX_STARS, rate)
    unit.rate_multiplier = REVERT_RATE_MULTIPLIER
    unit.amount_unit = AMOUNT_UNIT
    unit.units_per_usd = rate
    unit.units = None
    unit.min_qty = None
    unit.max_qty = None
    unit.price_usd = REVERT_PRICE_USD
    unit.active = True
    unit.updated_at = now()

    # quantity stays 1: the variable path re-derives the star count from what was
    # charged and never reads it, and a pack-era number here would be a trap for
    # the next forward run.
    await upsert_mapping(
        session,
        MappingUpsert(
            sku_id=unit.id,
            supplier_slug=SUPPLIER_SLUG,
            kind="game",
            external_product_id=str(STARS_SERVICE_ID),
            external_variant_id=None,
            quantity=MAPPING_QUANTITY,
            extra=mapping.extra or {},
            is_active=True,
            updated_by=ADMIN_ID,
        ),
    )
    _reactivate_packs(pack_rows, packs)
    await session.flush()

    changed = _print_diff(before, _snapshot(unit, mapping))
    await _finish(session, dry_run=dry_run, changed=changed)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _decimal(raw: str) -> Decimal:
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"{raw!r} is not a number") from exc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the CLI. ``python - --revert < script`` reaches this the same way."""
    parser = argparse.ArgumentParser(
        prog="2026-08-21_telegram_stars_unit_sku",
        description="Move Telegram Stars onto one unit SKU (or put the packs back).",
    )
    parser.add_argument(
        "--revert",
        action="store_true",
        help="packs back on, tg-stars-any variable again (not a row-level restore)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the before/after table and roll back instead of committing",
    )
    parser.add_argument(
        "--units-per-usd",
        type=_decimal,
        default=None,
        help="revert only: Stars per USD (default: the live G-Engine rate)",
    )
    parser.add_argument(
        "--packs",
        default=None,
        help=(
            "revert only: comma-separated sku_codes to reactivate "
            "(default: every inactive SKU of the product)"
        ),
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> None:
    """Run one path against the configured database."""
    args = parse_args(argv)
    codes = [code.strip() for code in args.packs.split(",") if code.strip()] if args.packs else None
    async with get_session_factory()() as session:
        if args.revert:
            await revert(
                session, units_per_usd=args.units_per_usd, packs=codes, dry_run=args.dry_run
            )
        else:
            await convert(session, dry_run=args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
