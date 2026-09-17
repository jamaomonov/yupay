"""Hourly price-refresh worker + history endpoint + admin trigger.

Verified end-to-end:

- Game catalogue movement → ``Sku.cost_usdt`` flipped, history row inserted.
- No movement → history table left alone.
- Telegram alert bot called when |Δ%| ≥ threshold; suppressed otherwise.
- Each mapping processed in its own transaction (one failure doesn't
  poison the run).
- ``GET /admin/integrations/sku-prices/{id}/history`` returns rows newest
  first.
- ``POST /admin/integrations/refresh-all-prices`` mirrors the scheduler.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from urllib.parse import urlencode

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
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
    NOVA_STEAM_SENTINEL,
    SkuSupplierMapping,
    SupplierPriceHistory,
)
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
G2B_BASE = "https://g2b.test/v1"
NOVA_BASE = "https://nova.test"
ALERT_BOT_TOKEN = "alert-bot-token"
ALERT_CHAT_ID = "555000"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("G2B_API_KEY", "test-key")
    monkeypatch.setenv("G2B_BASE_URL", G2B_BASE)
    monkeypatch.setenv("NOVA_API_KEY", "test-nova-key")
    monkeypatch.setenv("NOVA_BASE_URL", NOVA_BASE)
    monkeypatch.setenv("TG_ALERT_BOT_TOKEN", ALERT_BOT_TOKEN)
    monkeypatch.setenv("TG_ALERT_CHAT_ID", ALERT_CHAT_ID)
    monkeypatch.setenv("PRICE_ALERT_THRESHOLD_PCT", "5")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login_admin(client: AsyncClient, db: AsyncSession, tg_id: int) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "U"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200
    token = r.json()["access_token"]
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()
    return token


async def _seed_sku(
    db: AsyncSession,
    slug_suffix: str,
    initial_cost: str | None = None,
    *,
    price_usd: str = "1.00",
    margin_percent: str | None = None,
) -> str:
    category = Category(
        id=new_id(),
        slug=f"cat-{slug_suffix}",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Cat")],
    )
    brand = Brand(
        id=new_id(),
        slug=f"br-{slug_suffix}",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Br")],
    )
    product = Product(
        id=new_id(),
        slug=f"prod-{slug_suffix}",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Prod")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"sk-{slug_suffix}",
        denomination="60",
        region="WW",
        price_usd=Decimal(price_usd),
        cost_usdt=Decimal(initial_cost) if initial_cost else None,
        margin_percent=Decimal(margin_percent) if margin_percent else None,
        sort_order=10,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    await db.commit()
    return sku.id


async def _seed_mapping(
    db: AsyncSession,
    *,
    sku_id: str,
    game_code: str,
    denom: str,
) -> SkuSupplierMapping:
    row = SkuSupplierMapping(
        sku_id=sku_id,
        supplier_slug="g2b",
        kind="game",
        external_product_id=game_code,
        external_variant_id=denom,
        quantity=1,
        extra={},
        is_active=True,
    )
    db.add(row)
    await db.commit()
    return row


async def _seed_nova_mapping(
    db: AsyncSession,
    *,
    sku_id: str,
    category_id: str,
    offer_id: str | None,
) -> SkuSupplierMapping:
    row = SkuSupplierMapping(
        sku_id=sku_id,
        supplier_slug="nova",
        kind="game",
        external_product_id=category_id,
        external_variant_id=offer_id,
        quantity=1,
        extra={},
        is_active=True,
    )
    db.add(row)
    await db.commit()
    return row


async def _seed_two_mapping_sku(
    db: AsyncSession,
    *,
    slug_suffix: str,
    initial_g2b_cost: str,
) -> tuple[str, SkuSupplierMapping, SkuSupplierMapping]:
    """A SKU with **two** active mappings (G2B + NOVA), sourcing forced onto
    NOVA — the exact shape 22 production SKUs now have (Free Fire's switch)
    and the scenario the routed-supplier rule exists for. Returns
    ``(sku_id, g2b_mapping, nova_mapping)``.
    """
    from yupay.modules.sourcing import service as sourcing_svc

    sku_id = await _seed_sku(db, slug_suffix=slug_suffix, initial_cost=initial_g2b_cost)
    g2b_mapping = await _seed_mapping(db, sku_id=sku_id, game_code="pubgm", denom="60")
    nova_mapping = await _seed_nova_mapping(
        db, sku_id=sku_id, category_id="pubg_mobile_auto", offer_id="offer-60uc"
    )
    await sourcing_svc.set_rule(
        db, sku_id=sku_id, mode="force_supplier", supplier_slug="nova", admin_id="test"
    )
    await db.commit()
    return sku_id, g2b_mapping, nova_mapping


# ---------- routed-supplier rule (per-supplier costs, §4) ----------


async def test_routed_supplier_writes_cost_and_history(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Two active mappings, sourcing forced onto NOVA. Refreshing the
    **routed** mapping (NOVA) writes both ``Sku.cost_usdt`` and a history
    row."""
    from yupay.modules.integrations import service as svc

    sku_id, _g2b_mapping, nova_mapping = await _seed_two_mapping_sku(
        db_session, slug_suffix="routed-nova", initial_g2b_cost="0.82"
    )

    outcome = await svc.refresh_sku_cost_for_mapping(
        db_session,
        mapping=nova_mapping,
        nova_offers_cache={
            "pubg_mobile_auto": {
                "ok": True,
                "offers": [{"offer_id": "offer-60uc", "name": "60 UC", "price_usd": 0.79}],
            }
        },
    )
    await db_session.commit()

    assert outcome.wrote_cost is True
    assert outcome.updated is True
    assert outcome.new_cost == Decimal("0.79")

    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("0.79")

    history = (
        (
            await db_session.execute(
                select(SupplierPriceHistory).where(
                    SupplierPriceHistory.sku_id == sku_id,
                    SupplierPriceHistory.supplier_slug == "nova",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(history) == 1
    assert history[0].cost_usdt == Decimal("0.79")


@respx.mock
async def test_non_routed_supplier_writes_history_only(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """The **other** mapping (G2B, while sourcing is forced onto NOVA)
    records a history row and must leave ``Sku.cost_usdt`` exactly as it
    was — asserted against the old value itself, not merely "not the new
    G2B price"."""
    from yupay.modules.integrations import service as svc

    sku_id, g2b_mapping, _nova_mapping = await _seed_two_mapping_sku(
        db_session, slug_suffix="non-routed-g2b", initial_g2b_cost="0.82"
    )
    respx.get(f"{G2B_BASE}/games/pubgm/catalogue").mock(
        return_value=httpx.Response(
            200,
            json={"catalogues": [{"id": 1, "name": "60", "amount": 0.95}]},
        )
    )

    outcome = await svc.refresh_sku_cost_for_mapping(db_session, mapping=g2b_mapping)
    await db_session.commit()

    assert outcome.wrote_cost is False
    assert outcome.updated is False
    assert outcome.new_cost == Decimal("0.95")

    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("0.82")  # the OLD value — never touched by G2B here

    history = (
        (
            await db_session.execute(
                select(SupplierPriceHistory).where(
                    SupplierPriceHistory.sku_id == sku_id,
                    SupplierPriceHistory.supplier_slug == "g2b",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(history) == 1
    assert history[0].cost_usdt == Decimal("0.95")


@respx.mock
async def test_both_suppliers_history_queryable_with_correct_supplier_slug(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """After refreshing both mappings once, the per-supplier comparison the
    admin screen reads has one history row per supplier, each correctly
    attributed — and only the routed supplier's number survives on the
    SKU itself."""
    from yupay.modules.integrations import service as svc

    sku_id, g2b_mapping, nova_mapping = await _seed_two_mapping_sku(
        db_session, slug_suffix="both-history", initial_g2b_cost="0.82"
    )
    respx.get(f"{G2B_BASE}/games/pubgm/catalogue").mock(
        return_value=httpx.Response(
            200, json={"catalogues": [{"id": 1, "name": "60", "amount": 0.95}]}
        )
    )

    await svc.refresh_sku_cost_for_mapping(
        db_session,
        mapping=nova_mapping,
        nova_offers_cache={
            "pubg_mobile_auto": {
                "ok": True,
                "offers": [{"offer_id": "offer-60uc", "name": "60 UC", "price_usd": 0.79}],
            }
        },
    )
    await svc.refresh_sku_cost_for_mapping(db_session, mapping=g2b_mapping)
    await db_session.commit()

    history = (
        (
            await db_session.execute(
                select(SupplierPriceHistory)
                .where(SupplierPriceHistory.sku_id == sku_id)
                .order_by(SupplierPriceHistory.supplier_slug)
            )
        )
        .scalars()
        .all()
    )
    assert [(h.supplier_slug, h.cost_usdt) for h in history] == [
        ("g2b", Decimal("0.95")),
        ("nova", Decimal("0.79")),
    ]

    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("0.79")  # only the routed supplier's write survives


async def test_nova_steam_mapping_is_skipped_entirely(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A NOVA mapping whose ``external_product_id`` is the Steam sentinel
    has no catalogue price — it is reported with a reason and writes
    nothing at all, not even history."""
    from yupay.modules.integrations import service as svc

    sku_id = await _seed_sku(db_session, slug_suffix="nova-steam", initial_cost="1.00")
    steam_mapping = await _seed_nova_mapping(
        db_session, sku_id=sku_id, category_id=NOVA_STEAM_SENTINEL, offer_id=None
    )

    outcome = await svc.refresh_sku_cost_for_mapping(db_session, mapping=steam_mapping)
    await db_session.commit()

    assert outcome.wrote_cost is False
    assert outcome.updated is False
    assert outcome.new_cost is None
    assert outcome.reason is not None

    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("1.00")

    history = (
        (
            await db_session.execute(
                select(SupplierPriceHistory).where(SupplierPriceHistory.sku_id == sku_id)
            )
        )
        .scalars()
        .all()
    )
    assert history == []


# ---------- worker ----------


@respx.mock
async def test_refresh_all_records_history_and_fires_alert(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """First-time pricing → cost set, history row written, Telegram alert
    sent (no previous cost → always alert)."""
    sku_id = await _seed_sku(db_session, slug_suffix="alert-fire")
    await _seed_mapping(db_session, sku_id=sku_id, game_code="pubgm", denom="60")

    respx.get(f"{G2B_BASE}/games/pubgm/catalogue").mock(
        return_value=httpx.Response(
            200,
            json={"catalogues": [{"id": 1, "name": "60", "amount": 0.89}]},
        )
    )
    tg_route = respx.post(f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    from yupay.modules.integrations.price_refresh import refresh_all_mappings

    report = await refresh_all_mappings()
    assert report.checked == 1
    assert report.moved == 1
    assert report.alerts_sent == 1
    assert tg_route.called

    history = (
        (
            await db_session.execute(
                select(SupplierPriceHistory).where(SupplierPriceHistory.sku_id == sku_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(history) == 1
    assert history[0].cost_usdt == Decimal("0.89")
    assert history[0].previous_cost_usdt is None

    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("0.89")


@respx.mock
async def test_refresh_all_skips_alert_under_threshold(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """1% move with 5% threshold → cost updates, history records, alert
    is NOT sent."""
    sku_id = await _seed_sku(db_session, slug_suffix="under-thr", initial_cost="0.890000")
    await _seed_mapping(db_session, sku_id=sku_id, game_code="pubgm", denom="60")

    respx.get(f"{G2B_BASE}/games/pubgm/catalogue").mock(
        return_value=httpx.Response(
            200,
            json={"catalogues": [{"id": 1, "name": "60", "amount": 0.898}]},
        )
    )
    tg_route = respx.post(f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    from yupay.modules.integrations.price_refresh import refresh_all_mappings

    report = await refresh_all_mappings()
    assert report.checked == 1
    assert report.moved == 1
    assert report.alerts_sent == 0
    assert not tg_route.called


@respx.mock
async def test_refresh_all_noop_when_price_unchanged(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """G2B returns the same price → nothing recorded, nothing alerted."""
    sku_id = await _seed_sku(db_session, slug_suffix="noop", initial_cost="0.890000")
    await _seed_mapping(db_session, sku_id=sku_id, game_code="pubgm", denom="60")

    respx.get(f"{G2B_BASE}/games/pubgm/catalogue").mock(
        return_value=httpx.Response(
            200,
            json={"catalogues": [{"id": 1, "name": "60", "amount": 0.89}]},
        )
    )

    from yupay.modules.integrations.price_refresh import refresh_all_mappings

    report = await refresh_all_mappings()
    assert report.checked == 1
    assert report.moved == 0
    assert report.alerts_sent == 0
    history = (
        (
            await db_session.execute(
                select(SupplierPriceHistory).where(SupplierPriceHistory.sku_id == sku_id)
            )
        )
        .scalars()
        .all()
    )
    assert history == []


@respx.mock
async def test_refresh_recomputes_price_from_saved_margin(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A SKU with a saved margin gets price_usd re-derived alongside
    cost_usdt — the protection the feature exists for: cost jumps from
    $10 to $13, and a 20% margin on file means the shelf price follows
    to $15.60 instead of sitting frozen at the old $12 (which would be
    below the new cost)."""
    sku_id = await _seed_sku(
        db_session,
        slug_suffix="margin-protect",
        initial_cost="10.00",
        price_usd="12.00",
        margin_percent="20",
    )
    await _seed_mapping(db_session, sku_id=sku_id, game_code="pubgm", denom="60")

    respx.get(f"{G2B_BASE}/games/pubgm/catalogue").mock(
        return_value=httpx.Response(
            200,
            json={"catalogues": [{"id": 1, "name": "60", "amount": 13.00}]},
        )
    )
    tg_route = respx.post(f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    from yupay.modules.integrations.price_refresh import refresh_all_mappings

    report = await refresh_all_mappings()
    assert report.moved == 1
    assert report.alerts_sent == 1

    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("13.00")
    assert sku.price_usd == Decimal("15.60")

    sent = json.loads(tg_route.calls.last.request.content)
    assert "Цена USD" in sent["text"]
    assert "$15.60" in sent["text"]
    assert "наценка 20" in sent["text"]


@respx.mock
async def test_refresh_leaves_price_alone_without_a_saved_margin(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """No margin on file → cost_usdt still updates (pre-existing behaviour),
    but price_usd is left exactly as an admin set it — never silently
    changed for a SKU nobody has ever attached a margin to."""
    sku_id = await _seed_sku(
        db_session,
        slug_suffix="no-margin",
        initial_cost="10.00",
        price_usd="12.00",
    )
    await _seed_mapping(db_session, sku_id=sku_id, game_code="pubgm", denom="60")

    respx.get(f"{G2B_BASE}/games/pubgm/catalogue").mock(
        return_value=httpx.Response(
            200,
            json={"catalogues": [{"id": 1, "name": "60", "amount": 13.00}]},
        )
    )
    tg_route = respx.post(f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    from yupay.modules.integrations.price_refresh import refresh_all_mappings

    await refresh_all_mappings()

    sku = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert sku.cost_usdt == Decimal("13.00")
    assert sku.price_usd == Decimal("12.00")

    sent = json.loads(tg_route.calls.last.request.content)
    assert "Цена USD" not in sent["text"]


# ---------- admin endpoints ----------


@respx.mock
async def test_history_endpoint_returns_newest_first(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    sku_id = await _seed_sku(db_session, slug_suffix="hist")
    await _seed_mapping(db_session, sku_id=sku_id, game_code="pubgm", denom="60")
    respx.get(f"{G2B_BASE}/games/pubgm/catalogue").mock(
        side_effect=[
            httpx.Response(200, json={"catalogues": [{"id": 1, "name": "60", "amount": 0.89}]}),
            httpx.Response(200, json={"catalogues": [{"id": 1, "name": "60", "amount": 0.95}]}),
        ]
    )
    respx.post(f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    from yupay.modules.integrations.price_refresh import refresh_all_mappings

    await refresh_all_mappings()
    await refresh_all_mappings()

    admin = await _login_admin(integration_client, db_session, tg_id=901)
    r = await integration_client.get(
        f"/api/v1/admin/integrations/sku-prices/{sku_id}/history",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    # Newest first.
    assert items[0]["cost_usdt"] == "0.950000"
    assert items[0]["previous_cost_usdt"] == "0.890000"
    assert items[1]["cost_usdt"] == "0.890000"


@respx.mock
async def test_manual_refresh_all_endpoint(
    integration_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    sku_id = await _seed_sku(db_session, slug_suffix="manual")
    await _seed_mapping(db_session, sku_id=sku_id, game_code="pubgm", denom="60")
    respx.get(f"{G2B_BASE}/games/pubgm/catalogue").mock(
        return_value=httpx.Response(
            200,
            json={"catalogues": [{"id": 1, "name": "60", "amount": 0.89}]},
        )
    )
    respx.post(f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    admin = await _login_admin(integration_client, db_session, tg_id=902)
    r = await integration_client.post(
        "/api/v1/admin/integrations/refresh-all-prices",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["checked"] == 1
    assert body["moved"] == 1
    assert body["alerts_sent"] == 1
