"""Integration tests for ``GET /api/v1/admin/sourcing/brands/{brand_slug}``.

Covers:
- one row per active SKU of the brand; an inactive SKU is excluded
- the reported route matches ``sourcing.resolve_for_sku`` for every SKU
- a reserve supplier (nova) never appears as the live route, even with an
  older active mapping than the incumbent (ADR-0081)
- a candidate supplier with no mapping at all reports
  ``has_active_mapping=False`` and no cost
- the latest ``supplier_price_history`` row wins when several exist
- 404 for an unknown brand slug
- 403 for a non-admin caller
- bounded SQL query count — adding SKUs must not grow it (no N+1)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import event
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
from yupay.modules.integrations.models import (
    SkuSupplierMapping,
    SupplierCatalogCache,
    SupplierPriceHistory,
)
from yupay.modules.sourcing import service as sourcing_svc
from yupay.modules.sourcing.models import SkuSourcingRule
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"


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
    body: dict[str, str] = r.json()
    return body["access_token"]


async def _grant_admin(db: AsyncSession, tg_id: int) -> None:
    from sqlalchemy import select, update

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
    token = await _login_user(integration_client, tg_id=9001)
    await _grant_admin(db_session, tg_id=9001)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def sql_counter(db_engine) -> AsyncIterator[dict[str, int]]:
    """Counts every cursor execution on the engine the app is wired to.

    Copied from ``test_orders_routes.py`` (AGENTS.md §10: every list endpoint
    must have an integration test asserting query count) — duplicated
    locally rather than imported, matching this suite's existing convention
    of per-file test helpers.
    """
    holder = {"n": 0}

    def _before(conn, cursor, statement, parameters, context, executemany) -> None:
        holder["n"] += 1

    sync_engine = db_engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _before)
    try:
        yield holder
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before)


async def _measure_get(
    client: AsyncClient, counter: dict[str, int], url: str, headers: dict[str, str]
) -> int:
    counter["n"] = 0
    r = await client.get(url, headers=headers)
    assert r.status_code == 200, r.text
    assert counter["n"] > 0, "sql_counter saw no queries — listener not wired to the app engine"
    return counter["n"]


async def _seed_category_and_brand(db: AsyncSession, *, brand_slug: str) -> tuple[str, str]:
    category = Category(
        id=new_id(),
        slug=f"cat-{brand_slug}",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug=brand_slug,
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name=brand_slug)],
    )
    db.add_all([category, brand])
    await db.flush()
    return category.id, brand.id


async def _make_product(db: AsyncSession, *, brand_id: str, slug: str, kind: str) -> str:
    product = Product(
        id=new_id(),
        slug=slug,
        brand_id=brand_id,
        kind=kind,
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name=slug)],
    )
    db.add(product)
    await db.flush()
    return product.id


async def _make_sku(
    db: AsyncSession,
    *,
    product_id: str,
    sku_code: str,
    active: bool = True,
    price_usd: Decimal = Decimal("1.00"),
    cost_usdt: Decimal | None = None,
) -> str:
    sku = Sku(
        id=new_id(),
        product_id=product_id,
        sku_code=sku_code,
        denomination="100",
        region="WW",
        price_usd=price_usd,
        cost_usdt=cost_usdt,
        sort_order=10,
        active=active,
    )
    db.add(sku)
    await db.flush()
    return sku.id


async def _make_mapping(
    db: AsyncSession,
    *,
    sku_id: str,
    supplier_slug: str,
    kind: str = "game",
    is_active: bool = True,
    created_at: datetime | None = None,
) -> None:
    db.add(
        SkuSupplierMapping(
            sku_id=sku_id,
            supplier_slug=supplier_slug,
            kind=kind,
            external_product_id="ext-1",
            external_variant_id="100",
            quantity=1,
            extra={},
            is_active=is_active,
            created_at=created_at or datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    await db.flush()


async def _make_history(
    db: AsyncSession,
    *,
    sku_id: str,
    supplier_slug: str,
    cost_usdt: Decimal,
    captured_at: datetime,
) -> None:
    db.add(
        SupplierPriceHistory(
            id=new_id(),
            sku_id=sku_id,
            supplier_slug=supplier_slug,
            kind="game",
            external_product_id="ext-1",
            external_variant_id="100",
            cost_usdt=cost_usdt,
            captured_at=captured_at,
        )
    )
    await db.flush()


@pytest.fixture
async def _seed_brand(db_session: AsyncSession) -> dict[str, str]:
    """A brand with two products, several SKUs, mixed mappings and one
    explicit rule — matches the task-3-brief scenario verbatim.

    - sku1 (top_up): active g2b mapping (incumbent) + an *older* active nova
      mapping — nova is a reserve (ADR-0081) and must never win despite
      being older. Two g2b price-history rows so the latest one must win.
      gengine has no mapping at all for this SKU.
    - sku2 (top_up): explicit ``force_supplier`` rule onto gengine (needs an
      active gengine mapping to pass ``set_rule``'s validation guard).
    - sku3 (voucher): no mapping at all — auto-routes to inventory.
    - sku4 (top_up, INACTIVE): must not appear in the response at all.
    """
    brand_slug = "mlbb-overview-test"
    _category_id, brand_id = await _seed_category_and_brand(db_session, brand_slug=brand_slug)
    product_a = await _make_product(
        db_session, brand_id=brand_id, slug="mlbb-diamonds-test", kind="top_up"
    )
    product_b = await _make_product(
        db_session, brand_id=brand_id, slug="mlbb-gift-test", kind="voucher"
    )

    sku1 = await _make_sku(db_session, product_id=product_a, sku_code="mlbb-sku1-test")
    sku2 = await _make_sku(db_session, product_id=product_a, sku_code="mlbb-sku2-test")
    sku3 = await _make_sku(db_session, product_id=product_b, sku_code="mlbb-sku3-test")
    sku4 = await _make_sku(
        db_session, product_id=product_a, sku_code="mlbb-sku4-test", active=False
    )

    await _make_mapping(
        db_session,
        sku_id=sku1,
        supplier_slug="g2b",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    await _make_mapping(
        db_session,
        sku_id=sku1,
        supplier_slug="nova",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),  # older, but a reserve
    )
    await _make_history(
        db_session,
        sku_id=sku1,
        supplier_slug="g2b",
        cost_usdt=Decimal("1.000000"),
        captured_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    await _make_history(
        db_session,
        sku_id=sku1,
        supplier_slug="g2b",
        cost_usdt=Decimal("1.500000"),
        captured_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    await _make_history(
        db_session,
        sku_id=sku1,
        supplier_slug="nova",
        cost_usdt=Decimal("2.000000"),
        captured_at=datetime(2026, 2, 1, tzinfo=UTC),
    )

    await _make_mapping(db_session, sku_id=sku2, supplier_slug="gengine")
    await db_session.commit()

    await sourcing_svc.set_rule(
        db_session,
        sku_id=sku2,
        mode="force_supplier",
        supplier_slug="gengine",
        admin_id="test-admin",
    )
    await db_session.commit()

    return {
        "brand_slug": brand_slug,
        "sku1": sku1,
        "sku2": sku2,
        "sku3": sku3,
        "sku4": sku4,
    }


async def test_overview_reports_one_row_per_active_sku(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
    _seed_brand: dict[str, str],
) -> None:
    r = await integration_client.get(
        f"/api/v1/admin/sourcing/brands/{_seed_brand['brand_slug']}",
        headers=_admin_headers,
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    sku_ids = {item["sku_id"] for item in items}

    # sku4 is inactive — excluded.
    assert sku_ids == {_seed_brand["sku1"], _seed_brand["sku2"], _seed_brand["sku3"]}


async def test_overview_route_matches_resolve_for_sku(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
    _seed_brand: dict[str, str],
) -> None:
    r = await integration_client.get(
        f"/api/v1/admin/sourcing/brands/{_seed_brand['brand_slug']}",
        headers=_admin_headers,
    )
    assert r.status_code == 200, r.text
    by_sku = {item["sku_id"]: item for item in r.json()["items"]}

    for key in ("sku1", "sku2", "sku3"):
        sku_id = _seed_brand[key]
        decision = await sourcing_svc.resolve_for_sku(db_session, sku_id)
        assert by_sku[sku_id]["primary"] == decision.primary, key
        assert by_sku[sku_id]["fallback"] == decision.fallback, key
        assert by_sku[sku_id]["rule_present"] == decision.rule_present, key

    # Concrete expectations, not just "matches the service": sku1 must route
    # to g2b (the incumbent), never nova (reserve, older mapping or not).
    assert by_sku[_seed_brand["sku1"]]["primary"] == "supplier:g2b"
    assert by_sku[_seed_brand["sku1"]]["rule_present"] is False
    # sku2 carries an explicit force_supplier rule onto gengine.
    assert by_sku[_seed_brand["sku2"]]["primary"] == "supplier:gengine"
    assert by_sku[_seed_brand["sku2"]]["rule_present"] is True
    # sku3 (voucher, no mapping) is inventory-first by kind default, falling
    # back to the default mock supplier (no real mapping to prefer instead).
    assert by_sku[_seed_brand["sku3"]]["primary"] == "inventory"
    assert by_sku[_seed_brand["sku3"]]["fallback"] == "supplier:mock"
    assert by_sku[_seed_brand["sku3"]]["rule_present"] is False


async def test_overview_voucher_sku_reports_its_fallback_cost_owner(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    """Task 1's fix, pinned: a voucher SKU with an active mapping routes
    ``primary="inventory"``, and the real cost owner —
    ``integrations.cost_refresh.is_routed_supplier``'s second shape, the one
    ADR-0083 Decision 1 names as load-bearing — is only visible through
    ``fallback``. Before the fix, ``SourcingBrandSkuOut`` carried ``primary``
    only, so this screen could not show who owns this SKU's ``cost_usdt``.
    """
    brand_slug = "voucher-fallback-overview-test"
    _category_id, brand_id = await _seed_category_and_brand(db_session, brand_slug=brand_slug)
    product_id = await _make_product(
        db_session, brand_id=brand_id, slug="voucher-fallback-product-test", kind="voucher"
    )
    sku_id = await _make_sku(db_session, product_id=product_id, sku_code="voucher-fallback-test")
    await _make_mapping(db_session, sku_id=sku_id, supplier_slug="g2b", kind="voucher")
    await db_session.commit()

    r = await integration_client.get(
        f"/api/v1/admin/sourcing/brands/{brand_slug}",
        headers=_admin_headers,
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    row = items[0]

    assert row["primary"] == "inventory"
    assert row["fallback"] == "supplier:g2b"


async def test_overview_supplier_comparison_list(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
    _seed_brand: dict[str, str],
) -> None:
    r = await integration_client.get(
        f"/api/v1/admin/sourcing/brands/{_seed_brand['brand_slug']}",
        headers=_admin_headers,
    )
    assert r.status_code == 200, r.text
    by_sku = {item["sku_id"]: item for item in r.json()["items"]}

    sku1_suppliers = {s["supplier_slug"]: s for s in by_sku[_seed_brand["sku1"]]["suppliers"]}
    assert set(sku1_suppliers) == {"g2b", "gengine", "nova"}

    # g2b: active mapping, latest of two history rows (1.5, not 1.0) wins.
    # It is also sku1's routed (incumbent) supplier, but a history row wins
    # over the "current" fallback whenever one exists.
    assert sku1_suppliers["g2b"]["has_active_mapping"] is True
    assert Decimal(sku1_suppliers["g2b"]["latest_cost_usdt"]) == Decimal("1.5")
    assert sku1_suppliers["g2b"]["captured_at"].startswith("2026-06-01")
    assert sku1_suppliers["g2b"]["cost_source"] == "history"

    # nova: active mapping (a reserve — reported, just never routed to), but
    # it does have its own history row, so it still reports "history".
    assert sku1_suppliers["nova"]["has_active_mapping"] is True
    assert Decimal(sku1_suppliers["nova"]["latest_cost_usdt"]) == Decimal("2.0")
    assert sku1_suppliers["nova"]["cost_source"] == "history"

    # gengine: no mapping at all on this SKU, and not the routed supplier
    # either — the exact case the brief calls out: has_active_mapping=false,
    # no cost, and cost_source=None (genuinely unknown, not "not captured"
    # for a supplier we actually buy from).
    assert sku1_suppliers["gengine"]["has_active_mapping"] is False
    assert sku1_suppliers["gengine"]["latest_cost_usdt"] is None
    assert sku1_suppliers["gengine"]["captured_at"] is None
    assert sku1_suppliers["gengine"]["cost_source"] is None

    # sku2: only gengine is mapped (and it's the forced route).
    sku2_suppliers = {s["supplier_slug"]: s for s in by_sku[_seed_brand["sku2"]]["suppliers"]}
    assert sku2_suppliers["gengine"]["has_active_mapping"] is True
    assert sku2_suppliers["g2b"]["has_active_mapping"] is False
    assert sku2_suppliers["g2b"]["latest_cost_usdt"] is None
    assert sku2_suppliers["g2b"]["cost_source"] is None
    assert sku2_suppliers["nova"]["has_active_mapping"] is False
    # gengine is sku2's routed supplier (force_supplier rule) with no history
    # row, but "current" requires a cost to actually report *and* a
    # supplier price collection reaches — neither holds here: sku2.cost_usdt
    # is None (no cost has ever been written) and gengine has no
    # cost_lookup support at all, so cost_source is honestly None, not
    # "current" over nothing.
    assert sku2_suppliers["gengine"]["cost_source"] is None
    assert sku2_suppliers["gengine"]["latest_cost_usdt"] is None


async def test_overview_cost_source_current_for_routed_supplier_with_own_cost(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    """Task 1's fix, pinned on a SKU that actually carries a cost: a top_up
    SKU whose only mapping (g2b) has never had a ``supplier_price_history``
    row still reports g2b's price, sourced from ``Sku.cost_usdt`` — not
    ``None`` rendered as "цена не снята" — because g2b is the supplier this
    SKU routes to (mirrors the production Free Fire finding: zero g2b
    history rows, g2b's price sitting in ``cost_usdt`` to the cent).
    """
    brand_slug = "cost-source-current-test"
    _category_id, brand_id = await _seed_category_and_brand(db_session, brand_slug=brand_slug)
    product_id = await _make_product(
        db_session, brand_id=brand_id, slug="cost-source-current-product-test", kind="top_up"
    )
    sku_id = await _make_sku(
        db_session,
        product_id=product_id,
        sku_code="cost-source-current-sku-test",
        cost_usdt=Decimal("4.250000"),
    )
    await _make_mapping(db_session, sku_id=sku_id, supplier_slug="g2b")
    await db_session.commit()

    r = await integration_client.get(
        f"/api/v1/admin/sourcing/brands/{brand_slug}",
        headers=_admin_headers,
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row["primary"] == "supplier:g2b"

    suppliers_by_slug = {s["supplier_slug"]: s for s in row["suppliers"]}
    g2b = suppliers_by_slug["g2b"]
    assert g2b["cost_source"] == "current"
    assert Decimal(g2b["latest_cost_usdt"]) == Decimal("4.25")
    assert g2b["captured_at"] is None

    # A non-routed, no-history supplier on the same SKU still reports None —
    # "current" is not the default just because *some* supplier on the row
    # got it.
    assert suppliers_by_slug["gengine"]["cost_source"] is None
    assert suppliers_by_slug["gengine"]["latest_cost_usdt"] is None


async def test_overview_cost_source_none_for_routed_supplier_price_collection_does_not_reach(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    """Task 2's fix: a routed supplier still reports ``cost_source=None`` when
    price collection has never reached it, even though ``Sku.cost_usdt`` is
    not ``None``.

    The example is **waxpeer**, which is now the only supplier outside
    ``PRICE_COLLECTION_SUPPORTED_SUPPLIERS``. It used to be gengine; gengine
    joined the set on 2026-09-21 once its catalogue cache started carrying
    prices, which is the whole point of naming the set rather than hardcoding
    a list per call site.

    Unlike the sku2 case in ``test_overview_supplier_comparison_list``, this
    SKU *does* carry a real cost — so this pins the fix on its own, not
    coincidentally alongside "no cost to report at all". A SKU force-routed
    to a supplier ``cost_refresh`` never collects for can only have
    ``Sku.cost_usdt`` because some *other*, earlier-routed supplier wrote it
    — reporting that number as this one's "current" price would be true of a
    supplier we never actually queried.
    """
    brand_slug = "cost-source-unsupported-routed-test"
    _category_id, brand_id = await _seed_category_and_brand(db_session, brand_slug=brand_slug)
    product_id = await _make_product(
        db_session,
        brand_id=brand_id,
        slug="cost-source-unsupported-routed-product-test",
        kind="top_up",
    )
    sku_id = await _make_sku(
        db_session,
        product_id=product_id,
        sku_code="cost-source-unsupported-routed-sku-test",
        cost_usdt=Decimal("9.990000"),
    )
    await _make_mapping(db_session, sku_id=sku_id, supplier_slug="waxpeer")
    await db_session.commit()

    await sourcing_svc.set_rule(
        db_session,
        sku_id=sku_id,
        mode="force_supplier",
        supplier_slug="waxpeer",
        admin_id="test-admin",
    )
    await db_session.commit()

    r = await integration_client.get(
        f"/api/v1/admin/sourcing/brands/{brand_slug}",
        headers=_admin_headers,
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row["primary"] == "supplier:waxpeer"

    waxpeer = next(s for s in row["suppliers"] if s["supplier_slug"] == "waxpeer")
    assert waxpeer["cost_source"] is None
    assert waxpeer["latest_cost_usdt"] is None


async def test_overview_cost_source_current_for_voucher_fallback_supplier(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    """The voucher inventory-fallback shape: ``primary="inventory"``,
    ``fallback="supplier:g2b"``. ``is_routed_supplier`` treats the
    fallback slug as the routed one for this shape (ADR-0083 Decision 1),
    so it must resolve to ``cost_source="current"`` too, not just the
    top_up ``primary="supplier:<slug>"`` shape covered above.
    """
    brand_slug = "cost-source-voucher-fallback-test"
    _category_id, brand_id = await _seed_category_and_brand(db_session, brand_slug=brand_slug)
    product_id = await _make_product(
        db_session,
        brand_id=brand_id,
        slug="cost-source-voucher-fallback-product-test",
        kind="voucher",
    )
    sku_id = await _make_sku(
        db_session,
        product_id=product_id,
        sku_code="cost-source-voucher-fallback-sku-test",
        cost_usdt=Decimal("7.500000"),
    )
    await _make_mapping(db_session, sku_id=sku_id, supplier_slug="g2b", kind="voucher")
    await db_session.commit()

    r = await integration_client.get(
        f"/api/v1/admin/sourcing/brands/{brand_slug}",
        headers=_admin_headers,
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row["primary"] == "inventory"
    assert row["fallback"] == "supplier:g2b"

    g2b = next(s for s in row["suppliers"] if s["supplier_slug"] == "g2b")
    assert g2b["cost_source"] == "current"
    assert Decimal(g2b["latest_cost_usdt"]) == Decimal("7.5")
    assert g2b["captured_at"] is None


async def test_overview_primary_names_a_supplier_present_in_its_own_suppliers_list(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    """The invariant the defect broke: ``primary`` must never name a
    supplier absent from that same SKU's ``suppliers`` comparison list.

    Before the fix, the comparison list's candidate set was fixed to
    ``MAPPING_REQUIRED_SUPPLIERS`` (g2b, gengine, nova). ``waxpeer`` is a
    real, live supplier in the fulfilment ``REGISTRY`` that sits outside
    that set, and a SKU whose only active mapping is to waxpeer still
    auto-routes to it via ``_pick_auto_mapping_slug`` (it is not a
    reserve). So the endpoint reported ``primary == "supplier:waxpeer"``
    next to a ``suppliers`` list that never contained a "waxpeer" entry at
    all — a route whose supplier is missing from its own comparison.
    """
    brand_slug = "waxpeer-overview-test"
    _category_id, brand_id = await _seed_category_and_brand(db_session, brand_slug=brand_slug)
    product_id = await _make_product(
        db_session, brand_id=brand_id, slug="waxpeer-overview-product-test", kind="top_up"
    )
    sku_id = await _make_sku(db_session, product_id=product_id, sku_code="waxpeer-sku-test")
    await _make_mapping(db_session, sku_id=sku_id, supplier_slug="waxpeer")
    await db_session.commit()

    r = await integration_client.get(
        f"/api/v1/admin/sourcing/brands/{brand_slug}",
        headers=_admin_headers,
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    row = items[0]

    suppliers_by_slug = {s["supplier_slug"]: s for s in row["suppliers"]}
    assert "waxpeer" in suppliers_by_slug, "waxpeer missing from the comparison list entirely"
    assert suppliers_by_slug["waxpeer"]["has_active_mapping"] is True

    assert row["primary"] == "supplier:waxpeer"
    primary_slug = row["primary"].removeprefix("supplier:")
    assert primary_slug in suppliers_by_slug, (
        f"primary names {primary_slug!r} but it is absent from the SKU's own "
        f"suppliers list: {sorted(suppliers_by_slug)}"
    )


async def test_overview_primary_from_force_supplier_rule_is_present_in_suppliers_list(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    """Same invariant as the test above, broken through the *other* branch of
    ``primary``'s two sources: an explicit ``force_supplier`` rule rather
    than an auto-picked mapping.

    ``_resolve_explicit_rule`` returns ``f"supplier:{rule.supplier_slug}"``
    for *any* slug, and ``set_rule`` only requires an active mapping row
    when the slug is in ``MAPPING_REQUIRED_SUPPLIERS`` — waxpeer needs none.
    Before the fix, ``candidate_slugs`` was built from
    ``MAPPING_REQUIRED_SUPPLIERS | {mapping rows}`` only (no rule rows), so
    a SKU force-routed onto waxpeer with *no* mapping row anywhere at all
    still reported ``primary == "supplier:waxpeer"`` next to a ``suppliers``
    list that never contained a "waxpeer" entry — the exact defect the prior
    fix closed on the mapping branch, reopened here on the rule branch of
    the same ``if rule is not None and rule.mode != "auto"``.
    """
    brand_slug = "force-rule-overview-test"
    _category_id, brand_id = await _seed_category_and_brand(db_session, brand_slug=brand_slug)
    product_id = await _make_product(
        db_session, brand_id=brand_id, slug="force-rule-overview-product-test", kind="top_up"
    )
    sku_id = await _make_sku(db_session, product_id=product_id, sku_code="force-rule-sku-test")
    await db_session.commit()

    # No SkuSupplierMapping row at all for this SKU — waxpeer or otherwise.
    await sourcing_svc.set_rule(
        db_session,
        sku_id=sku_id,
        mode="force_supplier",
        supplier_slug="waxpeer",
        admin_id="test-admin",
    )
    await db_session.commit()

    r = await integration_client.get(
        f"/api/v1/admin/sourcing/brands/{brand_slug}",
        headers=_admin_headers,
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    row = items[0]

    assert row["primary"] == "supplier:waxpeer"
    suppliers_by_slug = {s["supplier_slug"]: s for s in row["suppliers"]}
    assert "waxpeer" in suppliers_by_slug, "waxpeer missing from the comparison list entirely"
    # No mapping row exists — the comparison entry is present but empty.
    assert suppliers_by_slug["waxpeer"]["has_active_mapping"] is False
    assert suppliers_by_slug["waxpeer"]["latest_cost_usdt"] is None

    primary_slug = row["primary"].removeprefix("supplier:")
    assert primary_slug in suppliers_by_slug, (
        f"primary names {primary_slug!r} but it is absent from the SKU's own "
        f"suppliers list: {sorted(suppliers_by_slug)}"
    )


async def test_overview_malformed_force_supplier_rule_reports_invalid(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
    _seed_brand: dict[str, str],
) -> None:
    """A ``force_supplier`` row with an empty ``supplier_slug`` — a shape
    ``set_rule`` itself refuses to write, but a direct SQL statement, a
    seed, or a migration still can — must not 400 the whole brand screen.
    This is the exact screen an operator opens to *fix* routing, so one
    broken row must not take the other rows down with it.

    ``supplier_slug=""`` rather than ``NULL``: the table's own
    ``ck_sku_sourcing_rules_supplier_required`` CHECK constraint (migration
    0010) already blocks ``NULL`` at the database level, so that particular
    row can never exist — but the constraint only tests ``IS NOT NULL``, and
    ``_resolve_explicit_rule``'s guard is ``if not rule.supplier_slug``,
    which is also true for an empty string. ``""`` clears the DB constraint
    while still tripping the application-level one, which is exactly the gap
    a stray SQL statement, a seed, or a migration could fall into.

    Written directly through the session (``db_session.add``), bypassing
    ``set_rule``'s validation entirely, to reproduce a row nothing in this
    module would ever construct on its own.
    """
    broken_sku = _seed_brand["sku3"]  # currently ruleless — auto/inventory
    db_session.add(
        SkuSourcingRule(
            sku_id=broken_sku,
            mode="force_supplier",
            supplier_slug="",
            updated_by="test-direct-sql",
        )
    )
    await db_session.commit()

    r = await integration_client.get(
        f"/api/v1/admin/sourcing/brands/{_seed_brand['brand_slug']}",
        headers=_admin_headers,
    )
    assert r.status_code == 200, r.text
    by_sku = {item["sku_id"]: item for item in r.json()["items"]}

    # The broken row renders as "invalid" rather than 500ing/400ing the page.
    assert by_sku[broken_sku]["primary"] == "invalid"
    assert by_sku[broken_sku]["rule_present"] is True

    # The other SKUs of the same brand still load normally alongside it.
    assert by_sku[_seed_brand["sku1"]]["primary"] == "supplier:g2b"
    assert by_sku[_seed_brand["sku2"]]["primary"] == "supplier:gengine"


async def test_overview_sku_fields(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
    _seed_brand: dict[str, str],
) -> None:
    r = await integration_client.get(
        f"/api/v1/admin/sourcing/brands/{_seed_brand['brand_slug']}",
        headers=_admin_headers,
    )
    by_sku = {item["sku_id"]: item for item in r.json()["items"]}
    row = by_sku[_seed_brand["sku1"]]
    assert row["sku_code"] == "mlbb-sku1-test"
    assert row["denomination"] == "100"
    assert row["product_slug"] == "mlbb-diamonds-test"
    # product_kind lets the brand-overview screen stop offering
    # force_inventory on a row the backend (set_rule) would refuse anyway —
    # sku1 is under product_a (kind=top_up), sku3 under product_b
    # (kind=voucher); each row reports its own product's kind, not a
    # constant or the brand's.
    assert row["product_kind"] == "top_up"
    voucher_row = by_sku[_seed_brand["sku3"]]
    assert voucher_row["product_kind"] == "voucher"
    assert Decimal(row["price_usd"]) == Decimal("1.00")


async def test_overview_unknown_brand_404s(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    r = await integration_client.get(
        "/api/v1/admin/sourcing/brands/does-not-exist",
        headers=_admin_headers,
    )
    assert r.status_code == 404


async def test_overview_non_admin_forbidden(
    integration_client: AsyncClient,
    _seed_brand: dict[str, str],
) -> None:
    token = await _login_user(integration_client, tg_id=9002)
    r = await integration_client.get(
        f"/api/v1/admin/sourcing/brands/{_seed_brand['brand_slug']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


async def test_overview_sql_query_count_is_bounded(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    db_engine,
    _admin_headers: dict[str, str],
    sql_counter: dict[str, int],
) -> None:
    """Adding more SKUs (each with its own mapping + history row, spread
    across two *products* and two *suppliers*) must not grow the query
    count — the three N+1s the brief calls out: resolving the route,
    reading mappings, and reading price history per row.

    The original fixture put every SKU under one product with one supplier,
    so a per-product or per-supplier N+1 (e.g. a query keyed on
    ``product_id`` or ``supplier_slug`` instead of batched with ``IN``)
    would never have shown up here. Alternating both flushes that blind
    spot out. A generous absolute ceiling runs beside the delta check too:
    the delta assertion alone would pass a constant blow-up (5 queries ->
    50, still flat as SKUs are added) that is still a real regression.
    """
    brand_slug = "query-count-brand-test"
    _category_id, brand_id = await _seed_category_and_brand(db_session, brand_slug=brand_slug)
    product_a = await _make_product(
        db_session, brand_id=brand_id, slug="query-count-product-a-test", kind="top_up"
    )
    product_b = await _make_product(
        db_session, brand_id=brand_id, slug="query-count-product-b-test", kind="top_up"
    )
    products = (product_a, product_b)
    suppliers = ("g2b", "gengine")

    async def _add_sku(n: int) -> None:
        product_id = products[n % 2]
        supplier_slug = suppliers[n % 2]
        sku_id = await _make_sku(db_session, product_id=product_id, sku_code=f"qc-sku-{n}-test")
        await _make_mapping(db_session, sku_id=sku_id, supplier_slug=supplier_slug)
        await _make_history(
            db_session,
            sku_id=sku_id,
            supplier_slug=supplier_slug,
            cost_usdt=Decimal("1.000000"),
            captured_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    for n in range(2):
        await _add_sku(n)
    await db_session.commit()

    url = f"/api/v1/admin/sourcing/brands/{brand_slug}"
    small_count = await _measure_get(integration_client, sql_counter, url, _admin_headers)

    for n in range(2, 6):
        await _add_sku(n)
    await db_session.commit()

    large_count = await _measure_get(integration_client, sql_counter, url, _admin_headers)

    assert large_count == small_count, (
        f"query count grew from {small_count} to {large_count} as SKUs were added — N+1"
    )
    # Absolute ceiling: the endpoint runs five bounded sourcing queries plus
    # the request's auth/admin lookups, not dozens — a constant blow-up
    # (5 queries -> 50, still flat as SKUs are added) would slip past the
    # delta check above but must still fail here. 30 leaves real headroom
    # above what this measures today (comfortably under 20) without coming
    # anywhere near "dozens."
    assert small_count <= 30, (
        f"query count {small_count} is far above what this endpoint should need"
    )


async def _cache_stock(
    db: AsyncSession,
    *,
    supplier_slug: str,
    stock: object,
    kind: str = "game_denom",
    external_id: str = "100",
    parent: str = "ext-1",
) -> None:
    """The catalogue row the screen now reads a per-supplier count from.

    Defaults line up with ``_make_mapping``'s ``ext-1``/``100``, so a test
    only names the supplier and the number it cares about.
    """
    db.add(
        SupplierCatalogCache(
            supplier_slug=supplier_slug,
            kind=kind,
            external_id=external_id,
            parent_external_id=parent,
            title="denom",
            raw={"stock": stock},
        )
    )
    await db.commit()


async def test_overview_reports_each_supplier_s_own_stock(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    """The question the screen could not answer before.

    ``Sku.supplier_stock`` holds one number — the routed supplier's — which
    is right for the shelf and useless for comparing suppliers. Production
    2026-09-22: ``roblox-2000`` was off sale because G-Engine, the supplier
    it was pinned to, sat at 0, while NOVA held 19 and G2B 96. Nothing on
    this screen said so.
    """
    brand_slug = "stock-compare-brand-test"
    _category_id, brand_id = await _seed_category_and_brand(db_session, brand_slug=brand_slug)
    product_id = await _make_product(
        db_session, brand_id=brand_id, slug="stock-compare-product-test", kind="top_up"
    )
    sku_id = await _make_sku(db_session, product_id=product_id, sku_code="stock-compare-sku-test")
    await _make_mapping(db_session, sku_id=sku_id, supplier_slug="gengine")
    await _make_mapping(db_session, sku_id=sku_id, supplier_slug="nova")
    await db_session.commit()
    await _cache_stock(db_session, supplier_slug="gengine", stock=0)
    await _cache_stock(db_session, supplier_slug="nova", stock=19)

    resp = await integration_client.get(
        f"/api/v1/admin/sourcing/brands/{brand_slug}", headers=_admin_headers
    )

    assert resp.status_code == 200, resp.text
    suppliers = {s["supplier_slug"]: s for s in resp.json()["items"][0]["suppliers"]}
    assert suppliers["gengine"]["stock"] == 0
    assert suppliers["nova"]["stock"] == 19
    assert suppliers["nova"]["stock_at"] is not None
    # g2b is a candidate on every row but this SKU was never mapped to it,
    # so we have never asked it about this rung. Not zero — unknown.
    assert suppliers["g2b"]["stock"] is None


async def test_overview_untracked_stock_reads_as_unknown_not_zero(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _admin_headers: dict[str, str],
) -> None:
    """``-1`` upstream means "not tracked", and ``normalise_stock`` owns that
    rule — reading it a second time here would be a second rule to keep in
    step. Rendering it as 0 would take a sellable line off the comparison."""
    brand_slug = "stock-untracked-brand-test"
    _category_id, brand_id = await _seed_category_and_brand(db_session, brand_slug=brand_slug)
    product_id = await _make_product(
        db_session, brand_id=brand_id, slug="stock-untracked-product-test", kind="top_up"
    )
    sku_id = await _make_sku(db_session, product_id=product_id, sku_code="stock-untracked-sku-test")
    await _make_mapping(db_session, sku_id=sku_id, supplier_slug="g2b")
    await db_session.commit()
    await _cache_stock(db_session, supplier_slug="g2b", stock=-1)

    resp = await integration_client.get(
        f"/api/v1/admin/sourcing/brands/{brand_slug}", headers=_admin_headers
    )

    suppliers = {s["supplier_slug"]: s for s in resp.json()["items"][0]["suppliers"]}
    assert suppliers["g2b"]["stock"] is None
