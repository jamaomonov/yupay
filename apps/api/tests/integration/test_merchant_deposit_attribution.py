"""Deposit credits that name the order they settle (Merchant B2B M3b, Task 2).

M2 shipped ``refunded_usd`` on ``GET /merchant/v1/orders/{merchant_order_id}``
reading the ledger by *direction* — the debit legs on the merchant's
``merchant_deposit`` account across every transaction referencing the order —
so that whatever M3 called a refund would land there without a contract
change. It could not: ``credit_deposit``, the only surface that credits a
deposit, referenced the **merchant**, and the field filtered on the **order**.
``refunded_usd`` was ``"0.00"`` by construction, and the hand settlement
support performs after a failed delivery was invisible on the order it paid
for.

Four properties carry this file:

* **the attribution is real end to end** — a credit that names an order shows
  on that order's ``refunded_usd`` *and* reconciles on the statement, which
  are the two surfaces a reseller has;
* **it is additive** — a credit with no order is byte-for-byte the transaction
  it was before: same legs, same ``merchant`` reference, same null columns on
  ``/transactions``. Pinned, not merely left unbroken;
* **only the reference moves** — the posting table in the module README is the
  contract, and a credit's legs do not change because it gained a reference;
* **an order that is not this merchant's is refused exactly like one that
  never existed** — including an id that is not a UUID at all, which reaches a
  ``uuid`` column and used to be the shape of a 500.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from typing import Any
from urllib.parse import quote, urlencode

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
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
from yupay.modules.wallet.models import WalletAccount, WalletTransaction

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
ORDERS_PATH = "/merchant/v1/orders"
TXN_PATH = "/merchant/v1/transactions"

#: Cost $1.00 at 7% markup — the price every order below is placed at.
PRICE = "1.07"


# ---------- harness ----------


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
    """Log a Telegram user in and grant it the admin role."""
    user_json = json.dumps({"id": 96, "first_name": "Admin"}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await integration_client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == 96)
        )
    ).scalar_one()
    await db_session.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


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
    key_id: str = payload["key_id"]
    secret: str = payload["secret"]
    return key_id, secret


async def _credit(
    client: AsyncClient,
    headers: dict[str, str],
    merchant_id: str,
    amount: str,
    *,
    order_id: str | None = None,
    key: str | None = None,
) -> Response:
    """Post one deposit credit, optionally naming the order it settles."""
    body: dict[str, Any] = {"amount": amount}
    if order_id is not None:
        body["order_id"] = order_id
    return await client.post(
        f"/api/v1/admin/merchants/{merchant_id}/deposit-credits",
        headers={**headers, "Idempotency-Key": key or f"settle-{new_id()}"},
        json=body,
    )


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


async def _post_order(
    client: AsyncClient, key_id: str, secret: str, payload: dict[str, Any]
) -> Response:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return await client.post(
        ORDERS_PATH,
        content=body,
        headers=_signed(key_id, secret, method="POST", path=ORDERS_PATH, body=body),
    )


async def _read_order(
    client: AsyncClient, key_id: str, secret: str, merchant_order_id: str
) -> Response:
    path = f"{ORDERS_PATH}/{quote(merchant_order_id, safe='')}"
    return await client.get(path, headers=_signed(key_id, secret, path=path))


async def _statement(client: AsyncClient, key_id: str, secret: str) -> list[dict[str, Any]]:
    r = await client.get(TXN_PATH, headers=_signed(key_id, secret, path=TXN_PATH))
    assert r.status_code == 200, r.text
    items: list[dict[str, Any]] = r.json()["items"]
    return items


def _seed_sku(db: AsyncSession, *, n: int = 1) -> str:
    """One category → brand → product → SKU chain at $1.00 cost / 7% markup."""
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


async def _placed(
    client: AsyncClient,
    headers: dict[str, str],
    db: AsyncSession,
    *,
    merchant_order_id: str,
    title: str = "Reseller",
    n: int = 1,
) -> tuple[str, str, str, str]:
    """A merchant, a key, a funded deposit and one placed order.

    Returns ``(merchant_id, key_id, secret, order_id)``.
    """
    merchant_id = await _new_merchant(client, headers, title=title)
    key_id, secret = await _new_key(client, headers, merchant_id)
    assert (await _credit(client, headers, merchant_id, "10.00")).status_code == 201
    sku_id = _seed_sku(db, n=n)
    await db.commit()
    r = await _post_order(
        client,
        key_id,
        secret,
        {"merchant_order_id": merchant_order_id, "sku_id": sku_id, "expected_price": PRICE},
    )
    assert r.status_code == 201, r.text
    order_id: str = r.json()["order_id"]
    return merchant_id, key_id, secret, order_id


async def _txn(db: AsyncSession, transaction_id: str) -> WalletTransaction:
    return (
        await db.execute(
            select(WalletTransaction)
            .options(selectinload(WalletTransaction.postings))
            .where(WalletTransaction.id == transaction_id)
        )
    ).scalar_one()


async def _account_id(db: AsyncSession, *, owner_type: str, owner_id: str, kind: str) -> str:
    return (
        await db.execute(
            select(WalletAccount.id).where(
                WalletAccount.owner_type == owner_type,
                WalletAccount.owner_id == owner_id,
                WalletAccount.kind == kind,
            )
        )
    ).scalar_one()


def _legs(txn: WalletTransaction) -> dict[str, tuple[str, Decimal]]:
    return {p.account_id: (p.direction, p.amount) for p in txn.postings}


# ---------- the attribution ----------


async def test_a_credit_naming_an_order_lands_on_that_orders_refunded_usd(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The whole point: the settlement is visible where the merchant looks."""
    _merchant_id, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-1"
    )
    before = await _read_order(integration_client, key_id, secret, "acme-1")
    assert before.status_code == 200, before.text
    # The charge is a *credit* leg on a debit-normal account, so it is not
    # mistaken for money coming back.
    assert before.json()["refunded_usd"] == "0.00"

    credited = await _credit(
        integration_client, admin_headers, _merchant_id, PRICE, order_id=order_id
    )
    assert credited.status_code == 201, credited.text

    after = await _read_order(integration_client, key_id, secret, "acme-1")
    assert after.status_code == 200, after.text
    body = after.json()
    assert body["refunded_usd"] == PRICE
    assert body["price_usd"] == PRICE


async def test_a_credit_naming_an_order_reconciles_on_the_statement(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """``/transactions`` maps the reference back to the reseller's own id."""
    merchant_id, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme/ref/2"
    )
    assert (
        await _credit(integration_client, admin_headers, merchant_id, PRICE, order_id=order_id)
    ).status_code == 201

    settlement = next(
        row
        for row in await _statement(integration_client, key_id, secret)
        if row["kind"] == "merchant_deposit_credit" and row["amount_usd"] == PRICE
    )
    assert settlement["order_id"] == order_id
    assert settlement["merchant_order_id"] == "acme/ref/2"


async def test_the_credit_response_echoes_the_order_it_was_booked_against(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Read off the transaction, like ``amount`` — so a replay cannot lie."""
    merchant_id, _key_id, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-3"
    )
    r = await _credit(integration_client, admin_headers, merchant_id, PRICE, order_id=order_id)
    assert r.status_code == 201, r.text
    assert r.json()["order_id"] == order_id


# ---------- additive: a credit with no order is what it always was ----------


async def test_a_credit_without_an_order_is_unchanged(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Same legs, same ``merchant`` reference, same null statement columns."""
    merchant_id, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-4"
    )
    r = await _credit(integration_client, admin_headers, merchant_id, "500.00")
    assert r.status_code == 201, r.text
    assert r.json()["order_id"] is None

    txn = await _txn(db_session, r.json()["transaction_id"])
    assert txn.kind == "merchant_deposit_credit"
    assert txn.reference_type == "merchant"
    assert txn.reference_id == merchant_id
    deposit_account = await _account_id(
        db_session, owner_type="merchant", owner_id=merchant_id, kind="merchant_deposit"
    )
    house = await _account_id(
        db_session, owner_type="house", owner_id="house", kind="house_payments_received"
    )
    assert _legs(txn) == {
        deposit_account: ("D", Decimal("500.00")),
        house: ("C", Decimal("500.00")),
    }

    row = next(
        item
        for item in await _statement(integration_client, key_id, secret)
        if item["transaction_id"] == txn.id
    )
    assert row["order_id"] is None
    assert row["merchant_order_id"] is None

    # And it does not leak onto the order that happens to exist.
    read = await _read_order(integration_client, key_id, secret, "acme-4")
    assert read.json()["refunded_usd"] == "0.00"
    assert order_id  # placed, charged, and still unrefunded


async def test_naming_an_order_moves_the_reference_and_nothing_else(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The README's posting table is the contract; a reference is not a leg."""
    merchant_id, _key_id, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-5"
    )
    plain = await _credit(integration_client, admin_headers, merchant_id, PRICE)
    attributed = await _credit(
        integration_client, admin_headers, merchant_id, PRICE, order_id=order_id
    )
    assert plain.status_code == 201, plain.text
    assert attributed.status_code == 201, attributed.text

    one = await _txn(db_session, plain.json()["transaction_id"])
    two = await _txn(db_session, attributed.json()["transaction_id"])
    assert one.kind == two.kind == "merchant_deposit_credit"
    assert _legs(one) == _legs(two)
    assert (one.reference_type, one.reference_id) == ("merchant", merchant_id)
    assert (two.reference_type, two.reference_id) == ("order", order_id)


# ---------- scope: the order must be this merchant's ----------


async def test_another_merchants_order_is_refused_exactly_like_a_nonexistent_one(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """No oracle: the refusal must not confirm somebody else's order exists."""
    _theirs, _key, _secret, their_order = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="theirs-1", title="A", n=1
    )
    mine = await _new_merchant(integration_client, admin_headers, title="B")

    poached = await _credit(integration_client, admin_headers, mine, PRICE, order_id=their_order)
    invented = await _credit(integration_client, admin_headers, mine, PRICE, order_id=new_id())

    assert poached.status_code == 404, poached.text
    assert invented.status_code == 404, invented.text
    assert poached.json() == invented.json()
    assert poached.json()["code"] == "order_not_found"


async def test_an_order_id_that_is_not_a_uuid_is_the_same_refusal_not_a_500(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """It reaches a ``uuid`` column. ``{braced}`` is a real .NET spelling."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    invented = await _credit(
        integration_client, admin_headers, merchant_id, PRICE, order_id=new_id()
    )
    for bad in ("not-a-uuid", "", "0198c3d1", f"{{{new_id()}}}", "\x00"):
        r = await _credit(integration_client, admin_headers, merchant_id, PRICE, order_id=bad)
        assert r.status_code == 404, (bad, r.status_code, r.text)
        assert r.json() == invented.json(), bad


async def test_a_refused_credit_books_nothing(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """A 404 must not leave a transaction or a balance behind."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    assert (
        await _credit(integration_client, admin_headers, merchant_id, PRICE, order_id=new_id())
    ).status_code == 404

    assert (await db_session.execute(select(WalletTransaction.id))).scalars().all() == []
    listing = await integration_client.get("/api/v1/admin/merchants", headers=admin_headers)
    assert listing.status_code == 200, listing.text
    row = next(m for m in listing.json()["items"] if m["id"] == merchant_id)
    # Compared as a number: a merchant with no ``merchant_deposit`` account at
    # all reads ``Decimal("0")``, which the admin list serialises unscaled.
    assert Decimal(row["deposit_balance"]) == Decimal("0")


# ---------- replay ----------


async def test_a_replay_keeps_the_first_attribution(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The ledger replays by key without comparing parameters.

    A second call under one key books nothing, so it cannot re-point the first
    transaction at another order — and the response says so, the same way it
    already does for a mismatched ``amount``.
    """
    merchant_id, key_id, secret, first_order = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-6"
    )
    sku_id = _seed_sku(db_session, n=2)
    await db_session.commit()
    second = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "acme-7", "sku_id": sku_id, "expected_price": PRICE},
    )
    assert second.status_code == 201, second.text
    second_order: str = second.json()["order_id"]

    key = f"settle-{new_id()}"
    one = await _credit(
        integration_client, admin_headers, merchant_id, PRICE, order_id=first_order, key=key
    )
    two = await _credit(
        integration_client, admin_headers, merchant_id, PRICE, order_id=second_order, key=key
    )
    assert one.status_code == 201, one.text
    assert two.status_code == 201, two.text
    assert two.json()["transaction_id"] == one.json()["transaction_id"]
    assert two.json()["order_id"] == first_order

    assert (await _read_order(integration_client, key_id, secret, "acme-6")).json()[
        "refunded_usd"
    ] == PRICE
    assert (await _read_order(integration_client, key_id, secret, "acme-7")).json()[
        "refunded_usd"
    ] == "0.00"
