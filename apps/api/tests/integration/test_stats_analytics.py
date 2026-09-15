"""Integration tests for analytics aggregation services."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

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
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.payments.models import Payment
from yupay.modules.stats import service as svc
from yupay.modules.stats.schemas import AnalyticsRange
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
