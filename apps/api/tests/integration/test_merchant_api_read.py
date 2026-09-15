"""The machine API's two read endpoints (M2, Task 3; spec §9.1).

``GET /merchant/v1/me`` and ``GET /merchant/v1/catalog``, end to end against
the real mounted app — the prefix is mounted by ``bootstrap``, not by the
test, so a failure here is the shipped surface's.

The signature is rebuilt by hand from the module README rather than imported
from ``merchants.signing``: a test that calls the implementation it is
testing proves only that the function is deterministic. Task 2's
``test_merchant_api_auth.py`` owns the auth *matrix*; this module asserts only
that each new endpoint sits behind the dependency at all (401 unsigned, 403
frozen), and then spends itself on the two contracts.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import delete, event, select, update
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
from yupay.modules.gifts.checkout import STEAM_GIFT_SKU_CODE
from yupay.modules.merchants.models import Merchant
from yupay.modules.merchants.pricing import merchant_price
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
ME_PATH = "/merchant/v1/me"
CATALOG_PATH = "/merchant/v1/catalog"


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
    user_json = json.dumps({"id": 91, "first_name": "Admin"}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await integration_client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == 91)
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
    client: AsyncClient, headers: dict[str, str], merchant_id: str, amount: str, key: str
) -> None:
    r = await client.post(
        f"/api/v1/admin/merchants/{merchant_id}/deposit-credits",
        headers={**headers, "Idempotency-Key": key},
        json={"amount": amount},
    )
    assert r.status_code == 201, r.text


def _signed(
    key_id: str, secret: str, *, method: str = "GET", path: str, query: str = ""
) -> dict[str, str]:
    """The three auth headers, transcribed from the module README by hand."""
    ts = str(int(time.time()))
    message = "\n".join((ts, method.upper(), path, query, hashlib.sha256(b"").hexdigest())).encode()
    return {
        "X-Merchant-Key": key_id,
        "X-Merchant-Timestamp": ts,
        "X-Merchant-Signature": hmac.new(
            secret.encode("utf-8"), message, hashlib.sha256
        ).hexdigest(),
    }


async def _get(
    client: AsyncClient, key_id: str, secret: str, path: str, query: str = ""
) -> Response:
    url = f"{path}?{query}" if query else path
    return await client.get(url, headers=_signed(key_id, secret, path=path, query=query))


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


# ---------- catalog seeding ----------


def _seed_brand(
    db: AsyncSession,
    *,
    n: int,
    brand_visible_b2b: bool = True,
    brand_active: bool = True,
    skus: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """One category → brand → product → SKUs unit. Returns the ids by role.

    ``skus`` entries carry ``sku_code`` plus any ``Sku`` overrides; the
    defaults are a b2b-visible SKU with a cost and the stock 7% markup.
    """
    category = Category(
        id=new_id(),
        slug=f"cat-{n}",
        sort_order=n,
        active=True,
        translations=[CategoryTranslation(locale="ru", name=f"Категория {n}")],
    )
    brand = Brand(
        id=new_id(),
        slug=f"brand-{n}",
        category_id=category.id,
        sort_order=n,
        active=brand_active,
        visible_b2b=brand_visible_b2b,
        translations=[BrandTranslation(locale="ru", name=f"Бренд {n}")],
    )
    product = Product(
        id=new_id(),
        slug=f"product-{n}",
        brand_id=brand.id,
        kind="top_up",
        sort_order=n,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name=f"Продукт {n}")],
    )
    ids = {"category": category.id, "brand": brand.id, "product": product.id}
    rows: list[Any] = [category, brand, product]
    for i, spec in enumerate(skus or [{"sku_code": f"sku-{n}"}]):
        overrides = dict(spec)
        code = overrides.pop("sku_code")
        sku = Sku(
            id=new_id(),
            product_id=product.id,
            sku_code=code,
            denomination=overrides.pop("denomination", f"{n}00 UC"),
            region="GLOBAL",
            price_usd=Decimal("9.99"),
            cost_usdt=overrides.pop("cost_usdt", Decimal("1.000000")),
            visible_b2b=overrides.pop("visible_b2b", True),
            b2b_markup_pct=overrides.pop("b2b_markup_pct", Decimal("7")),
            sort_order=i,
            active=True,
            **overrides,
        )
        ids[code] = sku.id
        rows.append(sku)
    db.add_all(rows)
    return ids


def _no_floats(raw: str) -> object:
    """``json.loads`` hook that refuses any JSON number.

    Money on this surface is a string end to end (AGENTS.md §9). A float would
    round-trip through IEEE-754 on the merchant's side, which is how a price
    becomes 1.0599999999999999.
    """
    raise AssertionError(f"money must be a JSON string, got the number {raw}")


def _skus_of(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten the brands → products → skus tree, keyed by ``sku_code``."""
    return {
        sku["sku_code"]: sku
        for brand in body["brands"]
        for product in brand["products"]
        for sku in product["skus"]
    }


# ---------- every endpoint sits behind the dependency ----------
#
# Enumerated from the mounted app, not listed by hand: a Task 4/5 endpoint
# added to the router without ``merchant_auth`` would pass a list-driven test
# by simply not being in the list. The same shape as
# ``test_affiliate_routes``' admin-gate sweep.


def _machine_calls() -> list[tuple[str, str]]:
    """``(method, concrete path)`` for every route under ``/merchant/v1``.

    Path parameters are filled with a placeholder: authentication runs in a
    dependency, before the handler and before body parsing, so a nonexistent
    id still proves the gate.
    """
    from fastapi.routing import APIRoute
    from yupay.bootstrap import create_app

    calls: list[tuple[str, str]] = []
    for route in create_app().routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/merchant/v1"):
            continue
        # Every method, not just the first: one path registered for both GET
        # and POST would otherwise be half-swept.
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            calls.append((method, re.sub(r"\{[^}]+\}", "placeholder", route.path)))
    assert calls, "no /merchant/v1 routes found — the enumeration is wrong"
    return calls


async def test_the_sweep_enumerates_every_endpoint_the_machine_api_ships() -> None:
    """The sweep above is only a gate if it actually sees the new routes.

    ``_machine_calls`` fills path parameters with a placeholder by regex, so a
    route declared with a Starlette convertor
    (``{merchant_order_id:path}`` — see Task 5's order read, which needs it
    because ``merchant_order_id`` may contain a ``/``) has to survive that
    substitution. This pins the whole enumeration rather than trusting it: add
    an endpoint and this fails until the list says so, which is the moment to
    check the 401/403 sweeps still cover it.

    ``async`` despite awaiting nothing: the module carries
    ``pytestmark = pytest.mark.asyncio``, and a sync function under it is a
    ``PytestWarning``, not a passing test with a quirk.
    """
    assert set(_machine_calls()) == {
        ("GET", "/merchant/v1/me"),
        ("GET", "/merchant/v1/catalog"),
        ("POST", "/merchant/v1/orders"),
        ("GET", "/merchant/v1/orders/placeholder"),
        ("GET", "/merchant/v1/transactions"),
        ("POST", "/merchant/v1/validate/player"),
    }


async def test_no_machine_endpoint_answers_an_unsigned_request(
    integration_client: AsyncClient,
) -> None:
    for method, path in _machine_calls():
        r = await integration_client.request(method, path)

        assert r.status_code == 401, f"{method} {path}: {r.text}"
        assert r.json()["code"] == "missing_credentials", f"{method} {path}: {r.text}"


async def test_no_machine_endpoint_answers_a_frozen_merchant(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    r = await integration_client.post(
        f"/api/v1/admin/merchants/{merchant_id}/freeze", headers=admin_headers
    )
    assert r.status_code == 200, r.text

    for method, path in _machine_calls():
        r = await integration_client.request(
            method, path, headers=_signed(key_id, secret, method=method, path=path)
        )

        assert r.status_code == 403, f"{method} {path}: {r.text}"
        assert r.json()["code"] == "merchant_frozen", f"{method} {path}: {r.text}"


# ---------- GET /me ----------


async def test_me_returns_the_profile_of_the_signing_merchant(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers, title="Acme Resale")
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)

    r = await _get(integration_client, key_id, secret, ME_PATH)

    assert r.status_code == 200, r.text
    assert r.json() == {
        "merchant_id": merchant_id,
        "title": "Acme Resale",
        "status": "active",
        "balance_usd": "0.00",
    }


async def test_me_balance_is_the_ledgers_signed_sum_of_every_credit(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """Ruling 5: the balance is the posting sum, not a column."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(integration_client, admin_headers, merchant_id, "40.00", "read-test-credit-one")
    await _credit(integration_client, admin_headers, merchant_id, "2.50", "read-test-credit-two")

    r = await _get(integration_client, key_id, secret, ME_PATH)

    assert r.status_code == 200, r.text
    assert r.json()["balance_usd"] == "42.50"


async def test_me_never_shows_another_merchants_money(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    mine = await _new_merchant(integration_client, admin_headers, title="Mine")
    theirs = await _new_merchant(integration_client, admin_headers, title="Theirs")
    key_id, secret = await _new_key(integration_client, admin_headers, mine)
    await _credit(integration_client, admin_headers, theirs, "500.00", "read-test-their-credit")

    r = await _get(integration_client, key_id, secret, ME_PATH)

    assert r.status_code == 200, r.text
    assert r.json()["merchant_id"] == mine
    assert r.json()["balance_usd"] == "0.00"


async def test_me_serialises_money_as_a_string_never_a_float(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    await _credit(
        integration_client, admin_headers, merchant_id, "10.10", "read-test-credit-string"
    )

    r = await _get(integration_client, key_id, secret, ME_PATH)

    # Parsed with ``parse_float`` disabled: if the wire carried a JSON number
    # the loader would raise rather than quietly hand back a float.
    raw = json.loads(r.text, parse_float=_no_floats, parse_int=_no_floats)
    assert raw["balance_usd"] == "10.10"


# ---------- GET /catalog ----------


async def test_catalog_returns_the_b2b_visible_tree(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    ids = _seed_brand(db_session, n=1, skus=[{"sku_code": "vis-1", "denomination": "60 UC"}])
    await db_session.commit()

    r = await _get(integration_client, key_id, secret, CATALOG_PATH)

    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["brands"]) == 1
    brand = body["brands"][0]
    assert brand["brand_id"] == ids["brand"]
    assert brand["slug"] == "brand-1"
    assert brand["name"] == "Бренд 1"
    assert len(brand["products"]) == 1
    product = brand["products"][0]
    assert product["product_id"] == ids["product"]
    assert product["slug"] == "product-1"
    assert product["name"] == "Продукт 1"
    assert len(product["skus"]) == 1
    sku = product["skus"][0]
    # Exact shape, not a subset: this is a frozen third-party contract, and a
    # field added to ``MerchantSkuOut`` would otherwise be caught only by the
    # OpenAPI drift check. Same reason ``/me`` asserts its whole body.
    assert set(sku) == {
        "sku_id",
        "sku_code",
        "name",
        "kind",
        "price_usd",
        "retail_price_usd",
        "unit_price_usd",
        "unit",
        "min_qty",
        "max_qty",
        "min_amount_usd",
        "max_amount_usd",
        "updated_at",
    }
    assert set(product) == {"product_id", "slug", "name", "required_fields", "skus"}
    # The seeded product asks for nothing; the field exists either way, so a
    # client reads one shape rather than branching on whether a key is there.
    assert product["required_fields"] == []
    # M4 added four: the cabinet groups its catalog by section and draws the
    # brand's artwork, and both come from here rather than from a second
    # endpoint the two surfaces could disagree with. Additive, which v1
    # allows — what this set still catches is a rename or a removal.
    assert set(brand) == {
        "brand_id",
        "slug",
        "name",
        "category_slug",
        "category_name",
        "logo_url",
        "hero_image_url",
        "products",
    }
    # The seeded brand has a category and no artwork, which is the shape most
    # of the real catalog is in today.
    assert brand["category_slug"] is not None
    assert brand["logo_url"] is None
    assert set(body) == {"brands"}
    assert sku["sku_id"] == ids["vis-1"]
    assert sku["sku_code"] == "vis-1"
    assert sku["name"] == "60 UC"
    # A fixed denomination: one price, and the unit half of the row empty.
    # Both halves are always present as keys — a client branching on `kind`
    # should not also have to branch on whether a field exists.
    assert sku["kind"] == "fixed"
    assert isinstance(sku["price_usd"], str)
    # The storefront's own price for the same thing — public either way, and
    # the reference the wholesale price is a discount against.
    assert sku["retail_price_usd"] == "9.99"
    assert sku["unit_price_usd"] is None
    assert sku["unit"] is None
    assert sku["min_qty"] is None
    assert sku["max_qty"] is None
    assert sku["min_amount_usd"] is None
    assert sku["max_amount_usd"] is None
    assert sku["updated_at"]


async def test_the_catalog_publishes_the_form_a_product_expects(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """What `fulfillment_data` takes, from the catalog rather than from prose.

    The machine API has always said the field is required without saying what
    goes in it, so every new product was a documentation round trip before a
    reseller could sell it. The pattern travels too: a bad player id can be
    refused in their own UI instead of costing a 422.

    Junk is skipped rather than 500ing the whole catalog — this column is JSONB
    written by an admin form and by the G2B importer, so a malformed row is a
    data problem and not every merchant's problem.
    """
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    ids = _seed_brand(db_session, n=9, skus=[{"sku_code": "ff-100"}])
    product = await db_session.get(Product, ids["product"])
    assert product is not None
    product.required_fields = [
        {
            "key": "player_id",
            "type": "text",
            "required": True,
            "label": {"ru": "ID игрока", "en": "Player ID"},
            "placeholder": {"ru": "12345678"},
            "pattern": "^[0-9]{6,20}$",
        },
        {"type": "text", "label": {"ru": "без ключа"}},
    ]
    await db_session.commit()

    r = await _get(integration_client, key_id, secret, CATALOG_PATH)

    assert r.status_code == 200, r.text
    fields = r.json()["brands"][0]["products"][0]["required_fields"]
    assert [f["key"] for f in fields] == ["player_id"], "a field with no key is not a field"
    assert fields[0]["required"] is True
    assert fields[0]["pattern"] == "^[0-9]{6,20}$"
    assert fields[0]["label"]["ru"] == "ID игрока"
    assert fields[0]["placeholder"] == {"ru": "12345678"}


async def test_catalog_prices_a_unit_sku_by_the_unit(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The shape a currency sold by the unit takes — G-Engine's UNFIXED.

    The number matters as much as the shape. One Telegram Star costs
    $0.015455; at the stock 7% markup the honest per-unit price is $0.016537,
    and rounding it to the cent — which is what the price list did before
    there was a unit shape — publishes $0.02, a 29% markup and more than our
    own retail price of $0.0191. A thousand Stars at the published rate is
    $16.54; at the rounded one it was $20.00.
    """
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    _seed_brand(
        db_session,
        n=7,
        skus=[
            {
                "sku_code": "stars-1",
                "denomination": "Любое количество",
                "cost_usdt": Decimal("0.015455"),
                "amount_unit": "stars",
                "min_qty": 50,
                "max_qty": 50_000,
            }
        ],
    )
    await db_session.commit()

    r = await _get(integration_client, key_id, secret, CATALOG_PATH)
    assert r.status_code == 200, r.text
    sku = r.json()["brands"][0]["products"][0]["skus"][0]

    assert sku["kind"] == "unit"
    assert sku["unit_price_usd"] == "0.016537"
    assert sku["retail_price_usd"] == "9.99"
    assert sku["price_usd"] is None, "a unit SKU has no price until a quantity is chosen"
    assert sku["unit"] == "stars"
    assert sku["min_qty"] == 50
    assert sku["max_qty"] == 50_000


async def test_catalog_hides_skus_that_are_not_b2b_visible(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    _seed_brand(
        db_session,
        n=1,
        skus=[
            {"sku_code": "shown"},
            {"sku_code": "hidden-sku", "visible_b2b": False},
        ],
    )
    await db_session.commit()

    r = await _get(integration_client, key_id, secret, CATALOG_PATH)

    assert r.status_code == 200, r.text
    assert set(_skus_of(r.json())) == {"shown"}


async def test_catalog_hides_every_sku_of_a_retail_only_brand(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Effective visibility is ``brand.visible_b2b AND sku.visible_b2b``."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    _seed_brand(db_session, n=1, skus=[{"sku_code": "shown"}])
    _seed_brand(db_session, n=2, brand_visible_b2b=False, skus=[{"sku_code": "retail-only-brand"}])
    await db_session.commit()

    r = await _get(integration_client, key_id, secret, CATALOG_PATH)

    assert r.status_code == 200, r.text
    assert set(_skus_of(r.json())) == {"shown"}
    assert [b["slug"] for b in r.json()["brands"]] == ["brand-1"]


async def test_a_variable_amount_sku_is_listed_as_a_dollar_balance(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The third shape: a balance loaded in dollars (the Steam wallet).

    This used to assert the opposite — that such a SKU is withheld, because
    "cost × markup has nothing to work on". That was true of retail's pricing,
    where the margin is a spread on the exchange rate, and it stopped being
    true once B2B priced these off face value: a dollar of wallet costs us a
    dollar (no supplier commission — owner, 2026-09-15), so the markup is the
    whole margin. $100 of balance at 4% is $104.

    The row therefore publishes the price of ONE dollar and the bounds, and
    the order carries ``amount_usd``.
    """
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    _seed_brand(
        db_session,
        n=1,
        skus=[
            {"sku_code": "fixed"},
            {
                "sku_code": "any-amount",
                # ``ck_skus_variable_amount_complete`` wants the whole set.
                "variable_amount": True,
                "min_amount_usd": Decimal("1"),
                "max_amount_usd": Decimal("100"),
                "rate_multiplier": Decimal("1.05"),
            },
        ],
    )
    await db_session.commit()

    r = await _get(integration_client, key_id, secret, CATALOG_PATH)

    assert r.status_code == 200, r.text
    rows = {s["sku_code"]: s for s in r.json()["brands"][0]["products"][0]["skus"]}
    assert set(rows) == {"fixed", "any-amount"}

    amount = rows["any-amount"]
    assert amount["kind"] == "amount"
    assert amount["unit"] == "usd"
    # One dollar of balance, at the seeder's stock 7% markup.
    assert amount["unit_price_usd"] == "1.070000"
    assert amount["price_usd"] is None, "a balance has no price until an amount is chosen"
    assert amount["retail_price_usd"] is None, "a face-value placeholder is not a price"
    assert amount["min_amount_usd"] == "1.00"
    assert amount["max_amount_usd"] == "100.00"
    assert rows["fixed"]["kind"] == "fixed"


async def test_a_sku_with_no_cost_is_absent_rather_than_free(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Ruling 3: ``effective_cost is None`` means NOT SELLABLE, never zero."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    _seed_brand(
        db_session,
        n=1,
        skus=[
            {"sku_code": "priced"},
            {"sku_code": "costless", "cost_usdt": None},
        ],
    )
    await db_session.commit()

    r = await _get(integration_client, key_id, secret, CATALOG_PATH)

    assert r.status_code == 200, r.text
    skus = _skus_of(r.json())
    assert set(skus) == {"priced"}
    assert "costless" not in skus
    assert all(Decimal(s["price_usd"]) > 0 for s in skus.values())


async def test_a_brand_whose_only_sku_is_unpriced_does_not_appear_at_all(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """No empty brand or product shells — a merchant iterating them finds goods."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    _seed_brand(db_session, n=1, skus=[{"sku_code": "only", "cost_usdt": None}])
    await db_session.commit()

    r = await _get(integration_client, key_id, secret, CATALOG_PATH)

    assert r.status_code == 200, r.text
    assert r.json() == {"brands": []}


async def test_a_sku_below_the_margin_floor_is_absent_rather_than_advertised(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """A price the order path would refuse must never reach the price list.

    Nothing floors ``b2b_markup_pct`` — the schemas accept ``ge=-999.99`` and
    0068 adds no ``CHECK``, deliberately (spec §8.3 makes
    ``violates_margin_floor`` the guard) — so both mistakes below are one admin
    keystroke away. Publishing either would break a promise *after* the
    reseller quoted their own customer off our number.
    """
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    _seed_brand(
        db_session,
        n=1,
        skus=[
            # `0.5` typed for `5`: priced at 0.5% over cost, under the 2% floor.
            {"sku_code": "fat-fingered", "b2b_markup_pct": Decimal("0.5")},
            # Exactly at the floor is still sellable — the guard is `<`, not `<=`.
            {"sku_code": "at-the-floor", "b2b_markup_pct": Decimal("2")},
            {"sku_code": "healthy", "b2b_markup_pct": Decimal("7")},
        ],
    )
    await db_session.commit()

    r = await _get(integration_client, key_id, secret, CATALOG_PATH)

    assert r.status_code == 200, r.text
    assert set(_skus_of(r.json())) == {"at-the-floor", "healthy"}


async def test_a_minus_100_markup_withholds_the_sku_instead_of_publishing_it_free(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Ruling 3's outcome, reached through the markup rather than the cost.

    ``merchant_price(cost, -100)`` is exactly ``0.00``. A costless SKU is
    already absent; a SKU priced at zero by a typo'd markup must be too, or the
    catalog advertises a free product.
    """
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    _seed_brand(
        db_session,
        n=1,
        skus=[
            {"sku_code": "would-be-free", "b2b_markup_pct": Decimal("-100")},
            {"sku_code": "priced", "b2b_markup_pct": Decimal("7")},
        ],
    )
    await db_session.commit()
    # The arithmetic the guard is protecting against, stated outright.
    assert merchant_price(Decimal("1.000000"), Decimal("-100")) == Decimal("0.00")

    r = await _get(integration_client, key_id, secret, CATALOG_PATH)

    assert r.status_code == 200, r.text
    skus = _skus_of(r.json())
    assert set(skus) == {"priced"}
    assert all(Decimal(sku["price_usd"]) > 0 for sku in skus.values())


async def test_a_brand_whose_only_sku_fails_the_floor_does_not_appear_at_all(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """No empty shell is left behind when the floor is what removed the SKU."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    _seed_brand(db_session, n=1, skus=[{"sku_code": "only", "b2b_markup_pct": Decimal("-50")}])
    await db_session.commit()

    r = await _get(integration_client, key_id, secret, CATALOG_PATH)

    assert r.json() == {"brands": []}


async def test_the_steam_gift_sku_never_appears(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Ruling 4: gifts are a v1 non-goal; ``visible_b2b`` is what excludes them."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    _seed_brand(
        db_session,
        n=1,
        skus=[
            {"sku_code": "ordinary"},
            # Seeded exactly as the gifts module ships it: a real cost, a
            # b2b-visible brand above it, and the default visible_b2b=False.
            {"sku_code": STEAM_GIFT_SKU_CODE, "visible_b2b": False},
        ],
    )
    await db_session.commit()

    r = await _get(integration_client, key_id, secret, CATALOG_PATH)

    assert r.status_code == 200, r.text
    assert STEAM_GIFT_SKU_CODE not in _skus_of(r.json())


async def test_the_price_is_this_merchants_price_from_the_pricing_module(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    _seed_brand(
        db_session,
        n=1,
        skus=[
            {"sku_code": "cheap", "cost_usdt": Decimal("0.990000"), "b2b_markup_pct": Decimal("7")},
            {
                "sku_code": "rich",
                "cost_usdt": Decimal("12.500000"),
                "b2b_markup_pct": Decimal("3.5"),
            },
        ],
    )
    await db_session.commit()

    r = await _get(integration_client, key_id, secret, CATALOG_PATH)

    assert r.status_code == 200, r.text
    skus = _skus_of(r.json())
    assert skus["cheap"]["price_usd"] == str(merchant_price(Decimal("0.990000"), Decimal("7")))
    assert skus["rich"]["price_usd"] == str(merchant_price(Decimal("12.5"), Decimal("3.5")))
    # Round UP to the cent, never down: 0.99 * 1.07 = 1.0593.
    assert skus["cheap"]["price_usd"] == "1.06"


async def test_a_per_merchant_markup_adjustment_moves_only_that_merchants_price(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """``markup_adjustment_pp`` is dormant in v1 but the price must honour it."""
    plain = await _new_merchant(integration_client, admin_headers, title="Plain")
    negotiated = await _new_merchant(integration_client, admin_headers, title="Negotiated")
    plain_key = await _new_key(integration_client, admin_headers, plain)
    negotiated_key = await _new_key(integration_client, admin_headers, negotiated)
    _seed_brand(
        db_session,
        n=1,
        skus=[{"sku_code": "deal", "cost_usdt": Decimal("100.000000")}],
    )
    await db_session.execute(
        update(Merchant).where(Merchant.id == negotiated).values(markup_adjustment_pp=Decimal("-2"))
    )
    await db_session.commit()

    plain_body = (await _get(integration_client, *plain_key, CATALOG_PATH)).json()
    negotiated_body = (await _get(integration_client, *negotiated_key, CATALOG_PATH)).json()

    assert _skus_of(plain_body)["deal"]["price_usd"] == "107.00"
    assert _skus_of(negotiated_body)["deal"]["price_usd"] == "105.00"


async def test_a_sku_without_a_denomination_is_named_by_its_code(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    _seed_brand(db_session, n=1, skus=[{"sku_code": "nameless", "denomination": None}])
    await db_session.commit()

    r = await _get(integration_client, key_id, secret, CATALOG_PATH)

    assert _skus_of(r.json())["nameless"]["name"] == "nameless"


async def test_a_retail_deactivated_sku_still_ships_to_merchants(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """``active`` is the storefront's switch; the B2B gate is ``visible_b2b``.

    Pinned because it is a design decision, not an oversight: a SKU pulled from
    the storefront for a reason that does not apply B2B (a landing page being
    rewritten, a seasonal hide) must not silently vanish from a reseller's
    integration. Both flags exist so the two surfaces can disagree.
    """
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    _seed_brand(db_session, n=1, skus=[{"sku_code": "retail-off"}])
    _seed_brand(db_session, n=2, brand_active=False, skus=[{"sku_code": "brand-retail-off"}])
    await db_session.execute(update(Sku).where(Sku.sku_code == "retail-off").values(active=False))
    await db_session.commit()

    r = await _get(integration_client, key_id, secret, CATALOG_PATH)

    assert set(_skus_of(r.json())) == {"retail-off", "brand-retail-off"}


async def test_a_name_falls_back_through_the_locales_and_then_to_the_slug(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Default locale wins; any translation beats none; no translation ⇒ slug."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    ids = _seed_brand(db_session, n=1, skus=[{"sku_code": "only"}])
    # Brand: an ``en`` row only. Product: no translation row at all.
    await db_session.execute(
        update(BrandTranslation)
        .where(BrandTranslation.brand_id == ids["brand"])
        .values(locale="en", name="Brand One")
    )
    await db_session.execute(
        delete(ProductTranslation).where(ProductTranslation.product_id == ids["product"])
    )
    await db_session.commit()

    r = await _get(integration_client, key_id, secret, CATALOG_PATH)

    brand = r.json()["brands"][0]
    assert brand["name"] == "Brand One"
    assert brand["products"][0]["name"] == "product-1"


async def test_an_empty_b2b_catalog_is_an_empty_list_not_an_error(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)

    r = await _get(integration_client, key_id, secret, CATALOG_PATH)

    assert r.status_code == 200, r.text
    assert r.json() == {"brands": []}


# ---------- the N+1 guard (AGENTS.md §10, ruling 2) ----------


async def test_the_catalog_query_count_does_not_scale_with_catalog_size(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    sql_counter: dict[str, int],
) -> None:
    """Self-calibrating: the SAME count for one brand and for six.

    Be precise about what this does and does not catch. It catches a **per-row**
    load — an N+1 — because that is the only thing that makes the second
    measurement larger. It is deliberately blind to a *constant* extra query
    (someone adding a fourth statement, or a ``selectinload`` that fires once
    per request): those appear at both catalog sizes and cancel out. That is
    the right trade — a constant query is not an N+1, and an absolute number
    would be a magic constant that every legitimate change has to relitigate —
    but it means this test is not a query *budget*.
    """
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    _seed_brand(db_session, n=1, skus=[{"sku_code": "sku-1-a"}, {"sku_code": "sku-1-b"}])
    await db_session.commit()

    # Untracked warm-up: it stamps ``last_used_at`` (throttled to one write a
    # minute), so the measured calls below both skip that UPDATE.
    assert (await _get(integration_client, key_id, secret, CATALOG_PATH)).status_code == 200

    sql_counter["n"] = 0
    assert (await _get(integration_client, key_id, secret, CATALOG_PATH)).status_code == 200
    with_one = sql_counter["n"]
    assert with_one > 0, "sql_counter saw no queries — listener not wired to the app engine"

    for n in range(2, 7):
        _seed_brand(
            db_session,
            n=n,
            skus=[
                {"sku_code": f"sku-{n}-a"},
                {"sku_code": f"sku-{n}-b"},
                {"sku_code": f"sku-{n}-c"},
            ],
        )
    await db_session.commit()

    sql_counter["n"] = 0
    r = await _get(integration_client, key_id, secret, CATALOG_PATH)
    with_six = sql_counter["n"]

    assert r.status_code == 200, r.text
    assert len(_skus_of(r.json())) == 17
    assert with_six == with_one, f"catalog grew from {with_one} to {with_six} queries"


# ---------- where it is mounted, and what limits it (ruling 1) ----------


async def test_the_machine_api_is_mounted_at_its_own_prefix_and_not_under_api_v1(
    integration_client: AsyncClient, app: Any
) -> None:
    """``/merchant/v1`` is versioned independently of the storefront API.

    A breaking change here means ``/merchant/v2``, never an edit — so it must
    not inherit ``/api/v1``'s version number, and must not be reachable
    through it either.
    """
    paths = {getattr(route, "path", None) for route in app.routes}
    assert {ME_PATH, CATALOG_PATH} <= paths
    assert not {p for p in paths if p and p.startswith("/api/v1/merchant/")}

    r = await integration_client.get(f"/api/v1{ME_PATH}")
    assert r.status_code == 404, r.text


async def test_the_two_documented_rate_limits_are_the_ones_configured() -> None:
    """The merchant README publishes these numbers; they cannot drift quietly.

    Both axes appear in the module README's rate-limit table, which is a
    third-party contract, so a change here is a change to something resellers
    have already sized their pollers against.

    This pins configuration only. The *behaviour* that matters — that the
    coarse slowapi tier does not apply to this prefix at all, so a merchant
    never receives its non-problem+json 429 — is pinned in
    ``test_rate_limit.py::test_the_merchant_machine_api_is_exempt``, because
    the global limiter is disabled under ``ENVIRONMENT=test`` and no assertion
    here could see it.
    """
    from yupay.core.config import get_settings

    settings = get_settings()
    assert settings.auth_ip_guard_window_seconds == 60
    assert settings.auth_ip_guard_bucket_max["merchant-api"] == 600
    assert settings.merchant_api_key_rate_max == 600
