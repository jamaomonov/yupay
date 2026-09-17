"""Integration tests for the inventory + sourcing skeleton.

Covers:
- bulk_upload happy path + dedup detection
- counts endpoint reflects state
- reserve_and_issue atomically pulls one code; admin listing shows cleartext
- void_for_order_item flips state
- sourcing default (no rule) = inventory-first with mock fallback
- sourcing force_supplier overrides stock — even with codes available
- sourcing force_inventory + no stock → task fails
- Admin upsert / get-decision / delete-rule
- 403 for non-admin
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.errors import ValidationError
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
from yupay.modules.inventory import service as inv_svc
from yupay.modules.inventory.crypto import code_hash, decrypt
from yupay.modules.inventory.models import InventoryCode
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.users.models import TelegramLink, User


async def _make_order_item(db: AsyncSession, *, sku_id: str, email: str) -> str:
    """Service-level helper: insert a minimal order + order_item satisfying FKs."""
    order = Order(
        id=new_id(),
        user_id=None,
        guest_email=email,
        status="paid",
        currency="USD",
        total_usd=Decimal("1"),
        total_charged=Decimal("1"),
        expires_at=__import__("datetime").datetime.fromtimestamp(
            time.time() + 3600,
            tz=__import__("datetime").timezone.utc,
        ),
    )
    item = OrderItem(
        id=new_id(),
        order_id=order.id,
        sku_id=sku_id,
        qty=1,
        unit_price_usd=Decimal("1"),
    )
    db.add_all([order, item])
    await db.commit()
    return item.id


pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login_user(client: AsyncClient, tg_id: int) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "U"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _grant_admin(db: AsyncSession, tg_id: int) -> str:
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()
    return user_id


@pytest.fixture
async def _seed_sku(db_session: AsyncSession) -> str:
    category = Category(
        id=new_id(),
        slug="vouchers",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Ваучеры")],
    )
    brand = Brand(
        id=new_id(),
        slug="netflix",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Netflix")],
    )
    product = Product(
        id=new_id(),
        slug="netflix-gift",
        brand_id=brand.id,
        kind="voucher",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Gift card")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="netflix-10-us",
        denomination="10",
        region="US",
        price_usd=Decimal("1.00"),
        sort_order=10,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    return sku.id


async def _pay_order(client: AsyncClient, *, token: str, sku_id: str, key_suffix: str) -> str:
    """Create + pay an order; returns order_id (status=delivered or failed after fulfilment)."""
    create = await client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": f"inv-test-{key_suffix}",
        },
        json={
            "currency": "USD",
            "items": [{"sku_id": sku_id, "qty": 1, "fulfillment_data": {}}],
        },
    )
    assert create.status_code == 201, create.text
    order_id = create.json()["id"]
    intent = await client.post(
        "/api/v1/payments/intents",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "ik-inventory-sourcing-routes-01-padpadpad",
        },
        json={"order_id": order_id, "provider": "mock"},
    )
    external_id = intent.json()["external_id"]
    wh = await client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {
                "event_id": f"evt_inv_{key_suffix}",
                "payment_id": external_id,
                "outcome": "succeeded",
            }
        ),
        headers={"content-type": "application/json"},
    )
    assert wh.status_code == 200, wh.text
    return order_id


# ---------- inventory ----------


async def test_bulk_upload_happy_path_and_dedup(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    admin = await _login_user(integration_client, tg_id=301)
    await _grant_admin(db_session, tg_id=301)
    headers = {"Authorization": f"Bearer {admin}"}

    r = await integration_client.post(
        "/api/v1/admin/inventory/bulk-upload",
        headers=headers,
        json={
            "sku_id": _seed_sku,
            "codes": ["AAA-001", "AAA-002", "AAA-001", "AAA-003"],  # third is a dupe
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 4
    assert body["succeeded"] == 3
    assert body["duplicates"] == 1

    # Re-uploading "AAA-001" later → duplicate against persisted hash.
    again = await integration_client.post(
        "/api/v1/admin/inventory/bulk-upload",
        headers=headers,
        json={"sku_id": _seed_sku, "codes": ["AAA-001", "AAA-999"]},
    )
    assert again.status_code == 200
    assert again.json()["succeeded"] == 1
    assert again.json()["duplicates"] == 1

    counts = await integration_client.get(
        f"/api/v1/admin/inventory/sku/{_seed_sku}", headers=headers
    )
    assert counts.status_code == 200
    cb = counts.json()
    assert cb["available"] == 4
    assert cb["reserved"] == 0
    assert cb["issued"] == 0


async def test_admin_codes_listing_shows_cleartext(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    admin = await _login_user(integration_client, tg_id=302)
    await _grant_admin(db_session, tg_id=302)
    headers = {"Authorization": f"Bearer {admin}"}
    await integration_client.post(
        "/api/v1/admin/inventory/bulk-upload",
        headers=headers,
        json={"sku_id": _seed_sku, "codes": ["LIST-001", "LIST-002"]},
    )
    r = await integration_client.get(
        f"/api/v1/admin/inventory/codes?sku_id={_seed_sku}", headers=headers
    )
    assert r.status_code == 200
    codes = sorted([row["code"] for row in r.json()["items"]])
    assert codes == ["LIST-001", "LIST-002"]


async def test_reserve_and_issue_at_service_layer(db_session: AsyncSession, _seed_sku: str) -> None:
    await inv_svc.bulk_upload(
        db_session,
        sku_id=_seed_sku,
        codes=["SVC-001", "SVC-002"],
        uploaded_by="test",
    )
    item_id = await _make_order_item(db_session, sku_id=_seed_sku, email="a@y.io")
    issued = await inv_svc.reserve_and_issue(db_session, sku_id=_seed_sku, order_item_id=item_id)
    assert issued.code in ("SVC-001", "SVC-002")

    # Replay returns the same row, not a second one.
    again = await inv_svc.reserve_and_issue(db_session, sku_id=_seed_sku, order_item_id=item_id)
    assert again.inventory_code_id == issued.inventory_code_id


async def test_no_stock_raises(db_session: AsyncSession, _seed_sku: str) -> None:
    item_id = await _make_order_item(db_session, sku_id=_seed_sku, email="b@y.io")
    with pytest.raises(inv_svc.NoStockError):
        await inv_svc.reserve_and_issue(db_session, sku_id=_seed_sku, order_item_id=item_id)


async def test_non_admin_forbidden(integration_client: AsyncClient, _seed_sku: str) -> None:
    user = await _login_user(integration_client, tg_id=303)
    r = await integration_client.post(
        "/api/v1/admin/inventory/bulk-upload",
        headers={"Authorization": f"Bearer {user}"},
        json={"sku_id": _seed_sku, "codes": ["X"]},
    )
    assert r.status_code == 403


# ---------- sourcing rules ----------


async def test_default_decision_is_auto(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    admin = await _login_user(integration_client, tg_id=311)
    await _grant_admin(db_session, tg_id=311)
    r = await integration_client.get(
        f"/api/v1/admin/sourcing/rules/{_seed_sku}",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["primary"] == "inventory"
    assert body["fallback"] == "supplier:mock"
    assert body["strict"] is False
    assert body["rule_present"] is False


async def test_upsert_and_delete_rule(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    admin = await _login_user(integration_client, tg_id=312)
    await _grant_admin(db_session, tg_id=312)
    headers = {"Authorization": f"Bearer {admin}"}

    r = await integration_client.put(
        f"/api/v1/admin/sourcing/rules/{_seed_sku}",
        headers=headers,
        json={"mode": "force_supplier", "supplier_slug": "mock"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "force_supplier"
    assert r.json()["supplier_slug"] == "mock"

    decision = await integration_client.get(
        f"/api/v1/admin/sourcing/rules/{_seed_sku}", headers=headers
    )
    assert decision.json()["primary"] == "supplier:mock"
    assert decision.json()["strict"] is True

    deleted = await integration_client.delete(
        f"/api/v1/admin/sourcing/rules/{_seed_sku}", headers=headers
    )
    assert deleted.status_code == 204

    after = await integration_client.get(
        f"/api/v1/admin/sourcing/rules/{_seed_sku}", headers=headers
    )
    assert after.json()["primary"] == "inventory"


async def test_upsert_rule_idempotency_key_replays_cached_response(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    """A repeated ``PUT`` with the same ``Idempotency-Key`` replays the first
    response verbatim instead of re-running ``set_rule``.

    We mutate the rule directly in the DB (and send a *different* request
    body) between the two calls — if the handler re-executed, the second
    response and the DB row would both reflect the mutation. They don't.
    """
    from yupay.modules.sourcing.models import SkuSourcingRule

    admin = await _login_user(integration_client, tg_id=314)
    await _grant_admin(db_session, tg_id=314)
    headers = {
        "Authorization": f"Bearer {admin}",
        "Idempotency-Key": "sourcing-upsert-replay-0001",
    }

    first = await integration_client.put(
        f"/api/v1/admin/sourcing/rules/{_seed_sku}",
        headers=headers,
        json={"mode": "force_supplier", "supplier_slug": "mock"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["mode"] == "force_supplier"

    # Mutate the row out from under the handler so a live re-execution would
    # observably differ from the first response.
    await db_session.execute(
        update(SkuSourcingRule)
        .where(SkuSourcingRule.sku_id == _seed_sku)
        .values(mode="manual", supplier_slug=None)
    )
    await db_session.commit()

    replay = await integration_client.put(
        f"/api/v1/admin/sourcing/rules/{_seed_sku}",
        headers=headers,
        json={"mode": "manual"},  # different body — the replay must ignore it
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()

    # The direct mutation above is still in place — the replay never called
    # ``set_rule`` a second time.
    row = (
        await db_session.execute(select(SkuSourcingRule).where(SkuSourcingRule.sku_id == _seed_sku))
    ).scalar_one()
    assert row.mode == "manual"
    assert row.supplier_slug is None


async def test_force_supplier_validation_requires_slug(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    admin = await _login_user(integration_client, tg_id=313)
    await _grant_admin(db_session, tg_id=313)
    r = await integration_client.put(
        f"/api/v1/admin/sourcing/rules/{_seed_sku}",
        headers={"Authorization": f"Bearer {admin}"},
        json={"mode": "force_supplier"},
    )
    assert r.status_code in (422,)  # core ValidationError


# ---------- end-to-end through fulfilment ----------


async def test_inventory_serves_paid_order(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    """With stock + auto sourcing, the paid order is fulfilled from inventory."""
    admin = await _login_user(integration_client, tg_id=321)
    await _grant_admin(db_session, tg_id=321)
    await integration_client.post(
        "/api/v1/admin/inventory/bulk-upload",
        headers={"Authorization": f"Bearer {admin}"},
        json={"sku_id": _seed_sku, "codes": ["STOCK-AAA-001"]},
    )

    customer = await _login_user(integration_client, tg_id=322)
    order_id = await _pay_order(
        integration_client, token=customer, sku_id=_seed_sku, key_suffix="stock-aa"
    )

    detail = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {customer}"},
    )
    assert detail.json()["status"] == "delivered"

    deliveries = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries",
        headers={"Authorization": f"Bearer {customer}"},
    )
    items = deliveries.json()["items"]
    assert len(items) == 1
    assert items[0]["artifact_kind"] == "voucher_code"
    assert items[0]["artifact"]["code"] == "STOCK-AAA-001"
    # source is an internal audit field stripped by the buyer-facing artifact
    # allow-list (fulfillment.service.BUYER_SAFE_ARTIFACT_KEYS).
    assert "source" not in items[0]["artifact"]


async def test_auto_falls_back_to_supplier_when_no_stock(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    customer = await _login_user(integration_client, tg_id=331)
    order_id = await _pay_order(
        integration_client, token=customer, sku_id=_seed_sku, key_suffix="auto-fb"
    )
    detail = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {customer}"},
    )
    assert detail.json()["status"] == "delivered"
    deliveries = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries",
        headers={"Authorization": f"Bearer {customer}"},
    )
    items = deliveries.json()["items"]
    # Mock supplier delivers a "MOCK-..." code, not an inventory one.
    assert items[0]["artifact"]["code"].startswith("MOCK-")


async def test_force_supplier_overrides_stock(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    """Stock exists but admin forced supplier route — mock supplier issues the code."""
    admin = await _login_user(integration_client, tg_id=341)
    await _grant_admin(db_session, tg_id=341)
    admin_h = {"Authorization": f"Bearer {admin}"}
    await integration_client.post(
        "/api/v1/admin/inventory/bulk-upload",
        headers=admin_h,
        json={"sku_id": _seed_sku, "codes": ["FORCE-STOCK-001"]},
    )
    await integration_client.put(
        f"/api/v1/admin/sourcing/rules/{_seed_sku}",
        headers=admin_h,
        json={"mode": "force_supplier", "supplier_slug": "mock"},
    )

    customer = await _login_user(integration_client, tg_id=342)
    order_id = await _pay_order(
        integration_client, token=customer, sku_id=_seed_sku, key_suffix="force-sup"
    )
    deliveries = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries",
        headers={"Authorization": f"Bearer {customer}"},
    )
    items = deliveries.json()["items"]
    assert items[0]["artifact"]["code"].startswith("MOCK-")

    # Inventory row stayed available — not consumed.
    counts = await integration_client.get(
        f"/api/v1/admin/inventory/sku/{_seed_sku}", headers=admin_h
    )
    assert counts.json()["available"] == 1


async def test_force_inventory_with_no_stock_fails_task(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
) -> None:
    admin = await _login_user(integration_client, tg_id=351)
    await _grant_admin(db_session, tg_id=351)
    admin_h = {"Authorization": f"Bearer {admin}"}
    await integration_client.put(
        f"/api/v1/admin/sourcing/rules/{_seed_sku}",
        headers=admin_h,
        json={"mode": "force_inventory"},
    )

    customer = await _login_user(integration_client, tg_id=352)
    order_id = await _pay_order(
        integration_client, token=customer, sku_id=_seed_sku, key_suffix="force-inv"
    )
    detail = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {customer}"},
    )
    # Order didn't reach delivered — task failed for lack of stock.
    assert detail.json()["status"] != "delivered"
    # Admin sees the failing task.
    tasks = await integration_client.get(
        f"/api/v1/admin/fulfillment/tasks?order_id={order_id}", headers=admin_h
    )
    failing = [t for t in tasks.json()["items"] if t["status"] == "failed"]
    assert failing, tasks.json()


async def test_encryption_at_rest(db_session: AsyncSession, _seed_sku: str) -> None:
    """Stored ciphertext is not the plaintext; decryption round-trips."""
    await inv_svc.bulk_upload(
        db_session,
        sku_id=_seed_sku,
        codes=["SECRET-XYZ-9000"],
        uploaded_by="test",
    )
    row = (
        await db_session.execute(select(InventoryCode).where(InventoryCode.sku_id == _seed_sku))
    ).scalar_one()
    assert row.code_ciphertext != b"SECRET-XYZ-9000"
    assert row.code_hash == code_hash("SECRET-XYZ-9000")
    assert decrypt(row.code_ciphertext, row.code_nonce) == "SECRET-XYZ-9000"


# ---------- kind-aware auto defaults (sourcing.resolve_for_sku) ----------


async def _make_topup_sku(db: AsyncSession) -> str:
    category = Category(
        id=new_id(),
        slug="games-topup",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug="mlbb",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="MLBB")],
    )
    product = Product(
        id=new_id(),
        slug="mlbb-diamonds",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Diamonds")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="mlbb-100",
        denomination="100",
        region="WW",
        price_usd=Decimal("2.00"),
        sort_order=10,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    await db.commit()
    return sku.id


async def test_topup_without_mapping_routes_to_manual(db_session: AsyncSession) -> None:
    """A ``top_up`` SKU with no supplier mapping must NOT try inventory or
    mock — it goes straight to the manual admin queue."""
    from yupay.modules.sourcing import service as sourcing_svc

    sku_id = await _make_topup_sku(db_session)
    decision = await sourcing_svc.resolve_for_sku(db_session, sku_id)
    assert decision.primary == "supplier:manual"
    assert decision.fallback is None


async def test_topup_with_mapping_routes_to_supplier(db_session: AsyncSession) -> None:
    """Once a ``top_up`` SKU has an active g2b mapping, the default route is
    the supplier with a manual fallback."""
    from yupay.modules.integrations.models import SkuSupplierMapping
    from yupay.modules.sourcing import service as sourcing_svc

    sku_id = await _make_topup_sku(db_session)
    db_session.add(
        SkuSupplierMapping(
            sku_id=sku_id,
            supplier_slug="g2b",
            kind="game",
            external_product_id="mlbb",
            external_variant_id="100",
            quantity=1,
            extra={},
            is_active=True,
        )
    )
    await db_session.commit()

    decision = await sourcing_svc.resolve_for_sku(db_session, sku_id)
    assert decision.primary == "supplier:g2b"
    assert decision.fallback == "supplier:manual"
    assert decision.strict is False


async def test_auto_keeps_the_older_mapping_when_a_reserve_is_added(
    db_session: AsyncSession,
) -> None:
    """A reserve mapping must never take the route by being added.

    The older row is the incumbent: it is the one orders have been going to.
    Without an explicit order this test is a coin flip, which is exactly the
    bug — so it inserts the newcomer (gengine) mapping first in *insert* order
    but with a newer ``created_at`` than the incumbent (g2b), and asserts
    that the ``created_at`` order wins, not insertion order.

    This pairing alone cannot tell ``created_at`` ordering from alphabetical
    ordering — ``g2b`` is both the older row and the earlier slug — so the
    test below it inverts the two and is what actually falsifies a
    slug-only implementation. Both are kept: this one is the realistic
    shape, that one is the proof.

    The newcomer here is ``gengine`` rather than a reserve supplier, because a
    reserve is excluded from this choice altogether and would prove nothing
    about ordering.
    """
    from yupay.modules.integrations.models import SkuSupplierMapping
    from yupay.modules.sourcing import service as sourcing_svc

    sku_id = await _make_topup_sku(db_session)
    db_session.add_all(
        [
            SkuSupplierMapping(
                sku_id=sku_id,
                supplier_slug="gengine",
                kind="game",
                external_product_id="2",
                external_variant_id="100",
                quantity=1,
                extra={},
                is_active=True,
                created_at=datetime(2026, 9, 17, tzinfo=UTC),
            ),
            SkuSupplierMapping(
                sku_id=sku_id,
                supplier_slug="g2b",
                kind="game",
                external_product_id="mlbb",
                external_variant_id="100",
                quantity=1,
                extra={},
                is_active=True,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        ]
    )
    await db_session.commit()

    decision = await sourcing_svc.resolve_for_sku(db_session, sku_id)
    assert decision.primary == "supplier:g2b"
    assert decision.fallback == "supplier:manual"


async def test_auto_never_routes_to_a_reserve_supplier(
    db_session: AsyncSession,
) -> None:
    """A reserve is reached by an operator's decision, never by an accident.

    The oldest-mapping rule keeps the incumbent's route only while there IS an
    incumbent. A top-up SKU that never got one — or whose only mapping an
    operator deactivated during a switch — would otherwise have the reserve's
    mapping as its oldest, and would quietly start buying from a supplier
    nobody chose. With the key unset it is worse than quiet: the adapter
    refuses before calling, graded RETURNED, so orders that used to wait in the
    manual queue would fail and refund instead.

    Four documents assert this cannot happen. This is where it is true.
    """
    from yupay.modules.integrations.models import SkuSupplierMapping
    from yupay.modules.sourcing import service as sourcing_svc

    sku_id = await _make_topup_sku(db_session)
    db_session.add(
        SkuSupplierMapping(
            sku_id=sku_id,
            supplier_slug="nova",
            kind="game",
            external_product_id="mobile_legends_ru",
            external_variant_id="275_diamonds",
            quantity=1,
            extra={},
            is_active=True,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    await db_session.commit()

    decision = await sourcing_svc.resolve_for_sku(db_session, sku_id)
    assert decision.primary == "supplier:manual"
    assert decision.strict is True


async def test_auto_prefers_the_older_mapping_over_the_earlier_slug(
    db_session: AsyncSession,
) -> None:
    """``created_at`` decides, and the slug only breaks a tie.

    The test above pairs an older ``g2b`` with a newer ``gengine``, where the
    chronological and the alphabetical answer happen to agree — so an
    implementation that sorted by ``supplier_slug`` alone would pass it while
    getting the rule exactly wrong. This one inverts the pairing: the incumbent
    is ``gengine`` and the newcomer is ``g2b``, so the two orderings disagree
    and only the chronological one gives the answer asserted here.

    Neither side may be a reserve supplier, which is excluded from this choice
    entirely — see ``test_auto_never_routes_to_a_reserve_supplier``.
    """
    from yupay.modules.integrations.models import SkuSupplierMapping
    from yupay.modules.sourcing import service as sourcing_svc

    sku_id = await _make_topup_sku(db_session)
    db_session.add_all(
        [
            SkuSupplierMapping(
                sku_id=sku_id,
                supplier_slug="g2b",
                kind="game",
                external_product_id="mlbb",
                external_variant_id="100",
                quantity=1,
                extra={},
                is_active=True,
                created_at=datetime(2026, 9, 17, tzinfo=UTC),
            ),
            SkuSupplierMapping(
                sku_id=sku_id,
                supplier_slug="gengine",
                kind="game",
                external_product_id="2",
                external_variant_id="100",
                quantity=1,
                extra={},
                is_active=True,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        ]
    )
    await db_session.commit()

    decision = await sourcing_svc.resolve_for_sku(db_session, sku_id)
    assert decision.primary == "supplier:gengine"
    assert decision.fallback == "supplier:manual"


async def test_voucher_with_mapping_prefers_supplier_over_mock(
    db_session: AsyncSession, _seed_sku: str
) -> None:
    """A ``voucher`` SKU stays inventory-first, but once it has an active
    supplier mapping the fallback is that supplier — not ``mock``."""
    from yupay.modules.integrations.models import SkuSupplierMapping
    from yupay.modules.sourcing import service as sourcing_svc

    db_session.add(
        SkuSupplierMapping(
            sku_id=_seed_sku,
            supplier_slug="g2b",
            kind="voucher",
            external_product_id="42",
            external_variant_id=None,
            quantity=1,
            extra={},
            is_active=True,
        )
    )
    await db_session.commit()

    decision = await sourcing_svc.resolve_for_sku(db_session, _seed_sku)
    assert decision.primary == "inventory"
    assert decision.fallback == "supplier:g2b"


async def test_upsert_rule_replays_pre_sku_code_body(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_sku: str
) -> None:
    """A replay body cached before ``sku_code`` was added (the deploy window) must
    still replay with 200 — sku_code falls back to the sku_id — not 500."""
    from yupay.core.idempotency import save_replay

    admin = await _login_user(integration_client, tg_id=350)
    await _grant_admin(db_session, tg_id=350)
    key = "idem-pre-skucode-rule-0001"
    # Old-shape body: everything SourcingRuleOut needs EXCEPT sku_code.
    await save_replay(
        db_session,
        scope="sourcing.upsert_rule",
        idempotency_key=key,
        body={
            "sku_id": _seed_sku,
            "mode": "auto",
            "supplier_slug": None,
            "updated_by": None,
            "updated_at": "2026-01-01T00:00:00Z",
        },
    )
    await db_session.commit()

    r = await integration_client.put(
        f"/api/v1/admin/sourcing/rules/{_seed_sku}",
        headers={"Authorization": f"Bearer {admin}", "Idempotency-Key": key},
        json={"mode": "auto"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["sku_code"] == _seed_sku


async def test_force_supplier_needs_a_mapping_when_the_adapter_does(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_sku: str
) -> None:
    """Routing a SKU onto G2B with no mapping row does not route it there.

    It fails every order that arrives, one at a time, with "no active mapping"
    in the inbox. The operator said "use this supplier"; the honest answer is
    that it cannot be used yet — at the moment they say so, not at the first
    sale. Waxpeer needs no mapping and is not checked.
    """
    from yupay.modules.integrations.models import SkuSupplierMapping

    admin = await _login_user(integration_client, tg_id=341)
    await _grant_admin(db_session, tg_id=341)
    headers = {"Authorization": f"Bearer {admin}"}
    url = f"/api/v1/admin/sourcing/rules/{_seed_sku}"

    r = await integration_client.put(
        url, headers=headers, json={"mode": "force_supplier", "supplier_slug": "g2b"}
    )
    assert r.status_code == 422, r.text
    assert "mapping" in r.text.lower()

    r = await integration_client.put(
        url, headers=headers, json={"mode": "force_supplier", "supplier_slug": "waxpeer"}
    )
    assert r.status_code == 200, r.text

    db_session.add(
        SkuSupplierMapping(
            sku_id=_seed_sku, supplier_slug="g2b", kind="game", external_product_id="game-1"
        )
    )
    await db_session.commit()
    r = await integration_client.put(
        url, headers=headers, json={"mode": "force_supplier", "supplier_slug": "g2b"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["supplier_slug"] == "g2b"


async def test_force_supplier_nova_needs_an_active_mapping(
    db_session: AsyncSession, _seed_sku: str
) -> None:
    """``nova`` joined ``MAPPING_REQUIRED_SUPPLIERS`` — forcing a SKU onto it
    with no active mapping must be refused the same way g2b/gengine are."""
    from yupay.modules.sourcing import service as sourcing_svc

    with pytest.raises(ValidationError):
        await sourcing_svc.set_rule(
            db_session,
            sku_id=_seed_sku,
            mode="force_supplier",
            supplier_slug="nova",
            admin_id="admin-1",
        )


async def test_force_supplier_nova_accepted_with_an_active_mapping(
    db_session: AsyncSession, _seed_sku: str
) -> None:
    """Once an active nova mapping exists, forcing the SKU onto it succeeds."""
    from yupay.modules.integrations.models import SkuSupplierMapping
    from yupay.modules.sourcing import service as sourcing_svc

    db_session.add(
        SkuSupplierMapping(
            sku_id=_seed_sku,
            supplier_slug="nova",
            kind="voucher",
            external_product_id="42",
            external_variant_id=None,
            quantity=1,
            extra={},
            is_active=True,
        )
    )
    await db_session.commit()

    rule = await sourcing_svc.set_rule(
        db_session,
        sku_id=_seed_sku,
        mode="force_supplier",
        supplier_slug="nova",
        admin_id="admin-1",
    )
    assert rule.supplier_slug == "nova"
