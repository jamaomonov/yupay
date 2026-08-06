"""Guest access to delivered codes requires an order-scoped magic-link token.

The freely-mintable email-only guest token (``POST /auth/guest``) must no longer
unlock ``GET /orders/{id}/deliveries`` — otherwise anyone who knows a buyer's
email can mint a token and read their delivered codes (audit #1, an IDOR on
bearer instruments). Only a ``guest_order`` token bound to *that* order_id (minted
server-side and delivered via the order's email) grants code access.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

import yupay.api.v1  # noqa: F401  isort: skip  # resolve module import order

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.ids import new_id
from yupay.modules.auth import jwt as authjwt
from yupay.modules.auth.security import email_hash
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Category,
    CategoryTranslation,
    Product,
    ProductTranslation,
    Sku,
)
from yupay.modules.fulfillment.models import Delivery
from yupay.modules.orders.models import Order, OrderItem

pytestmark = pytest.mark.asyncio

GUEST_EMAIL = "buyer@example.com"
CODE = "SECRET-CODE-XYZ"


async def _seed_delivered_guest_order(db: AsyncSession) -> str:
    """A delivered guest order carrying one voucher code. Returns order_id."""
    category = Category(
        id=new_id(),
        slug="games-gda",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug="cs2-gda",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="CS2")],
    )
    product = Product(
        id=new_id(),
        slug="cs2-coins-gda",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Coins")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="cs2-100-gda",
        denomination="100",
        region="GLOBAL",
        price_usd=Decimal("0.99"),
        sort_order=10,
        active=True,
    )
    order = Order(
        id=new_id(),
        user_id=None,
        guest_email=GUEST_EMAIL,
        status="delivered",
        currency="USD",
        total_usd=Decimal("0.99"),
        total_charged=Decimal("0.99"),
        expires_at=now() + timedelta(hours=1),
    )
    item = OrderItem(
        id=new_id(),
        order_id=order.id,
        sku_id=sku.id,
        qty=1,
        unit_price_usd=Decimal("0.99"),
        fulfillment_state="delivered",
    )
    delivery = Delivery(
        id=new_id(),
        order_item_id=item.id,
        channel="in_app",
        artifact_kind="voucher_code",
        artifact={"code": CODE},
    )
    db.add_all([category, brand, product, sku, order, item])
    await db.flush()  # parents before the delivery FK
    db.add(delivery)
    await db.commit()
    return order.id


async def _admin_headers(client: AsyncClient, db: AsyncSession, *, tg_id: int) -> dict[str, str]:
    """Log a Telegram user in and grant them admin — returns Bearer headers."""
    import hashlib
    import hmac
    import json as _json
    import time
    from urllib.parse import urlencode

    from sqlalchemy import select, update
    from yupay.modules.users.models import TelegramLink, User

    fields = {
        "user": _json.dumps({"id": tg_id, "first_name": "A"}, separators=(",", ":")),
        "auth_date": str(int(time.time())),
    }
    data = "\n".join(f"{k}={v}" for k, v in sorted(fields.items())).encode()
    secret = hmac.new(b"WebAppData", b"123456:TEST", hashlib.sha256).digest()
    init = urlencode({**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()})
    login = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert login.status_code == 200, login.text

    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _guest_headers(token: str, email: str = GUEST_EMAIL) -> dict[str, str]:
    return {"Authorization": f"Guest {token}", "X-Guest-Email": email}


async def test_email_only_guest_token_cannot_read_codes(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The freely-mintable checkout guest token no longer unlocks codes."""
    order_id = await _seed_delivered_guest_order(db_session)
    e_hash = email_hash(GUEST_EMAIL, get_settings().auth_email_pepper)
    stale = authjwt.mint_guest(email_hash=e_hash)

    r = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries", headers=_guest_headers(stale)
    )
    assert r.status_code == 401, r.text


async def test_order_scoped_token_reads_its_own_codes(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_delivered_guest_order(db_session)
    e_hash = email_hash(GUEST_EMAIL, get_settings().auth_email_pepper)
    token = authjwt.mint_guest_order(order_id=order_id, email_hash=e_hash)

    r = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries", headers=_guest_headers(token)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    codes = [d.get("artifact", {}).get("code") for d in body["items"]]
    assert CODE in codes


async def test_token_for_another_order_is_rejected(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A guest_order token bound to a different order must not unlock this one."""
    order_id = await _seed_delivered_guest_order(db_session)
    e_hash = email_hash(GUEST_EMAIL, get_settings().auth_email_pepper)
    other = authjwt.mint_guest_order(order_id="some-other-order", email_hash=e_hash)

    r = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries", headers=_guest_headers(other)
    )
    assert r.status_code in (401, 404), r.text


async def test_email_mismatch_is_rejected(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    order_id = await _seed_delivered_guest_order(db_session)
    e_hash = email_hash(GUEST_EMAIL, get_settings().auth_email_pepper)
    token = authjwt.mint_guest_order(order_id=order_id, email_hash=e_hash)

    r = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries",
        headers=_guest_headers(token, email="attacker@example.com"),
    )
    assert r.status_code == 401, r.text


async def test_code_access_resend_mails_the_order_owner(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The correct email triggers a re-send — and it goes to the ORDER's address."""
    order_id = await _seed_delivered_guest_order(db_session)
    sent: list[dict[str, str]] = []

    async def _spy(*, to: str, subject: str, html: str, text: str) -> str:
        sent.append({"to": to, "html": html})
        return "m"

    monkeypatch.setattr("yupay.modules.notifications.service.send_email", _spy, raising=False)
    monkeypatch.setenv("WEB_BASE_URL", "https://yupay.uz/ru")
    get_settings.cache_clear()

    r = await integration_client.post(
        f"/api/v1/orders/{order_id}/code-access", json={"email": GUEST_EMAIL}
    )
    assert r.status_code == 204, r.text
    assert len(sent) == 1
    assert sent[0]["to"] == GUEST_EMAIL
    assert "?access=" in sent[0]["html"]
    get_settings.cache_clear()


async def test_code_access_is_non_enumerating(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wrong email (or unknown order) still returns 204 and sends nothing —
    so codes can never be re-mailed to an attacker-controlled address."""
    order_id = await _seed_delivered_guest_order(db_session)
    sent: list[str] = []

    async def _spy(*, to: str, subject: str, html: str, text: str) -> str:
        sent.append(to)
        return "m"

    monkeypatch.setattr("yupay.modules.notifications.service.send_email", _spy, raising=False)
    monkeypatch.setenv("WEB_BASE_URL", "https://yupay.uz/ru")
    get_settings.cache_clear()

    wrong = await integration_client.post(
        f"/api/v1/orders/{order_id}/code-access", json={"email": "attacker@example.com"}
    )
    unknown = await integration_client.post(
        f"/api/v1/orders/{new_id()}/code-access", json={"email": GUEST_EMAIL}
    )
    assert wrong.status_code == 204
    assert unknown.status_code == 204
    assert sent == []
    get_settings.cache_clear()


async def test_admin_can_read_delivered_codes_and_it_is_audited(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Support needs to see the code the customer got — and that access is logged.

    Codes are bearer instruments, so reading them is a privileged action: the
    endpoint is admin-only, returns the FULL artifact (internal fields included,
    unlike the customer view), and records who looked on the order timeline.
    """
    import hashlib
    import hmac
    import json as _json
    import time
    from urllib.parse import urlencode

    from sqlalchemy import select, update
    from yupay.modules.users.models import TelegramLink, User

    order_id = await _seed_delivered_guest_order(db_session)

    # Anonymous callers get nothing.
    anon = await integration_client.get(f"/api/v1/admin/orders/{order_id}/deliveries")
    assert anon.status_code in (401, 403), anon.text

    # Log in a user, then grant admin.
    tg_id = 8801
    # WebApp initData signing: HMAC(key=HMAC("WebAppData", bot_token), data).
    fields = {
        "user": _json.dumps({"id": tg_id, "first_name": "A"}, separators=(",", ":")),
        "auth_date": str(int(time.time())),
    }
    data = "\n".join(f"{k}={v}" for k, v in sorted(fields.items())).encode()
    secret = hmac.new(b"WebAppData", b"123456:TEST", hashlib.sha256).digest()
    init = urlencode({**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()})
    login = await integration_client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db_session.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db_session.commit()
    admin_h = {"Authorization": f"Bearer {token}"}

    r = await integration_client.get(f"/api/v1/admin/orders/{order_id}/deliveries", headers=admin_h)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items, "the seeded order has one delivery"
    # Full artifact: the customer view whitelists keys, the admin view must not.
    assert items[0]["artifact"]["code"] == CODE

    # The look-up is on the order timeline, attributed to the admin.
    detail = await integration_client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_h)
    assert detail.status_code == 200, detail.text
    kinds = [e["kind"] for e in detail.json()["events"]]
    assert "admin.deliveries_viewed" in kinds, kinds


async def test_admin_resend_delivery_email_goes_to_the_order_address(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Support can re-send the delivered email; it can only reach the buyer."""
    order_id = await _seed_delivered_guest_order(db_session)
    admin_h = await _admin_headers(integration_client, db_session, tg_id=8802)

    sent: list[str] = []

    async def _spy(*, to: str, subject: str, html: str, text: str) -> str:
        sent.append(to)
        return "m"

    monkeypatch.setattr("yupay.modules.notifications.service.send_email", _spy, raising=False)
    monkeypatch.setenv("WEB_BASE_URL", "https://yupay.uz/ru")
    get_settings.cache_clear()

    r = await integration_client.post(
        f"/api/v1/admin/orders/{order_id}/resend-delivery-email", headers=admin_h
    )
    assert r.status_code == 204, r.text
    assert sent == [GUEST_EMAIL]

    detail = await integration_client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_h)
    assert "admin.delivery_email_resent" in [e["kind"] for e in detail.json()["events"]]
    get_settings.cache_clear()
