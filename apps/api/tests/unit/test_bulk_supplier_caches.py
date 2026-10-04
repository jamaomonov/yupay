"""Supplier traffic that survives the 2026-10 bulk import.

The import maps a few thousand SKUs across ~260 FazerCards categories and
~130 G2B games. Two hourly passes used to ask a supplier once per *mapping*;
FazerCards answered 429 to four parallel ``/topups/offers`` calls the day the
catalogues were dumped. These pin the shapes that keep the traffic at one call
per category or game, paced, with a wait-and-retry on a 429.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest
from yupay.modules.fulfillment.suppliers import panel_client
from yupay.modules.fulfillment.suppliers.panel_client import PanelError, retry_after_seconds
from yupay.modules.fulfillment.suppliers.panel_fields import build_fields
from yupay.modules.integrations import cost_refresh, price_refresh
from yupay.modules.integrations.models import PANEL_STEAM_SENTINEL

pytestmark = pytest.mark.asyncio


def _mapping(*, supplier: str, kind: str = "game", product_id: str) -> Any:
    return Mock(supplier_slug=supplier, kind=kind, external_product_id=product_id)


# --- fields: identifiers that do not end in _id -------------------------------


@pytest.mark.parametrize("their_key", ["uid", "sid"])
async def test_a_bare_identifier_takes_our_player_id(their_key: str) -> None:
    spec = [{"key": their_key, "label": "ID", "type": "text"}]

    assert build_fields(spec, {"player_id": "123456"}) == {their_key: "123456"}


# --- 429 handling -------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "seconds"),
    [
        ("Слишком много запросов. Повторите через 45 с.", 45.0),
        ("slow down", 30.0),
        ("wait 600 s", 60.0),
    ],
)
async def test_the_wait_is_read_from_the_prose_and_capped(message: str, seconds: float) -> None:
    assert retry_after_seconds(message) == seconds


class _RateLimited(panel_client.PanelClient):
    """A client whose first ``get_offers`` is a 429, then answers."""

    def __init__(self) -> None:  # no HTTP session needed
        self.calls = 0

    async def get_offers(self, category_id: str) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            raise PanelError("Повторите через 7 с.", status=429)
        return {"offers": [{"offer_id": category_id}]}


async def test_a_paced_call_waits_out_one_429_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []

    async def _sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("yupay.modules.fulfillment.suppliers.panel_client.asyncio.sleep", _sleep)
    client = _RateLimited()

    body = await client.get_offers_paced("acecraft")

    assert body == {"offers": [{"offer_id": "acecraft"}]}
    assert client.calls == 2
    assert slept == [7.0, panel_client.BULK_PAUSE_SECONDS]


async def test_any_other_refusal_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("yupay.modules.fulfillment.suppliers.panel_client.asyncio.sleep", _sleep)

    class _Gone(_RateLimited):
        async def get_offers(self, category_id: str) -> dict[str, Any]:
            self.calls += 1
            raise PanelError("not found", status=404)

    client = _Gone()
    with pytest.raises(PanelError):
        await client.get_offers_paced("gone")
    assert client.calls == 1


# --- one call per category / game ---------------------------------------------


class _FakePanel:
    def __init__(self, failing: set[str] | None = None) -> None:
        self.asked: list[str] = []
        self.failing = failing or set()

    async def get_offers_paced(self, category_id: str) -> dict[str, Any]:
        self.asked.append(category_id)
        if category_id in self.failing:
            raise PanelError("boom", status=500)
        return {"offers": [], "category_id": category_id}


async def test_fzr_categories_are_fetched_once_each(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakePanel(failing={"broken"})
    monkeypatch.setattr(
        "yupay.modules.integrations.catalog_sync_panel.client_or_none", lambda _slug: fake
    )
    mappings = [
        _mapping(supplier="fzr", product_id="valorant_my"),
        _mapping(supplier="fzr", product_id="valorant_my"),
        _mapping(supplier="fzr", product_id="broken"),
        _mapping(supplier="fzr", product_id=PANEL_STEAM_SENTINEL),
        _mapping(supplier="fzr", kind="voucher", product_id="roblox_global"),
        _mapping(supplier="nova", product_id="valorant_my"),
    ]

    cache = await price_refresh._fetch_fzr_offers_cache(mappings)

    assert sorted(fake.asked) == ["broken", "valorant_my"]
    assert set(cache) == {"valorant_my"}


async def test_g2b_games_are_fetched_once_each(monkeypatch: pytest.MonkeyPatch) -> None:
    from yupay.modules.fulfillment.suppliers.g2b import G2bFulfiller

    asked: list[str] = []

    class _Client:
        async def games_catalogue(self, code: str) -> list[dict[str, Any]]:
            asked.append(code)
            if code == "down":
                raise RuntimeError("timeout")
            return [{"name": "475", "amount": 4.1}]

    fulfiller = G2bFulfiller(client=_Client())  # type: ignore[arg-type]
    monkeypatch.setattr(G2bFulfiller, "available", property(lambda _self: True))
    monkeypatch.setattr(G2bFulfiller, "_client", lambda _self: _Client())
    monkeypatch.setattr(
        "yupay.modules.fulfillment.suppliers.REGISTRY", {"g2b": fulfiller}, raising=False
    )
    mappings = [
        _mapping(supplier="g2b", product_id="valorant_my"),
        _mapping(supplier="g2b", product_id="valorant_my"),
        _mapping(supplier="g2b", product_id="down"),
        _mapping(supplier="g2b", kind="voucher", product_id="107"),
    ]

    cache = await price_refresh._fetch_g2b_catalogue_cache(mappings)

    assert sorted(asked) == ["down", "valorant_my"]
    assert cache == {"valorant_my": [{"name": "475", "amount": 4.1}]}


async def test_each_vendor_reads_its_own_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """fzr and NOVA share category ids; a shared cache would price one as the other."""
    seen: dict[str, Any] = {}

    async def _fzr(_db: Any, _m: Any, *, offers_cache: Any) -> str:
        seen["fzr"] = offers_cache
        return "fzr"

    async def _g2b(_db: Any, _m: Any, *, catalogue_cache: Any) -> str:
        seen["g2b"] = catalogue_cache
        return "g2b"

    monkeypatch.setattr(cost_refresh, "_fzr_raw_price", _fzr)
    monkeypatch.setattr(cost_refresh, "_g2b_raw_price", _g2b)
    nova: dict[str, Any] = {"x": "nova"}
    fzr: dict[str, Any] = {"x": "fzr"}
    g2b: dict[str, list[dict[str, Any]]] = {"code": []}

    await cost_refresh._lookup_price(
        None,  # type: ignore[arg-type]
        _mapping(supplier="fzr", product_id="x"),
        nova_offers_cache=nova,
        fzr_offers_cache=fzr,
        g2b_catalogue_cache=g2b,
    )
    await cost_refresh._lookup_price(
        None,  # type: ignore[arg-type]
        _mapping(supplier="g2b", product_id="code"),
        nova_offers_cache=nova,
        fzr_offers_cache=fzr,
        g2b_catalogue_cache=g2b,
    )

    assert seen == {"fzr": fzr, "g2b": g2b}


# --- the bulk route switch shares one fetch per supplier game -------------------


async def test_refresh_routed_cost_hands_the_shared_caches_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bulk switch re-prices 100 rungs of one game with one catalogue, not 100."""
    seen: dict[str, Any] = {}

    async def _resolve(_db: Any, _sku_id: str) -> Any:
        return Mock(primary="supplier:g2b")

    sentinel = cost_refresh.CostRefreshOutcome(updated=False, reason="stub")

    async def _refresh(_db: Any, *, mapping: Any, **kw: Any) -> cost_refresh.CostRefreshOutcome:
        seen.update(kw)
        seen["mapping"] = mapping
        return sentinel

    mapping = _mapping(supplier="g2b", product_id="pubgm")

    class _Db:
        async def execute(self, _stmt: Any) -> Any:
            class _R:
                def scalars(self) -> Any:
                    return self

                def all(self) -> list[Any]:
                    return [mapping]

            return _R()

    monkeypatch.setattr("yupay.modules.sourcing.service.resolve_for_sku", _resolve)
    monkeypatch.setattr(cost_refresh, "is_routed_supplier", lambda _d, _s: True)
    monkeypatch.setattr(cost_refresh, "supports_price_collection", lambda _s: True)
    monkeypatch.setattr(cost_refresh, "refresh_sku_cost_for_mapping", _refresh)
    caches = cost_refresh.SupplierCaches(
        nova_offers={"n": {}}, fzr_offers={"f": {}}, g2b_catalogue={"pubgm": []}
    )

    out = await cost_refresh.refresh_routed_cost(
        _Db(),  # type: ignore[arg-type]
        sku_id="sku-1",
        caches=caches,
    )

    assert out is sentinel
    assert seen["mapping"] is mapping
    assert seen["g2b_catalogue_cache"] == {"pubgm": []}
    assert seen["fzr_offers_cache"] == {"f": {}}
    assert seen["nova_offers_cache"] == {"n": {}}


async def test_prefetch_with_no_skus_fetches_nothing() -> None:
    caches = await cost_refresh.prefetch_supplier_caches(None, sku_ids=[])  # type: ignore[arg-type]
    assert caches == cost_refresh.SupplierCaches()
