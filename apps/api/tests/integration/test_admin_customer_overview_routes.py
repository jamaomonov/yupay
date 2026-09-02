"""Integration tests for the Customer 360 overview endpoint.

Covers:
- auth gate (401/403)
- 404 for unknown user
- happy path: user + recent_orders + recent_payments + open_fulfillment_tasks +
  wallet_balances + stats + risk_flags
- bounded SQL query count (no N+1 across the composed sources)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.payments.models import Payment
from yupay.modules.users.models import TelegramLink, User
from yupay.modules.wallet.models import WalletAccount

pytestmark = pytest.mark.asyncio


BOT_TOKEN = "123456:TEST"


def _sign_init_data(fields: dict[str, str], token: str = BOT_TOKEN) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login(client: AsyncClient, tg_id: int = 100500) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "Admin"}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    body: dict[str, str] = r.json()
    return body["access_token"]


async def _grant_admin(db_session: AsyncSession, tg_id: int) -> None:
    from sqlalchemy import select

    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db_session.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db_session.commit()


@pytest.fixture
async def _admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    token = await _login(integration_client, tg_id=42)
    await _grant_admin(db_session, tg_id=42)
    return {"Authorization": f"Bearer {token}"}


# ---------- fixture builders ----------


async def _make_user(
    db: AsyncSession,
    *,
    email: str | None = None,
    display_name: str | None = None,
    tg_user_id: int | None = None,
    tg_username: str | None = None,
    created_days_ago: int = 30,
) -> str:
    user_id = str(uuid.uuid4())
    created = datetime.now(UTC) - timedelta(days=created_days_ago)
    db.add(
        User(
            id=user_id,
            email=email,
            display_name=display_name,
            locale="ru",
            display_currency="USD",
            roles=[],
            created_at=created,
            updated_at=created,
        )
    )
    await db.flush()
    if tg_user_id is not None:
        db.add(
            TelegramLink(
                id=str(uuid.uuid4()),
                user_id=user_id,
                tg_user_id=tg_user_id,
                tg_username=tg_username,
            )
        )
    await db.commit()
    return user_id


async def _make_order(
    db: AsyncSession,
    *,
    user_id: str,
    status: str = "pending_payment",
    total_usd: str = "10.00",
) -> str:
    order_id = str(uuid.uuid4())
    db.add(
        Order(
            id=order_id,
            user_id=user_id,
            guest_email=None,
            status=status,
            currency="USD",
            total_usd=Decimal(total_usd),
            total_charged=Decimal(total_usd),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db.commit()
    return order_id


async def _make_payment(
    db: AsyncSession,
    *,
    order_id: str,
    status: str = "pending",
    amount: str = "10.00",
) -> str:
    payment_id = str(uuid.uuid4())
    db.add(
        Payment(
            id=payment_id,
            order_id=order_id,
            provider="stub",
            status=status,
            amount=Decimal(amount),
            currency="USD",
        )
    )
    await db.commit()
    return payment_id


async def _make_order_item(
    db: AsyncSession,
    *,
    order_id: str,
    unit_price_usd: str = "1.00",
    rate_multiplier: str | None = None,
    pin_rate: bool = False,
) -> str:
    """Build the full catalog chain needed to satisfy the order_items FK constraints.

    Passing ``rate_multiplier`` makes the SKU variable-amount (a Steam-style
    top-up), which also requires the min/max bounds —
    ``ck_skus_variable_amount_complete`` rejects a partial set. ``pin_rate``
    additionally freezes that multiplier onto the line the way checkout does
    (ADR-0051); leaving it off models a row written before that column existed.
    """
    slug = uuid.uuid4().hex[:8]
    cat_id = str(uuid.uuid4())
    brand_id = str(uuid.uuid4())
    product_id = str(uuid.uuid4())
    sku_id = str(uuid.uuid4())
    item_id = str(uuid.uuid4())
    db.add(Category(id=cat_id, slug=f"c-{slug}"))
    await db.flush()
    db.add(Brand(id=brand_id, slug=f"b-{slug}", category_id=cat_id))
    await db.flush()
    db.add(Product(id=product_id, slug=f"p-{slug}", brand_id=brand_id, kind="top_up"))
    await db.flush()
    variable_kwargs: dict[str, object] = {}
    if rate_multiplier is not None:
        variable_kwargs = {
            "variable_amount": True,
            "min_amount_usd": Decimal("1.00"),
            "max_amount_usd": Decimal("300.00"),
            "rate_multiplier": Decimal(rate_multiplier),
        }
    db.add(
        Sku(
            id=sku_id,
            product_id=product_id,
            sku_code=f"sku-{slug}",
            price_usd=Decimal("1.00"),
            **variable_kwargs,  # type: ignore[arg-type]
        )
    )
    await db.flush()
    db.add(
        OrderItem(
            id=item_id,
            order_id=order_id,
            sku_id=sku_id,
            qty=1,
            unit_price_usd=Decimal(unit_price_usd),
            rate_multiplier=(
                Decimal(rate_multiplier) if pin_rate and rate_multiplier is not None else None
            ),
        )
    )
    await db.commit()
    return item_id


async def _make_fulfillment_task(
    db: AsyncSession, *, order_id: str, status: str = "pending", supplier: str = "manual"
) -> str:
    item_id = await _make_order_item(db, order_id=order_id)
    task_id = str(uuid.uuid4())
    db.add(
        FulfillmentTask(
            id=task_id,
            order_id=order_id,
            order_item_id=item_id,
            supplier=supplier,
            status=status,
        )
    )
    await db.commit()
    return task_id


async def _make_wallet_account(
    db: AsyncSession,
    *,
    user_id: str,
    kind: str = "user_wallet",
    currency: str = "USD",
) -> str:
    account_id = str(uuid.uuid4())
    db.add(
        WalletAccount(
            id=account_id,
            owner_type="user",
            owner_id=user_id,
            kind=kind,
            currency=currency,
            status="active",
        )
    )
    await db.commit()
    return account_id


# ---------- auth gate ----------


async def test_overview_requires_token(integration_client: AsyncClient) -> None:
    user_id = str(uuid.uuid4())
    r = await integration_client.get(f"/api/v1/admin/customers/{user_id}/overview")
    assert r.status_code == 401


async def test_overview_forbids_non_admin(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _login(integration_client, tg_id=200)
    target_id = await _make_user(db_session, email="t@example.com")
    r = await integration_client.get(
        f"/api/v1/admin/customers/{target_id}/overview",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


# ---------- 404 ----------


async def test_overview_404_for_unknown_user(
    integration_client: AsyncClient, _admin_headers: dict[str, str]
) -> None:
    r = await integration_client.get(
        f"/api/v1/admin/customers/{uuid.uuid4()}/overview", headers=_admin_headers
    )
    assert r.status_code == 404


# ---------- happy path ----------


async def test_overview_returns_full_structure(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    user_id = await _make_user(
        db_session,
        email="alice@example.com",
        display_name="Alice",
        tg_user_id=12345,
        tg_username="alice",
        created_days_ago=30,
    )
    o1 = await _make_order(db_session, user_id=user_id, status="delivered")
    o2 = await _make_order(db_session, user_id=user_id, status="pending_payment")
    await _make_payment(db_session, order_id=o1, status="succeeded")
    await _make_payment(db_session, order_id=o2, status="pending")
    await _make_fulfillment_task(db_session, order_id=o1, status="pending")
    await _make_wallet_account(db_session, user_id=user_id)

    r = await integration_client.get(
        f"/api/v1/admin/customers/{user_id}/overview", headers=_admin_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) >= {
        "user",
        "recent_orders",
        "recent_payments",
        "open_fulfillment_tasks",
        "wallet_balances",
        "stats",
        "risk_flags",
    }
    assert body["user"]["id"] == user_id
    assert body["user"]["email"] == "alice@example.com"
    assert len(body["recent_orders"]) == 2
    assert {o["id"] for o in body["recent_orders"]} == {o1, o2}
    assert len(body["recent_payments"]) == 2
    assert len(body["open_fulfillment_tasks"]) == 1
    assert len(body["wallet_balances"]) == 1
    assert body["wallet_balances"][0]["kind"] == "user_wallet"
    assert isinstance(body["risk_flags"], list)
    assert body["stats"]["total_orders"] == 2


async def test_overview_excludes_other_users_data(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    target_id = await _make_user(db_session, email="target@example.com")
    other_id = await _make_user(db_session, email="other@example.com")
    target_order = await _make_order(db_session, user_id=target_id)
    other_order = await _make_order(db_session, user_id=other_id)
    await _make_payment(db_session, order_id=other_order)

    r = await integration_client.get(
        f"/api/v1/admin/customers/{target_id}/overview", headers=_admin_headers
    )
    assert r.status_code == 200
    body = r.json()
    order_ids = {o["id"] for o in body["recent_orders"]}
    assert order_ids == {target_order}
    assert other_order not in order_ids
    assert body["recent_payments"] == []


async def test_overview_empty_user_has_zero_aggregates(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    user_id = await _make_user(db_session, email="empty@example.com")
    r = await integration_client.get(
        f"/api/v1/admin/customers/{user_id}/overview", headers=_admin_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recent_orders"] == []
    assert body["recent_payments"] == []
    assert body["open_fulfillment_tasks"] == []
    assert body["wallet_balances"] == []
    assert body["stats"]["total_orders"] == 0


async def test_spend_counts_the_steam_markup_not_the_face_value(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    """A $10 Steam top-up costs the buyer more than $10.

    `Order.total_usd` holds the credit the customer picked; the money they
    actually paid is that times the SKU's `rate_multiplier` (the markup is the
    whole business model). Summing the face value reported a customer who
    spent ~$11.30 as having spent $10 — see `orders.revenue`.
    """
    user_id = await _make_user(db_session, email="steam-buyer@example.com")
    order_id = await _make_order(db_session, user_id=user_id, status="delivered")
    await _make_order_item(
        db_session, order_id=order_id, unit_price_usd="10.00", rate_multiplier="1.1300"
    )

    r = await integration_client.get(
        f"/api/v1/admin/customers/{user_id}/overview", headers=_admin_headers
    )
    assert r.status_code == 200, r.text
    stats = r.json()["stats"]
    assert stats["total_orders"] == 1
    assert Decimal(stats["total_spent_usd"]) == Decimal("11.30")


async def test_spend_uses_the_rate_frozen_on_the_line_not_todays_sku(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    """ADR-0051: raising the Steam margin must not revalue past orders.

    The line was sold at 1.13. The SKU now says 1.50. Reported spend has to
    stay at what was actually charged.
    """
    user_id = await _make_user(db_session, email="pinned-buyer@example.com")
    order_id = await _make_order(db_session, user_id=user_id, status="delivered")
    item_id = await _make_order_item(
        db_session,
        order_id=order_id,
        unit_price_usd="10.00",
        rate_multiplier="1.1300",
        pin_rate=True,
    )
    # The admin edits the margin after the sale.
    sku_id = (
        await db_session.execute(select(OrderItem.sku_id).where(OrderItem.id == item_id))
    ).scalar_one()
    await db_session.execute(
        update(Sku).where(Sku.id == sku_id).values(rate_multiplier=Decimal("1.5000"))
    )
    await db_session.commit()

    r = await integration_client.get(
        f"/api/v1/admin/customers/{user_id}/overview", headers=_admin_headers
    )
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["stats"]["total_spent_usd"]) == Decimal("11.30")


async def test_spend_leaves_a_fixed_price_order_alone(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    """The correction must not touch SKUs that were already priced at retail."""
    user_id = await _make_user(db_session, email="voucher-buyer@example.com")
    order_id = await _make_order(db_session, user_id=user_id, status="delivered", total_usd="25.00")
    await _make_order_item(db_session, order_id=order_id, unit_price_usd="25.00")

    r = await integration_client.get(
        f"/api/v1/admin/customers/{user_id}/overview", headers=_admin_headers
    )
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["stats"]["total_spent_usd"]) == Decimal("25.00")


# ---------- risk flags ----------


async def test_risk_flag_no_email(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    user_id = await _make_user(db_session, email=None, tg_user_id=777)
    r = await integration_client.get(
        f"/api/v1/admin/customers/{user_id}/overview", headers=_admin_headers
    )
    assert r.status_code == 200
    assert "no_email" in r.json()["risk_flags"]


async def test_risk_flag_no_telegram(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    user_id = await _make_user(db_session, email="t@example.com", tg_user_id=None)
    r = await integration_client.get(
        f"/api/v1/admin/customers/{user_id}/overview", headers=_admin_headers
    )
    assert r.status_code == 200
    assert "no_telegram" in r.json()["risk_flags"]


async def test_risk_flag_fresh_account(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    user_id = await _make_user(
        db_session, email="new@example.com", tg_user_id=999, created_days_ago=2
    )
    r = await integration_client.get(
        f"/api/v1/admin/customers/{user_id}/overview", headers=_admin_headers
    )
    assert r.status_code == 200
    assert "fresh_account" in r.json()["risk_flags"]


async def test_risk_flag_many_failed_payments(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    user_id = await _make_user(
        db_session, email="problem@example.com", tg_user_id=1000, created_days_ago=60
    )
    for _ in range(4):
        order_id = await _make_order(db_session, user_id=user_id, status="cancelled")
        await _make_payment(db_session, order_id=order_id, status="failed")
    r = await integration_client.get(
        f"/api/v1/admin/customers/{user_id}/overview", headers=_admin_headers
    )
    assert r.status_code == 200
    assert "many_failed_payments" in r.json()["risk_flags"]


# ---------- bounded SQL queries (no N+1) ----------


async def test_overview_sql_query_count_is_bounded(
    integration_client: AsyncClient,
    db_engine,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    """Adding wallet accounts must not multiply the query count linearly."""
    user_id = await _make_user(
        db_session, email="counter@example.com", tg_user_id=2000, created_days_ago=10
    )
    # Five distinct (kind, currency) accounts — unique constraint forbids duplicates.
    combos = [
        ("user_wallet", "USD"),
        ("user_wallet", "RUB"),
        ("user_wallet", "UZS"),
        ("user_cashback", "USD"),
        ("user_promo_credit", "USD"),
    ]
    for kind, currency in combos:
        await _make_wallet_account(db_session, user_id=user_id, kind=kind, currency=currency)

    counts: list[int] = []

    def _bump(*_args: object, **_kwargs: object) -> None:
        counts.append(1)

    sync_engine = db_engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _bump)
    try:
        r = await integration_client.get(
            f"/api/v1/admin/customers/{user_id}/overview", headers=_admin_headers
        )
        assert r.status_code == 200, r.text
    finally:
        event.remove(sync_engine, "before_cursor_execute", _bump)

    # A composition of <user, orders, payments, tasks, wallet-accounts, balances,
    # aggregate-stats, failed-payment-count> requires roughly that many queries; we
    # allow a generous ceiling but anything linear in account-count would blow this.
    # +2 over the original 12: ``User.steam_link`` is ``lazy="selectin"`` like the
    # telegram link beside it, a BOUNDED +1 per User load (two loads here), not an
    # N+1 — which is the only thing this ceiling exists to catch.
    assert len(counts) <= 14, f"expected ≤14 queries, got {len(counts)}"


# Reference Engine import keeps mypy from pruning the import.
_ = Engine
