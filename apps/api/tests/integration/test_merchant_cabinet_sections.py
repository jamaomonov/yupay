"""Orders, ledger and API keys, as the cabinet reads them.

Two properties are worth the setup cost. First, **scope**: every one of these
routes takes the merchant from the signed-in operator, so the test that
matters is two accounts side by side — one with orders and a key, one with
neither, each seeing only their own.

Second, **money comes from the ledger**. Two of the three SKU shapes put a
per-unit rate or a face value on the order line and the money somewhere else,
so a list built off the line would show $0.016537 against an order that cost
$16.54. The Stars case is in here for exactly that reason.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from decimal import Decimal
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.config import Settings, get_settings
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
from yupay.modules.merchants import cabinet_routes
from yupay.modules.merchants.models import MerchantUser
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BASE = "/merchant/cabinet"
CABINET_URL = "https://reseller.yupay.test"
PASSWORD = "correct-horse-battery"
BOT_TOKEN = "123456:TEST"


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


@pytest.fixture
async def admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    """Log a Telegram user in and grant it the admin role.

    Crediting a deposit is support's job, not a merchant's, so the one thing
    these tests cannot do through the cabinet is give themselves money — which
    is the point of the whole onboarding shape.
    """
    user_json = json.dumps({"id": 92, "first_name": "Admin"}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await integration_client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == 92)
        )
    ).scalar_one()
    await db_session.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    mails: list[dict[str, str]] = []

    async def _send(*, to: str, subject: str, html: str, text: str) -> str:
        mails.append({"to": to, "html": html, "subject": subject, "text": text})
        return "msg-test"

    base = get_settings().model_dump()
    base["merchant_cabinet_url"] = CABINET_URL
    monkeypatch.setattr(cabinet_routes, "send_email", _send)
    monkeypatch.setattr(cabinet_routes, "get_settings", lambda: Settings(**base))
    return mails


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _signed_up(
    client: AsyncClient, mails: list[dict[str, str]], email: str
) -> tuple[str, str]:
    """Register and confirm. Returns ``(access_token, merchant_id)``."""
    r = await client.post(
        f"{BASE}/register",
        json={"email": email, "password": PASSWORD, "title": "ACME", "accept_offer": True},
    )
    assert r.status_code == 201, r.text
    link = re.search(r'href="([^"]+/confirm\?token=[^"]+)"', mails[-1]["html"])
    assert link is not None
    token = parse_qs(urlparse(link.group(1)).query)["token"][0]
    tokens = await client.post(f"{BASE}/confirm", json={"token": token})
    assert tokens.status_code == 200, tokens.text
    access = str(tokens.json()["access_token"])
    me = await client.get(f"{BASE}/me", headers=_auth(access))
    return access, str(me.json()["merchant_id"])


async def _credit(
    client: AsyncClient, headers: dict[str, str], merchant_id: str, amount: str
) -> None:
    r = await client.post(
        f"/api/v1/admin/merchants/{merchant_id}/deposit-credits",
        headers={**headers, "Idempotency-Key": f"credit-{new_id()}"},
        json={"amount": amount},
    )
    assert r.status_code == 201, r.text


def _seed_stars(db: AsyncSession) -> str:
    """One unit SKU priced like Telegram Stars, returning its id."""
    category = Category(id=new_id(), slug=f"cat-{new_id()[:8]}", sort_order=0, active=True)
    category.translations = [CategoryTranslation(locale="ru", name="Категория")]
    brand = Brand(
        id=new_id(),
        slug=f"brand-{new_id()[:8]}",
        category_id=category.id,
        sort_order=0,
        active=True,
        visible_b2b=True,
    )
    brand.translations = [BrandTranslation(locale="ru", name="Бренд")]
    product = Product(
        id=new_id(),
        slug=f"product-{new_id()[:8]}",
        brand_id=brand.id,
        kind="top_up",
        sort_order=0,
        active=True,
        required_fields=[],
    )
    product.translations = [ProductTranslation(locale="ru", name="Продукт")]
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="stars-unit",
        denomination="Любое количество",
        region="GLOBAL",
        price_usd=Decimal("0.0191"),
        cost_usdt=Decimal("0.015455"),
        visible_b2b=True,
        b2b_markup_pct=Decimal("7"),
        amount_unit="stars",
        min_qty=50,
        max_qty=50_000,
        sort_order=0,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    return sku.id


async def test_the_orders_list_shows_what_the_deposit_paid_not_the_line(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    sent: list[dict[str, str]],
) -> None:
    """A thousand Stars cost $16.54; the line says $0.016537.

    The list reads the ledger, which is the only authority on what an order
    took — `deposit.charged_for_order` says so in its own docstring, and this
    is the screen where believing the line would be most visible.
    """
    access, merchant_id = await _signed_up(integration_client, sent, "ops@acme.example.com")
    await _credit(integration_client, admin_headers, merchant_id, "40.00")
    sku_id = _seed_stars(db_session)
    await db_session.commit()

    placed = await integration_client.post(
        f"{BASE}/orders",
        headers=_auth(access),
        json={"sku_id": sku_id, "quantity": 1000, "expected_price": "16.54"},
    )
    assert placed.status_code == 201, placed.text

    listed = await integration_client.get(f"{BASE}/orders", headers=_auth(access))

    assert listed.status_code == 200, listed.text
    rows = listed.json()["items"]
    assert len(rows) == 1
    assert rows[0]["price_usd"] == "16.54"
    assert rows[0]["refunded_usd"] == "0.00"
    assert rows[0]["sku_code"] == "stars-unit"
    # The cabinet minted it, and it is visibly not a reseller's own id.
    assert rows[0]["merchant_order_id"].startswith("manual-")


async def test_search_finds_an_order_by_either_id(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    sent: list[dict[str, str]],
) -> None:
    """Both halves of the search box, because only one of them is text.

    ``Order.id`` is a Postgres ``uuid``. ``uuid ILIKE text`` is not an
    operator, so an uncast comparison does not return nothing — it raises,
    and the whole endpoint answers 500 the moment anybody types. A test that
    exercised only the status filter would never have seen it; this one was
    written after a browser did.
    """
    access, merchant_id = await _signed_up(integration_client, sent, "find@acme.example.com")
    await _credit(integration_client, admin_headers, merchant_id, "40.00")
    sku_id = _seed_stars(db_session)
    await db_session.commit()
    placed = await integration_client.post(
        f"{BASE}/orders",
        headers=_auth(access),
        json={"sku_id": sku_id, "quantity": 1000, "expected_price": "16.54"},
    )
    assert placed.status_code == 201, placed.text
    mine = str(placed.json()["merchant_order_id"])
    ours = str(placed.json()["order_id"])

    async def _search(needle: str) -> list[dict[str, object]]:
        r = await integration_client.get(
            f"{BASE}/orders", headers=_auth(access), params={"search": needle}
        )
        assert r.status_code == 200, r.text
        items: list[dict[str, object]] = r.json()["items"]
        return items

    # Their own id, whole and in part; our id, whole and in part.
    assert [row["merchant_order_id"] for row in await _search(mine)] == [mine]
    assert [row["merchant_order_id"] for row in await _search(mine[-12:])] == [mine]
    assert [row["merchant_order_id"] for row in await _search(ours)] == [mine]
    assert [row["merchant_order_id"] for row in await _search(ours[-12:])] == [mine]
    assert await _search("no-such-order") == []


async def test_one_operator_never_lists_another_merchants_orders(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    sent: list[dict[str, str]],
) -> None:
    """The rule every route on this surface rests on, on the busiest screen."""
    buyer, buyer_merchant = await _signed_up(integration_client, sent, "a@acme.example.com")
    watcher, _ = await _signed_up(integration_client, sent, "b@other.example.com")
    await _credit(integration_client, admin_headers, buyer_merchant, "40.00")
    sku_id = _seed_stars(db_session)
    await db_session.commit()
    assert (
        await integration_client.post(
            f"{BASE}/orders",
            headers=_auth(buyer),
            json={"sku_id": sku_id, "quantity": 1000, "expected_price": "16.54"},
        )
    ).status_code == 201

    theirs = await integration_client.get(f"{BASE}/orders", headers=_auth(buyer))
    others = await integration_client.get(f"{BASE}/orders", headers=_auth(watcher))

    assert len(theirs.json()["items"]) == 1
    assert others.json()["items"] == []


async def test_an_unknown_status_filter_is_refused_rather_than_ignored(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    """A filter that quietly matches everything is worse than one that 422s:
    an operator narrowing to "failed" and seeing delivered rows would trust the
    wrong list."""
    access, _ = await _signed_up(integration_client, sent, "filter@acme.example.com")

    r = await integration_client.get(
        f"{BASE}/orders", headers=_auth(access), params={"status_filter": "nonsense"}
    )

    assert r.status_code == 422
    assert r.json()["code"] == "unknown_status"


async def test_the_ledger_shows_a_credit_and_the_charge_against_it(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    sent: list[dict[str, str]],
) -> None:
    access, merchant_id = await _signed_up(integration_client, sent, "ledger@acme.example.com")
    await _credit(integration_client, admin_headers, merchant_id, "40.00")
    sku_id = _seed_stars(db_session)
    await db_session.commit()
    assert (
        await integration_client.post(
            f"{BASE}/orders",
            headers=_auth(access),
            json={"sku_id": sku_id, "quantity": 1000, "expected_price": "16.54"},
        )
    ).status_code == 201

    r = await integration_client.get(f"{BASE}/transactions", headers=_auth(access))

    assert r.status_code == 200, r.text
    amounts = [row["amount_usd"] for row in r.json()["items"]]
    # Signed: the credit is positive and the order's charge is negative, and
    # the two add up to the balance the dashboard shows.
    assert "40.00" in amounts
    assert "-16.54" in amounts


async def test_a_key_is_issued_once_and_never_shown_again(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    """Self-serve rotation, and the secret's one appearance.

    A list that could show the secret would mean we had kept it in a readable
    form; the row holds it encrypted so a signature can be verified at all.
    """
    access, _ = await _signed_up(integration_client, sent, "keys@acme.example.com")

    created = await integration_client.post(
        f"{BASE}/api-keys", headers=_auth(access), json={"label": "staging"}
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["secret"]
    assert body["label"] == "staging"

    listed = await integration_client.get(f"{BASE}/api-keys", headers=_auth(access))
    assert listed.status_code == 200
    rows = listed.json()
    assert [row["key_id"] for row in rows] == [body["key_id"]]
    assert all("secret" not in row for row in rows)


async def test_revoking_a_key_leaves_it_listed_and_stamped(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    """Revoked, not deleted: an operator asking "did I turn that one off?"
    needs an answer, and a vanished row cannot give one."""
    access, _ = await _signed_up(integration_client, sent, "revoke@acme.example.com")
    key_id = (
        await integration_client.post(f"{BASE}/api-keys", headers=_auth(access), json={})
    ).json()["key_id"]

    revoked = await integration_client.delete(f"{BASE}/api-keys/{key_id}", headers=_auth(access))

    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["revoked_at"] is not None
    rows = (await integration_client.get(f"{BASE}/api-keys", headers=_auth(access))).json()
    assert [row["revoked_at"] is not None for row in rows] == [True]


async def test_one_operator_never_revokes_another_merchants_key(
    integration_client: AsyncClient, sent: list[dict[str, str]], db_session: AsyncSession
) -> None:
    """The scope check that matters most: a key id is guessable from a log."""
    owner, _ = await _signed_up(integration_client, sent, "owner@acme.example.com")
    stranger, _ = await _signed_up(integration_client, sent, "stranger@other.example.com")
    key_id = (
        await integration_client.post(f"{BASE}/api-keys", headers=_auth(owner), json={})
    ).json()["key_id"]

    attempt = await integration_client.delete(f"{BASE}/api-keys/{key_id}", headers=_auth(stranger))

    assert attempt.status_code == 404
    rows = (await integration_client.get(f"{BASE}/api-keys", headers=_auth(owner))).json()
    assert rows[0]["revoked_at"] is None, "the owner's key must still be live"


async def test_every_section_refuses_a_signed_out_browser(
    integration_client: AsyncClient, sent: list[dict[str, str]], db_session: AsyncSession
) -> None:
    """No route on this surface is readable without a session.

    Enumerated rather than spot-checked: a new section added without the
    dependency is the failure this catches, and it is silent otherwise.
    """
    for path in ("/me", "/catalog", "/orders", "/transactions", "/api-keys"):
        r = await integration_client.get(f"{BASE}{path}")
        assert r.status_code == 401, f"{path} answered {r.status_code}"

    users = (await db_session.execute(select(MerchantUser))).scalars().all()
    assert users == [], "nothing above should have created an account"
