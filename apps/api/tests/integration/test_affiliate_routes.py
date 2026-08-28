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


async def _grant_admin(db: AsyncSession, tg_id: int) -> None:
    """Give a Telegram-linked user the admin role."""
    from yupay.modules.users.models import User as UserModel

    user_id = (
        await db.execute(
            select(UserModel.id)
            .join(TelegramLink, TelegramLink.user_id == UserModel.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    user = await db.get(UserModel, user_id)
    assert user is not None
    user.roles = ["admin"]
    await db.flush()


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


ADMIN_PREFIX = "/api/v1/admin/affiliate"


async def test_every_admin_route_refuses_a_non_admin(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Enumerated from the live app, not from a list.

    A route added to the admin router later without `require_admin` would pass
    a list-driven test by not being in the list.
    """
    from yupay.bootstrap import create_app

    app = create_app()
    admin_paths = {
        route.path for route in app.routes if getattr(route, "path", "").startswith(ADMIN_PREFIX)
    }
    assert admin_paths, "no admin routes found — the enumeration is wrong"

    buyer = await _login(integration_client, tg_id=903_001)
    for path in sorted(admin_paths):
        # Path params are irrelevant here: authorization runs before the
        # handler, so a bogus id still proves the gate.
        concrete = (
            path.replace("{partner_id}", "x").replace("{payout_id}", "x").replace("{code_id}", "x")
        )
        for method in ("GET", "POST", "PATCH"):
            anon = await integration_client.request(method, concrete)
            assert anon.status_code != 200, f"{method} {concrete} answered an anonymous caller"

            as_buyer = await integration_client.request(
                method, concrete, headers={"Authorization": f"Bearer {buyer}"}
            )
            assert as_buyer.status_code != 200, f"{method} {concrete} answered a plain buyer"


async def test_the_payout_queue_never_carries_a_full_card_number(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The whole reason the detail view is a separate endpoint.

    An admin has the queue open all day and may screenshot it; the full number
    belongs behind a deliberate second click, not in the list.
    """
    from decimal import Decimal

    from yupay.core.clock import now
    from yupay.core.ids import new_id
    from yupay.modules.affiliate.models import AffiliatePartner, AffiliatePayout

    card = "8600444455556666"
    partner = AffiliatePartner(id=new_id(), email=f"p-{new_id()}@example.test", status="active")
    db_session.add(partner)
    await db_session.flush()
    payout = AffiliatePayout(
        id=new_id(),
        partner_id=partner.id,
        amount=Decimal("100000"),
        currency="UZS",
        card_number=card,
        card_holder="QUEUE TEST",
        status="requested",
        created_at=now(),
    )
    db_session.add(payout)
    await db_session.flush()
    await db_session.commit()

    token = await _login(integration_client, tg_id=903_002)
    await _grant_admin(db_session, 903_002)
    await db_session.commit()
    admin_token = await _login(integration_client, tg_id=903_002)
    auth = {"Authorization": f"Bearer {admin_token}"}
    assert token != ""

    queue = await integration_client.get(f"{ADMIN_PREFIX}/payouts", headers=auth)
    assert queue.status_code == 200, queue.text
    assert card not in queue.text
    assert card[-4:] in queue.text

    detail = await integration_client.get(f"{ADMIN_PREFIX}/payouts/{payout.id}", headers=auth)
    assert detail.status_code == 200, detail.text
    # The one place it is allowed to appear: the admin is about to type it into
    # a banking app.
    assert detail.json()["card_number"] == card


async def _admin_auth(client: AsyncClient, db: AsyncSession, tg_id: int) -> dict[str, str]:
    """Sign in and become an admin. Returns the Authorization header."""
    await _login(client, tg_id=tg_id)
    await _grant_admin(db, tg_id)
    await db.commit()
    token = await _login(client, tg_id=tg_id)
    return {"Authorization": f"Bearer {token}"}


async def test_an_admin_runs_the_whole_programme_over_http(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Application to paid partner, through the API a person actually uses.

    The step this proves is the one the whole feature was missing: none of it
    needs a shell any more.
    """
    from decimal import Decimal

    from yupay.core.clock import now
    from yupay.core.ids import new_id
    from yupay.modules.affiliate.models import AffiliatePartner, AffiliatePayout

    auth = await _admin_auth(integration_client, db_session, 904_001)

    # 1. Someone applies.
    applied = await integration_client.post(
        "/api/v1/affiliate/applications",
        json={"email": "runme@example.com", "display_name": "Run Me"},
    )
    assert applied.status_code == 202, applied.text

    queue = await integration_client.get(f"{ADMIN_PREFIX}/applications", headers=auth)
    assert queue.status_code == 200, queue.text
    pending = [p for p in queue.json()["items"] if p["email"] == "runme@example.com"]
    assert len(pending) == 1
    partner_id = pending[0]["id"]

    # 2. The admin approves. The email send is best-effort and must not be able
    #    to fail the approval.
    approved = await integration_client.post(
        f"{ADMIN_PREFIX}/applications/{partner_id}/approve", headers=auth
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "active"

    # 3. And issues a code.
    issued = await integration_client.post(
        f"{ADMIN_PREFIX}/partners/{partner_id}/codes",
        headers=auth,
        json={"code": "runme7", "discount_percent": "7", "commission_percent": "2"},
    )
    assert issued.status_code == 201, issued.text
    assert issued.json()["code"] == "RUNME7"
    code_id = issued.json()["id"]

    # 4. Retunes it, then switches it off.
    retuned = await integration_client.patch(
        f"{ADMIN_PREFIX}/codes/{code_id}", headers=auth, json={"discount_percent": "9"}
    )
    assert retuned.status_code == 200, retuned.text
    # Compared as a number: how many trailing zeros a Numeric column
    # serialises with is not part of the contract.
    assert Decimal(retuned.json()["discount_percent"]) == Decimal("9")

    off = await integration_client.patch(
        f"{ADMIN_PREFIX}/codes/{code_id}", headers=auth, json={"active": False}
    )
    assert off.status_code == 200, off.text
    assert off.json()["active"] is False

    # 5. A payout arrives and is settled.
    payout = AffiliatePayout(
        id=new_id(),
        partner_id=partner_id,
        amount=Decimal("100000"),
        currency="UZS",
        card_number="8600777788889999",
        card_holder="RUN ME",
        status="requested",
        created_at=now(),
    )
    db_session.add(payout)
    await db_session.flush()
    await db_session.commit()

    paid = await integration_client.post(
        f"{ADMIN_PREFIX}/payouts/{payout.id}/paid", headers=auth, json={"note": "sent"}
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "paid"

    # 6. And the partner is switched off.
    suspended = await integration_client.post(
        f"{ADMIN_PREFIX}/partners/{partner_id}/suspend", headers=auth
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["status"] == "suspended"

    partner = await db_session.get(AffiliatePartner, partner_id)
    assert partner is not None


async def test_an_application_can_be_turned_down_with_a_note(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    auth = await _admin_auth(integration_client, db_session, 904_002)

    await integration_client.post(
        "/api/v1/affiliate/applications", json={"email": "nope@example.com"}
    )
    queue = await integration_client.get(f"{ADMIN_PREFIX}/applications", headers=auth)
    partner_id = next(p["id"] for p in queue.json()["items"] if p["email"] == "nope@example.com")

    rejected = await integration_client.post(
        f"{ADMIN_PREFIX}/applications/{partner_id}/reject",
        headers=auth,
        json={"note": "audience does not match"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["admin_note"] == "audience does not match"


async def test_a_rate_outside_the_range_is_refused_by_the_endpoint(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The admin sees the range, not a constraint name."""
    auth = await _admin_auth(integration_client, db_session, 904_003)

    await integration_client.post(
        "/api/v1/affiliate/applications", json={"email": "rates@example.com"}
    )
    queue = await integration_client.get(f"{ADMIN_PREFIX}/applications", headers=auth)
    partner_id = next(p["id"] for p in queue.json()["items"] if p["email"] == "rates@example.com")
    await integration_client.post(f"{ADMIN_PREFIX}/applications/{partner_id}/approve", headers=auth)

    bad = await integration_client.post(
        f"{ADMIN_PREFIX}/partners/{partner_id}/codes",
        headers=auth,
        json={"code": "TOOMUCH", "discount_percent": "15", "commission_percent": "2"},
    )
    assert bad.status_code == 422, bad.text
    assert "10" in bad.text


async def test_rejecting_a_payout_returns_the_money_over_http(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    from decimal import Decimal

    from yupay.core.clock import now
    from yupay.core.ids import new_id
    from yupay.modules.affiliate.models import AffiliatePartner, AffiliatePayout

    auth = await _admin_auth(integration_client, db_session, 904_004)

    partner = AffiliatePartner(id=new_id(), email=f"p-{new_id()}@example.test", status="active")
    db_session.add(partner)
    await db_session.flush()
    payout = AffiliatePayout(
        id=new_id(),
        partner_id=partner.id,
        amount=Decimal("100000"),
        currency="UZS",
        card_number="8600111100002222",
        card_holder="REFUND ME",
        status="requested",
        created_at=now(),
    )
    db_session.add(payout)
    await db_session.flush()
    await db_session.commit()

    rejected = await integration_client.post(
        f"{ADMIN_PREFIX}/payouts/{payout.id}/reject", headers=auth, json={"note": "bad card"}
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["card_last4"] == "2222"


async def _partner_with_password(
    client: AsyncClient, db: AsyncSession, email: str, password: str
) -> str:
    """An active partner with a password, ready to sign in. Returns their id."""
    from yupay.modules.affiliate import partners
    from yupay.modules.affiliate.models import AffiliatePartner

    r = await client.post("/api/v1/affiliate/applications", json={"email": email})
    assert r.status_code == 202, r.text
    row = (
        await db.execute(select(AffiliatePartner).where(AffiliatePartner.email == email))
    ).scalar_one()
    token = await partners.approve(db, partner_id=row.id)
    await partners.set_password(db, token=token, password=password)
    await db.commit()
    return str(row.id)


async def test_the_refresh_token_never_appears_in_a_response_body(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """It grants a 30-day session that can move money out.

    In the body, one XSS regression reads it. In an HttpOnly cookie, the same
    regression cannot — which is why the buyer flow has done it this way since
    ADR-0007 and why the panel no longer keeps it in sessionStorage.
    """
    from yupay.modules.auth.cookies import PARTNER_REFRESH_COOKIE_NAME

    email, password = "cookie@example.com", "a good long password"
    await _partner_with_password(integration_client, db_session, email, password)

    r = await integration_client.post(
        "/api/v1/affiliate/auth/login", json={"email": email, "password": password}
    )
    assert r.status_code == 200, r.text
    assert "refresh_token" not in r.json()
    assert r.json()["access_token"]

    cookie = r.cookies.get(PARTNER_REFRESH_COOKIE_NAME)
    assert cookie, "the refresh token must ride a cookie"
    # And it must be a different cookie from the buyer's, or a partner signing
    # in would wipe their own shopping session.
    assert PARTNER_REFRESH_COOKIE_NAME != "refresh_token"


async def test_refresh_reads_the_cookie_and_rotates_it(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    from yupay.modules.auth.cookies import PARTNER_REFRESH_COOKIE_NAME

    email, password = "rotate@example.com", "a good long password"
    await _partner_with_password(integration_client, db_session, email, password)

    first = await integration_client.post(
        "/api/v1/affiliate/auth/login", json={"email": email, "password": password}
    )
    assert first.status_code == 200, first.text
    original = first.cookies.get(PARTNER_REFRESH_COOKIE_NAME)

    # No body at all: the client never holds the token, so it cannot send one.
    rotated = await integration_client.post("/api/v1/affiliate/auth/refresh")
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["access_token"]
    assert rotated.cookies.get(PARTNER_REFRESH_COOKIE_NAME) != original


async def test_refresh_without_a_cookie_is_refused(integration_client: AsyncClient) -> None:
    from yupay.modules.auth.cookies import PARTNER_REFRESH_COOKIE_NAME

    integration_client.cookies.delete(PARTNER_REFRESH_COOKIE_NAME)
    r = await integration_client.post("/api/v1/affiliate/auth/refresh")
    assert r.status_code == 401, r.text


async def test_logout_clears_the_cookie(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:

    email, password = "bye@example.com", "a good long password"
    await _partner_with_password(integration_client, db_session, email, password)

    await integration_client.post(
        "/api/v1/affiliate/auth/login", json={"email": email, "password": password}
    )
    out = await integration_client.post("/api/v1/affiliate/auth/logout")
    assert out.status_code == 204, out.text

    # Cleared, so the next refresh has nothing to present.
    again = await integration_client.post("/api/v1/affiliate/auth/refresh")
    assert again.status_code == 401, again.text
