"""Steam margin against what the supplier actually charged (NOVA).

``margin_usd_expr``'s variable-amount branch assumed a dollar of Steam wallet
costs a dollar — true of Waxpeer and G-Engine, which charge face value, false
of NOVA, whose plan discount means $10 of wallet costs us $9.80. Once
``fulfillment.service._record_supplier_charge`` has frozen that real figure
onto ``OrderItem.cost_usdt`` (covered separately in
``test_fulfillment_supplier_cost_recording.py``), ``margin_usd_expr`` must
read it instead of the assumption.

These tests run the real ``charged_usd_expr`` / ``margin_usd_expr`` SQL
against Postgres rather than re-deriving the arithmetic in Python: the
property under test is that gross and margin stay consistent
(``gross - margin == cost``), which a hand-written mirror of the formula could
get wrong in exactly the same way the SQL could.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Category,
    CategoryTranslation,
    Product,
    ProductTranslation,
    Sku,
)
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.orders.revenue import charged_usd_expr, margin_usd_expr

pytestmark = pytest.mark.asyncio


async def _seed_sku(
    db: AsyncSession, slug: str, *, variable: bool, sku_multiplier: str | None = None
) -> str:
    """One SKU, fixed or variable-amount. Category/Brand/Product are scaffolding
    the FK chain requires; nothing about them is under test."""
    category = Category(id=new_id(), slug=f"c-{slug}", sort_order=0, active=True)
    category.translations = [CategoryTranslation(locale="ru", name="C")]
    db.add(category)
    await db.flush()
    brand = Brand(id=new_id(), slug=f"b-{slug}", category_id=category.id, sort_order=0, active=True)
    brand.translations = [BrandTranslation(locale="ru", name="B")]
    db.add(brand)
    await db.flush()
    product = Product(id=new_id(), slug=f"p-{slug}", brand_id=brand.id, kind="top_up")
    product.translations = [ProductTranslation(locale="ru", name="P")]
    db.add(product)
    await db.flush()
    # ``ck_skus_variable_amount_complete`` requires the bounds and a multiplier
    # whenever ``variable_amount`` is true — the OrderItem's own pinned
    # ``rate_multiplier`` (ADR-0051) wins in every test below, so the SKU-level
    # one here only needs to be a valid, unused fallback.
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"sk-{slug}",
        price_usd=Decimal("10.00"),
        variable_amount=variable,
        min_amount_usd=Decimal("1.00") if variable else None,
        max_amount_usd=Decimal("1000.00") if variable else None,
        rate_multiplier=(Decimal(sku_multiplier) if sku_multiplier is not None else Decimal("1.10"))
        if variable
        else None,
    )
    db.add(sku)
    await db.flush()
    return sku.id


async def _line(
    db: AsyncSession,
    *,
    sku_id: str,
    qty: int = 1,
    unit: str = "10.00",
    pinned_multiplier: str | None = None,
    cost: str | None = None,
    discount: str | None = None,
) -> str:
    """One order with a single line, returning the line's id."""
    order = Order(
        id=new_id(),
        guest_email="g@example.com",
        status="delivered",
        currency="USD",
        total_usd=Decimal(unit) * qty,
        total_charged=Decimal(unit) * qty,
        expires_at=datetime.now(UTC),
    )
    db.add(order)
    await db.flush()
    item = OrderItem(
        id=new_id(),
        order_id=order.id,
        sku_id=sku_id,
        qty=qty,
        unit_price_usd=Decimal(unit),
        rate_multiplier=Decimal(pinned_multiplier) if pinned_multiplier is not None else None,
        cost_usdt=Decimal(cost) if cost is not None else None,
        discount_usd=Decimal(discount) if discount is not None else Decimal("0"),
    )
    db.add(item)
    await db.flush()
    return str(item.id)


async def _figures(db: AsyncSession, item_id: str) -> tuple[Decimal, Decimal | None]:
    """The real ``charged_usd_expr`` / ``margin_usd_expr`` for one line."""
    stmt = (
        select(charged_usd_expr(), margin_usd_expr())
        .select_from(OrderItem)
        .join(Sku, Sku.id == OrderItem.sku_id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(OrderItem.id == item_id)
    )
    gross_raw, margin_raw = (await db.execute(stmt)).one()
    gross = Decimal(str(gross_raw))
    margin = Decimal(str(margin_raw)) if margin_raw is not None else None
    return gross, margin


async def test_a_variable_line_with_a_recorded_cost_reports_margin_against_it(
    db_session: AsyncSession,
) -> None:
    """NOVA's shape: $10 of face value at a 1.10 multiplier, but only $9.80
    actually left our account. Margin is the markup *plus* the discount NOVA
    gave us, not just the markup."""
    sku_id = await _seed_sku(db_session, "nova-var", variable=True)
    item_id = await _line(
        db_session, sku_id=sku_id, unit="10.00", pinned_multiplier="1.10", cost="9.80"
    )

    gross, margin = await _figures(db_session, item_id)

    assert gross == Decimal("11.00")
    assert margin == Decimal("1.20")
    # The invariant: what we kept, plus what the supplier took, is what the
    # customer paid.
    assert gross - margin == Decimal("9.80")


async def test_a_variable_line_without_a_recorded_cost_keeps_the_old_margin(
    db_session: AsyncSession,
) -> None:
    """Every variable line written before this change has ``cost_usdt IS
    NULL`` (0 of 316 on production carry one) and must keep taking the old
    branch: margin assumed at face value, not read from a cost nobody
    recorded."""
    sku_id = await _seed_sku(db_session, "old-var", variable=True)
    item_id = await _line(db_session, sku_id=sku_id, unit="10.00", pinned_multiplier="1.10")

    gross, margin = await _figures(db_session, item_id)

    assert gross == Decimal("11.00")
    assert margin == Decimal("1.00"), "unchanged: qty * unit_price_usd * (multiplier - 1)"
    # Same invariant, but against the *assumed* cost (face value), because
    # that is what the old formula actually encodes.
    assert gross - margin == Decimal("10.00")


async def test_a_fixed_price_line_is_untouched(db_session: AsyncSession) -> None:
    """The new branch is gated on ``variable_amount`` — a fixed line's margin
    is exactly the pre-existing ``qty * (unit_price_usd - cost_usdt)``, cost
    recorded or not."""
    sku_id = await _seed_sku(db_session, "fixed", variable=False)
    item_id = await _line(db_session, sku_id=sku_id, qty=2, unit="25.00", cost="20.00")

    gross, margin = await _figures(db_session, item_id)

    assert gross == Decimal("50.00")
    assert margin == Decimal("10.00")
    assert gross - margin == Decimal("40.00")


async def test_a_discounted_variable_line_keeps_the_invariant(db_session: AsyncSession) -> None:
    """A discount lowers what we received and what we kept by the same
    amount and leaves what we paid the supplier alone — so it must cancel out
    of the invariant, not just out of the individual numbers."""
    sku_id = await _seed_sku(db_session, "nova-discount", variable=True)
    item_id = await _line(
        db_session,
        sku_id=sku_id,
        unit="10.00",
        pinned_multiplier="1.10",
        cost="9.80",
        discount="1.00",
    )

    gross, margin = await _figures(db_session, item_id)

    assert gross == Decimal("10.00")
    assert margin == Decimal("0.20")
    assert gross - margin == Decimal("9.80")


async def test_the_new_branch_falls_back_to_the_sku_multiplier_like_the_gross_does(
    db_session: AsyncSession,
) -> None:
    """The property `margin_usd_expr`'s docstring calls the way the invariant
    "quietly stops holding", asserted rather than described.

    The gross prefers the multiplier frozen on the line and falls back to the
    live SKU only for rows written before that column existed (ADR-0051). The
    margin has to resolve it the *same* way: read the live SKU while the gross
    reads the frozen one and the two stop agreeing the first time somebody
    edits a SKU's markup. Every other case here pins the line's own multiplier,
    so this is the only one that exercises the fallback — and it is the one a
    future edit swapping the coalesce for `Sku.rate_multiplier` would pass
    while breaking the others.
    """
    sku_id = await _seed_sku(db_session, "nova-fallback", variable=True, sku_multiplier="1.20")
    item_id = await _line(
        db_session, sku_id=sku_id, unit="10.00", pinned_multiplier=None, cost="9.80"
    )

    gross, margin = await _figures(db_session, item_id)

    assert gross == Decimal("12.00")
    assert margin == Decimal("2.20")
    assert gross - margin == Decimal("9.80")


async def test_the_frozen_multiplier_beats_the_live_one_in_both_expressions(
    db_session: AsyncSession,
) -> None:
    """The case where the two answers actually disagree.

    The test above proves the fallback is reached when the line froze nothing;
    it cannot prove the *precedence*, because a SKU whose multiplier equals the
    line's gives the same number either way. Here they differ — the line froze
    1.10, the SKU has since been edited to 1.20 — so an expression reading the
    live SKU produces 12.00/2.20 and one honouring ADR-0051's freeze produces
    11.00/1.20. Only the second is right: an admin editing a markup must not
    revalue orders already taken.

    Verified by mutation: replacing the coalesce with `Sku.rate_multiplier`
    leaves every other case in this file green and fails this one.
    """
    sku_id = await _seed_sku(db_session, "nova-frozen-wins", variable=True, sku_multiplier="1.20")
    item_id = await _line(
        db_session, sku_id=sku_id, unit="10.00", pinned_multiplier="1.10", cost="9.80"
    )

    gross, margin = await _figures(db_session, item_id)

    assert gross == Decimal("11.00"), "the gross must use the rate frozen at checkout"
    assert margin == Decimal("1.20"), "and so must the margin, or the two stop agreeing"
    assert gross - margin == Decimal("9.80")
