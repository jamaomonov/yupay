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

import csv
import hashlib
import hmac
import io
import json
import re
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, quote, urlencode, urlparse

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
from yupay.modules.orders.models import Order
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
    client: AsyncClient,
    headers: dict[str, str],
    merchant_id: str,
    amount: str,
    order_id: str | None = None,
) -> None:
    """Credit the deposit; with ``order_id``, book it as that order's refund."""
    r = await client.post(
        f"/api/v1/admin/merchants/{merchant_id}/deposit-credits",
        headers={**headers, "Idempotency-Key": f"credit-{new_id()}"},
        json={"amount": amount, **({"order_id": order_id} if order_id else {})},
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


async def test_the_summary_counts_this_merchant_and_nets_a_refund_out(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    sent: list[dict[str, str]],
) -> None:
    """Exact counts, ledger money, and `since` supplied by the caller.

    The netting is the part worth asserting: an order charged and settled
    inside the same window spent nothing, and a dashboard that showed $16.54
    against it would have a reseller chasing money that already came back.
    """
    mine, my_merchant = await _signed_up(integration_client, sent, "sum@acme.example.com")
    theirs, _ = await _signed_up(integration_client, sent, "sum@other.example.com")
    await _credit(integration_client, admin_headers, my_merchant, "80.00")
    sku_id = _seed_stars(db_session)
    await db_session.commit()

    placed = [
        await integration_client.post(
            f"{BASE}/orders",
            headers=_auth(mine),
            json={"sku_id": sku_id, "quantity": 1000, "expected_price": "16.54"},
        )
        for _ in range(2)
    ]
    assert [r.status_code for r in placed] == [201, 201], placed[0].text
    since = quote((datetime.now(UTC) - timedelta(hours=1)).isoformat())

    before = await integration_client.get(f"{BASE}/summary?since={since}", headers=_auth(mine))
    # Support settles one of them in full. The settlement guard refuses while
    # fulfilment is still in flight — crediting then would return the money
    # with the supplier call still coming — so the runbook's own order applies:
    # cancel the task first, then settle.
    settled_order = str(placed[0].json()["order_id"])
    refused = await integration_client.post(
        f"/api/v1/admin/merchants/{my_merchant}/deposit-credits",
        headers={**admin_headers, "Idempotency-Key": f"credit-{new_id()}"},
        json={"amount": "16.54", "order_id": settled_order},
    )
    assert refused.status_code == 409, "settling a live order must still be refused"
    for task_id in refused.json()["open_task_ids"]:
        cancelled = await integration_client.post(
            f"/api/v1/admin/fulfillment/tasks/{task_id}/cancel", headers=admin_headers
        )
        assert cancelled.status_code == 200, cancelled.text
    await _credit(
        integration_client,
        admin_headers,
        my_merchant,
        "16.54",
        order_id=settled_order,
    )
    after = await integration_client.get(f"{BASE}/summary?since={since}", headers=_auth(mine))
    stranger = await integration_client.get(f"{BASE}/summary?since={since}", headers=_auth(theirs))

    assert before.status_code == 200, before.text
    assert before.json() == {
        "orders": 2,
        "delivered": 0,
        "spend_usd": "33.08",
        "spend_capped": False,
    }
    assert after.json()["spend_usd"] == "16.54", "a settled order spent nothing"
    assert after.json()["orders"] == 2, "the count is of orders, not of money"
    assert stranger.json() == {
        "orders": 0,
        "delivered": 0,
        "spend_usd": "0.00",
        "spend_capped": False,
    }


async def test_the_summary_refuses_a_window_it_would_not_read(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    """Bounded in both directions, so a crafted `since` is not a history scan."""
    access, _ = await _signed_up(integration_client, sent, "window@acme.example.com")

    future = await integration_client.get(
        f"{BASE}/summary?since={quote((datetime.now(UTC) + timedelta(hours=1)).isoformat())}",
        headers=_auth(access),
    )
    ancient = await integration_client.get(
        f"{BASE}/summary?since={quote((datetime.now(UTC) - timedelta(days=90)).isoformat())}",
        headers=_auth(access),
    )

    assert future.status_code == 422
    assert future.json()["code"] == "bad_window"
    assert ancient.status_code == 422
    assert ancient.json()["code"] == "window_too_long"


async def test_the_statement_export_is_the_screen_in_a_file(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    sent: list[dict[str, str]],
) -> None:
    """Same reader, same numbers, and safe to open in a spreadsheet.

    The formula guard is the part a reviewer would otherwise call paranoid:
    ``merchant_order_id`` is free text from the reseller's own system and the
    file is opened by their accountant, so a value starting with ``=`` would
    execute there. It is prefixed with an apostrophe, which Excel strips on
    display — and which must **not** reach the money or date columns, because
    it would make them unparseable.
    """
    access, merchant_id = await _signed_up(integration_client, sent, "csv@acme.example.com")
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

    export = await integration_client.get(f"{BASE}/transactions.csv", headers=_auth(access))

    assert export.status_code == 200, export.text
    assert export.headers["content-type"].startswith("text/csv")
    # The filename names the range the file covers, so a truncated run says so.
    assert "yupay-statement-" in export.headers["content-disposition"]
    body = export.text
    assert body.startswith("\ufeff"), "Excel reads a CSV without a BOM as the system codepage"
    rows = list(csv.reader(io.StringIO(body.lstrip("\ufeff")), delimiter=","))
    assert rows[0] == [
        "created_at",
        "kind",
        "amount_usd",
        "merchant_order_id",
        "order_id",
        "transaction_id",
    ]
    # The charge and the credit, newest first, with the screen's own numbers.
    assert [row[1] for row in rows[1:]] == ["merchant_order_charge", "merchant_deposit_credit"]
    assert [row[2] for row in rows[1:]] == ["-16.54", "40.00"]
    assert rows[1][3].startswith("manual-"), "an ordinary id is not rewritten"


async def test_the_statement_defuses_a_formula_without_touching_the_numbers(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    sent: list[dict[str, str]],
) -> None:
    """A `merchant_order_id` a reseller's system chose, starting with `=`.

    Reachable only through the machine API — the cabinet mints its own ids —
    which is exactly why it is worth a test: the id in the file is not one we
    control.
    """
    access, merchant_id = await _signed_up(integration_client, sent, "inject@acme.example.com")
    await _credit(integration_client, admin_headers, merchant_id, "40.00")
    order = Order(
        id=new_id(),
        merchant_id=merchant_id,
        status="delivered",
        currency="USD",
        total_usd=Decimal("16.54"),
        total_charged=Decimal("16.54"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        idempotency_key="=cmd|'/c calc'!A1",
        source="merchant_api",
    )
    db_session.add(order)
    await db_session.commit()
    await _credit(integration_client, admin_headers, merchant_id, "1.00", order_id=order.id)

    export = await integration_client.get(f"{BASE}/transactions.csv", headers=_auth(access))

    rows = list(csv.reader(io.StringIO(export.text.lstrip("\ufeff"))))
    settled = next(row for row in rows[1:] if row[4] == order.id)
    assert settled[3] == "'=cmd|'/c calc'!A1", "a leading = must not reach a spreadsheet live"
    assert settled[2] == "1.00", "the money column is never prefixed"


async def test_the_price_list_export_is_the_catalog_flattened(
    integration_client: AsyncClient, db_session: AsyncSession, sent: list[dict[str, str]]
) -> None:
    """One row per orderable SKU, priced for this merchant.

    Built from `price_list.build`, so the export cannot advertise a price the
    order path would refuse — the property the catalog read already has.
    """
    access, _ = await _signed_up(integration_client, sent, "prices@acme.example.com")
    sku_id = _seed_stars(db_session)
    await db_session.commit()

    export = await integration_client.get(f"{BASE}/catalog.csv", headers=_auth(access))
    tree = await integration_client.get(f"{BASE}/catalog", headers=_auth(access))

    assert export.status_code == 200, export.text
    rows = list(csv.reader(io.StringIO(export.text.lstrip("\ufeff"))))
    assert rows[0][:5] == ["sku_id", "sku_code", "brand", "product", "kind"]
    body = [row for row in rows[1:] if row[0] == sku_id]
    assert len(body) == 1, "exactly one row per SKU"
    from_tree = tree.json()["brands"][0]["products"][0]["skus"][0]
    assert body[0][1] == from_tree["sku_code"]
    assert body[0][7] == from_tree["unit_price_usd"], "the same price the tree quotes"


async def test_the_timezone_is_the_callers_own_and_must_be_loadable(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    """A display setting, validated by loading the zone rather than by a list.

    The "callers own" half has no id in the path to get wrong, which is the
    point: the test exists so that a future field on this endpoint which does
    take one fails here.
    """
    mine, _ = await _signed_up(integration_client, sent, "tz@acme.example.com")
    theirs, _ = await _signed_up(integration_client, sent, "tz@other.example.com")

    ok = await integration_client.patch(
        f"{BASE}/me", headers=_auth(mine), json={"timezone": "Europe/Moscow"}
    )
    bad = await integration_client.patch(
        f"{BASE}/me", headers=_auth(mine), json={"timezone": "Mars/Olympus"}
    )

    assert ok.status_code == 200, ok.text
    assert ok.json()["timezone"] == "Europe/Moscow"
    assert bad.status_code == 422
    # Unchanged by the refusal, and the other account untouched by the success.
    assert (await integration_client.get(f"{BASE}/me", headers=_auth(mine))).json()[
        "timezone"
    ] == "Europe/Moscow"
    assert (await integration_client.get(f"{BASE}/me", headers=_auth(theirs))).json()[
        "timezone"
    ] == "Asia/Tashkent"


async def test_a_key_carries_the_allowlist_it_was_issued_with(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    """Same field, same rules and the same validator as the admin surface.

    A typo'd entry stored verbatim would never match and would lock the
    merchant out of their own API with a 403 nobody can explain, so it is
    refused at the parse boundary — on this surface too, which is the thing
    a second copy of the validator would eventually stop doing.
    """
    access, _ = await _signed_up(integration_client, sent, "ips@acme.example.com")

    issued = await integration_client.post(
        f"{BASE}/api-keys",
        headers=_auth(access),
        json={"label": "boxed", "ip_allowlist": ["203.0.113.5", " 10.0.0.0/8 "]},
    )
    refused = await integration_client.post(
        f"{BASE}/api-keys", headers=_auth(access), json={"ip_allowlist": ["not-an-ip"]}
    )
    plain = await integration_client.post(
        f"{BASE}/api-keys", headers=_auth(access), json={"label": "no filter"}
    )

    assert issued.status_code == 201, issued.text
    assert issued.json()["ip_allowlist"] == ["203.0.113.5", "10.0.0.0/8"], "entries are trimmed"
    assert refused.status_code == 422
    assert plain.status_code == 201
    assert plain.json()["ip_allowlist"] is None, "an omitted list means no filter, not an empty one"
    listed = {
        row["key_id"]: row["ip_allowlist"]
        for row in (await integration_client.get(f"{BASE}/api-keys", headers=_auth(access))).json()
    }
    assert len(listed) == 2, "the refused call must not have minted a credential"
    assert listed[issued.json()["key_id"]] == ["203.0.113.5", "10.0.0.0/8"]


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
    patched = await integration_client.patch(f"{BASE}/me", json={"timezone": "UTC"})
    assert patched.status_code == 401
    summary = await integration_client.get(
        f"{BASE}/summary?since={quote(datetime.now(UTC).isoformat())}"
    )
    assert summary.status_code == 401
    for export in ("/transactions.csv", "/catalog.csv"):
        assert (await integration_client.get(f"{BASE}{export}")).status_code == 401, export

    users = (await db_session.execute(select(MerchantUser))).scalars().all()
    assert users == [], "nothing above should have created an account"
