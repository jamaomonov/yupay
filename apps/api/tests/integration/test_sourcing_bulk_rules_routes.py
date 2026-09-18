"""Integration tests for ``PUT /api/v1/admin/sourcing/rules:bulk``.

Covers:
- every listed SKU gets the rule; the response reports success per SKU
- a partial failure (one SKU forced onto a supplier with no active mapping)
  does not fail the batch — it is reported by name, the rest are written
- ``mode="auto"`` deletes existing explicit rules, same as the single-SKU path
- a reserve supplier (nova) is reachable only via ``force_supplier`` with an
  active mapping — the single-SKU ``set_rule`` guard survives the bulk path
- the list is capped at 100 SKUs per request
- a missing SKU is a per-item failure, not a 404 for the whole request
- Idempotency-Key replay
- 403 for non-admin
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
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
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.sourcing.models import SkuSourcingRule
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"

BULK_URL = "/api/v1/admin/sourcing/rules:bulk"


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login_user(client: AsyncClient, tg_id: int) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "U"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _grant_admin(db: AsyncSession, tg_id: int) -> None:
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()


@pytest.fixture
async def _admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    token = await _login_user(integration_client, tg_id=9101)
    await _grant_admin(db_session, tg_id=9101)
    return {"Authorization": f"Bearer {token}"}


async def _seed_brand_with_skus(db: AsyncSession, *, n: int, slug_prefix: str) -> list[str]:
    """``n`` active top_up SKUs under one fresh brand — enough for bulk tests."""
    category = Category(
        id=new_id(),
        slug=f"cat-{slug_prefix}",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug=f"brand-{slug_prefix}",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name=slug_prefix)],
    )
    product = Product(
        id=new_id(),
        slug=f"product-{slug_prefix}",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name=slug_prefix)],
    )
    db.add_all([category, brand, product])
    await db.flush()

    sku_ids: list[str] = []
    for i in range(n):
        sku = Sku(
            id=new_id(),
            product_id=product.id,
            sku_code=f"{slug_prefix}-sku-{i}",
            denomination="100",
            region="WW",
            price_usd="1.00",
            sort_order=10,
            active=True,
        )
        db.add(sku)
        sku_ids.append(sku.id)
    await db.commit()
    return sku_ids


async def _add_mapping(db: AsyncSession, *, sku_id: str, supplier_slug: str) -> None:
    db.add(
        SkuSupplierMapping(
            sku_id=sku_id,
            supplier_slug=supplier_slug,
            kind="game",
            external_product_id="ext-1",
            external_variant_id="100",
            quantity=1,
            extra={},
            is_active=True,
        )
    )
    await db.commit()


async def test_bulk_sets_rule_for_every_listed_sku(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    sku_ids = await _seed_brand_with_skus(db_session, n=3, slug_prefix="bulk-happy")
    for sku_id in sku_ids:
        await _add_mapping(db_session, sku_id=sku_id, supplier_slug="waxpeer")

    r = await integration_client.put(
        BULK_URL,
        headers=_admin_headers,
        json={"sku_ids": sku_ids, "mode": "force_supplier", "supplier_slug": "waxpeer"},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert {item["sku_id"] for item in items} == set(sku_ids)
    assert all(item["ok"] is True for item in items), items
    assert all(item["error"] is None for item in items), items

    rows = (
        (
            await db_session.execute(
                select(SkuSourcingRule).where(SkuSourcingRule.sku_id.in_(sku_ids))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 3
    assert all(row.mode == "force_supplier" and row.supplier_slug == "waxpeer" for row in rows)


async def test_bulk_partial_failure_writes_the_rest_and_names_the_failure(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    """One SKU forced onto ``nova`` (mapping-required, and a reserve supplier)
    with no active mapping fails by name; the other SKUs are still written.
    """
    sku_ids = await _seed_brand_with_skus(db_session, n=3, slug_prefix="bulk-partial")
    bad_sku = sku_ids[1]
    for sku_id in sku_ids:
        if sku_id != bad_sku:
            await _add_mapping(db_session, sku_id=sku_id, supplier_slug="nova")
    # No nova mapping for `bad_sku` — set_rule's guard must refuse it.

    r = await integration_client.put(
        BULK_URL,
        headers=_admin_headers,
        json={"sku_ids": sku_ids, "mode": "force_supplier", "supplier_slug": "nova"},
    )
    assert r.status_code == 200, r.text
    by_sku = {item["sku_id"]: item for item in r.json()["items"]}

    assert by_sku[bad_sku]["ok"] is False
    assert by_sku[bad_sku]["error"] is not None
    assert "nova" in by_sku[bad_sku]["error"]
    assert "mapping" in by_sku[bad_sku]["error"].lower()

    good_skus = [s for s in sku_ids if s != bad_sku]
    for sku_id in good_skus:
        assert by_sku[sku_id]["ok"] is True, by_sku[sku_id]
        assert by_sku[sku_id]["error"] is None

    # The successful writes are actually committed, not rolled back by the
    # one failure — this is the point of the bulk endpoint.
    rows = (
        (
            await db_session.execute(
                select(SkuSourcingRule).where(SkuSourcingRule.sku_id.in_(good_skus))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert all(row.supplier_slug == "nova" for row in rows)

    # The failed SKU has no rule row at all.
    failed_row = (
        await db_session.execute(select(SkuSourcingRule).where(SkuSourcingRule.sku_id == bad_sku))
    ).scalar_one_or_none()
    assert failed_row is None


async def test_bulk_force_supplier_accepts_a_reserve_supplier_with_active_mapping(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    """The reserve guard (ADR-0081) only ever blocks *automatic* routing to a
    reserve supplier. An explicit ``force_supplier`` bulk write onto ``nova``
    with an active mapping must succeed — proving the single-SKU guard's
    shape (mapping-required check, not a blanket reserve ban) survives the
    bulk path unmodified.
    """
    from yupay.modules.sourcing import service as sourcing_svc

    sku_ids = await _seed_brand_with_skus(db_session, n=1, slug_prefix="bulk-reserve")
    sku_id = sku_ids[0]
    await _add_mapping(db_session, sku_id=sku_id, supplier_slug="nova")

    r = await integration_client.put(
        BULK_URL,
        headers=_admin_headers,
        json={"sku_ids": [sku_id], "mode": "force_supplier", "supplier_slug": "nova"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["ok"] is True

    decision = await sourcing_svc.resolve_for_sku(db_session, sku_id)
    assert decision.primary == "supplier:nova"
    assert decision.strict is True


async def test_bulk_mode_auto_deletes_existing_rules(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    from yupay.modules.sourcing import service as sourcing_svc

    sku_ids = await _seed_brand_with_skus(db_session, n=2, slug_prefix="bulk-auto")
    for sku_id in sku_ids:
        await sourcing_svc.set_rule(
            db_session,
            sku_id=sku_id,
            mode="force_inventory",
            supplier_slug=None,
            admin_id="setup",
        )
    await db_session.commit()

    r = await integration_client.put(
        BULK_URL,
        headers=_admin_headers,
        json={"sku_ids": sku_ids, "mode": "auto", "supplier_slug": None},
    )
    assert r.status_code == 200, r.text
    assert all(item["ok"] is True for item in r.json()["items"]), r.json()

    rows = (
        (
            await db_session.execute(
                select(SkuSourcingRule).where(SkuSourcingRule.sku_id.in_(sku_ids))
            )
        )
        .scalars()
        .all()
    )
    assert rows == []


async def test_bulk_mode_auto_is_a_success_when_no_rule_existed(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    """A SKU that was already implicitly 'auto' (no rule row) reaching
    ``mode="auto"`` in bulk must not be reported as a failure — the desired
    end state (no explicit rule) is already true.
    """
    sku_ids = await _seed_brand_with_skus(db_session, n=1, slug_prefix="bulk-auto-noop")

    r = await integration_client.put(
        BULK_URL,
        headers=_admin_headers,
        json={"sku_ids": sku_ids, "mode": "auto", "supplier_slug": None},
    )
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["ok"] is True
    assert r.json()["items"][0]["error"] is None


async def test_bulk_missing_sku_is_a_per_item_failure_not_a_404(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    sku_ids = await _seed_brand_with_skus(db_session, n=2, slug_prefix="bulk-missing")
    for sku_id in sku_ids:
        await _add_mapping(db_session, sku_id=sku_id, supplier_slug="waxpeer")
    missing_id = new_id()

    r = await integration_client.put(
        BULK_URL,
        headers=_admin_headers,
        json={
            "sku_ids": [*sku_ids, missing_id],
            "mode": "force_supplier",
            "supplier_slug": "waxpeer",
        },
    )
    assert r.status_code == 200, r.text
    by_sku = {item["sku_id"]: item for item in r.json()["items"]}

    assert by_sku[missing_id]["ok"] is False
    assert by_sku[missing_id]["error"] is not None
    for sku_id in sku_ids:
        assert by_sku[sku_id]["ok"] is True, by_sku[sku_id]


async def test_bulk_capped_at_100_skus(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    too_many = [new_id() for _ in range(101)]
    r = await integration_client.put(
        BULK_URL,
        headers=_admin_headers,
        json={"sku_ids": too_many, "mode": "auto", "supplier_slug": None},
    )
    assert r.status_code == 422, r.text


async def test_bulk_idempotency_key_replays_cached_response(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    """A repeated ``PUT`` with the same ``Idempotency-Key`` replays the first
    response verbatim instead of re-running the writes."""
    sku_ids = await _seed_brand_with_skus(db_session, n=2, slug_prefix="bulk-idem")
    for sku_id in sku_ids:
        await _add_mapping(db_session, sku_id=sku_id, supplier_slug="waxpeer")
    headers = {**_admin_headers, "Idempotency-Key": "sourcing-bulk-replay-0001"}

    first = await integration_client.put(
        BULK_URL,
        headers=headers,
        json={"sku_ids": sku_ids, "mode": "force_supplier", "supplier_slug": "waxpeer"},
    )
    assert first.status_code == 200, first.text

    # Mutate a row out from under the handler so a live re-execution would
    # observably differ from the first response.
    await db_session.execute(
        update(SkuSourcingRule)
        .where(SkuSourcingRule.sku_id == sku_ids[0])
        .values(mode="manual", supplier_slug=None)
    )
    await db_session.commit()

    replay = await integration_client.put(
        BULK_URL,
        headers=headers,
        # Different body — the replay must ignore it.
        json={"sku_ids": sku_ids, "mode": "force_inventory", "supplier_slug": None},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()

    row = (
        await db_session.execute(
            select(SkuSourcingRule).where(SkuSourcingRule.sku_id == sku_ids[0])
        )
    ).scalar_one()
    assert row.mode == "manual"


async def test_bulk_non_admin_forbidden(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    sku_ids = await _seed_brand_with_skus(db_session, n=1, slug_prefix="bulk-forbidden")
    token = await _login_user(integration_client, tg_id=9102)
    r = await integration_client.put(
        BULK_URL,
        headers={"Authorization": f"Bearer {token}"},
        json={"sku_ids": sku_ids, "mode": "auto", "supplier_slug": None},
    )
    assert r.status_code == 403
