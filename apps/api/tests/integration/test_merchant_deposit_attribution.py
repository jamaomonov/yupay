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

**M3c Task 4 adds a fifth, and it is the one that moves order state.** A
settlement that brings an order to *full* is the end of that order, whoever
decided it, so leaving it ``fulfilling`` is the same lie Task 6 removed for the
automatic path. For that to be true the delivery has to be over — the admin
routes refuse a settled order with ``409 deposit_already_returned`` but **the
drain never did**, so fix round 1 refuses the settlement itself while a task is
open (``409 order_still_fulfilling``). The closure therefore lives at the
posting rather than in the button — the runbook's ``curl`` and M4's cabinet
reach the same function — and the last section here is what proves it, from
both directions: a full settlement closes, a partial does not, and finishing a
partial does.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import quote, urlencode

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
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
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.merchants.models import MerchantWebhookDelivery
from yupay.modules.orders.models import Order, OrderEvent, OrderItem
from yupay.modules.orders.service import list_stuck_paid_orders
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
    # The delivery has to have failed before anybody settles it: since M3c fix
    # round 1 an attributed credit is refused while a task is still open.
    await _fail_the_line(db_session, order_id)
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
    await _fail_the_line(db_session, order_id)
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
    await _fail_the_line(db_session, order_id)
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
    await _fail_the_line(db_session, order_id)
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
    await _fail_the_line(db_session, first_order)
    await _fail_the_line(db_session, second_order)

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


# ---------- M3c Task 4: a full settlement ends the order ----------


async def _order_row(db: AsyncSession, order_id: str) -> Order:
    return (await db.execute(select(Order).where(Order.id == order_id))).scalar_one()


async def _fail_the_line(db: AsyncSession, order_id: str) -> None:
    """Leave the order in the state a terminal supplier failure leaves it in.

    Written directly rather than driven through the saga because what this
    file is about is the **settlement**, not how the delivery died: the
    fulfilment side of that is ``test_merchant_auto_refund.py``'s subject and
    has a mock supplier for it. What matters here is the shape an operator
    meets — the item ``failed``, the **task** ``failed``, the order still
    ``fulfilling``, the money still gone — which is exactly what
    ``_apply_failure`` writes.

    **The task half was missing in the first version of this helper and that
    was the whole of fix round 1's Critical.** Failing only the item left every
    settlement test crediting an order whose task was still ``pending`` — the
    one state a settlement must now refuse, because the drain would go on to
    buy the goods for an order whose money had already gone back. A helper that
    builds a state the feature forbids is a helper that tests something else.
    """
    await db.execute(
        update(OrderItem).where(OrderItem.order_id == order_id).values(fulfillment_state="failed")
    )
    await db.execute(
        update(FulfillmentTask)
        .where(FulfillmentTask.order_id == order_id)
        .values(status="failed", last_error="supplier said no")
    )
    await db.commit()


@pytest.fixture
async def second_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A second connection — the worker, racing the operator.

    A lock is not observable from one session: two coroutines sharing a
    transaction see each other's uncommitted writes and take no locks against
    each other. Same shape as ``test_merchant_auto_refund``'s.
    """
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


async def _refunded(db: AsyncSession, merchant_id: str, order_id: str) -> Decimal:
    """What the ledger says has come back on this order."""
    from yupay.modules.merchants.deposit import refunded_for_order

    return await refunded_for_order(db, merchant_id=merchant_id, order_id=order_id)


async def _cancel_the_task(db: AsyncSession, order_id: str) -> None:
    """Cancel the delivery without failing the line — the other settleable shape.

    ``cancel_open_tasks_for_order`` leaves ``OrderItem.fulfillment_state``
    alone, so this is an order with nothing coming and **no failed item**: the
    state a settlement reads as ``order_failed`` rather than
    ``fulfillment_failed_refunded``.
    """
    await db.execute(
        update(FulfillmentTask)
        .where(FulfillmentTask.order_id == order_id)
        .values(status="cancelled")
    )
    await db.commit()


async def _failed_events(db: AsyncSession, order_id: str) -> list[OrderEvent]:
    return list(
        (
            await db.execute(
                select(OrderEvent)
                .where(OrderEvent.order_id == order_id, OrderEvent.kind == "order.failed")
                .order_by(OrderEvent.created_at, OrderEvent.id)
            )
        )
        .scalars()
        .all()
    )


async def test_a_full_settlement_closes_the_order(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The ruling: what ends an order is that the money is back, not who decided it.

    Task 6 made this true of the drain's automatic refund. The same is true of
    a settlement a person books: ``retry_task`` and ``complete_manual_task``
    both refuse a settled order with ``409 deposit_already_returned``, so every
    exit is closed while the state says "in progress" — and the five-minute
    stuck-order alert keeps firing about money that is already back.
    """
    merchant_id, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-settled"
    )
    await _fail_the_line(db_session, order_id)
    before = await _order_row(db_session, order_id)
    assert before.status == "fulfilling"

    assert (
        await _credit(integration_client, admin_headers, merchant_id, PRICE, order_id=order_id)
    ).status_code == 201

    after = await _order_row(db_session, order_id)
    await db_session.refresh(after)
    assert after.status == "failed"

    body = (await _read_order(integration_client, key_id, secret, "acme-settled")).json()
    assert body["status"] == "failed"
    # Not ``order_failed``: the precedence Task 6 fixed puts "your money is
    # back" ahead of "support closed this", and a hand settlement reaches it
    # for the same reason the drain does — the ledger, not the caller.
    assert body["failure_reason"] == "fulfillment_failed_refunded"
    assert body["refunded_usd"] == PRICE


async def test_a_partial_settlement_leaves_the_order_open(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """A sum is not a flag, and the reason is that **money is still owed**.

    Not that closing would take away a retry the operator was about to use:
    ``_refuse_a_settled_merchant_order`` already refuses ``retry_task`` and
    ``complete_manual_task`` on *any* returned amount, so a partially settled
    order lost its retry the moment the first cent landed. What is left is the
    rest of the charge, and that is a person mid-decision.
    """
    merchant_id, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-partial"
    )
    await _fail_the_line(db_session, order_id)

    assert (
        await _credit(integration_client, admin_headers, merchant_id, "0.01", order_id=order_id)
    ).status_code == 201

    row = await _order_row(db_session, order_id)
    await db_session.refresh(row)
    assert row.status == "fulfilling"
    body = (await _read_order(integration_client, key_id, secret, "acme-partial")).json()
    assert body["status"] == "fulfilling"
    assert body["refunded_usd"] == "0.01"


async def test_finishing_a_partial_settlement_closes_it(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Settling in stages is allowed, so the last stage has to be the one that ends it.

    The runbook tells an operator to credit the remainder under a **new** key,
    "and the state resolves itself". This is that sentence made true of the
    order row as well as of ``failure_reason``.
    """
    merchant_id, _key_id, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-staged"
    )
    await _fail_the_line(db_session, order_id)
    assert (
        await _credit(integration_client, admin_headers, merchant_id, "0.07", order_id=order_id)
    ).status_code == 201
    row = await _order_row(db_session, order_id)
    await db_session.refresh(row)
    assert row.status == "fulfilling"

    assert (
        await _credit(integration_client, admin_headers, merchant_id, "1.00", order_id=order_id)
    ).status_code == 201

    await db_session.refresh(row)
    assert row.status == "failed"


async def test_a_second_settlement_is_refused_and_nothing_moves_twice(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Double settlement is impossible from every surface, and says so in a code.

    ``order_already_settled`` predates this task; what is new is that the
    refusal now also protects an order that is already **closed**, so the
    second press cannot produce a second ``order.failed`` line on a timeline
    that is published to the reseller.
    """
    merchant_id, _key_id, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-twice"
    )
    await _fail_the_line(db_session, order_id)
    assert (
        await _credit(integration_client, admin_headers, merchant_id, PRICE, order_id=order_id)
    ).status_code == 201

    second = await _credit(integration_client, admin_headers, merchant_id, PRICE, order_id=order_id)

    assert second.status_code == 409, second.text
    assert second.json()["code"] == "order_already_settled"
    assert len(await _failed_events(db_session, order_id)) == 1


async def test_a_replay_of_the_settlement_closes_once(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """An operator's timeout retry replays the credit; it must not re-close.

    The closure is guarded by ``FAILABLE_STATUSES``, which a closed order is
    already outside — so this is idempotent for the same reason the credit is,
    and one order still shows one ending.
    """
    merchant_id, _key_id, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-replay"
    )
    await _fail_the_line(db_session, order_id)
    key = f"settle-{new_id()}"
    one = await _credit(
        integration_client, admin_headers, merchant_id, PRICE, order_id=order_id, key=key
    )
    two = await _credit(
        integration_client, admin_headers, merchant_id, PRICE, order_id=order_id, key=key
    )

    assert one.status_code == 201, one.text
    assert two.status_code == 201, two.text
    assert two.json()["transaction_id"] == one.json()["transaction_id"]
    row = await _order_row(db_session, order_id)
    await db_session.refresh(row)
    assert row.status == "failed"
    assert len(await _failed_events(db_session, order_id)) == 1


async def test_the_settled_order_leaves_the_stuck_order_watchdog(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The consequence the whole ruling is for, measured rather than assumed.

    ``list_stuck_paid_orders`` selects ``paid``/``fulfilling``/``fulfilled``
    with ``delivered_at IS NULL``, so a settled-but-open order matched it every
    five minutes for ever — an alert whose text is "Деньги у нас, товара у
    клиента нет" about money that is already back. The sibling is the control.
    """
    merchant_id, _key_id, _secret, settled_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-quiet-2"
    )
    _m2, _k2, _s2, open_id = await _placed(
        integration_client,
        admin_headers,
        db_session,
        merchant_order_id="beta-loud-2",
        title="Other",
        n=2,
    )
    await _fail_the_line(db_session, settled_id)
    assert (
        await _credit(integration_client, admin_headers, merchant_id, PRICE, order_id=settled_id)
    ).status_code == 201

    stuck = [o.id for o in await list_stuck_paid_orders(db_session, older_than_minutes=0)]

    assert settled_id not in stuck
    assert open_id in stuck


async def test_the_settlement_announces_the_order_state_by_push(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Task 6 corrected "money by push, order state by poll" — keep it corrected.

    The hand path already emitted ``balance.credited``; the closure routes
    through ``orders.service.on_order_status_changed``, the one seam, so
    ``order.status_changed`` follows it in the same transaction.
    """
    merchant_id, _key_id, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-push-2"
    )
    hook = await integration_client.put(
        f"/api/v1/admin/merchants/{merchant_id}/webhook",
        headers=admin_headers,
        json={"url": "https://reseller.example/hooks/yupay"},
    )
    assert hook.status_code == 200, hook.text
    await _fail_the_line(db_session, order_id)

    assert (
        await _credit(integration_client, admin_headers, merchant_id, PRICE, order_id=order_id)
    ).status_code == 201

    rows = list(
        (
            await db_session.execute(
                select(MerchantWebhookDelivery)
                .where(MerchantWebhookDelivery.merchant_id == merchant_id)
                .order_by(MerchantWebhookDelivery.created_at, MerchantWebhookDelivery.id)
            )
        )
        .scalars()
        .all()
    )
    assert [row.event_type for row in rows] == ["balance.credited", "order.status_changed"]
    assert rows[1].payload["status"] == "failed"
    assert rows[1].payload["merchant_order_id"] == "acme-push-2"


async def test_a_retail_order_cannot_be_settled_this_way_at_all(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Retail is out of reach of this path by scope, one layer above the closer.

    ``_resolve_order_reference`` matches ``Order.merchant_id == merchant_id``,
    so a storefront order is refused with the same ``404 order_not_found`` as
    an id that never existed — it never reaches the money, let alone the
    status. The row is re-read afterwards because "refused" and "left alone"
    are two claims.
    """
    merchant_id = await _new_merchant(integration_client, admin_headers, title="Reseller")
    retail = Order(
        id=new_id(),
        status="fulfilling",
        currency="USD",
        total_usd=Decimal("1.07"),
        total_charged=Decimal("1.07"),
        guest_email="buyer@example.com",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db_session.add(retail)
    await db_session.commit()

    refused = await _credit(
        integration_client, admin_headers, merchant_id, PRICE, order_id=retail.id
    )

    assert refused.status_code == 404, refused.text
    assert refused.json()["code"] == "order_not_found"
    await db_session.refresh(retail)
    assert retail.status == "fulfilling"


async def test_settling_an_order_whose_delivery_never_failed_reads_as_a_hand_closure(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The reason the reseller reads splits on the **item**, not on the credit.

    Nearly every attributed credit settles a failed delivery, and that reads
    ``fulfillment_failed_refunded``. The other settleable shape is an order
    whose delivery was **cancelled** rather than failed — nothing is coming,
    but no item is ``failed`` — and that closes the order too while reading
    ``order_failed``: a person ended it, the delivery did not. Pinned rather
    than left to be discovered, because it is the one place the two paths give
    a reseller different words for the same amount of money returned.

    Note what the setup can no longer be. This used to cancel nothing and
    settle a **live** order; since fix round 1 that is refused
    (``order_still_fulfilling``), because the drain would have gone on to buy
    the goods. Reaching this state now requires stopping the delivery first,
    which is the point of the refusal.
    """
    merchant_id, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-goodwill"
    )
    await _cancel_the_task(db_session, order_id)

    assert (
        await _credit(integration_client, admin_headers, merchant_id, PRICE, order_id=order_id)
    ).status_code == 201

    body = (await _read_order(integration_client, key_id, secret, "acme-goodwill")).json()
    assert body["status"] == "failed"
    assert body["failure_reason"] == "order_failed"
    assert body["refunded_usd"] == PRICE


# ---------- fix round 1: a live delivery blocks the settlement ----------


async def test_a_settlement_is_refused_while_the_delivery_is_still_coming(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The Critical, closed: the drain was never guarded, only Retry was.

    Three documents said "every way of delivering a settled order is already
    refused". ``retry_task`` and ``complete_manual_task`` carry
    ``_refuse_a_settled_merchant_order``; ``drain_pending_tasks`` claims on
    ``status == 'pending'`` alone. So a settlement could close the order, push
    ``order.status_changed`` to the reseller, and then have the worker buy the
    goods and write a ``Delivery`` they can read — goods and money out, with
    our own API asserting the opposite.

    The order below is exactly the state every settlement test used to build:
    placed, task ``pending``, nothing failed.
    """
    merchant_id, _key_id, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-live"
    )
    open_task = (
        await db_session.execute(
            select(FulfillmentTask.id).where(FulfillmentTask.order_id == order_id)
        )
    ).scalar_one()

    refused = await _credit(
        integration_client, admin_headers, merchant_id, PRICE, order_id=order_id
    )

    assert refused.status_code == 409, refused.text
    body = refused.json()
    assert body["code"] == "order_still_fulfilling"
    # Named, not implied: a bare 409 at 3am tells an operator nothing to do.
    assert body["open_task_ids"] == [open_task]
    assert "cancel the task first" in body["detail"]
    # And nothing moved: no credit, no closure.
    row = await _order_row(db_session, order_id)
    await db_session.refresh(row)
    assert row.status == "fulfilling"
    assert await _refunded(db_session, merchant_id, order_id) == Decimal("0")


async def test_the_refusal_lifts_once_the_delivery_has_stopped(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The control: the guard is about the task, not about settling at all.

    Without this the refusal could be a blanket "no" and the test above would
    still pass — which is how a guard becomes an outage.
    """
    merchant_id, _key_id, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-lifts"
    )
    assert (
        await _credit(integration_client, admin_headers, merchant_id, PRICE, order_id=order_id)
    ).status_code == 409

    await _fail_the_line(db_session, order_id)

    assert (
        await _credit(integration_client, admin_headers, merchant_id, PRICE, order_id=order_id)
    ).status_code == 201
    row = await _order_row(db_session, order_id)
    await db_session.refresh(row)
    assert row.status == "failed"


async def test_an_operators_timeout_retry_is_not_refused_by_the_new_guard(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Skipped on a replay, exactly as the over-settlement cap is.

    A retry under the same key books nothing, so refusing it would answer 409
    to a credit that already landed and turn the endpoint's idempotency off —
    the failure ``credit_deposit``'s replay read exists to prevent. Here the
    task is re-opened between the two calls, so the guard would fire on the
    second if it ran at all.
    """
    merchant_id, _key_id, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-idem"
    )
    await _fail_the_line(db_session, order_id)
    key = f"settle-{new_id()}"
    first = await _credit(
        integration_client, admin_headers, merchant_id, PRICE, order_id=order_id, key=key
    )
    assert first.status_code == 201, first.text

    # An admin re-drove the task after the settlement — the state the guard
    # refuses — and then the operator's client retried the original credit.
    await db_session.execute(
        update(FulfillmentTask).where(FulfillmentTask.order_id == order_id).values(status="pending")
    )
    await db_session.commit()

    replay = await _credit(
        integration_client, admin_headers, merchant_id, PRICE, order_id=order_id, key=key
    )

    assert replay.status_code == 201, replay.text
    assert replay.json()["transaction_id"] == first.json()["transaction_id"]


async def test_the_settlement_holds_the_task_so_the_drain_cannot_take_it(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    second_session: AsyncSession,
) -> None:
    """What makes the refusal total rather than advisory — over two connections.

    An unlocked read is a check-then-act: the guard looks, sees no open task,
    and a drainer claims one a millisecond later, between the check and the
    posting. ``lock_tasks_for_order`` takes ``FOR UPDATE`` on the order's task
    rows, and ``drain_pending_tasks`` claims with ``FOR UPDATE SKIP LOCKED`` —
    so while the settlement's transaction lives the drain **skips** this order
    rather than waiting on it. No deadlock, no window.

    Two real connections, because a lock is invisible from one: two coroutines
    on one session see each other's uncommitted writes and take no locks
    against each other at all.
    """
    _merchant_id, _key_id, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-lock"
    )
    task_id = (
        await db_session.execute(
            select(FulfillmentTask.id).where(FulfillmentTask.order_id == order_id)
        )
    ).scalar_one()

    # The settlement's half: hold the lock, uncommitted.
    from yupay.modules.merchants.deposit import _lock_order_for_settlement

    _order, open_tasks = await _lock_order_for_settlement(db_session, order_id=order_id)
    assert open_tasks == [task_id]

    # The drain's half, on its own connection, claiming exactly as the worker
    # does. It must find nothing rather than block.
    claimed = (
        (
            await second_session.execute(
                select(FulfillmentTask.id)
                .where(FulfillmentTask.status == "pending")
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )

    assert task_id not in claimed

    # And the **order** row is held too, which is the other half: it serialises
    # this settlement against `_try_settle_order` (which locks the same row
    # before writing `delivered`) and against a second concurrent credit.
    # `NOWAIT` turns "would block" into an error we can assert on instead of
    # hanging the suite.
    with pytest.raises(DBAPIError):
        await second_session.execute(
            select(Order.id).where(Order.id == order_id).with_for_update(nowait=True)
        )

    await db_session.rollback()
    await second_session.rollback()
