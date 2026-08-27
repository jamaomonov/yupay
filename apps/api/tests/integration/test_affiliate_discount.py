"""Affiliate discount: admission, arithmetic, attribution, and the margin reports.

The reason this module exists at all is the last one. Revenue and margin are
computed from order lines, not from ``total_charged``, so a discount that only
reduced the payable total would be invisible to every report — full margin
shown on precisely the orders that have the least of it.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


def _unique_code(prefix: str) -> str:
    """A collision-free test code.

    Not derived from ``new_id()``: it is a UUIDv7, so its leading characters
    are a timestamp and codes minted inside one test share them.
    """
    return f"{prefix}{secrets.token_hex(5).upper()}"


async def test_order_carries_discount_columns(db_session: AsyncSession) -> None:
    """The new columns exist and default to "no discount"."""
    from yupay.core.clock import now
    from yupay.core.ids import new_id
    from yupay.modules.orders.models import Order

    moment = now()
    order = Order(
        id=new_id(),
        guest_email=f"g-{new_id()}@example.test",
        status="pending_payment",
        currency="UZS",
        total_usd=Decimal("1"),
        total_charged=Decimal("12000"),
        purpose="catalog",
        expires_at=moment + timedelta(days=1),
    )
    db_session.add(order)
    await db_session.flush()
    await db_session.refresh(order)

    assert order.affiliate_code_id is None
    assert order.discount_charged == Decimal("0")


async def _seed_partner_and_code(
    db: AsyncSession,
    *,
    discount_percent: Decimal = Decimal("5"),
    active: bool = True,
    partner_status: str = "active",
    linked_user_id: str | None = None,
) -> tuple[str, str]:
    """Create a partner and one code.

    Returns:
        ``(code_id, code)``.
    """
    from yupay.core.ids import new_id
    from yupay.modules.affiliate.models import AffiliateCode, AffiliatePartner

    partner = AffiliatePartner(
        id=new_id(),
        email=f"p-{new_id()}@example.test",
        status=partner_status,
        user_id=linked_user_id,
    )
    db.add(partner)
    await db.flush()

    code = AffiliateCode(
        id=new_id(),
        partner_id=partner.id,
        code=_unique_code("C"),
        discount_percent=discount_percent,
        commission_percent=Decimal("2"),
        active=active,
    )
    db.add(code)
    await db.flush()
    return code.id, code.code


async def _new_user(db: AsyncSession) -> str:
    from yupay.core.ids import new_id
    from yupay.modules.users.models import User

    user = User(id=new_id())
    db.add(user)
    await db.flush()
    return user.id


async def _order(
    db: AsyncSession,
    *,
    user_id: str,
    status: str,
    affiliate_code_id: str | None = None,
    paid: bool = False,
) -> str:
    from yupay.core.clock import now
    from yupay.core.ids import new_id
    from yupay.modules.orders.models import Order

    moment = now()
    order = Order(
        id=new_id(),
        user_id=user_id,
        status=status,
        currency="UZS",
        total_usd=Decimal("1"),
        total_charged=Decimal("12000"),
        purpose="catalog",
        expires_at=moment + timedelta(days=1),
        paid_at=moment if paid else None,
        affiliate_code_id=affiliate_code_id,
    )
    db.add(order)
    await db.flush()
    return order.id


async def test_resolve_accepts_a_valid_code_for_a_fresh_buyer(db_session: AsyncSession) -> None:
    from yupay.modules.affiliate.discount import ResolvedDiscount, resolve_code

    _, code = await _seed_partner_and_code(db_session, discount_percent=Decimal("7"))
    user_id = await _new_user(db_session)

    result = await resolve_code(db_session, code=code, user_id=user_id, purpose="catalog")
    assert isinstance(result, ResolvedDiscount)
    assert result.percent == Decimal("7")


async def test_resolve_normalises_case_and_whitespace(db_session: AsyncSession) -> None:
    from yupay.modules.affiliate.discount import ResolvedDiscount, resolve_code

    _, code = await _seed_partner_and_code(db_session)
    user_id = await _new_user(db_session)

    result = await resolve_code(
        db_session, code=f"  {code.lower()} ", user_id=user_id, purpose="catalog"
    )
    assert isinstance(result, ResolvedDiscount)


async def test_resolve_rejects_a_guest(db_session: AsyncSession) -> None:
    from yupay.modules.affiliate.discount import resolve_code

    _, code = await _seed_partner_and_code(db_session)
    assert await resolve_code(db_session, code=code, user_id=None, purpose="catalog") == "guest"


async def test_resolve_rejects_a_wallet_topup(db_session: AsyncSession) -> None:
    """A top-up is a 1:1 deposit. Discounting one prints money."""
    from yupay.modules.affiliate.discount import resolve_code

    _, code = await _seed_partner_and_code(db_session)
    user_id = await _new_user(db_session)
    assert (
        await resolve_code(db_session, code=code, user_id=user_id, purpose="wallet_topup")
        == "not_catalog"
    )


async def test_resolve_hides_whether_an_unusable_code_exists(db_session: AsyncSession) -> None:
    """Nonexistent, inactive, and suspended-partner codes are indistinguishable.

    Otherwise the preview endpoint is a directory of other people's codes.
    """
    from yupay.modules.affiliate.discount import resolve_code

    user_id = await _new_user(db_session)
    _, inactive = await _seed_partner_and_code(db_session, active=False)
    _, suspended = await _seed_partner_and_code(db_session, partner_status="suspended")

    for candidate in (_unique_code("Z"), inactive, suspended):
        assert (
            await resolve_code(db_session, code=candidate, user_id=user_id, purpose="catalog")
            == "unknown"
        )


async def test_resolve_rejects_a_buyer_who_already_belongs_to_a_partner(
    db_session: AsyncSession,
) -> None:
    from yupay.core.ids import new_id
    from yupay.modules.affiliate.discount import resolve_code
    from yupay.modules.affiliate.models import AffiliateAttribution, AffiliateCode

    _, code = await _seed_partner_and_code(db_session)
    other_code_id, _ = await _seed_partner_and_code(db_session)
    user_id = await _new_user(db_session)

    existing = await db_session.get(AffiliateCode, other_code_id)
    assert existing is not None
    db_session.add(
        AffiliateAttribution(
            id=new_id(),
            user_id=user_id,
            partner_id=existing.partner_id,
            code_id=other_code_id,
        )
    )
    await db_session.flush()

    assert (
        await resolve_code(db_session, code=code, user_id=user_id, purpose="catalog")
        == "already_used"
    )


async def test_resolve_rejects_a_buyer_with_a_prior_paid_order(db_session: AsyncSession) -> None:
    """Deliberately "no prior *paid* order", not "no prior order": an abandoned
    unpaid cart must not disqualify someone forever."""
    from yupay.modules.affiliate.discount import ResolvedDiscount, resolve_code

    _, code = await _seed_partner_and_code(db_session)
    user_id = await _new_user(db_session)

    await _order(db_session, user_id=user_id, status="expired")
    assert isinstance(
        await resolve_code(db_session, code=code, user_id=user_id, purpose="catalog"),
        ResolvedDiscount,
    )

    await _order(db_session, user_id=user_id, status="paid", paid=True)
    assert (
        await resolve_code(db_session, code=code, user_id=user_id, purpose="catalog")
        == "not_first_order"
    )


async def test_resolve_rejects_a_partner_using_their_own_code(db_session: AsyncSession) -> None:
    from yupay.modules.affiliate.discount import resolve_code

    user_id = await _new_user(db_session)
    _, code = await _seed_partner_and_code(db_session, linked_user_id=user_id)

    assert (
        await resolve_code(db_session, code=code, user_id=user_id, purpose="catalog") == "own_code"
    )


async def test_resolve_rejects_while_an_unpaid_coded_order_is_open(
    db_session: AsyncSession,
) -> None:
    """Narrows the spec's known gap: without this a buyer could open two orders
    with two codes and pay both, taking two discounts for one attribution."""
    from yupay.modules.affiliate.discount import resolve_code

    code_id, _ = await _seed_partner_and_code(db_session)
    _, second = await _seed_partner_and_code(db_session)
    user_id = await _new_user(db_session)

    await _order(db_session, user_id=user_id, status="pending_payment", affiliate_code_id=code_id)

    assert (
        await resolve_code(db_session, code=second, user_id=user_id, purpose="catalog")
        == "pending_coded_order"
    )


async def _seed_sku(db: AsyncSession, *, price_usd: str, cost_usdt: str | None) -> str:
    """One buyable SKU, with the whole category → brand → product chain it needs."""
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

    cat = Category(id=new_id(), slug=f"c-{new_id()[:8]}", sort_order=0, active=True)
    cat.translations = [CategoryTranslation(locale="ru", name="Игры")]
    db.add(cat)
    await db.flush()

    brand = Brand(
        id=new_id(), slug=f"b-{new_id()[:8]}", category_id=cat.id, sort_order=0, active=True
    )
    brand.translations = [BrandTranslation(locale="ru", name="B")]
    db.add(brand)
    await db.flush()

    product = Product(id=new_id(), slug=f"p-{new_id()[:8]}", brand_id=brand.id, kind="top_up")
    product.translations = [ProductTranslation(locale="ru", name="P")]
    db.add(product)
    await db.flush()

    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"s-{new_id()[:8]}",
        price_usd=Decimal(price_usd),
        cost_usdt=Decimal(cost_usdt) if cost_usdt is not None else None,
    )
    db.add(sku)
    await db.flush()
    return sku.id


async def test_create_order_applies_the_discount(db_session: AsyncSession) -> None:
    """The server prices the order; the client only names a code."""
    from yupay.core.ids import new_id
    from yupay.modules.affiliate.discount import discount_amount
    from yupay.modules.orders.schemas import OrderCreate, OrderItemIn
    from yupay.modules.orders.service import Actor, create_order

    code_id, code = await _seed_partner_and_code(db_session, discount_percent=Decimal("10"))
    user_id = await _new_user(db_session)
    sku_id = await _seed_sku(db_session, price_usd="10.00", cost_usdt="8.00")

    order = await create_order(
        db_session,
        OrderCreate(
            currency="USD",
            items=[OrderItemIn(sku_id=sku_id, qty=2)],
            affiliate_code=code,
        ),
        actor=Actor(user_id=user_id, email=None),
        idempotency_key=new_id(),
    )

    full = Decimal("20.00")
    expected_discount = discount_amount(full, Decimal("10"), "USD")
    assert expected_discount == Decimal("2.00")
    assert order.discount_charged == expected_discount
    assert order.total_charged == full - expected_discount
    assert order.affiliate_code_id == code_id
    # The order-level discount has to reach the lines, or every margin report
    # keeps showing the pre-discount number.
    assert sum(item.discount_usd for item in order.items) == expected_discount


async def test_create_order_ignores_an_unusable_code(db_session: AsyncSession) -> None:
    """A code that no longer applies must not fail the checkout.

    The buyer saw the verdict at preview time; losing a sale over a discount
    that expired thirty seconds ago is the worse trade.
    """
    from yupay.core.ids import new_id
    from yupay.modules.orders.schemas import OrderCreate, OrderItemIn
    from yupay.modules.orders.service import Actor, create_order

    _, code = await _seed_partner_and_code(db_session, active=False)
    user_id = await _new_user(db_session)
    sku_id = await _seed_sku(db_session, price_usd="10.00", cost_usdt="8.00")

    order = await create_order(
        db_session,
        OrderCreate(
            currency="USD",
            items=[OrderItemIn(sku_id=sku_id, qty=1)],
            affiliate_code=code,
        ),
        actor=Actor(user_id=user_id, email=None),
        idempotency_key=new_id(),
    )

    assert order.total_charged == Decimal("10.00")
    assert order.discount_charged == Decimal("0")
    assert order.affiliate_code_id is None


async def test_create_order_without_a_code_is_unchanged(db_session: AsyncSession) -> None:
    """The overwhelmingly common path must not have moved."""
    from yupay.core.ids import new_id
    from yupay.modules.orders.schemas import OrderCreate, OrderItemIn
    from yupay.modules.orders.service import Actor, create_order

    sku_id = await _seed_sku(db_session, price_usd="10.00", cost_usdt="8.00")

    order = await create_order(
        db_session,
        OrderCreate(currency="USD", items=[OrderItemIn(sku_id=sku_id, qty=1)]),
        actor=Actor(user_id=None, email="g@example.test"),
        idempotency_key=new_id(),
    )

    assert order.total_charged == Decimal("10.00")
    assert order.discount_charged == Decimal("0")
    assert order.affiliate_code_id is None
    assert all(item.discount_usd == Decimal("0") for item in order.items)


async def test_attribution_is_bound_when_a_coded_order_is_paid(
    db_session: AsyncSession,
) -> None:
    """The binding happens at payment, not at order creation: an abandoned cart
    must not tie a buyer to a partner who sold them nothing."""
    from sqlalchemy import select
    from yupay.modules.affiliate.attribution import bind_attribution
    from yupay.modules.affiliate.models import AffiliateAttribution, AffiliateCode
    from yupay.modules.orders.models import Order

    code_id, _ = await _seed_partner_and_code(db_session)
    user_id = await _new_user(db_session)
    order_id = await _order(
        db_session, user_id=user_id, status="paid", affiliate_code_id=code_id, paid=True
    )
    order = await db_session.get(Order, order_id)
    assert order is not None

    assert await bind_attribution(db_session, order=order) is True

    row = (
        await db_session.execute(
            select(AffiliateAttribution).where(AffiliateAttribution.user_id == user_id)
        )
    ).scalar_one()
    code = await db_session.get(AffiliateCode, code_id)
    assert code is not None
    assert row.partner_id == code.partner_id
    assert row.first_order_id == order_id


async def test_a_second_coded_order_does_not_rebind(db_session: AsyncSession) -> None:
    """UNIQUE(user_id) is the guarantee; binding must report it, not raise."""
    from sqlalchemy import func, select
    from yupay.modules.affiliate.attribution import bind_attribution
    from yupay.modules.affiliate.models import AffiliateAttribution
    from yupay.modules.orders.models import Order

    first_code, _ = await _seed_partner_and_code(db_session)
    second_code, _ = await _seed_partner_and_code(db_session)
    user_id = await _new_user(db_session)

    for code_id in (first_code, second_code):
        order_id = await _order(
            db_session, user_id=user_id, status="paid", affiliate_code_id=code_id, paid=True
        )
        order = await db_session.get(Order, order_id)
        assert order is not None
        await bind_attribution(db_session, order=order)

    count = await db_session.scalar(
        select(func.count())
        .select_from(AffiliateAttribution)
        .where(AffiliateAttribution.user_id == user_id)
    )
    assert count == 1


async def test_binding_is_a_no_op_without_a_code_or_without_a_user(
    db_session: AsyncSession,
) -> None:
    """A payment webhook must never fail because of the affiliate program."""
    from yupay.core.clock import now
    from yupay.core.ids import new_id
    from yupay.modules.affiliate.attribution import bind_attribution
    from yupay.modules.orders.models import Order

    user_id = await _new_user(db_session)
    plain_id = await _order(db_session, user_id=user_id, status="paid", paid=True)
    plain = await db_session.get(Order, plain_id)
    assert plain is not None
    assert await bind_attribution(db_session, order=plain) is False

    code_id, _ = await _seed_partner_and_code(db_session)
    moment = now()
    guest = Order(
        id=new_id(),
        guest_email=f"g-{new_id()}@example.test",
        status="paid",
        currency="UZS",
        total_usd=Decimal("1"),
        total_charged=Decimal("12000"),
        purpose="catalog",
        expires_at=moment + timedelta(days=1),
        paid_at=moment,
        affiliate_code_id=code_id,
    )
    db_session.add(guest)
    await db_session.flush()
    assert await bind_attribution(db_session, order=guest) is False
