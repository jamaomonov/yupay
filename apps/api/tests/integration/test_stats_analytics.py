"""Integration tests for analytics aggregation services."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
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
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.merchants.models import Merchant
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.payments.models import Payment
from yupay.modules.stats import service as svc
from yupay.modules.stats.schemas import AnalyticsChannel, AnalyticsRange
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio


async def _seed_catalog(db: AsyncSession) -> tuple[str, str]:
    cat = Category(id=new_id(), slug="games", sort_order=0, active=True)
    cat.translations = [CategoryTranslation(locale="ru", name="Игры")]
    db.add(cat)
    await db.flush()
    brand = Brand(id=new_id(), slug="pubg", category_id=cat.id, sort_order=0, active=True)
    brand.translations = [BrandTranslation(locale="ru", name="PUBG")]
    db.add(brand)
    await db.flush()
    product = Product(id=new_id(), slug="pubg-uc", brand_id=brand.id, kind="top_up")
    product.translations = [ProductTranslation(locale="ru", name="PUBG UC")]
    db.add(product)
    await db.flush()
    sku_with = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="pubg-60",
        price_usd=Decimal("1.00"),
        cost_usdt=Decimal("0.60"),
    )
    sku_no = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="pubg-300",
        price_usd=Decimal("5.00"),
        cost_usdt=None,
    )
    db.add_all([sku_with, sku_no])
    await db.flush()
    return sku_with.id, sku_no.id


async def _paid_order(
    db: AsyncSession, *, sku_id: str, qty: int, unit: str, paid_ago_days: int
) -> None:
    moment = now() - timedelta(days=paid_ago_days)
    order = Order(
        id=new_id(),
        user_id=None,
        guest_email="g@example.com",
        status="delivered",
        currency="USD",
        total_usd=Decimal(unit) * qty,
        total_charged=Decimal(unit) * qty,
        created_at=moment,
        paid_at=moment,
        delivered_at=moment,
        expires_at=moment + timedelta(hours=1),
    )
    db.add(order)
    await db.flush()
    db.add(
        OrderItem(
            id=new_id(),
            order_id=order.id,
            sku_id=sku_id,
            qty=qty,
            unit_price_usd=Decimal(unit),
        )
    )
    await db.flush()


async def test_business_summary_and_margin_approx(db_session: AsyncSession) -> None:
    sku_with, sku_no = await _seed_catalog(db_session)
    # 2 units of the cost-known SKU @1.00 (cost 0.60) + 1 unit of cost-unknown @5.00
    await _paid_order(db_session, sku_id=sku_with, qty=2, unit="1.00", paid_ago_days=1)
    await _paid_order(db_session, sku_id=sku_no, qty=1, unit="5.00", paid_ago_days=2)

    out = await svc.build_business_analytics(db_session, r=AnalyticsRange.D30)

    assert out.summary.orders == 2
    assert out.summary.gmv_usd == Decimal("7.00")  # 2.00 + 5.00
    # margin only over cost-known revenue: revenue 2.00, cost 1.20 → margin 0.80
    assert out.summary.gross_margin_usd == Decimal("0.80")
    assert out.summary.margin_approx is True
    assert out.summary.margin_unknown_units == 1
    # AOV = gmv / paid orders
    assert out.summary.aov_usd == Decimal("3.50")
    brands = {b.slug: b for b in out.top_brands}
    assert brands["pubg"].units == 3
    assert brands["pubg"].revenue_usd == Decimal("7.00")
    # brand margin counts only the known-cost SKU: 2 units * (1.00 - 0.60) = 0.80
    assert brands["pubg"].margin_usd == Decimal("0.80")


async def _seed_steam_sku(db: AsyncSession) -> str:
    """A variable-amount (Steam) SKU: ``cost_usdt`` is NULL (dynamic cost);
    margin is instead driven by ``rate_multiplier`` — see
    ``docs/superpowers/specs/2026-08-04-steam-margin-analytics-design.md``."""
    cat = Category(id=new_id(), slug="wallets", sort_order=1, active=True)
    cat.translations = [CategoryTranslation(locale="ru", name="Кошельки")]
    db.add(cat)
    await db.flush()
    brand = Brand(id=new_id(), slug="steam", category_id=cat.id, sort_order=0, active=True)
    brand.translations = [BrandTranslation(locale="ru", name="Steam")]
    db.add(brand)
    await db.flush()
    product = Product(id=new_id(), slug="steam-wallet", brand_id=brand.id, kind="top_up")
    product.translations = [ProductTranslation(locale="ru", name="Steam Wallet")]
    db.add(product)
    await db.flush()
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="steam-wallet-variable",
        price_usd=Decimal("1.00"),
        cost_usdt=None,
        variable_amount=True,
        min_amount_usd=Decimal("1.00"),
        max_amount_usd=Decimal("300.00"),
        rate_multiplier=Decimal("1.20"),
    )
    db.add(sku)
    await db.flush()
    return sku.id


async def test_business_summary_steam_margin(db_session: AsyncSession) -> None:
    """Steam (variable-amount) margin is priced off ``rate_multiplier``, not
    ``cost_usdt`` (NULL for Steam) — regression for Steam always reporting
    zero margin and being swallowed into ``margin_unknown_units``."""
    steam_sku = await _seed_steam_sku(db_session)
    await _paid_order(db_session, sku_id=steam_sku, qty=1, unit="10.00", paid_ago_days=1)

    out = await svc.build_business_analytics(db_session, r=AnalyticsRange.D30)

    # margin = qty * unit_price_usd * (rate_multiplier - 1) = 1 * 10 * 0.20 = 2.00
    assert out.summary.gross_margin_usd == Decimal("2.00")
    assert out.summary.margin_unknown_units == 0

    brands = {b.slug: b for b in out.top_brands}
    assert brands["steam"].margin_usd == Decimal("2.00")
    skus = {s.sku_code: s for s in out.top_skus}
    assert skus["steam-wallet-variable"].margin_usd == Decimal("2.00")


async def test_business_summary_mixed_fixed_unknown_and_steam_margin(
    db_session: AsyncSession,
) -> None:
    """All three margin buckets in the same window: fixed-known-cost, a
    fixed SKU with no cost (still counted in ``margin_unknown_units``), and
    a variable/Steam SKU (no longer swallowed into unknown)."""
    sku_with, sku_no = await _seed_catalog(db_session)
    steam_sku = await _seed_steam_sku(db_session)
    await _paid_order(db_session, sku_id=sku_with, qty=2, unit="1.00", paid_ago_days=1)
    await _paid_order(db_session, sku_id=sku_no, qty=1, unit="5.00", paid_ago_days=1)
    await _paid_order(db_session, sku_id=steam_sku, qty=1, unit="10.00", paid_ago_days=1)

    out = await svc.build_business_analytics(db_session, r=AnalyticsRange.D30)

    # fixed-known margin 0.80 (2 * (1.00 - 0.60)) + steam margin 2.00 = 2.80;
    # the fixed-without-cost unit stays excluded from margin, counted as unknown.
    assert out.summary.gross_margin_usd == Decimal("2.80")
    assert out.summary.margin_unknown_units == 1


async def test_range_filtering(db_session: AsyncSession) -> None:
    sku_with, _ = await _seed_catalog(db_session)
    await _paid_order(db_session, sku_id=sku_with, qty=1, unit="1.00", paid_ago_days=2)
    await _paid_order(db_session, sku_id=sku_with, qty=1, unit="1.00", paid_ago_days=40)
    out7 = await svc.build_business_analytics(db_session, r=AnalyticsRange.D7)
    out90 = await svc.build_business_analytics(db_session, r=AnalyticsRange.D90)
    assert out7.summary.orders == 1
    assert out90.summary.orders == 2


async def _order_with_status(db: AsyncSession, *, status: str, moment: datetime) -> None:
    """Minimal order row for funnel/KPI counting tests — no items needed."""
    order = Order(
        id=new_id(),
        user_id=None,
        guest_email="g@example.com",
        status=status,
        currency="USD",
        total_usd=Decimal("1.00"),
        total_charged=Decimal("1.00"),
        created_at=moment,
        paid_at=None if status == "pending_payment" else moment,
        delivered_at=moment if status == "delivered" else None,
        expires_at=moment + timedelta(hours=1),
    )
    db.add(order)
    await db.flush()


async def test_funnel_paid_bucket_includes_progressed_orders(db_session: AsyncSession) -> None:
    """Orders that moved past ``paid`` (fulfilling/delivered) must still count
    in the funnel's ``paid`` bucket, and the KPI card's ``paid_orders`` must
    match the funnel exactly — regression for "Оплачено 0, Доставлено 6,
    Конверсия 100%" (delivered > paid is impossible)."""
    moment = now()
    await _order_with_status(db_session, status="pending_payment", moment=moment)
    await _order_with_status(db_session, status="paid", moment=moment)
    await _order_with_status(db_session, status="fulfilling", moment=moment)
    await _order_with_status(db_session, status="fulfilling", moment=moment)
    for _ in range(6):
        await _order_with_status(db_session, status="delivered", moment=moment)
    await _order_with_status(db_session, status="cancelled", moment=moment)

    out = await svc.build_business_analytics(db_session, r=AnalyticsRange.D30)
    funnel = out.funnel

    assert funnel.created == 11
    assert funnel.delivered == 6
    assert funnel.paid == 1 + 2 + 6  # paid + fulfilling + delivered, cumulative
    assert funnel.delivered <= funnel.paid <= funnel.created
    assert 0.0 <= funnel.payment_conversion_pct <= 100.0
    assert funnel.payment_conversion_pct == round((1 + 2 + 6) / 11 * 100, 2)

    # KPI card and funnel must agree exactly — same underlying counts.
    assert out.summary.orders == funnel.created
    assert out.summary.paid_orders == funnel.paid
    assert out.summary.delivered_orders == funnel.delivered


async def test_funnel_conversion_guards_divide_by_zero(db_session: AsyncSession) -> None:
    out = await svc.build_business_analytics(db_session, r=AnalyticsRange.D7)
    assert out.funnel.created == 0
    assert out.funnel.paid == 0
    assert out.funnel.delivered == 0
    assert out.funnel.payment_conversion_pct == 0.0


async def _bare_order_item(db: AsyncSession, sku_id: str) -> tuple[str, str]:
    """Create a minimal order + item so fulfilment-task FKs resolve."""
    moment = now()
    order = Order(
        id=new_id(),
        user_id=None,
        guest_email="g@example.com",
        status="paid",
        currency="USD",
        total_usd=Decimal("1.00"),
        total_charged=Decimal("1.00"),
        created_at=moment,
        paid_at=moment,
        expires_at=moment + timedelta(hours=1),
    )
    db.add(order)
    await db.flush()
    item = OrderItem(
        id=new_id(), order_id=order.id, sku_id=sku_id, qty=1, unit_price_usd=Decimal("1.00")
    )
    db.add(item)
    await db.flush()
    return order.id, item.id


async def test_ops_payments_and_fulfillment(db_session: AsyncSession) -> None:
    sku_with, _ = await _seed_catalog(db_session)
    moment = now()
    order_id, _ = await _bare_order_item(db_session, sku_with)
    db_session.add_all(
        [
            Payment(
                id=new_id(),
                order_id=order_id,
                provider="octo",
                status="succeeded",
                amount=Decimal("10.00"),
                currency="USD",
                created_at=moment,
                succeeded_at=moment,
            ),
            Payment(
                id=new_id(),
                order_id=order_id,
                provider="octo",
                status="failed",
                amount=Decimal("10.00"),
                currency="USD",
                created_at=moment,
            ),
            Payment(
                id=new_id(),
                order_id=order_id,
                provider="wallet",
                status="succeeded",
                amount=Decimal("3.00"),
                currency="USD",
                created_at=moment,
                succeeded_at=moment,
            ),
        ]
    )
    g2b_order1, g2b_item1 = await _bare_order_item(db_session, sku_with)
    g2b_order2, g2b_item2 = await _bare_order_item(db_session, sku_with)
    db_session.add_all(
        [
            FulfillmentTask(
                id=new_id(),
                order_id=g2b_order1,
                order_item_id=g2b_item1,
                supplier="g2b",
                status="succeeded",
                attempts_count=1,
                created_at=moment - timedelta(seconds=30),
                succeeded_at=moment,
            ),
            FulfillmentTask(
                id=new_id(),
                order_id=g2b_order2,
                order_item_id=g2b_item2,
                supplier="g2b",
                status="failed",
                attempts_count=3,
                created_at=moment,
            ),
        ]
    )
    await db_session.flush()

    out = await svc.build_ops_analytics(db_session, r=AnalyticsRange.D30)
    octo = next(p for p in out.payments if p.provider == "octo")
    assert octo.count == 2
    assert octo.success_rate_pct == 50.0
    g2b = next(f for f in out.fulfillment if f.supplier == "g2b")
    assert g2b.total == 2
    assert g2b.success_rate_pct == 50.0
    assert g2b.avg_attempts == 2.0


# ---------- HTTP endpoints ----------

BOT_TOKEN = "123456:TEST"


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    signed = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(signed)


async def _login_admin(client: AsyncClient, db: AsyncSession, tg_id: int = 555) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "A"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200, r.text
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()
    return r.json()["access_token"]


async def test_business_endpoint(integration_client: AsyncClient, db_session: AsyncSession) -> None:
    token = await _login_admin(integration_client, db_session)
    r = await integration_client.get(
        "/api/v1/admin/stats/analytics/business?range=30d",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["range"] == "30d"
    assert "summary" in r.json()


async def test_ops_endpoint_requires_admin(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/admin/stats/analytics/ops")
    assert r.status_code in (401, 403)


async def test_invalid_range_rejected(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _login_admin(integration_client, db_session)
    r = await integration_client.get(
        "/api/v1/admin/stats/analytics/business?range=bogus",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


async def test_provider_volume_is_dollars_not_the_charged_currency(
    db_session: AsyncSession,
) -> None:
    """The column says `volume_usd` and the admin renders it with a `$`.

    `Payment.amount` is the charge in the payment's **own** currency — so'm for
    Click, Payme and Uzum, USDT for crypto — so summing it put "$35 181 403"
    on the analytics page for what was 35 million so'm, and made the providers
    incomparable with each other on top of that, because the column silently
    mixed units. The order carries the same charge already converted at its own
    frozen FX snapshot, which is what the figure has to come from.
    """
    sku_with, _ = await _seed_catalog(db_session)
    moment = now()
    order_id, _ = await _bare_order_item(db_session, sku_with)
    # A UZS payment on a $1.00 order: 12 500 so'm charged, one dollar of volume.
    db_session.add(
        Payment(
            id=new_id(),
            order_id=order_id,
            provider="payme",
            status="succeeded",
            amount=Decimal("12500.00"),
            currency="UZS",
            created_at=moment,
            succeeded_at=moment,
        )
    )
    await db_session.flush()

    out = await svc.build_ops_analytics(db_session, r=AnalyticsRange.D30)
    payme = next(p for p in out.payments if p.provider == "payme")

    assert payme.volume_usd == Decimal("1.00"), "summed the charged so'm, not the order's USD"


async def test_the_daily_series_carries_margin(db_session: AsyncSession) -> None:
    """The calendar's whole point: what each day earned, not only what it took.

    Margin lived on the summary alone, so a series row could say "$400 of
    revenue" with no way to tell a good day from one that sold at cost.
    """
    sku_with, _ = await _seed_catalog(db_session)
    order_id, _ = await _bare_order_item(db_session, sku_with)
    await db_session.flush()

    out = await svc.build_business_analytics(db_session, r=AnalyticsRange.D30)

    assert out.revenue_series, "expected the seeded paid order to appear"
    point = out.revenue_series[-1]
    assert point.margin_usd is not None
    # The seeded SKU has a known cost, so nothing that day is unpriced.
    assert point.margin_unknown_units == 0


async def test_an_explicit_window_is_honoured_at_both_ends(db_session: AsyncSession) -> None:
    """One day, one month, or an arbitrary span — the calendar asks for all three.

    A preset range is open-ended at the top, which cannot express "that
    Tuesday". The upper bound is exclusive, so two adjacent windows never
    double-count the boundary order.
    """
    sku_with, _ = await _seed_catalog(db_session)
    await _bare_order_item(db_session, sku_with)
    await db_session.flush()
    moment = now()

    inside = await svc.build_business_analytics(
        db_session, since=moment - timedelta(hours=1), until=moment + timedelta(hours=1)
    )
    before = await svc.build_business_analytics(
        db_session, since=moment - timedelta(days=3), until=moment - timedelta(days=2)
    )

    assert inside.summary.gmv_usd > 0
    assert inside.range is None, "a custom window has no preset to report"
    assert inside.since is not None
    assert inside.until is not None
    assert before.summary.gmv_usd == 0, "the upper bound was not applied"
    assert before.revenue_series == []


async def test_retail_and_b2b_are_reported_apart(db_session: AsyncSession) -> None:
    """`IS_SALE` is both channels, so every headline blended them.

    A reseller buys at a wholesale price with a thinner markup, so a good B2B
    month reads as a margin collapse once it is averaged into retail.
    """
    sku_with, _ = await _seed_catalog(db_session)
    await _bare_order_item(db_session, sku_with)
    merchant_order_id, _ = await _bare_order_item(db_session, sku_with)
    merchant = Merchant(id=new_id(), title="Reseller", status="active")
    db_session.add(merchant)
    await db_session.flush()
    order = (
        await db_session.execute(select(Order).where(Order.id == merchant_order_id))
    ).scalar_one()
    # `ck_orders_actor_exclusive`: an order has exactly one actor arm, so a
    # merchant order carries no guest address. The constraint caught this the
    # first time and it is right to.
    order.merchant_id = merchant.id
    order.guest_email = None
    await db_session.flush()

    out = await svc.build_business_analytics(db_session, r=AnalyticsRange.D30)

    channels = {c.channel: c for c in out.channels}
    assert channels["retail"].orders == 1
    assert channels["b2b"].orders == 1
    assert channels["retail"].gmv_usd > 0
    assert channels["b2b"].gmv_usd > 0


async def test_every_hour_is_reported_even_the_quiet_ones(db_session: AsyncSession) -> None:
    """A chart with gaps reads as missing data rather than as a quiet night."""
    sku_with, _ = await _seed_catalog(db_session)
    await _bare_order_item(db_session, sku_with)
    await db_session.flush()

    out = await svc.build_business_analytics(db_session, r=AnalyticsRange.D30)

    assert [p.hour for p in out.hourly] == list(range(24))
    assert sum(p.orders for p in out.hourly) == 1


async def test_refunds_are_reported_in_money(db_session: AsyncSession) -> None:
    """The funnel counts refunds in orders, which says nothing about the hole."""
    sku_with, _ = await _seed_catalog(db_session)
    order_id, _ = await _bare_order_item(db_session, sku_with)
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    order.status = "refunded"
    await db_session.flush()

    out = await svc.build_business_analytics(db_session, r=AnalyticsRange.D30)

    assert out.summary.refunded_usd > 0


async def test_the_previous_window_is_the_same_length(db_session: AsyncSession) -> None:
    """ "1486 orders" is neither good nor bad without the number it replaced.

    The comparison window is derived from the current one rather than
    configured, so a 30-day figure is never held up against a week.
    """
    sku_with, _ = await _seed_catalog(db_session)
    order_id, _ = await _bare_order_item(db_session, sku_with)
    moment = now()
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    # Sold during the *previous* week, not this one.
    order.paid_at = moment - timedelta(days=10)
    await db_session.flush()

    out = await svc.build_business_analytics(
        db_session, since=moment - timedelta(days=7), until=moment
    )

    assert out.summary.gmv_usd == 0, "the order is outside the current window"
    assert out.previous is not None, "and inside the one before it"
    assert out.previous.gmv_usd > 0


async def test_wallet_liability_is_reported(db_session: AsyncSession) -> None:
    """Customer money we hold is a balance, not a period figure — and it is ours
    to return, not to spend, so it belongs on the operations tab."""
    out = await svc.build_ops_analytics(db_session, r=AnalyticsRange.D30)

    # No wallets seeded here; what is pinned is that the field exists and is
    # a list rather than absent, so the admin never renders `undefined`.
    assert isinstance(out.wallet_liability, list)


async def test_the_tab_can_be_scoped_to_one_half_of_the_business(
    db_session: AsyncSession,
) -> None:
    """Retail and B2B have different economics, so a blended tab hides both.

    The comparison block is the deliberate exception: it is the thing being
    compared, so it stays whole whichever half is asked for.
    """
    sku_with, _ = await _seed_catalog(db_session)
    await _bare_order_item(db_session, sku_with)
    merchant_order_id, _ = await _bare_order_item(db_session, sku_with)
    merchant = Merchant(id=new_id(), title="Reseller", status="active")
    db_session.add(merchant)
    await db_session.flush()
    order = (
        await db_session.execute(select(Order).where(Order.id == merchant_order_id))
    ).scalar_one()
    # `ck_orders_actor_exclusive`: exactly one actor arm per order.
    order.merchant_id = merchant.id
    order.guest_email = None
    await db_session.flush()

    every = await svc.build_business_analytics(db_session, r=AnalyticsRange.D30)
    retail = await svc.build_business_analytics(
        db_session, r=AnalyticsRange.D30, channel=AnalyticsChannel.RETAIL
    )
    b2b = await svc.build_business_analytics(
        db_session, r=AnalyticsRange.D30, channel=AnalyticsChannel.B2B
    )

    assert every.summary.orders == 2
    assert retail.summary.orders == 1
    assert b2b.summary.orders == 1
    assert retail.summary.gmv_usd + b2b.summary.gmv_usd == every.summary.gmv_usd
    assert retail.channel is AnalyticsChannel.RETAIL
    # The comparison block is not scoped: it is what the scoping is compared to.
    assert {c.channel for c in retail.channels} == {c.channel for c in every.channels}


async def test_provider_volume_counts_the_markup_on_a_steam_order(
    db_session: AsyncSession,
) -> None:
    """`Order.total_usd` is the face value the customer picked, not what we took.

    A $10 Steam top-up at a 1.13 multiplier is charged ~$11.30. Reporting the
    provider's volume from `total_usd` drops the markup — which is the whole
    margin the business runs on — so the figure is summed from `charged_usd`.
    """
    _sku_with, _ = await _seed_catalog(db_session)
    variable = Sku(
        id=new_id(),
        product_id=(await db_session.execute(select(Sku.product_id).limit(1))).scalar_one(),
        sku_code="steam-10",
        price_usd=Decimal("10.00"),
        cost_usdt=None,
        variable_amount=True,
        # `ck_skus_variable_amount_complete`: a variable SKU is only complete
        # with its bounds and its multiplier.
        min_amount_usd=Decimal("1.00"),
        max_amount_usd=Decimal("500.00"),
        rate_multiplier=Decimal("1.13"),
    )
    db_session.add(variable)
    await db_session.flush()

    moment = now()
    order = Order(
        id=new_id(),
        user_id=None,
        guest_email="g@example.com",
        status="delivered",
        currency="UZS",
        total_usd=Decimal("10.00"),
        total_charged=Decimal("134380.00"),
        created_at=moment,
        paid_at=moment,
        expires_at=moment + timedelta(hours=1),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        OrderItem(
            id=new_id(),
            order_id=order.id,
            sku_id=variable.id,
            qty=1,
            unit_price_usd=Decimal("10.00"),
            rate_multiplier=Decimal("1.13"),
        )
    )
    db_session.add(
        Payment(
            id=new_id(),
            order_id=order.id,
            provider="click",
            status="succeeded",
            amount=Decimal("134380.00"),
            currency="UZS",
            created_at=moment,
            succeeded_at=moment,
        )
    )
    await db_session.flush()

    out = await svc.build_ops_analytics(db_session, r=AnalyticsRange.D30)

    click = next(p for p in out.payments if p.provider == "click")
    assert click.volume_usd == Decimal("11.30"), "the markup is ours and belongs in the volume"


async def test_a_day_cell_and_the_day_behind_it_are_the_same_day(
    db_session: AsyncSession,
) -> None:
    """The calendar's cell and its click-through must cover one window.

    `date_trunc('day', <timestamptz>)` cuts in the *session* timezone — UTC on
    prod — while the calendar means the day an operator lives in, five hours
    east. Observed: a cell read $674.43 for 6 September and opening it showed
    $100.31, because the cell was a UTC day and the click asked for a Tashkent
    one. Nothing on screen could tell you which you were reading.

    Pinned with a sale at 21:00 Tashkent, which is 16:00 UTC the same day, and
    one at 02:00 Tashkent, which is 21:00 UTC the day *before*. Bucketed in UTC
    the two land on different dates; bucketed locally they land on one.
    """
    sku_with, _ = await _seed_catalog(db_session)
    local = ZoneInfo("Asia/Tashkent")
    evening = datetime(2026, 9, 6, 21, 0, tzinfo=local)
    small_hours = datetime(2026, 9, 6, 2, 0, tzinfo=local)
    for moment in (evening, small_hours):
        order = Order(
            id=new_id(),
            user_id=None,
            guest_email="g@example.com",
            status="delivered",
            currency="USD",
            total_usd=Decimal("1.00"),
            total_charged=Decimal("1.00"),
            created_at=moment,
            paid_at=moment,
            expires_at=moment + timedelta(hours=1),
        )
        db_session.add(order)
        await db_session.flush()
        db_session.add(
            OrderItem(
                id=new_id(),
                order_id=order.id,
                sku_id=sku_with,
                qty=1,
                unit_price_usd=Decimal("1.00"),
            )
        )
    await db_session.flush()

    # Exactly the window the calendar sends when its 6 September cell is
    # clicked: local midnight to local midnight, `until` exclusive.
    out = await svc.build_business_analytics(
        db_session,
        since=datetime(2026, 9, 6, tzinfo=local),
        until=datetime(2026, 9, 7, tzinfo=local),
    )

    assert [p.date.isoformat() for p in out.revenue_series] == ["2026-09-06"], (
        "one local day is one bucket, not two"
    )
    point = out.revenue_series[0]
    assert point.orders == 2
    # And the cell agrees with the headline it opens into.
    assert point.revenue_usd == out.summary.gmv_usd
