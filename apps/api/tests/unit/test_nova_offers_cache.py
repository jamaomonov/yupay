"""Which NOVA mappings warm the ``/topups/offers`` cache, and which do not.

``_fetch_nova_offers_cache`` exists purely as an optimisation — a cache miss
degrades to a live per-mapping call inside `_nova_raw_price` — so a wrong
entry in it never produces a wrong price. It can still produce pure waste: a
category from the wrong catalogue, warmed every hour, that nothing downstream
was ever going to read.

That is what shipped. The set-construction excluded only the Steam sentinel,
so every ``voucher`` mapping's category — a NOVA gift-card category, a
different catalogue reached by a different endpoint — was sent to
``/topups/offers`` and 404'd, on a tick that runs hourly, forever, once a SKU
was mapped. Found 2026-09-22 while mapping Standoff 2's 500 Gold to NOVA:
`roblox_global` had been doing this silently since the Roblox mappings landed
the day before. The two Fragment sentinels had the identical bug from before
either of these branches, unnoticed because nothing had looked.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest
from yupay.modules.integrations import price_refresh as mod
from yupay.modules.integrations.models import (
    NOVA_FRAGMENT_PREMIUM,
    NOVA_FRAGMENT_STARS,
    NOVA_STEAM_SENTINEL,
)

pytestmark = pytest.mark.asyncio


class _FakeClient:
    def __init__(self) -> None:
        self.asked: list[str] = []

    async def get_offers(self, category_id: str) -> dict[str, Any]:
        self.asked.append(category_id)
        return {"offers": []}


def _mapping(*, supplier: str, kind: str, product_id: str) -> Any:
    return Mock(supplier_slug=supplier, kind=kind, external_product_id=product_id)


@pytest.fixture
def _nova(monkeypatch: pytest.MonkeyPatch) -> _FakeClient:
    """Registers a NOVA fulfiller whose `_client()` is the fake above —
    `_fetch_nova_offers_cache` checks `isinstance(fulfiller, NovaFulfiller)`,
    so a bare stand-in will not do."""
    from yupay.modules.fulfillment.suppliers.nova import NovaFulfiller

    client = _FakeClient()
    fulfiller = NovaFulfiller(client=client)  # type: ignore[arg-type]
    monkeypatch.setattr(NovaFulfiller, "available", property(lambda _self: True))
    monkeypatch.setattr(
        "yupay.modules.fulfillment.suppliers.REGISTRY", {"nova": fulfiller}, raising=False
    )
    return client


async def test_a_game_mapping_warms_the_cache(_nova: _FakeClient) -> None:
    mappings = [_mapping(supplier="nova", kind="game", product_id="pubg_mobile_auto")]

    cache = await mod._fetch_nova_offers_cache(mappings)

    assert _nova.asked == ["pubg_mobile_auto"]
    assert "pubg_mobile_auto" in cache


async def test_a_voucher_mapping_is_never_asked_of_topups(_nova: _FakeClient) -> None:
    """The regression. A gift-card category lives in the other catalogue —
    asking `/topups/offers` about it is a guaranteed 404, and nothing reads
    this cache for a voucher mapping anyway."""
    mappings = [_mapping(supplier="nova", kind="voucher", product_id="roblox_global")]

    cache = await mod._fetch_nova_offers_cache(mappings)

    assert _nova.asked == []
    assert cache == {}


@pytest.mark.parametrize(
    "sentinel", [NOVA_STEAM_SENTINEL, NOVA_FRAGMENT_STARS, NOVA_FRAGMENT_PREMIUM]
)
async def test_a_sentinel_category_is_never_asked_of_topups(
    _nova: _FakeClient, sentinel: str
) -> None:
    """None of the three has a `/topups/offers` entry: Steam has no
    catalogue, Fragment is a separate API family entirely."""
    mappings = [_mapping(supplier="nova", kind="game", product_id=sentinel)]

    await mod._fetch_nova_offers_cache(mappings)

    assert _nova.asked == []


async def test_a_g2b_mapping_is_ignored(_nova: _FakeClient) -> None:
    mappings = [_mapping(supplier="g2b", kind="game", product_id="107")]

    cache = await mod._fetch_nova_offers_cache(mappings)

    assert _nova.asked == []
    assert cache == {}


async def test_two_mappings_in_one_category_cost_one_call(_nova: _FakeClient) -> None:
    mappings = [
        _mapping(supplier="nova", kind="game", product_id="pubg_mobile_auto"),
        _mapping(supplier="nova", kind="game", product_id="pubg_mobile_auto"),
    ]

    await mod._fetch_nova_offers_cache(mappings)

    assert _nova.asked == ["pubg_mobile_auto"]


async def test_no_registered_nova_adapter_returns_an_empty_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("yupay.modules.fulfillment.suppliers.REGISTRY", {}, raising=False)
    mappings = [_mapping(supplier="nova", kind="game", product_id="pubg_mobile_auto")]

    cache = await mod._fetch_nova_offers_cache(mappings)

    assert cache == {}
