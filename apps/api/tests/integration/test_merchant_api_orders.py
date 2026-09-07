"""``POST /merchant/v1/orders`` — the money path (M2, Task 4; spec §8.4, §9.3, §9.5).

A reseller spends a real deposit and the order is born ``paid``. Everything
here runs against the *live* mounted app, so a failure is the shipped
surface's, and every money assertion is exact: a deposit that fell by
"about" the right amount is a bug nobody would notice until an invoice
disagreed.

The signature is rebuilt by hand from the module README rather than imported
from ``merchants.signing`` — same reason as ``test_merchant_api_read.py``: a
test that calls the implementation it is testing proves only that the
function is deterministic. Task 2's ``test_merchant_api_auth.py`` owns the
auth matrix; this module asserts the money.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, text, update
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
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.users.models import TelegramLink, User
from yupay.modules.wallet.models import WalletAccount, WalletPosting, WalletTransaction

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
ORDERS_PATH = "/merchant/v1/orders"


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
) -> None:
    r = await client.post(
        f"/api/v1/admin/merchants/{merchant_id}/deposit-credits",
        headers={**headers, "Idempotency-Key": f"credit-{new_id()}"},
        json={"amount": amount},
    )
    assert r.status_code == 201, r.text


def _signed(key_id: str, secret: str, *, method: str, path: str, body: bytes) -> dict[str, str]:
    """The three auth headers, transcribed from the module README by hand."""
    ts = str(int(time.time()))
    message = "\n".join((ts, method.upper(), path, "", hashlib.sha256(body).hexdigest())).encode()
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
    """Sign and send exactly the bytes we send — never a re-serialised body."""
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return await client.post(
        ORDERS_PATH,
        content=body,
        headers=_signed(key_id, secret, method="POST", path=ORDERS_PATH, body=body),
    )


# ---------- catalog seeding ----------


def _seed_sku(
    db: AsyncSession,
    *,
    n: int = 1,
    brand_visible_b2b: bool = True,
    required_fields: list[dict[str, Any]] | None = None,
    kind: str = "top_up",
    **sku_overrides: Any,
) -> str:
    """One category → brand → product → SKU chain. Returns the SKU id.

    Defaults are a b2b-visible, in-stock, $1.00-cost SKU at the stock 7%
    markup — ``merchant_price`` of ``"1.07"``.
    """
    category = Category(
        id=new_id(),
        slug=f"cat-{n}-{new_id()[:8]}",
        sort_order=n,
        active=True,
        translations=[CategoryTranslation(locale="ru", name=f"Категория {n}")],
    )
    brand = Brand(
        id=new_id(),
        slug=f"brand-{n}-{new_id()[:8]}",
        category_id=category.id,
        sort_order=n,
        active=True,
        visible_b2b=brand_visible_b2b,
        translations=[BrandTranslation(locale="ru", name=f"Бренд {n}")],
    )
    product = Product(
        id=new_id(),
        slug=f"product-{n}-{new_id()[:8]}",
        brand_id=brand.id,
        kind=kind,
        sort_order=n,
        active=True,
        required_fields=required_fields or [],
        translations=[ProductTranslation(locale="ru", name=f"Продукт {n}")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"sku-{n}-{new_id()[:8]}",
        denomination=sku_overrides.pop("denomination", f"{n}00 UC"),
        region="GLOBAL",
        price_usd=sku_overrides.pop("price_usd", Decimal("9.99")),
        cost_usdt=sku_overrides.pop("cost_usdt", Decimal("1.000000")),
        visible_b2b=sku_overrides.pop("visible_b2b", True),
        b2b_markup_pct=sku_overrides.pop("b2b_markup_pct", Decimal("7")),
        sort_order=0,
        active=sku_overrides.pop("active", True),
        **sku_overrides,
    )
    db.add_all([category, brand, product, sku])
    return sku.id


async def _seeded(db: AsyncSession, **kwargs: Any) -> str:
    sku_id = _seed_sku(db, **kwargs)
    await db.commit()
    return sku_id


async def _balance(db: AsyncSession, merchant_id: str) -> Decimal:
    from yupay.modules.merchants import api as merchants

    return await merchants.deposit_balance(db, merchant_id=merchant_id)


def _no_floats(raw: str) -> object:
    """``json.loads`` hook that refuses any JSON number — money is a string."""
    raise AssertionError(f"money must be a JSON string, got the number {raw}")


# ---------- happy path ----------


async def test_placing_an_order_debits_the_deposit_by_exactly_the_charged_price(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The whole flow: order born paid, deposit down by the exact price, task created."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "40.00")
    sku_id = await _seeded(db_session)

    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "acme-1", "sku_id": sku_id, "expected_price": "1.07"},
    )

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["merchant_order_id"] == "acme-1"
    assert body["sku_id"] == sku_id
    assert body["price_usd"] == "1.07"
    # 40.00 - 1.07, to the cent, not "about".
    assert body["balance_usd"] == "38.93"
    assert await _balance(db_session, merchant_id) == Decimal("38.93")

    order = (
        await db_session.execute(select(Order).where(Order.id == body["order_id"]))
    ).scalar_one()
    assert order.merchant_id == merchant_id
    assert order.user_id is None
    assert order.guest_email is None
    assert order.delivery_email is None
    assert order.purpose == "catalog"
    assert order.currency == "USD"
    assert order.total_usd == Decimal("1.07")
    assert order.total_charged == Decimal("1.07")
    assert order.paid_at is not None
    assert order.idempotency_key == "acme-1"
    # ``paid`` is a moment, not a resting place: fulfilment is enqueued inside
    # the same transaction, which flips the order to ``fulfilling``. A top-up
    # SKU with no supplier mapping routes to the manual admin queue.
    assert order.status == "fulfilling"
    assert body["status"] == "fulfilling"

    task = (
        await db_session.execute(
            select(FulfillmentTask).where(FulfillmentTask.order_id == order.id)
        )
    ).scalar_one()
    assert task.supplier == "manual"
    assert task.status == "pending"


async def test_fulfilment_is_enqueued_and_never_run_inside_the_money_transaction(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The supplier is never called from inside the transaction that took the money.

    With ``fulfilment_async`` off — its default in code, and the state of any
    environment that does not set ``FULFILMENT_ASYNC``, production's own value
    notwithstanding — ``start_for_order`` runs the supplier purchase inline. Anything raising
    after that and before the commit rolls back the order, the debit and the
    delivery while the supplier keeps the money, and the merchant then retries
    the same ``merchant_order_id``, finds nothing, and buys it twice. This path
    forces the queue on at the call site so that shape cannot occur.

    The precondition below is what makes this a real test rather than a
    tautology: it asserts the flag is genuinely off, so the ``pending`` task is
    the override's doing. Deleting ``settings=_enqueue_only()`` makes the
    fulfiller run and fails on both assertions.
    """
    from yupay.core.config import get_settings
    from yupay.modules.fulfillment.suppliers.manual import ManualFulfiller

    assert get_settings().fulfilment_async is False, (
        "this test is only meaningful while the flag defaults to off"
    )

    async def _never(**_kwargs: object) -> None:
        raise AssertionError("a supplier was called inside the money transaction")

    monkeypatch.setattr(ManualFulfiller, "fulfill", _never)

    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "10.00")
    sku_id = await _seeded(db_session)

    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "queued-1", "sku_id": sku_id, "expected_price": "1.07"},
    )

    assert r.status_code == 201, r.text
    assert r.json()["status"] == "fulfilling"
    task = (
        await db_session.execute(
            select(FulfillmentTask).where(FulfillmentTask.order_id == r.json()["order_id"])
        )
    ).scalar_one()
    assert task.status == "pending", "the task was executed inline, not enqueued"
    # The money landed regardless — the whole point is that the debit is
    # durable and the delivery is the worker's problem.
    assert await _balance(db_session, merchant_id) == Decimal("8.93")


async def test_the_deposit_charge_posts_the_readme_legs(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """``C merchant_deposit / D house_payments_received`` — the module README's table."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "10.00")
    sku_id = await _seeded(db_session)

    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "legs-1", "sku_id": sku_id, "expected_price": "1.07"},
    )
    assert r.status_code == 201, r.text

    rows = (
        await db_session.execute(
            select(WalletAccount.kind, WalletPosting.direction, WalletPosting.amount)
            .join(WalletPosting, WalletPosting.account_id == WalletAccount.id)
            .join(
                WalletTransaction,
                WalletTransaction.id == WalletPosting.transaction_id,
            )
            .where(WalletTransaction.kind == "merchant_order_charge")
        )
    ).all()
    assert sorted((kind, direction, str(amount)) for kind, direction, amount in rows) == [
        ("house_payments_received", "D", "1.070000"),
        ("merchant_deposit", "C", "1.070000"),
    ]


async def test_the_price_is_the_merchant_formula_and_not_the_retail_price(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The seam's whole point: ``price_usd`` is ``$9.99`` retail, ``$2.20`` wholesale."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "50.00")
    sku_id = await _seeded(
        db_session, price_usd=Decimal("9.99"), cost_usdt=Decimal("2"), b2b_markup_pct=Decimal("10")
    )

    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "priced-1", "sku_id": sku_id, "expected_price": "2.20"},
    )

    assert r.status_code == 201, r.text
    assert r.json()["price_usd"] == "2.20"
    item = (
        await db_session.execute(
            select(OrderItem).where(OrderItem.order_id == r.json()["order_id"])
        )
    ).scalar_one()
    assert item.unit_price_usd == Decimal("2.20")
    # The retail price never touched this order.
    assert item.unit_price_usd != Decimal("9.99")


async def test_fulfillment_data_reaches_the_order_item(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The merchant's end-customer identifier is transit-only, but it must arrive."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "10.00")
    sku_id = await _seeded(
        db_session,
        required_fields=[{"key": "player_id", "type": "text", "required": True}],
    )

    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {
            "merchant_order_id": "ff-1",
            "sku_id": sku_id,
            "expected_price": "1.07",
            "fulfillment_data": {"player_id": "5123456789"},
        },
    )

    assert r.status_code == 201, r.text
    item = (
        await db_session.execute(
            select(OrderItem).where(OrderItem.order_id == r.json()["order_id"])
        )
    ).scalar_one()
    assert item.fulfillment_data == {"player_id": "5123456789"}


async def test_a_malformed_body_answers_problem_json_and_not_a_500(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """A non-UUID ``sku_id`` — the likeliest integrator typo on this endpoint.

    Two things are pinned. The body is the RFC 7807 shape the module README
    publishes, where it used to be FastAPI's ``{"detail": [ ... ]}`` with no
    ``type`` and no ``code``. And it does not 500: pydantic puts the original
    ``ValueError`` **object** in ``ctx["error"]``, so a handler that reached
    for ``json.dumps`` instead of ``jsonable_encoder`` would turn this exact
    request into an unhandled server error.
    """
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)

    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "bad-1", "sku_id": "not-a-uuid", "expected_price": "1.07"},
    )

    assert r.status_code == 422, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["code"] == "invalid_request"
    assert body["errors"][0]["loc"] == ["body", "sku_id"]


async def test_a_missing_required_field_is_a_validation_error(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "10.00")
    sku_id = await _seeded(
        db_session,
        required_fields=[{"key": "player_id", "type": "text", "required": True}],
    )

    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "ff-2", "sku_id": sku_id, "expected_price": "1.07"},
    )

    assert r.status_code == 422, r.text
    assert await _balance(db_session, merchant_id) == Decimal("10.00")
    assert (await db_session.execute(select(Order))).scalars().all() == []


async def test_money_leaves_this_endpoint_as_a_string_never_a_float(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "10.00")
    sku_id = await _seeded(db_session)

    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "str-1", "sku_id": sku_id, "expected_price": "1.07"},
    )

    assert r.status_code == 201, r.text
    body = json.loads(r.text, parse_float=_no_floats, parse_int=_no_floats)
    assert body["price_usd"] == "1.07"
    assert body["balance_usd"] == "8.93"


async def test_expected_price_is_accepted_as_a_string_or_as_a_number(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The README asks for a string; a well-formed number is accepted anyway.

    Refusing ``1.07`` because it arrived unquoted would be a worse failure mode
    than accepting it — the number is exact at two decimals and unambiguous,
    and the merchant's intent is not in doubt. What we do *not* accept is more
    precision than a price has: ``1.075`` is refused in either spelling by
    ``decimal_places=2``, loudly, before anything is priced.

    Pinned in both spellings because "we happen to be lenient" and "we promise
    to be lenient" are different, and the README now says the second.
    """
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "10.00")
    sku_id = await _seeded(db_session)

    quoted = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "spell-1", "sku_id": sku_id, "expected_price": "1.07"},
    )
    bare = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "spell-2", "sku_id": sku_id, "expected_price": 1.07},
    )
    too_precise = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "spell-3", "sku_id": sku_id, "expected_price": "1.075"},
    )

    assert quoted.status_code == 201, quoted.text
    assert bare.status_code == 201, bare.text
    assert quoted.json()["price_usd"] == bare.json()["price_usd"] == "1.07"
    assert too_precise.status_code == 422, too_precise.text


# ---------- item_unavailable (404) ----------


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        pytest.param({"visible_b2b": False}, "not_b2b_visible", id="sku-not-b2b-visible"),
        pytest.param({"brand_visible_b2b": False}, "not_b2b_visible", id="brand-not-b2b-visible"),
        pytest.param({"cost_usdt": None}, "no_cost", id="no-wholesale-cost"),
        pytest.param({"supplier_stock": 0}, "out_of_stock", id="supplier-out-of-stock"),
        pytest.param({"active": False}, "not_for_sale", id="deactivated"),
        pytest.param(
            {
                # ``ck_skus_variable_amount_complete`` wants the whole set.
                "variable_amount": True,
                "min_amount_usd": Decimal("1"),
                "max_amount_usd": Decimal("100"),
                "rate_multiplier": Decimal("1.05"),
            },
            "variable_amount",
            id="variable-amount",
        ),
    ],
)
async def test_an_unsellable_sku_is_item_unavailable_and_says_why(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    overrides: dict[str, Any],
    reason: str,
) -> None:
    """Ruling 2: the 404 is the merchant's only warning, so it must be actionable."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "10.00")
    sku_id = await _seeded(db_session, **overrides)

    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "gone-1", "sku_id": sku_id, "expected_price": "1.07"},
    )

    assert r.status_code == 404, r.text
    body = r.json()
    assert body["code"] == "item_unavailable"
    assert body["reason"] == reason
    assert body["sku_id"] == sku_id
    assert await _balance(db_session, merchant_id) == Decimal("10.00")


async def test_an_unknown_sku_is_item_unavailable(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "10.00")

    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "gone-2", "sku_id": new_id(), "expected_price": "1.07"},
    )

    assert r.status_code == 404, r.text
    assert r.json()["code"] == "item_unavailable"
    assert r.json()["reason"] == "unknown_sku"


async def test_a_sku_id_that_is_not_a_uuid_is_refused_at_the_parse_boundary(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """``uuid = 'not-a-uuid'`` is a Postgres ``DataError``, i.e. a 500 where a
    clean rejection belongs — the same trap ``merchant_id=""`` was."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)

    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "bad-1", "sku_id": "not-a-uuid", "expected_price": "1.07"},
    )

    assert r.status_code == 422, r.text


# ---------- the ±2% drift rule (spec §8.4, amended by the owner 2026-09-07) ----------


async def test_a_price_below_ours_but_inside_the_band_is_still_charged_at_ours(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Spec §8.4 as amended: within ±2% the order executes at OUR price.

    Until 2026-09-07 this charged the lower of the two and the merchant kept
    the difference. The band decides whether the order proceeds; it has never
    decided anything else since.
    """
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "10.00")
    # cost 100, markup 7 → our price is 107.00; 105.90 is 1.03% below it.
    sku_id = await _seeded(db_session, cost_usdt=Decimal("100"))
    await _credit(integration_client, admin_headers, merchant_id, "200.00")

    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "drift-1", "sku_id": sku_id, "expected_price": "105.90"},
    )

    assert r.status_code == 201, r.text
    assert r.json()["price_usd"] == "107.00"
    # 210.00 credited, 107.00 charged — not 105.90, which would leave 104.10.
    assert await _balance(db_session, merchant_id) == Decimal("103.00")


async def test_quoting_the_full_two_percent_low_buys_at_our_price_and_takes_no_discount(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The standing giveaway the old rule allowed, pinned closed end to end.

    ``/catalog`` is live-computed and never cached, so a merchant can read our
    exact price and send ``current × 0.98`` on every order — drift is exactly
    the tolerance, so the band accepts. Under ``min(current, expected)`` that
    was a guaranteed 2% off wholesale, ~31% of the margin at the default 7%
    markup, bounded by nothing (the margin floor runs on our price, before the
    drift rule) and recorded nowhere. If this fails, the discount is back.
    """
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "200.00")
    # cost 100, markup 7 → our price is 107.00. 107.00 × 0.98 = 104.86.
    sku_id = await _seeded(db_session, cost_usdt=Decimal("100"))

    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "shaved-1", "sku_id": sku_id, "expected_price": "104.86"},
    )

    assert r.status_code == 201, r.text
    assert r.json()["price_usd"] == "107.00"
    assert r.json()["balance_usd"] == "93.00"
    # The deposit falls by our price, to the cent — 200.00 - 104.86 = 95.14 is
    # the number that must never come back.
    assert await _balance(db_session, merchant_id) == Decimal("93.00")
    item = (
        await db_session.execute(
            select(OrderItem).where(OrderItem.order_id == r.json()["order_id"])
        )
    ).scalar_one()
    assert item.unit_price_usd == Decimal("107.00")


async def test_a_price_above_ours_but_inside_the_band_still_charges_ours(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The other direction, unchanged by the amendment: we take no windfall either."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "210.00")
    sku_id = await _seeded(db_session, cost_usdt=Decimal("100"))

    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "drift-2", "sku_id": sku_id, "expected_price": "108.50"},
    )

    assert r.status_code == 201, r.text
    assert r.json()["price_usd"] == "107.00"
    assert await _balance(db_session, merchant_id) == Decimal("103.00")


@pytest.mark.parametrize("expected", ["104.00", "110.00"], ids=["too-low", "too-high"])
async def test_a_price_outside_the_band_is_price_changed_and_carries_the_current_price(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    expected: str,
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "500.00")
    sku_id = await _seeded(db_session, cost_usdt=Decimal("100"))

    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "drift-3", "sku_id": sku_id, "expected_price": expected},
    )

    assert r.status_code == 422, r.text
    body = r.json()
    assert body["code"] == "price_changed"
    assert body["current_price"] == "107.00"
    assert body["expected_price"] == expected
    assert await _balance(db_session, merchant_id) == Decimal("500.00")
    assert (await db_session.execute(select(Order))).scalars().all() == []


# ---------- margin floor (422) ----------


async def test_a_markup_below_the_margin_floor_is_refused(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """``0.5`` typed for ``5``: the price clears nothing, so the order is refused.

    The same setting ``price_list.build`` reads, so the catalog and the order
    path cannot disagree about which SKUs are sellable.
    """
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "10.00")
    sku_id = await _seeded(db_session, cost_usdt=Decimal("100"), b2b_markup_pct=Decimal("0.5"))

    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "floor-1", "sku_id": sku_id, "expected_price": "100.50"},
    )

    assert r.status_code == 422, r.text
    assert r.json()["code"] == "margin_floor"
    assert await _balance(db_session, merchant_id) == Decimal("10.00")
    assert (await db_session.execute(select(Order))).scalars().all() == []


# ---------- insufficient deposit (409) ----------


async def test_an_empty_deposit_is_refused_before_any_row_is_written(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    sku_id = await _seeded(db_session)

    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "broke-1", "sku_id": sku_id, "expected_price": "1.07"},
    )

    assert r.status_code == 409, r.text
    body = r.json()
    assert body["code"] == "insufficient_deposit"
    assert body["balance_usd"] == "0.00"
    assert body["required_usd"] == "1.07"
    # No orphan rows: not the order, not the ledger transaction.
    assert (await db_session.execute(select(Order))).scalars().all() == []
    assert (await db_session.execute(select(WalletTransaction))).scalars().all() == []


async def test_a_deposit_one_cent_short_is_refused(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "1.06")
    sku_id = await _seeded(db_session)

    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "broke-2", "sku_id": sku_id, "expected_price": "1.07"},
    )

    assert r.status_code == 409, r.text
    assert r.json()["code"] == "insufficient_deposit"
    assert await _balance(db_session, merchant_id) == Decimal("1.06")


async def test_a_deposit_exactly_equal_to_the_price_buys(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The guard is ``<``, not ``<=`` — spending your last cent is allowed."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "1.07")
    sku_id = await _seeded(db_session)

    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "exact-1", "sku_id": sku_id, "expected_price": "1.07"},
    )

    assert r.status_code == 201, r.text
    assert await _balance(db_session, merchant_id) == Decimal("0")


async def test_two_sequential_orders_cannot_overdraw_the_deposit(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "1.50")
    sku_id = await _seeded(db_session)

    first = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "seq-1", "sku_id": sku_id, "expected_price": "1.07"},
    )
    second = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "seq-2", "sku_id": sku_id, "expected_price": "1.07"},
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text
    assert second.json()["code"] == "insufficient_deposit"
    assert await _balance(db_session, merchant_id) == Decimal("0.43")


async def test_two_orders_in_flight_at_once_cannot_overdraw_the_deposit(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Two different ``merchant_order_id``s, so idempotency cannot be what saves us.

    End-to-end, through the real endpoint. It does not *prove* the lock — two
    ASGI requests on one event loop may well serialise before they reach it,
    and this passes with ``with_for_update()`` deleted — which is why
    ``test_a_concurrent_charge_waits_for_the_lock_instead_of_overdrawing``
    exists below and drives the guard where it actually binds. This one pins
    the shape a caller sees: one 201, one 409, and a balance that adds up.
    """
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "1.50")
    sku_id = await _seeded(db_session)

    first, second = await asyncio.gather(
        _post_order(
            integration_client,
            key_id,
            secret,
            {"merchant_order_id": "race-a", "sku_id": sku_id, "expected_price": "1.07"},
        ),
        _post_order(
            integration_client,
            key_id,
            secret,
            {"merchant_order_id": "race-b", "sku_id": sku_id, "expected_price": "1.07"},
        ),
    )

    statuses = sorted((first.status_code, second.status_code))
    assert statuses == [201, 409], f"{first.text} / {second.text}"
    assert await _balance(db_session, merchant_id) == Decimal("0.43")
    orders = (await db_session.execute(select(Order))).scalars().all()
    assert len(orders) == 1


async def test_a_concurrent_charge_waits_for_the_lock_instead_of_overdrawing(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    db_engine: Any,
) -> None:
    """Ruling 3: the ledger's own guard, driven where it binds.

    The interleave is written by hand rather than left to ``asyncio.gather``,
    because gather does not reliably produce it: two tasks on one event loop
    usually run to completion in turn, and the second then reads a balance the
    first has already committed — which is why the end-to-end race above
    passes with the lock deleted and proves nothing about it.

    Here session A holds the deposit row and has not committed. A charge on
    session B must **block** on that row, not read the stale pre-spend balance
    behind it. ``assert not task.done()`` is the whole test: without
    ``charge_deposit``'s ``SELECT … FOR UPDATE`` B sails past, sees $1.50,
    posts, and finishes — and the deposit ends up overdrawn.

    Falsified: deleting ``with_for_update()`` fails this on that assertion.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from yupay.core.errors import ConflictError
    from yupay.modules.merchants import api as merchants
    from yupay.modules.merchants.deposit import DEPOSIT_CURRENCY

    merchant_id = await _new_merchant(integration_client, admin_headers)
    # The credit through the admin route creates both wallet accounts, so the
    # two sessions below contend for the deposit row and nothing else.
    await _credit(integration_client, admin_headers, merchant_id, "1.50")
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    async def charge(session: AsyncSession) -> str:
        try:
            await merchants.charge_deposit(
                session, merchant_id=merchant_id, amount=Decimal("1.07"), order_id=new_id()
            )
            await session.commit()
        except ConflictError:
            await session.rollback()
            return "refused"
        return "charged"

    async with factory() as a, factory() as b:
        # A takes the row the guard locks, and holds it: an order of its own,
        # mid-transaction.
        await a.execute(
            select(WalletAccount)
            .where(
                WalletAccount.owner_type == "merchant",
                WalletAccount.owner_id == merchant_id,
                WalletAccount.kind == "merchant_deposit",
                WalletAccount.currency == DEPOSIT_CURRENCY,
            )
            .with_for_update()
        )
        pending = asyncio.create_task(charge(b))
        await asyncio.sleep(0.25)

        assert not pending.done(), "the second charge read the balance without waiting"

        assert await charge(a) == "charged"
        assert await pending == "refused"

    assert await _balance(db_session, merchant_id) == Decimal("0.43")


# ---------- replay (spec §9.3) ----------


async def test_a_replay_with_the_same_body_returns_the_same_order_and_debits_once(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "10.00")
    sku_id = await _seeded(db_session)
    payload = {"merchant_order_id": "replay-1", "sku_id": sku_id, "expected_price": "1.07"}

    first = await _post_order(integration_client, key_id, secret, payload)
    second = await _post_order(integration_client, key_id, secret, payload)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["order_id"] == second.json()["order_id"]
    assert await _balance(db_session, merchant_id) == Decimal("8.93")
    assert len((await db_session.execute(select(Order))).scalars().all()) == 1


async def test_a_replay_with_a_different_body_is_a_conflict(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "10.00")
    sku_id = await _seeded(db_session)
    other_sku_id = await _seeded(db_session, n=2)

    first = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "replay-2", "sku_id": sku_id, "expected_price": "1.07"},
    )
    second = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "replay-2", "sku_id": other_sku_id, "expected_price": "1.07"},
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text
    assert second.json()["code"] == "order_id_reused"
    assert await _balance(db_session, merchant_id) == Decimal("8.93")


async def test_the_same_order_id_from_two_merchants_is_two_orders(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Idempotency is scoped per merchant — they cannot see each other's keys."""
    sku_id = await _seeded(db_session)
    ids: list[str] = []
    for title in ("Acme", "Globex"):
        merchant_id = await _new_merchant(integration_client, admin_headers, title=title)
        key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
        await _credit(integration_client, admin_headers, merchant_id, "10.00")
        r = await _post_order(
            integration_client,
            key_id,
            secret,
            {"merchant_order_id": "shared-id", "sku_id": sku_id, "expected_price": "1.07"},
        )
        assert r.status_code == 201, r.text
        ids.append(r.json()["order_id"])

    assert ids[0] != ids[1]


async def test_two_concurrent_creates_with_one_key_make_one_order_and_one_debit(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The race resolves in ``uq_orders_idem_merchant``, not in code."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "10.00")
    sku_id = await _seeded(db_session)
    payload = {"merchant_order_id": "race-1", "sku_id": sku_id, "expected_price": "1.07"}

    first, second = await asyncio.gather(
        _post_order(integration_client, key_id, secret, payload),
        _post_order(integration_client, key_id, secret, payload),
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["order_id"] == second.json()["order_id"]
    orders = (await db_session.execute(select(Order))).scalars().all()
    assert len(orders) == 1
    charges = (
        (
            await db_session.execute(
                select(WalletTransaction).where(WalletTransaction.kind == "merchant_order_charge")
            )
        )
        .scalars()
        .all()
    )
    assert len(charges) == 1
    assert await _balance(db_session, merchant_id) == Decimal("8.93")


async def _wait_until_blocked_on_the_orders_insert(db: AsyncSession) -> None:
    """Block until another backend is waiting on a lock to INSERT into ``orders``.

    Polling ``pg_stat_activity`` rather than sleeping a guessed interval. A
    sleep would make the test *look* deterministic and quietly stop
    discriminating on a slow machine: if the request had not reached its
    INSERT yet, ``not loser.done()`` is true for the wrong reason, the winner
    commits, and the loser then finds it on a pre-check and never enters the
    branch under test. Waiting for the lock itself cannot degrade that way —
    either the wait appears, or the test fails saying it never did.

    Args:
        db: A session on the same database, used only to read the view.

    Raises:
        AssertionError: If no such wait appears within the deadline.
    """
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        # End the transaction each round. ``pg_stat_activity`` is snapshotted
        # once per transaction, so a session that holds one open re-reads the
        # same stale answer until the deadline and then fails on a wait that
        # did in fact happen.
        await db.rollback()
        waiting = (
            await db.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' AND query ILIKE 'INSERT INTO orders %'"
                )
            )
        ).scalar_one()
        if waiting:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(
        "no backend ever waited on a lock to insert into orders — the loser did "
        "not reach its INSERT, so this test would not be exercising the branch"
    )


async def test_a_duplicate_that_loses_the_unique_index_gets_the_winner_not_a_500(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    db_engine: Any,
) -> None:
    """The documented concurrent-replay branch in ``orders.place``, actually entered.

    The test above cannot reach it. Two ASGI requests on one event loop
    serialise, so the second one's *pre-check* finds the first order and
    returns from there — and even an interleave that commits the winner later
    is caught by ``create_order``'s own ``_existing_idempotent_order``. The
    branch that handles a genuine loss of the unique index — every pre-check
    missed, the INSERT violated, ``create_order`` rolled back and handed us
    the winner's row — had no test on this branch at all, which is how a
    ``500`` lived on the money endpoint through six task reviews.

    The interleave is written by hand, and it is the real one rather than a
    simulation of it: session W places the winning order and **does not
    commit**, so it holds the uncommitted ``(merchant_id, idempotency_key)``
    key. The loser then goes through the live endpoint, misses on both
    pre-checks (W's row is invisible), reaches its INSERT and **blocks** on
    W's key. That wait is read out of ``pg_stat_activity`` rather than waited
    for by a sleep, and it is what makes the rest of the test more than a
    re-run of the replay path. Committing W releases it into the unique
    violation, the rollback, and the branch.

    Before the fix the loser answered a bare ``500``. ``create_order``'s
    ``db.rollback()`` expires every object in the session's identity map — the
    authenticated ``Merchant`` included, since ``merchant_auth`` loaded it
    from that same session — so reading ``merchant.id`` on the way into
    ``_replayed`` triggers a lazy refresh, which under asyncio raises
    ``MissingGreenlet``. Nothing catches it: restore ``merchant.id`` in place
    of the captured ``merchant_id`` and this test does not even get a response
    object, because the ASGI transport re-raises out of the request.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from yupay.modules.merchants import api as merchants
    from yupay.modules.merchants.machine_schemas import MerchantOrderCreateIn
    from yupay.modules.merchants.models import Merchant

    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "10.00")
    sku_id = await _seeded(db_session)
    payload = {"merchant_order_id": "race-lost", "sku_id": sku_id, "expected_price": "1.07"}

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as winner:
        merchant = (
            await winner.execute(select(Merchant).where(Merchant.id == merchant_id))
        ).scalar_one()
        placed = await merchants.place_order(
            winner, merchant=merchant, body=MerchantOrderCreateIn.model_validate(payload)
        )
        await winner.flush()

        loser = asyncio.create_task(_post_order(integration_client, key_id, secret, payload))
        await _wait_until_blocked_on_the_orders_insert(db_session)
        assert not loser.done(), "the loser answered without waiting on the winner's key"

        await winner.commit()
        r = await loser

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["order_id"] == placed.order_id
    assert body["merchant_order_id"] == "race-lost"
    # One order and one debit: the loser rolled back and bought nothing.
    orders = (await db_session.execute(select(Order))).scalars().all()
    assert len(orders) == 1
    charges = (
        (
            await db_session.execute(
                select(WalletTransaction).where(WalletTransaction.kind == "merchant_order_charge")
            )
        )
        .scalars()
        .all()
    )
    assert len(charges) == 1
    assert body["balance_usd"] == "8.93"
    assert await _balance(db_session, merchant_id) == Decimal("8.93")


# ---------- the seam: retail cannot inject a price ----------


async def test_a_retail_actor_cannot_inject_a_unit_price_through_the_same_door(
    db_session: AsyncSession,
) -> None:
    """The override is honoured for a merchant actor and for nobody else."""
    from yupay.modules.orders.schemas import OrderCreate, OrderItemIn
    from yupay.modules.orders.service import Actor, create_order

    sku_id = _seed_sku(db_session)
    await db_session.commit()
    body = OrderCreate(
        currency="USD",
        items=[OrderItemIn(sku_id=sku_id, qty=1)],
        guest_email="buyer@example.com",
    )

    with pytest.raises(ValidationError, match="merchant"):
        await create_order(
            db_session,
            body,
            actor=Actor(user_id=None, email="buyer@example.com"),
            idempotency_key="retail-injection-attempt",
            unit_price_usd_override=(Decimal("0.01"),),
        )


async def test_a_retail_order_without_an_override_still_pays_the_retail_price(
    db_session: AsyncSession,
) -> None:
    """The seam is inert when nobody uses it — retail stays byte-identical."""
    from yupay.modules.orders.schemas import OrderCreate, OrderItemIn
    from yupay.modules.orders.service import Actor, create_order

    sku_id = _seed_sku(db_session, price_usd=Decimal("9.99"))
    await db_session.commit()

    order = await create_order(
        db_session,
        OrderCreate(
            currency="USD",
            items=[OrderItemIn(sku_id=sku_id, qty=1)],
            guest_email="buyer@example.com",
        ),
        actor=Actor(user_id=None, email="buyer@example.com"),
        idempotency_key="retail-normal-order",
    )

    assert order.total_usd == Decimal("9.99")
    assert order.items[0].unit_price_usd == Decimal("9.99")


async def test_an_override_must_carry_one_price_per_line(db_session: AsyncSession) -> None:
    from yupay.modules.merchants.models import Merchant
    from yupay.modules.orders.schemas import OrderCreate, OrderItemIn
    from yupay.modules.orders.service import Actor, create_order

    merchant = Merchant(id=new_id(), title="Acme")
    db_session.add(merchant)
    sku_id = _seed_sku(db_session)
    await db_session.commit()

    with pytest.raises(ValidationError, match="one unit price per line"):
        await create_order(
            db_session,
            OrderCreate(currency="USD", items=[OrderItemIn(sku_id=sku_id, qty=1)]),
            actor=Actor(user_id=None, email=None, merchant_id=merchant.id),
            idempotency_key="ragged-override",
            unit_price_usd_override=(Decimal("1.00"), Decimal("2.00")),
        )


async def test_a_merchant_order_refuses_an_affiliate_code(db_session: AsyncSession) -> None:
    """Carried constraint 2: a reseller must not stack a retail discount on wholesale.

    ``resolve_code`` is called with ``user_id=actor.user_id``, which is
    ``None`` on the merchant arm — so an affiliate code would resolve *like a
    guest's* and take a retail discount off an already-wholesale price.
    """
    from yupay.modules.merchants.models import Merchant
    from yupay.modules.orders.schemas import OrderCreate, OrderItemIn
    from yupay.modules.orders.service import Actor, create_order

    merchant = Merchant(id=new_id(), title="Acme")
    db_session.add(merchant)
    sku_id = _seed_sku(db_session)
    await db_session.commit()

    with pytest.raises(ValidationError, match="affiliate"):
        await create_order(
            db_session,
            OrderCreate(
                currency="USD",
                items=[OrderItemIn(sku_id=sku_id, qty=1)],
                affiliate_code="PARTNER10",
            ),
            actor=Actor(user_id=None, email=None, merchant_id=merchant.id),
            idempotency_key="merchant-with-affiliate",
            unit_price_usd_override=(Decimal("1.07"),),
        )


async def test_a_merchant_order_carries_no_affiliate_discount(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The wire has no ``affiliate_code`` field at all — pinned, not assumed."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "10.00")
    sku_id = await _seeded(db_session)

    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {
            "merchant_order_id": "aff-1",
            "sku_id": sku_id,
            "expected_price": "1.07",
            "affiliate_code": "PARTNER10",
        },
    )

    assert r.status_code == 422, r.text


# ---------- no mail, ever (spec §9.5) ----------


async def test_a_merchant_order_has_no_delivery_recipient_even_with_an_address_on_the_row(
    db_session: AsyncSession,
) -> None:
    """Carried constraint 5: the skip is explicit, not accidental.

    ``delivery_email`` is written NULL on every merchant order, so today the
    address lookup returns ``None`` by falling off the end. This test forces
    an address onto the row so only a deliberate merchant guard can pass it.
    """
    from datetime import UTC, datetime, timedelta

    from yupay.modules.merchants.models import Merchant
    from yupay.modules.notifications.service import _delivery_recipient

    merchant = Merchant(id=new_id(), title="Acme")
    db_session.add(merchant)
    await db_session.flush()
    order = Order(
        id=new_id(),
        merchant_id=merchant.id,
        status="paid",
        currency="USD",
        total_usd=Decimal("1.07"),
        total_charged=Decimal("1.07"),
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        delivery_email="reseller-customer@example.com",
    )
    db_session.add(order)
    await db_session.commit()

    assert await _delivery_recipient(db_session, order) is None


async def test_no_mail_is_attempted_when_a_merchant_order_is_delivered(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not "it happens not to fire": nothing may reach ``send_email`` at all."""
    from yupay.modules.notifications import service as notifications

    sent: list[object] = []

    async def _spy(**kwargs: object) -> None:
        sent.append(kwargs)

    monkeypatch.setattr(notifications, "send_email", _spy)
    # Without a ``web_base_url`` both senders no-op on their own, which would
    # make this test pass with the guard deleted.
    from yupay.core.config import get_settings

    configured = get_settings().model_copy(update={"web_base_url": "https://yupay.uz/ru"})
    monkeypatch.setattr(notifications, "get_settings", lambda: configured)

    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "10.00")
    sku_id = await _seeded(db_session)
    r = await _post_order(
        integration_client,
        key_id,
        secret,
        {"merchant_order_id": "mail-1", "sku_id": sku_id, "expected_price": "1.07"},
    )
    assert r.status_code == 201, r.text
    order_id = r.json()["order_id"]
    # Force an address onto the row. A merchant order is written with every
    # address column NULL, so without this the senders would no-op on their
    # own and this test would pass with the guard deleted — which is exactly
    # the "it happens not to fire" it exists to rule out.
    await db_session.execute(
        update(Order)
        .where(Order.id == order_id)
        .values(delivery_email="reseller-customer@example.com")
    )
    await db_session.commit()

    await notifications.notify_order_paid(order_id)
    await notifications.notify_order_delivered(order_id)

    assert sent == []
