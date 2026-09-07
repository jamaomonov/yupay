"""``GET /merchant/v1/transactions`` — the reseller's own deposit ledger (M2, Task 5).

Every movement of the calling merchant's prepaid balance, newest first, keyset
paged. Three properties carry the weight:

* **Scope by the authenticated identity.** No path or query parameter names a
  merchant; B's page never contains A's rows.
* **Stable paging.** A reseller pulling their statement while an order debits
  the deposit must not skip a row or see one twice — which is what an OFFSET
  would do, since every new row lands at the head of a newest-first list and
  shifts everything after it.
* **One query.** The grouped ledger sum is M1's, shared with the admin panel,
  not a second sum over the same postings.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncSession
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
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
TXN_PATH = "/merchant/v1/transactions"
ORDERS_PATH = "/merchant/v1/orders"


# ---------- harness ----------


def _sign_init_data(fields: dict[str, str]) -> str:
    from urllib.parse import urlencode

    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


@pytest.fixture
async def admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    """Log a Telegram user in and grant it the admin role."""
    user_json = json.dumps({"id": 94, "first_name": "Admin"}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await integration_client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == 94)
        )
    ).scalar_one()
    await db_session.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def sql_counter(db_engine) -> AsyncIterator[dict[str, int]]:  # type: ignore[no-untyped-def]  # conftest fixture is untyped
    """Counts every cursor execution on the engine the app is wired to."""
    holder = {"n": 0}

    def _before(conn, cursor, statement, parameters, context, executemany) -> None:  # type: ignore[no-untyped-def]  # SQLAlchemy event signature
        holder["n"] += 1

    sync_engine = db_engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _before)
    try:
        yield holder
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before)


async def _new_merchant(
    client: AsyncClient, headers: dict[str, str], title: str = "Reseller"
) -> str:
    r = await client.post("/api/v1/admin/merchants", headers=headers, json={"title": title})
    assert r.status_code == 201, r.text
    merchant_id: str = r.json()["id"]
    return merchant_id


async def _new_key(
    client: AsyncClient, headers: dict[str, str], merchant_id: str
) -> tuple[str, str]:
    r = await client.post(
        f"/api/v1/admin/merchants/{merchant_id}/api-keys",
        headers=headers,
        json={"label": "server"},
    )
    assert r.status_code == 201, r.text
    payload = r.json()
    return payload["key_id"], payload["secret"]


async def _credit(
    client: AsyncClient, headers: dict[str, str], merchant_id: str, amount: str
) -> str:
    r = await client.post(
        f"/api/v1/admin/merchants/{merchant_id}/deposit-credits",
        headers={**headers, "Idempotency-Key": f"credit-{new_id()}"},
        json={"amount": amount},
    )
    assert r.status_code == 201, r.text
    txn_id: str = r.json()["transaction_id"]
    return txn_id


def _signed(
    key_id: str, secret: str, *, method: str = "GET", path: str, query: str = "", body: bytes = b""
) -> dict[str, str]:
    """The three auth headers, transcribed from the module README by hand."""
    ts = str(int(time.time()))
    message = "\n".join(
        (ts, method.upper(), path, query, hashlib.sha256(body).hexdigest())
    ).encode()
    return {
        "X-Merchant-Key": key_id,
        "X-Merchant-Timestamp": ts,
        "X-Merchant-Signature": hmac.new(
            secret.encode("utf-8"), message, hashlib.sha256
        ).hexdigest(),
        "Content-Type": "application/json",
    }


async def _page(client: AsyncClient, key_id: str, secret: str, *, query: str = "") -> Response:
    url = f"{TXN_PATH}?{query}" if query else TXN_PATH
    return await client.get(url, headers=_signed(key_id, secret, path=TXN_PATH, query=query))


async def _post_order(
    client: AsyncClient, key_id: str, secret: str, payload: dict[str, Any]
) -> Response:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return await client.post(
        ORDERS_PATH,
        content=body,
        headers=_signed(key_id, secret, method="POST", path=ORDERS_PATH, body=body),
    )


def _seed_sku(db: AsyncSession, *, n: int = 1) -> str:
    category = Category(
        id=new_id(),
        slug=f"cat-{n}-{new_id()[-8:]}",
        sort_order=n,
        active=True,
        translations=[CategoryTranslation(locale="ru", name=f"Категория {n}")],
    )
    brand = Brand(
        id=new_id(),
        slug=f"brand-{n}-{new_id()[-8:]}",
        category_id=category.id,
        sort_order=n,
        active=True,
        visible_b2b=True,
        translations=[BrandTranslation(locale="ru", name=f"Бренд {n}")],
    )
    product = Product(
        id=new_id(),
        slug=f"product-{n}-{new_id()[-8:]}",
        brand_id=brand.id,
        kind="top_up",
        sort_order=n,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name=f"Продукт {n}")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"sku-{n}-{new_id()[-8:]}",
        denomination=f"{n}00 UC",
        region="GLOBAL",
        price_usd=Decimal("9.99"),
        cost_usdt=Decimal("1.000000"),
        visible_b2b=True,
        b2b_markup_pct=Decimal("7"),
        sort_order=0,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    return sku.id


def _no_floats(raw: str) -> object:
    raise AssertionError(f"money must be a JSON string, got the number {raw}")


# ---------- the contract ----------


async def test_the_ledger_shows_credits_and_charges_with_signed_amounts(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """A credit moves the deposit up, an order charge moves it down.

    The sign is the whole point of the grouped query: a merchant reading this
    must be able to add the column up and land on ``/me``'s balance.
    """
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "10.00")
    sku_id = _seed_sku(db_session)
    await db_session.commit()
    placed = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "led-1", "sku_id": sku_id, "expected_price": "1.07"},
    )
    assert placed.status_code == 201, placed.text

    r = await _page(integration_client, key_id, secret)

    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["kind"] for i in items] == ["merchant_order_charge", "merchant_deposit_credit"]
    assert [i["amount_usd"] for i in items] == ["-1.07", "10.00"]
    assert sum(Decimal(i["amount_usd"]) for i in items) == Decimal("8.93")
    assert r.json()["next_cursor"] is None


async def test_a_charge_row_names_the_order_that_spent_the_money(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """A statement line a reseller cannot map to their own order number is a
    support ticket, so the row carries both ids."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "10.00")
    sku_id = _seed_sku(db_session)
    await db_session.commit()
    placed = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "acme/ref/1", "sku_id": sku_id, "expected_price": "1.07"},
    )
    assert placed.status_code == 201, placed.text

    r = await _page(integration_client, key_id, secret)

    charge = r.json()["items"][0]
    assert charge["order_id"] == placed.json()["order_id"]
    assert charge["merchant_order_id"] == "acme/ref/1"
    credit = r.json()["items"][1]
    assert credit["order_id"] is None
    assert credit["merchant_order_id"] is None


async def test_money_leaves_this_endpoint_as_a_string_never_a_float(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "10.50")

    r = await _page(integration_client, key_id, secret)

    assert r.status_code == 200, r.text
    json.loads(r.text, parse_float=_no_floats, parse_int=_no_floats)


async def test_an_untouched_deposit_is_an_empty_page_not_a_404(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """A merchant with no ledger yet is a real merchant with nothing on it."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)

    r = await _page(integration_client, key_id, secret)

    assert r.status_code == 200, r.text
    assert r.json() == {"items": [], "next_cursor": None}


# ---------- isolation ----------


async def test_a_merchants_ledger_never_contains_another_merchants_rows(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """Scoped by the authenticated identity, never by a parameter."""
    a_id = await _new_merchant(integration_client, admin_headers, title="A")
    b_id = await _new_merchant(integration_client, admin_headers, title="B")
    a_txn = await _credit(integration_client, admin_headers, a_id, "10.00")
    b_txn = await _credit(integration_client, admin_headers, b_id, "20.00")
    b_key, b_secret = await _new_key(integration_client, admin_headers, b_id)

    r = await _page(integration_client, b_key, b_secret)

    ids = [i["transaction_id"] for i in r.json()["items"]]
    assert ids == [b_txn]
    assert a_txn not in r.text


async def test_a_cursor_lifted_from_another_merchant_reveals_nothing(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """The cursor is a position, not a capability: the merchant scope is applied
    from the signed identity regardless of what the cursor says.

    **B's rows are seeded first, deliberately.** A cursor points at a moment,
    and every row older than it is filtered out — so seeding B *after* A would
    make the stolen cursor exclude B's own rows, hand back an empty page, and
    leave the assertion loop with nothing to iterate. The test would pass
    without the scoping it claims to test. Seeded this way, B has real rows on
    the far side of A's cursor, the loop actually runs, and the assertion is
    about scope rather than about emptiness.
    """
    b_id = await _new_merchant(integration_client, admin_headers, title="B")
    b_key, b_secret = await _new_key(integration_client, admin_headers, b_id)
    b_txns = {await _credit(integration_client, admin_headers, b_id, "1.00") for _ in range(2)}

    a_id = await _new_merchant(integration_client, admin_headers, title="A")
    a_key, a_secret = await _new_key(integration_client, admin_headers, a_id)
    a_txns = {await _credit(integration_client, admin_headers, a_id, "5.00") for _ in range(3)}
    a_page = await _page(integration_client, a_key, a_secret, query="limit=1")
    stolen = a_page.json()["next_cursor"]
    assert stolen

    r = await _page(integration_client, b_key, b_secret, query=f"cursor={stolen}")

    assert r.status_code == 200, r.text
    seen = {i["transaction_id"] for i in r.json()["items"]}
    # The loop has teeth only if it iterates: B's rows are older than A's
    # cursor, so all of them are on this page.
    assert seen == b_txns
    assert not seen & a_txns


# ---------- paging ----------


async def test_paging_walks_every_row_exactly_once(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    minted = [
        await _credit(integration_client, admin_headers, merchant_id, "1.00") for _ in range(5)
    ]

    seen: list[str] = []
    query = "limit=2"
    for _ in range(10):
        r = await _page(integration_client, key_id, secret, query=query)
        assert r.status_code == 200, r.text
        seen.extend(i["transaction_id"] for i in r.json()["items"])
        cursor = r.json()["next_cursor"]
        if cursor is None:
            break
        query = f"limit=2&cursor={cursor}"

    assert seen == list(reversed(minted))
    assert len(seen) == len(set(seen))


async def test_a_row_written_mid_walk_neither_skips_nor_repeats_an_older_one(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """Constraint 4: keyset paging, not OFFSET.

    A merchant pulling their statement while an order debits the deposit is
    the ordinary case, not a race to be tolerated. With OFFSET, the new row
    lands at the head of a newest-first list, every later row shifts down one,
    and page 2 re-serves the last row of page 1 — silently, with no error
    anywhere. Anchoring on the last row's ``(created_at, id)`` instead makes
    the second page mean "older than that row", which no insertion can move.
    """
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    original = [
        await _credit(integration_client, admin_headers, merchant_id, "1.00") for _ in range(4)
    ]

    first = await _page(integration_client, key_id, secret, query="limit=2")
    assert first.status_code == 200, first.text
    page_one = [i["transaction_id"] for i in first.json()["items"]]

    # The concurrent write: a fresh credit lands at the head of the list.
    intruder = await _credit(integration_client, admin_headers, merchant_id, "9.99")

    cursor = first.json()["next_cursor"]
    assert cursor
    second = await _page(integration_client, key_id, secret, query=f"limit=2&cursor={cursor}")
    assert second.status_code == 200, second.text
    page_two = [i["transaction_id"] for i in second.json()["items"]]

    assert page_one + page_two == list(reversed(original))
    assert intruder not in page_one + page_two


async def test_the_page_carries_a_cursor_only_while_older_rows_remain(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """A cursor on a full-but-final page would cost every client one wasted call."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    for _ in range(2):
        await _credit(integration_client, admin_headers, merchant_id, "1.00")

    exact = await _page(integration_client, key_id, secret, query="limit=2")

    assert len(exact.json()["items"]) == 2
    assert exact.json()["next_cursor"] is None


async def test_a_malformed_cursor_is_a_documented_422(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    bad = base64.urlsafe_b64encode(b"not-a-cursor").decode().rstrip("=")

    r = await _page(integration_client, key_id, secret, query=f"cursor={bad}")

    assert r.status_code == 422, r.text
    assert r.json()["code"] == "invalid_cursor"
    assert r.json()["type"] == "https://app.yupay.uz/errors/validation"


async def test_a_truncated_cursor_is_a_422_and_not_a_500(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """The failure a reseller actually hits: a cursor stored in a column that
    was two characters too short, or a URL line-wrapped by a retry.

    Truncation leaves the base64, the separator and the timestamp intact and
    only damages the id half — which used to be handed straight to
    ``uuid < $2``, where asyncpg raised ``DataError`` and it escaped as a bare
    500 from an endpoint whose published contract promises a recoverable 422.
    """
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    for _ in range(2):
        await _credit(integration_client, admin_headers, merchant_id, "1.00")
    real = (await _page(integration_client, key_id, secret, query="limit=1")).json()["next_cursor"]
    assert real

    r = await _page(integration_client, key_id, secret, query=f"cursor={real[:-2]}")

    assert r.status_code == 422, r.text
    assert r.json()["code"] == "invalid_cursor"


@pytest.mark.parametrize(
    ("payload", "why"),
    [
        (b"2026-09-07T08:20:11.402913+00:00|not-a-uuid", "the id half is not a UUID"),
        (b"2026-09-07T08:20:11.402913+00:00|", "the id half is empty"),
        (b"2026-09-07T08:20:11.402913+00:00", "no separator at all"),
        (b"|0198c3c0-0000-7000-8000-000000000000", "no timestamp"),
        (b"not-a-timestamp|0198c3c0-0000-7000-8000-000000000000", "the timestamp is prose"),
        (b"2026-09-07T08:20:11.402913|0198c3c0-0000-7000-8000-000000000000", "no timezone"),
        (b"\xff\xfe\x00garbage", "the right shape, garbage bytes"),
    ],
)
async def test_every_unreadable_cursor_is_one_422_with_one_code(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    payload: bytes,
    why: str,
) -> None:
    """Both halves are validated, not merely parsed — everything that survives
    ``decode_cursor`` is bound into a SQL comparison against a typed column.

    The naive-timestamp case is here for the same reason as the id: ``created_at``
    is ``timestamptz`` and every cursor we issue carries an offset, so a naive
    one is not one we issued and must not reach the driver to find that out.
    """
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "1.00")
    cursor = base64.urlsafe_b64encode(payload).decode().rstrip("=")

    r = await _page(integration_client, key_id, secret, query=f"cursor={cursor}")

    assert r.status_code == 422, (why, r.text)
    assert r.json()["code"] == "invalid_cursor", why


async def test_a_cursor_whose_uuid_is_spelled_oddly_is_still_read(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """``UUID()`` accepts braced, undashed and ``urn:uuid:`` spellings.

    Accepting them and passing the raw string through would parse here and
    still fail in Postgres — the same 500 one layer down — so the canonical
    form is what gets returned. Nothing we issue looks like this; the point is
    that the normalisation is real and not an accident of our own output.
    """
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    minted = [
        await _credit(integration_client, admin_headers, merchant_id, "1.00") for _ in range(2)
    ]
    newest = (await _page(integration_client, key_id, secret, query="limit=1")).json()["items"][0]
    braced = f"{{{newest['transaction_id']}}}"
    payload = f"{newest['created_at']}|{braced}".encode()
    cursor = base64.urlsafe_b64encode(payload).decode().rstrip("=")

    r = await _page(integration_client, key_id, secret, query=f"cursor={cursor}")

    assert r.status_code == 200, r.text
    assert [i["transaction_id"] for i in r.json()["items"]] == [minted[0]]


async def test_limit_is_bounded_by_the_contract(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """Out of range is a refusal, not a silent clamp — the same rule the admin
    ledger route states, and for the same reason: a client that asked for 500
    and got 200 has no way to know."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)

    assert (await _page(integration_client, key_id, secret, query="limit=0")).status_code == 422
    assert (await _page(integration_client, key_id, secret, query="limit=201")).status_code == 422
    assert (await _page(integration_client, key_id, secret, query="limit=200")).status_code == 200


# ---------- signing and cost ----------


async def test_the_query_string_is_part_of_the_signature(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """This is the first endpoint with a query, so the fourth canonical field
    finally has a consumer: a signature over ``limit=1`` must not spend on
    ``limit=200``."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "1.00")

    headers = _signed(key_id, secret, path=TXN_PATH, query="limit=1")
    r = await integration_client.get(f"{TXN_PATH}?limit=200", headers=headers)

    assert r.status_code == 401, r.text
    assert r.json()["code"] == "invalid_credentials"


async def test_the_page_costs_a_fixed_number_of_queries(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    sql_counter: dict[str, int],
) -> None:
    """AGENTS.md §10: a list endpoint's cost must not scale with its page.

    One grouped ledger query plus one bounded lookup that maps the page's
    order references back to the reseller's own ids — never one per row.
    """
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "50.00")
    sku_id = _seed_sku(db_session)
    await db_session.commit()
    for n in range(6):
        placed = await _post_order(
            integration_client,
            key_id,
            secret,
            {"merchant_order_id": f"cost-{n}", "sku_id": sku_id, "expected_price": "1.07"},
        )
        assert placed.status_code == 201, placed.text

    sql_counter["n"] = 0
    small = await _page(integration_client, key_id, secret, query="limit=2")
    assert small.status_code == 200, small.text
    cost_small = sql_counter["n"]

    sql_counter["n"] = 0
    big = await _page(integration_client, key_id, secret, query="limit=200")
    assert big.status_code == 200, big.text
    cost_big = sql_counter["n"]

    assert len(big.json()["items"]) == 7
    assert cost_big == cost_small, (cost_small, cost_big)
