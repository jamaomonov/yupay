"""The buyer-facing code preview.

Two things are being protected here. The endpoint must not become a lookup
service for other people's promo codes — every unusable code answers the same
way — and it must not be able to set a price: the amounts it returns are for
display, and ``create_order`` resolves the code again for itself.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.affiliate.models import AffiliateCode, AffiliatePartner
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Category,
    CategoryTranslation,
    Product,
    ProductTranslation,
    Sku,
)
from yupay.modules.users.models import TelegramLink

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login(client: AsyncClient, tg_id: int) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "U"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200, r.text
    return str(r.json()["access_token"])


async def _seed_sku(db: AsyncSession, *, price_usd: str) -> str:
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
        cost_usdt=Decimal("8.00"),
    )
    db.add(sku)
    await db.flush()
    await db.commit()
    return str(sku.id)


async def _seed_code(db: AsyncSession, *, percent: str, active: bool = True) -> str:
    partner = AffiliatePartner(id=new_id(), email=f"p-{new_id()}@example.test", status="active")
    db.add(partner)
    await db.flush()
    code = AffiliateCode(
        id=new_id(),
        partner_id=partner.id,
        code=f"C{secrets.token_hex(5).upper()}",
        discount_percent=Decimal(percent),
        commission_percent=Decimal("2"),
        active=active,
    )
    db.add(code)
    await db.flush()
    await db.commit()
    return str(code.code)


async def test_preview_reports_the_discount_and_both_totals(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    sku_id = await _seed_sku(db_session, price_usd="10.00")
    code = await _seed_code(db_session, percent="10")
    token = await _login(integration_client, tg_id=901_001)

    r = await integration_client.post(
        "/api/v1/affiliate/preview",
        json={"code": code, "currency": "USD", "items": [{"sku_id": sku_id, "qty": 2}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applicable"] is True
    assert Decimal(body["total_before"]) == Decimal("20.00")
    assert Decimal(body["discount"]) == Decimal("2.00")
    assert Decimal(body["total_after"]) == Decimal("18.00")
    assert Decimal(body["percent"]) == Decimal("10")


async def test_preview_gives_one_answer_for_every_unusable_code(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A nonexistent code and a disabled one must be indistinguishable.

    Anything else and this endpoint enumerates other people's promo codes.
    """
    sku_id = await _seed_sku(db_session, price_usd="10.00")
    disabled = await _seed_code(db_session, percent="10", active=False)
    token = await _login(integration_client, tg_id=901_002)

    answers = []
    for candidate in (f"C{secrets.token_hex(5).upper()}", disabled):
        r = await integration_client.post(
            "/api/v1/affiliate/preview",
            json={"code": candidate, "currency": "USD", "items": [{"sku_id": sku_id, "qty": 1}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        answers.append(r.json())

    assert answers[0]["applicable"] is False
    assert answers[0]["reason"] == "unknown"
    assert answers[0] == answers[1]
    # An inapplicable code must still return the real total, so the checkout
    # can keep showing a price rather than blanking out.
    assert Decimal(answers[0]["total_after"]) == Decimal("10.00")


async def test_preview_requires_a_signed_in_buyer(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Partner codes bind a buyer to a partner; a guest has nothing to bind."""
    sku_id = await _seed_sku(db_session, price_usd="10.00")
    code = await _seed_code(db_session, percent="10")

    r = await integration_client.post(
        "/api/v1/affiliate/preview",
        json={"code": code, "currency": "USD", "items": [{"sku_id": sku_id, "qty": 1}]},
    )
    assert r.status_code in (401, 403), r.text


async def test_preview_rejects_an_unknown_sku(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The cart is priced by the same code path checkout uses, so the same
    rules about what is buyable apply."""
    code = await _seed_code(db_session, percent="10")
    token = await _login(integration_client, tg_id=901_003)

    r = await integration_client.post(
        "/api/v1/affiliate/preview",
        json={"code": code, "currency": "USD", "items": [{"sku_id": new_id(), "qty": 1}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422, r.text


async def test_preview_cannot_set_a_price(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The request has no amount field at all — the server prices the cart.

    This is the property that makes the preview safe to expose: there is no
    number a client could send that would change what it is charged.
    """
    sku_id = await _seed_sku(db_session, price_usd="10.00")
    code = await _seed_code(db_session, percent="10")
    token = await _login(integration_client, tg_id=901_004)

    r = await integration_client.post(
        "/api/v1/affiliate/preview",
        json={
            "code": code,
            "currency": "USD",
            "items": [{"sku_id": sku_id, "qty": 1}],
            "total_before": "1.00",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422, r.text

    # And the honest request still prices from the catalog, not from anything
    # the client believes.
    ok = await integration_client.post(
        "/api/v1/affiliate/preview",
        json={"code": code, "currency": "USD", "items": [{"sku_id": sku_id, "qty": 1}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert Decimal(ok.json()["total_before"]) == Decimal("10.00")


async def test_preview_does_not_bind_or_create_anything(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A preview is a question, not a decision."""
    from yupay.modules.affiliate.models import AffiliateAttribution
    from yupay.modules.orders.models import Order

    sku_id = await _seed_sku(db_session, price_usd="10.00")
    code = await _seed_code(db_session, percent="10")
    token = await _login(integration_client, tg_id=901_005)

    await integration_client.post(
        "/api/v1/affiliate/preview",
        json={"code": code, "currency": "USD", "items": [{"sku_id": sku_id, "qty": 1}]},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert (await db_session.execute(select(AffiliateAttribution))).first() is None
    assert (await db_session.execute(select(Order))).first() is None
    assert (await db_session.execute(select(TelegramLink))).first() is not None


# Every partner-scoped path, as (method, path). A route added to the router
# without authentication will not appear here — which is why the next test
# reads the live app rather than this list.
PARTNER_PATHS = [
    ("GET", "/api/v1/affiliate/me"),
    ("GET", "/api/v1/affiliate/stats"),
    ("GET", "/api/v1/affiliate/balance"),
    ("GET", "/api/v1/affiliate/commissions"),
    ("GET", "/api/v1/affiliate/payouts"),
    ("POST", "/api/v1/affiliate/payouts"),
]

#: Paths under /affiliate that are public by design.
_PUBLIC = {
    "/api/v1/affiliate/applications",
    "/api/v1/affiliate/auth/login",
    "/api/v1/affiliate/auth/set-password",
    "/api/v1/affiliate/auth/refresh",
    "/api/v1/affiliate/auth/logout",
    # Buyer-authenticated, not partner-authenticated — covered by its own test.
    "/api/v1/affiliate/preview",
}


async def test_every_partner_route_refuses_an_anonymous_caller(
    integration_client: AsyncClient,
) -> None:
    """Read from the live app, not from a hand-written list.

    A route added to the partner router later without a dependency would pass a
    list-driven test by simply not being in the list. Enumerating the app makes
    the omission the failure.
    """
    from yupay.bootstrap import create_app

    app = create_app()
    partner_paths = {
        route.path
        for route in app.routes
        if "affiliate" in getattr(route, "path", "") and route.path not in _PUBLIC
    }
    assert partner_paths, "no partner routes found — the enumeration is wrong"

    for path in sorted(partner_paths):
        for method in ("GET", "POST"):
            r = await integration_client.request(method, path)
            assert r.status_code != 200, f"{method} {path} answered an anonymous caller"


async def test_a_buyer_token_cannot_read_the_panel(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The whole reason partner tokens have their own kind."""
    token = await _login(integration_client, tg_id=902_001)

    r = await integration_client.get(
        "/api/v1/affiliate/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 401, r.text


async def test_the_application_endpoint_answers_the_same_for_a_repeat(
    integration_client: AsyncClient,
) -> None:
    """Otherwise anyone with a list of addresses can discover the partners."""
    body = {"email": "repeat@example.com", "display_name": "R"}
    first = await integration_client.post("/api/v1/affiliate/applications", json=body)
    second = await integration_client.post("/api/v1/affiliate/applications", json=body)

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert first.json() == second.json()


async def test_a_partner_signs_in_and_reads_their_own_panel(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The whole flow over HTTP, end to end."""
    from yupay.modules.affiliate import partners

    r = await integration_client.post(
        "/api/v1/affiliate/applications",
        json={"email": "flow@example.com", "display_name": "Flow"},
    )
    assert r.status_code == 202, r.text

    from yupay.modules.affiliate.models import AffiliatePartner

    partner = (
        await db_session.execute(
            select(AffiliatePartner).where(AffiliatePartner.email == "flow@example.com")
        )
    ).scalar_one()
    link = await partners.approve(db_session, partner_id=partner.id)
    await db_session.commit()

    r = await integration_client.post(
        "/api/v1/affiliate/auth/set-password",
        json={"token": link, "password": "a long enough password"},
    )
    assert r.status_code == 204, r.text

    r = await integration_client.post(
        "/api/v1/affiliate/auth/login",
        json={"email": "flow@example.com", "password": "a long enough password"},
    )
    assert r.status_code == 200, r.text
    access = r.json()["access_token"]

    auth = {"Authorization": f"Bearer {access}"}
    me = await integration_client.get("/api/v1/affiliate/me", headers=auth)
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "flow@example.com"
    # The panel must not hand a partner their own password hash or the admin's
    # private note about them.
    assert "password_hash" not in me.json()
    assert "admin_note" not in me.json()

    balance = await integration_client.get("/api/v1/affiliate/balance", headers=auth)
    assert balance.status_code == 200, balance.text
    # Compared as a number: an untouched ledger account serialises as "0",
    # a used one at the column's scale. The value is what matters here, not
    # how many zeros Decimal chose to print.
    assert Decimal(balance.json()["available"]) == Decimal("0")
    assert balance.json()["currency"] == "UZS"
