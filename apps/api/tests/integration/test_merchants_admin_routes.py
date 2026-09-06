"""Integration tests for the merchant B2B admin surface (M1, Task 6).

Everything support needs to run a pilot merchant by hand, exercised through
the mounted app with real admin auth:

- ``POST/GET /api/v1/admin/merchants`` (list joins the USD deposit balance),
- ``POST /api/v1/admin/merchants/{id}/freeze|unfreeze``,
- ``POST /api/v1/admin/merchants/{id}/deposit-credits``,
- ``PATCH /api/v1/admin/catalog/skus/{id}/b2b``,
- ``POST /api/v1/admin/catalog/b2b/bulk-markup``,
- ``PATCH /api/v1/admin/catalog/brands/{id}/b2b``.

The deposit-credit endpoint namespaces the ledger idempotency key as
``merchant-credit:{merchant_id}:{client_key}`` — the wallet ledger replays
whatever transaction owns a key *without* comparing parameters, so the test
for a replay with an amended amount pins the one behaviour that makes the
mismatch visible: the response carries the ORIGINAL amount.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
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
from yupay.modules.merchants.models import Merchant
from yupay.modules.users.models import TelegramLink, User
from yupay.modules.wallet.models import WalletTransaction

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login(client: AsyncClient, tg_id: int) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "Admin"}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    token: str = r.json()["access_token"]
    return token


async def _grant_admin(db_session: AsyncSession, tg_id: int) -> None:
    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db_session.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db_session.commit()


@pytest.fixture
async def admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    token = await _login(integration_client, tg_id=42)
    await _grant_admin(db_session, tg_id=42)
    return {"Authorization": f"Bearer {token}"}


async def _create_merchant(
    client: AsyncClient, headers: dict[str, str], title: str = "Pilot Reseller"
) -> str:
    r = await client.post("/api/v1/admin/merchants", headers=headers, json={"title": title})
    assert r.status_code == 201, r.text
    merchant_id: str = r.json()["id"]
    return merchant_id


def _seed_catalog_unit(db: AsyncSession, tag: str, *, sku_count: int = 1) -> tuple[str, list[str]]:
    """Add category+brand+product+skus; returns ``(brand_id, sku_ids)``."""
    category = Category(
        id=new_id(),
        slug=f"cat-{tag}",
        sort_order=0,
        active=True,
        translations=[CategoryTranslation(locale="ru", name=f"Категория {tag}")],
    )
    brand = Brand(
        id=new_id(),
        slug=f"brand-{tag}",
        category_id=category.id,
        sort_order=0,
        active=True,
        translations=[BrandTranslation(locale="ru", name=f"Бренд {tag}")],
    )
    product = Product(
        id=new_id(),
        slug=f"product-{tag}",
        brand_id=brand.id,
        kind="top_up",
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name=f"Продукт {tag}")],
    )
    skus = [
        Sku(
            id=new_id(),
            product_id=product.id,
            sku_code=f"sku-{tag}-{n}",
            price_usd=Decimal("1.50"),
            cost_usdt=Decimal("1.00"),
            active=True,
        )
        for n in range(sku_count)
    ]
    db.add_all([category, brand, product, *skus])
    return brand.id, [s.id for s in skus]


# ---------- auth guard ----------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/admin/merchants"),
        ("POST", "/api/v1/admin/merchants"),
        ("POST", "/api/v1/admin/merchants/x/freeze"),
        ("POST", "/api/v1/admin/merchants/x/unfreeze"),
        ("POST", "/api/v1/admin/merchants/x/deposit-credits"),
        ("GET", "/api/v1/admin/merchants/x/transactions"),
        ("PATCH", "/api/v1/admin/catalog/skus/x/b2b"),
        ("POST", "/api/v1/admin/catalog/b2b/bulk-markup"),
        ("PATCH", "/api/v1/admin/catalog/brands/x/b2b"),
    ],
)
async def test_every_endpoint_requires_a_token(
    integration_client: AsyncClient, method: str, path: str
) -> None:
    r = await integration_client.request(method, path)
    assert r.status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/admin/merchants"),
        ("POST", "/api/v1/admin/merchants"),
        ("POST", "/api/v1/admin/merchants/x/freeze"),
        ("POST", "/api/v1/admin/merchants/x/unfreeze"),
        ("POST", "/api/v1/admin/merchants/x/deposit-credits"),
        ("GET", "/api/v1/admin/merchants/x/transactions"),
        ("PATCH", "/api/v1/admin/catalog/skus/x/b2b"),
        ("POST", "/api/v1/admin/catalog/b2b/bulk-markup"),
        ("PATCH", "/api/v1/admin/catalog/brands/x/b2b"),
    ],
)
async def test_non_admin_token_is_forbidden_everywhere(
    integration_client: AsyncClient, method: str, path: str
) -> None:
    """Today the guard is a router-level dependency (structurally shared);
    parametrizing anyway means a refactor to per-route deps cannot quietly
    drop the admin gate from one endpoint."""
    token = await _login(integration_client, tg_id=200)
    r = await integration_client.request(method, path, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


# ---------- create / list ----------


async def test_create_merchant(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    r = await integration_client.post(
        "/api/v1/admin/merchants", headers=admin_headers, json={"title": "Reseller One"}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == "Reseller One"
    assert body["status"] == "active"
    assert Decimal(str(body["deposit_balance"])) == Decimal("0")


async def test_create_merchant_blank_title_is_rejected(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    r = await integration_client.post(
        "/api/v1/admin/merchants", headers=admin_headers, json={"title": "   "}
    )
    assert r.status_code == 422


async def test_create_merchant_replays_by_idempotency_key(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """A retried create with the same key returns the same merchant, once."""
    headers = {**admin_headers, "Idempotency-Key": "merchants-admin-create-0001"}
    first = await integration_client.post(
        "/api/v1/admin/merchants", headers=headers, json={"title": "Retry Reseller"}
    )
    second = await integration_client.post(
        "/api/v1/admin/merchants", headers=headers, json={"title": "Retry Reseller"}
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]
    rows = (await db_session.execute(select(Merchant))).scalars().all()
    assert len(rows) == 1


async def test_list_merchants_joins_usd_balance(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    funded = await _create_merchant(integration_client, admin_headers, title="Funded")
    broke = await _create_merchant(integration_client, admin_headers, title="Broke")
    r = await integration_client.post(
        f"/api/v1/admin/merchants/{funded}/deposit-credits",
        headers={**admin_headers, "Idempotency-Key": "merchants-admin-list-0001"},
        json={"amount": "40.00", "note": "pilot funding"},
    )
    assert r.status_code == 201, r.text

    r = await integration_client.get("/api/v1/admin/merchants", headers=admin_headers)
    assert r.status_code == 200, r.text
    by_id = {m["id"]: m for m in r.json()["items"]}
    assert Decimal(str(by_id[funded]["deposit_balance"])) == Decimal("40.00")
    assert Decimal(str(by_id[broke]["deposit_balance"])) == Decimal("0")


@pytest.fixture
async def sql_counter(db_engine) -> AsyncIterator[dict[str, int]]:  # type: ignore[no-untyped-def]  # conftest fixture is untyped
    """Counts every cursor execution on the engine the app is wired to."""
    holder = {"n": 0}

    def _before(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        holder["n"] += 1

    sync_engine = db_engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _before)
    try:
        yield holder
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before)


async def test_list_merchants_is_one_grouped_query_not_n_plus_one(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    sql_counter: dict[str, int],
) -> None:
    """Self-calibrating N+1 guard (AGENTS.md §10): 1 row and 4 rows must cost equal SQL."""
    first = await _create_merchant(integration_client, admin_headers, title="M-0")
    await integration_client.post(
        f"/api/v1/admin/merchants/{first}/deposit-credits",
        headers={**admin_headers, "Idempotency-Key": "merchants-admin-nplus1-01"},
        json={"amount": "5.00", "note": None},
    )
    # Warm-up, then measure with one merchant.
    await integration_client.get("/api/v1/admin/merchants", headers=admin_headers)
    sql_counter["n"] = 0
    r = await integration_client.get("/api/v1/admin/merchants", headers=admin_headers)
    assert r.status_code == 200
    small = sql_counter["n"]
    assert small > 0, "sql_counter saw no queries — listener not wired to the app engine"

    for n in range(1, 4):
        mid = await _create_merchant(integration_client, admin_headers, title=f"M-{n}")
        await integration_client.post(
            f"/api/v1/admin/merchants/{mid}/deposit-credits",
            headers={**admin_headers, "Idempotency-Key": f"merchants-admin-nplus1-{n:02d}x"},
            json={"amount": "5.00", "note": None},
        )
    sql_counter["n"] = 0
    r = await integration_client.get("/api/v1/admin/merchants", headers=admin_headers)
    assert r.status_code == 200
    assert len(r.json()["items"]) == 4
    assert sql_counter["n"] == small


# ---------- freeze / unfreeze ----------


async def test_freeze_persists_and_blocks_nothing_in_m1(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    merchant_id = await _create_merchant(integration_client, admin_headers)

    r = await integration_client.post(
        f"/api/v1/admin/merchants/{merchant_id}/freeze", headers=admin_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "frozen"
    row = (
        await db_session.execute(select(Merchant).where(Merchant.id == merchant_id))
    ).scalar_one()
    assert row.status == "frozen"

    # M1: freezing blocks orders (an M2 concern), never money in — support can
    # still credit a frozen merchant's deposit.
    r = await integration_client.post(
        f"/api/v1/admin/merchants/{merchant_id}/deposit-credits",
        headers={**admin_headers, "Idempotency-Key": "merchants-admin-frozen-001"},
        json={"amount": "10.00", "note": "credit while frozen"},
    )
    assert r.status_code == 201, r.text

    r = await integration_client.post(
        f"/api/v1/admin/merchants/{merchant_id}/unfreeze", headers=admin_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"


async def test_freeze_unknown_merchant_404(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    r = await integration_client.post(
        f"/api/v1/admin/merchants/{new_id()}/freeze", headers=admin_headers
    )
    assert r.status_code == 404


# ---------- deposit credit ----------


async def test_deposit_credit_happy_path_namespaces_the_ledger_key(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    merchant_id = await _create_merchant(integration_client, admin_headers)
    client_key = "merchants-admin-credit-0001"
    r = await integration_client.post(
        f"/api/v1/admin/merchants/{merchant_id}/deposit-credits",
        headers={**admin_headers, "Idempotency-Key": client_key},
        json={"amount": "25.00", "note": "first top-up"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert Decimal(str(body["amount"])) == Decimal("25.00")
    assert Decimal(str(body["balance"])) == Decimal("25.00")

    # The ledger key is namespaced (wallet-gateway style) so an admin client's
    # key can never collide with another merchant's or another key domain.
    txn = (
        await db_session.execute(
            select(WalletTransaction).where(WalletTransaction.id == body["transaction_id"])
        )
    ).scalar_one()
    assert txn.idempotency_key == f"merchant-credit:{merchant_id}:{client_key}"
    assert txn.kind == "merchant_deposit_credit"


async def test_deposit_credit_requires_idempotency_key(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _create_merchant(integration_client, admin_headers)
    r = await integration_client.post(
        f"/api/v1/admin/merchants/{merchant_id}/deposit-credits",
        headers=admin_headers,
        json={"amount": "25.00", "note": None},
    )
    assert r.status_code == 422


async def test_deposit_credit_oversized_key_is_422_not_500(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """A 128-char client key must be a readable 422, never a 500.

    The ledger column is ``String(160)`` and the ``merchant-credit:{uuid}:``
    prefix consumes 53 chars — an unbounded client key would overflow into a
    ``DataError`` that ``post()`` does not catch, i.e. a deterministic 500 on
    every retry. The route caps the client half at 100 chars instead.
    """
    merchant_id = await _create_merchant(integration_client, admin_headers)
    long_key = "k" * 128
    r = await integration_client.post(
        f"/api/v1/admin/merchants/{merchant_id}/deposit-credits",
        headers={**admin_headers, "Idempotency-Key": long_key},
        json={"amount": "25.00", "note": None},
    )
    assert r.status_code == 422, r.text
    # Nothing booked: no ledger transaction exists and the balance is zero.
    txns = (
        (
            await db_session.execute(
                select(WalletTransaction).where(WalletTransaction.kind == "merchant_deposit_credit")
            )
        )
        .scalars()
        .all()
    )
    assert txns == []
    r = await integration_client.get("/api/v1/admin/merchants", headers=admin_headers)
    by_id = {m["id"]: m for m in r.json()["items"]}
    assert Decimal(str(by_id[merchant_id]["deposit_balance"])) == Decimal("0")


async def test_deposit_credit_replay_does_not_credit_twice(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _create_merchant(integration_client, admin_headers)
    headers = {**admin_headers, "Idempotency-Key": "merchants-admin-replay-0001"}
    first = await integration_client.post(
        f"/api/v1/admin/merchants/{merchant_id}/deposit-credits",
        headers=headers,
        json={"amount": "30.00", "note": None},
    )
    second = await integration_client.post(
        f"/api/v1/admin/merchants/{merchant_id}/deposit-credits",
        headers=headers,
        json={"amount": "30.00", "note": None},
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["transaction_id"] == first.json()["transaction_id"]
    assert Decimal(str(second.json()["balance"])) == Decimal("30.00")


async def test_deposit_credit_replay_with_amended_amount_returns_the_original(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """Same key, different amount → the ORIGINAL amount comes back.

    The ledger's ``post()`` replays whatever transaction owns an idempotency
    key WITHOUT checking parameters — a reused key with an amended amount
    silently returns the old transaction and books nothing new. The endpoint
    cannot make that retroactively safe, so it makes it VISIBLE instead: the
    response's ``amount`` is the replayed transaction's amount, and the admin
    UI can compare it with what was submitted and warn.
    """
    merchant_id = await _create_merchant(integration_client, admin_headers)
    headers = {**admin_headers, "Idempotency-Key": "merchants-admin-amend-00001"}
    first = await integration_client.post(
        f"/api/v1/admin/merchants/{merchant_id}/deposit-credits",
        headers=headers,
        json={"amount": "10.00", "note": None},
    )
    assert first.status_code == 201, first.text
    amended = await integration_client.post(
        f"/api/v1/admin/merchants/{merchant_id}/deposit-credits",
        headers=headers,
        json={"amount": "99.00", "note": None},
    )
    assert amended.status_code == 201, amended.text
    # Original amount, not the amended one — and the balance proves no second
    # credit was booked.
    assert Decimal(str(amended.json()["amount"])) == Decimal("10.00")
    assert Decimal(str(amended.json()["balance"])) == Decimal("10.00")
    assert amended.json()["transaction_id"] == first.json()["transaction_id"]


async def test_deposit_credit_rejects_non_positive_amount(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _create_merchant(integration_client, admin_headers)
    r = await integration_client.post(
        f"/api/v1/admin/merchants/{merchant_id}/deposit-credits",
        headers={**admin_headers, "Idempotency-Key": "merchants-admin-nonpos-001"},
        json={"amount": "-5.00", "note": None},
    )
    assert r.status_code == 422


# ---------- deposit ledger listing ----------


async def _credit(
    client: AsyncClient,
    headers: dict[str, str],
    merchant_id: str,
    *,
    amount: str,
    key: str,
    note: str | None = None,
) -> dict[str, object]:
    r = await client.post(
        f"/api/v1/admin/merchants/{merchant_id}/deposit-credits",
        headers={**headers, "Idempotency-Key": key},
        json={"amount": amount, "note": note},
    )
    assert r.status_code == 201, r.text
    body: dict[str, object] = r.json()
    return body


async def test_merchant_transactions_lists_credits_newest_first(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """The detail screen's ledger: every deposit movement, newest first.

    ``amount`` is the signed deposit delta (positive = balance up), ``note``
    is the operator's free text from the credit, ``actor`` the admin who
    booked it — everything support needs to answer "who topped this
    merchant up, when, and why" without joining tables by hand.
    """
    merchant_id = await _create_merchant(integration_client, admin_headers)
    first = await _credit(
        integration_client,
        admin_headers,
        merchant_id,
        amount="25.00",
        key="merchants-admin-ledger-0001",
        note="first top-up",
    )
    second = await _credit(
        integration_client,
        admin_headers,
        merchant_id,
        amount="10.50",
        key="merchants-admin-ledger-0002",
    )

    r = await integration_client.get(
        f"/api/v1/admin/merchants/{merchant_id}/transactions", headers=admin_headers
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["transaction_id"] for i in items] == [
        second["transaction_id"],
        first["transaction_id"],
    ]
    newest, oldest = items
    assert newest["kind"] == "merchant_deposit_credit"
    assert Decimal(str(newest["amount"])) == Decimal("10.50")
    assert newest["note"] is None
    assert Decimal(str(oldest["amount"])) == Decimal("25.00")
    assert oldest["note"] == "first top-up"
    actor = oldest["actor"]
    assert isinstance(actor, str)
    assert actor.startswith("admin:")
    assert oldest["created_at"]


async def test_merchant_transactions_empty_for_fresh_merchant_and_capped_by_limit(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _create_merchant(integration_client, admin_headers)
    r = await integration_client.get(
        f"/api/v1/admin/merchants/{merchant_id}/transactions", headers=admin_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []

    await _credit(
        integration_client,
        admin_headers,
        merchant_id,
        amount="5.00",
        key="merchants-admin-limit-0001",
    )
    newest = await _credit(
        integration_client,
        admin_headers,
        merchant_id,
        amount="7.00",
        key="merchants-admin-limit-0002",
    )
    r = await integration_client.get(
        f"/api/v1/admin/merchants/{merchant_id}/transactions?limit=1", headers=admin_headers
    )
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["transaction_id"] == newest["transaction_id"]

    # The bounds are contract, not a silent clamp: out-of-range is a 422.
    for bad in ("0", "201"):
        r = await integration_client.get(
            f"/api/v1/admin/merchants/{merchant_id}/transactions?limit={bad}",
            headers=admin_headers,
        )
        assert r.status_code == 422, r.text


async def test_merchant_transactions_are_isolated_per_merchant(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """One merchant's ledger never shows another merchant's movements.

    The query filters on the deposit account's ``owner_id``; this pins that
    filter against future refactors — a regression here would leak one
    reseller's top-up history into another's screen.
    """
    merchant_a = await _create_merchant(integration_client, admin_headers, title="Merchant A")
    merchant_b = await _create_merchant(integration_client, admin_headers, title="Merchant B")
    b_txn = await _credit(
        integration_client,
        admin_headers,
        merchant_b,
        amount="40.00",
        key="merchants-admin-isolate-b1",
    )

    # B has money; A's ledger must still be empty.
    r = await integration_client.get(
        f"/api/v1/admin/merchants/{merchant_a}/transactions", headers=admin_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []

    a_txn = await _credit(
        integration_client,
        admin_headers,
        merchant_a,
        amount="15.00",
        key="merchants-admin-isolate-a1",
    )
    r = await integration_client.get(
        f"/api/v1/admin/merchants/{merchant_a}/transactions", headers=admin_headers
    )
    ids = [item["transaction_id"] for item in r.json()["items"]]
    assert ids == [a_txn["transaction_id"]]
    assert b_txn["transaction_id"] not in ids


async def test_merchant_transactions_unknown_merchant_404(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    r = await integration_client.get(
        f"/api/v1/admin/merchants/{new_id()}/transactions", headers=admin_headers
    )
    assert r.status_code == 404


# ---------- SKU / brand B2B patches ----------


async def test_patch_sku_b2b_markup_and_visibility(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    _, (sku_id,) = _seed_catalog_unit(db_session, "patch")
    await db_session.commit()

    r = await integration_client.patch(
        f"/api/v1/admin/catalog/skus/{sku_id}/b2b",
        headers=admin_headers,
        json={"markup_pct": "5.5"},
    )
    assert r.status_code == 200, r.text
    assert Decimal(str(r.json()["b2b_markup_pct"])) == Decimal("5.5")
    assert r.json()["visible_b2b"] is False  # untouched

    r = await integration_client.patch(
        f"/api/v1/admin/catalog/skus/{sku_id}/b2b",
        headers=admin_headers,
        json={"visible_b2b": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["visible_b2b"] is True
    assert Decimal(str(r.json()["b2b_markup_pct"])) == Decimal("5.5")  # untouched

    row = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    await db_session.refresh(row)
    assert row.b2b_markup_pct == Decimal("5.5")
    assert row.visible_b2b is True


async def test_patch_sku_b2b_empty_body_is_rejected(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    _, (sku_id,) = _seed_catalog_unit(db_session, "empty")
    await db_session.commit()
    r = await integration_client.patch(
        f"/api/v1/admin/catalog/skus/{sku_id}/b2b", headers=admin_headers, json={}
    )
    assert r.status_code == 422


async def test_patch_sku_b2b_unknown_sku_404(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    r = await integration_client.patch(
        f"/api/v1/admin/catalog/skus/{new_id()}/b2b",
        headers=admin_headers,
        json={"visible_b2b": True},
    )
    assert r.status_code == 404


async def test_patch_brand_b2b_visibility(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    brand_id, _ = _seed_catalog_unit(db_session, "brandvis")
    await db_session.commit()
    r = await integration_client.patch(
        f"/api/v1/admin/catalog/brands/{brand_id}/b2b",
        headers=admin_headers,
        json={"visible_b2b": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["visible_b2b"] is True
    row = (await db_session.execute(select(Brand).where(Brand.id == brand_id))).scalar_one()
    await db_session.refresh(row)
    assert row.visible_b2b is True


# ---------- bulk markup ----------


async def test_bulk_markup_touches_only_the_named_brand(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    _, target_skus = _seed_catalog_unit(db_session, "target", sku_count=3)
    _, other_skus = _seed_catalog_unit(db_session, "other", sku_count=2)
    await db_session.commit()

    r = await integration_client.post(
        "/api/v1/admin/catalog/b2b/bulk-markup",
        headers=admin_headers,
        json={"brand_slug": "brand-target", "markup_pct": "5"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["affected"] == 3

    for sku_id in target_skus:
        row = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
        await db_session.refresh(row)
        assert row.b2b_markup_pct == Decimal("5")
    for sku_id in other_skus:
        row = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
        await db_session.refresh(row)
        assert row.b2b_markup_pct == Decimal("7")  # the schema default, untouched


async def test_bulk_markup_by_category(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    _, in_cat = _seed_catalog_unit(db_session, "incat", sku_count=2)
    _, out_cat = _seed_catalog_unit(db_session, "outcat", sku_count=1)
    await db_session.commit()

    r = await integration_client.post(
        "/api/v1/admin/catalog/b2b/bulk-markup",
        headers=admin_headers,
        json={"category": "cat-incat", "markup_pct": "4.25"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["affected"] == 2

    for sku_id in in_cat:
        row = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
        await db_session.refresh(row)
        assert row.b2b_markup_pct == Decimal("4.25")
    row = (await db_session.execute(select(Sku).where(Sku.id == out_cat[0]))).scalar_one()
    await db_session.refresh(row)
    assert row.b2b_markup_pct == Decimal("7")


async def test_bulk_markup_unknown_brand_404(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    r = await integration_client.post(
        "/api/v1/admin/catalog/b2b/bulk-markup",
        headers=admin_headers,
        json={"brand_slug": "no-such-brand", "markup_pct": "5"},
    )
    assert r.status_code == 404


async def test_bulk_markup_needs_exactly_one_target(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    _seed_catalog_unit(db_session, "both")
    await db_session.commit()
    both = await integration_client.post(
        "/api/v1/admin/catalog/b2b/bulk-markup",
        headers=admin_headers,
        json={"brand_slug": "brand-both", "category": "cat-both", "markup_pct": "5"},
    )
    assert both.status_code == 422
    neither = await integration_client.post(
        "/api/v1/admin/catalog/b2b/bulk-markup",
        headers=admin_headers,
        json={"markup_pct": "5"},
    )
    assert neither.status_code == 422
