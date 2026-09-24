"""The gift-card halves of the NOVA and G-Engine catalogue syncs.

Their happy paths are pinned end-to-end next door
(``tests/integration/test_integrations_catalog_sync_{nova,gengine}.py``,
through the real route and a real database). What is left here is everything
those cannot reach cheaply: the refusals.

That split matters more than usual for these two modules. Both promise their
caller — ``sync_{nova,gengine}_catalog``, which in turn promises the route and
the scheduler — that they **never raise**, whatever a supplier answers. A
promise like that is only worth the tests that try to break it, and each way
of breaking it is one ``except`` clause an integration test would need a
purpose-built respx failure to reach.

Fakes rather than a database: these functions' own logic is "what did the
supplier say, and what do I do about it", and the writes are one call into
``service`` that the integration tests already exercise for real.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from yupay.modules.fulfillment.suppliers.nova_client import NovaError, NovaUnavailableError
from yupay.modules.integrations import catalog_sync_gengine_vouchers as shop
from yupay.modules.integrations import catalog_sync_panel_vouchers as gift

pytestmark = pytest.mark.asyncio


#: These functions never touch the session — ``service`` is faked out below —
#: so the argument exists only to satisfy the signature. Widened once here
#: rather than cast at each of the twenty call sites; ``mypy --strict`` checks
#: test files too, and a per-call ``cast`` would bury the assertions.
_NO_DB: Any = None


def _as_client(fake: object) -> Any:
    """Hand a fake to a function typed for the real supplier client.

    The adapters these modules take are used for two or three methods and are
    duck-typed on purpose — what is under test is "what did the supplier say,
    and what do I do about it", not the HTTP client. One widening point keeps
    that from becoming an argument at every call.
    """
    return fake


class _Writes:
    """Stands in for ``integrations.service``, recording what was written."""

    def __init__(self, *, mapped: list[str] | None = None, boom: bool = False) -> None:
        self.rows: list[tuple[str, str, str]] = []
        self.pruned: list[tuple[str, set[str]]] = []
        self._mapped = mapped or []
        self._boom = boom

    async def upsert_catalog_entry(self, db: Any, **kw: Any) -> None:
        # Mirrors the real signature's strictness where it matters: a junk
        # price must blow up here, the way `Decimal(str(...))` would.
        if not isinstance(kw.get("price_usdt"), (Decimal, type(None))):
            raise TypeError("price must be a Decimal")
        # A flat row passes no parent at all, exactly as the real signature
        # allows — reading it as required here would turn "wrote a voucher"
        # into "the sweep failed", which is how this fake first lied.
        self.rows.append(
            (str(kw["kind"]), str(kw["external_id"]), str(kw.get("parent_external_id") or ""))
        )

    async def prune_catalog_denoms(
        self, db: Any, *, supplier_slug: str, parent_external_id: str, keep: set[str]
    ) -> int:
        self.pruned.append((parent_external_id, keep))
        return 0

    async def mapped_external_product_ids(self, db: Any, *, supplier_slug: str, kind: str) -> Any:
        if self._boom:
            raise RuntimeError("the database went away")
        return self._mapped


@pytest.fixture
def _svc(monkeypatch: pytest.MonkeyPatch) -> Any:
    def _install(module: Any, writes: _Writes) -> _Writes:
        monkeypatch.setattr(module, "svc", writes, raising=True)
        return writes

    return _install


# ---------- NOVA gift cards ----------


class _NovaClient:
    #: The real client carries its slug as a class attribute, and the sync
    #: reads it to decide which supplier's rows it is writing. A fake without
    #: one would only fail at the first log line, which is a long way from the
    #: mistake.
    slug = "nova"

    def __init__(self, cards: Any = None, categories: Any = None) -> None:
        self._cards = cards if cards is not None else []
        self._categories = categories if categories is not None else []
        self.asked: list[str] = []

    async def list_giftcards(self) -> list[dict[str, Any]]:
        if isinstance(self._categories, Exception):
            raise self._categories
        return list(self._categories)

    async def list_giftcard_cards(self, category_id: str) -> list[dict[str, Any]]:
        self.asked.append(category_id)
        if isinstance(self._cards, Exception):
            raise self._cards
        return list(self._cards)


async def test_a_category_with_no_id_is_skipped_not_written(_svc: Any) -> None:
    writes = _svc(gift, _Writes())
    client = _NovaClient(categories=[{"name": "nameless"}, {"category_id": "roblox_global"}])

    written, error = await gift.sync_giftcard_categories(_NO_DB, _as_client(client))

    assert (written, error) == (1, None)
    assert [row[1] for row in writes.rows] == ["roblox_global"]


async def test_a_failing_category_sweep_reports_rather_than_raises(_svc: Any) -> None:
    _svc(gift, _Writes())
    client = _NovaClient(categories=RuntimeError("upstream is down"))

    written, error = await gift.sync_giftcard_categories(_NO_DB, _as_client(client))

    assert written == 0
    assert "gift-card sync failed" in (error or "")


async def test_a_404_on_a_category_is_missing_not_an_error(_svc: Any) -> None:
    """The one thing this module discriminates: gone, versus refused.

    Guessing "the category is gone" from a rate limit would tell an operator
    their mapping is dead when it is not.
    """
    _svc(gift, _Writes(mapped=["roblox_global"]))
    client = _NovaClient(cards=NovaError("not found", status=404))

    written, missing, error = await gift.refresh_mapped_giftcards(_NO_DB, _as_client(client))

    assert (written, missing, error) == (0, 1, None)


@pytest.mark.parametrize(
    "boom",
    [NovaError("slow down", status=429), NovaUnavailableError("connection reset")],
    ids=["refused", "unreachable"],
)
async def test_an_ambiguous_refusal_is_an_error_not_a_delisting(_svc: Any, boom: Exception) -> None:
    _svc(gift, _Writes(mapped=["roblox_global"]))

    written, missing, error = await gift.refresh_mapped_giftcards(
        _NO_DB, _as_client(_NovaClient(cards=boom))
    )

    assert (written, missing) == (0, 0)
    assert "failed to refresh" in (error or "")


async def test_a_malformed_card_is_reported_not_raised(_svc: Any) -> None:
    _svc(gift, _Writes(mapped=["roblox_global"]))
    client = _NovaClient(cards=[{"card_id": "50_robux", "price_usd": "not a number"}])

    written, missing, error = await gift.refresh_mapped_giftcards(_NO_DB, _as_client(client))

    assert missing == 0
    assert "failed to refresh" in (error or "")


async def test_a_card_with_no_id_is_skipped_and_never_pruned_against(_svc: Any) -> None:
    writes = _svc(gift, _Writes(mapped=["roblox_global"]))
    client = _NovaClient(cards=[{"name": "nameless"}, {"card_id": "50_robux", "price_usd": "1.5"}])

    written, _missing, error = await gift.refresh_mapped_giftcards(_NO_DB, _as_client(client))

    assert (written, error) == (1, None)
    # The prune keeps exactly what was seen — an id-less row must not make
    # the set look complete.
    assert writes.pruned == [("roblox_global", {"50_robux"})]


async def test_the_mapped_category_fetch_is_capped(_svc: Any, monkeypatch: Any) -> None:
    """A data mistake must not turn one tick into hundreds of calls."""
    monkeypatch.setattr(gift, "_MAPPED_FETCH_CAP", 2)
    _svc(gift, _Writes(mapped=["a", "b", "c", "d"]))
    client = _NovaClient(cards=[])

    await gift.refresh_mapped_giftcards(_NO_DB, _as_client(client))

    assert client.asked == ["a", "b"]


async def test_the_on_demand_pull_names_a_category_that_does_not_exist(_svc: Any) -> None:
    _svc(gift, _Writes())
    client = _NovaClient(cards=NovaError("not found", status=404))

    written, error = await gift.sync_one_category_cards(
        _NO_DB, _as_client(client), category_id="nope"
    )

    assert written == 0
    assert "nope" in (error or "")


async def test_the_on_demand_pull_returns_what_it_wrote(_svc: Any) -> None:
    _svc(gift, _Writes())
    client = _NovaClient(cards=[{"card_id": "50_robux", "price_usd": "0.87"}])

    written, error = await gift.sync_one_category_cards(
        _NO_DB, _as_client(client), category_id="roblox_global"
    )

    assert (written, error) == (1, None)


# ---------- G-Engine shop products ----------


class _ShopClient:
    def __init__(self, pages: list[list[dict[str, Any]]] | None = None, denoms: Any = None) -> None:
        self._pages = pages or [[]]
        self._denoms = denoms if denoms is not None else []
        self.asked: list[int] = []

    async def list_shop_products(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
        index = offset // max(limit, 1)
        return self._pages[index] if index < len(self._pages) else []

    async def list_shop_denominations(self, product_id: int) -> list[dict[str, Any]]:
        self.asked.append(product_id)
        if isinstance(self._denoms, Exception):
            raise self._denoms
        return list(self._denoms)


def _page(n: int) -> list[dict[str, Any]]:
    return [{"id": i, "name": f"p{i}"} for i in range(n)]


async def test_a_full_first_page_is_followed_by_a_second(_svc: Any) -> None:
    from yupay.modules.fulfillment.suppliers.gengine_client import MAX_PAGE

    client = _ShopClient(pages=[_page(MAX_PAGE), _page(3)])

    items, truncated = await shop.list_all_shop_products(_as_client(client))

    assert (len(items), truncated) == (MAX_PAGE + 3, False)


async def test_a_full_second_page_says_it_was_truncated(_svc: Any) -> None:
    """Two pages is the budget, not the catalogue's size. Say when it ran out
    rather than reporting a short list as the whole thing."""
    from yupay.modules.fulfillment.suppliers.gengine_client import MAX_PAGE

    client = _ShopClient(pages=[_page(MAX_PAGE), _page(MAX_PAGE)])

    _items, truncated = await shop.list_all_shop_products(_as_client(client))

    assert truncated is True


async def test_a_shop_product_with_no_id_is_skipped(_svc: Any) -> None:
    writes = _svc(shop, _Writes())
    client = _ShopClient(pages=[[{"name": "nameless"}, {"id": 9, "name": "Roblox"}]])

    products, _denoms, error = await shop.sync_shop_catalog(_NO_DB, _as_client(client))

    assert (products, error) == (1, None)
    assert [row[1] for row in writes.rows] == ["9"]


async def test_a_failing_shop_sweep_still_refreshes_the_mapped_ladders(_svc: Any) -> None:
    writes = _svc(shop, _Writes(mapped=["9"]))

    class _Broken(_ShopClient):
        async def list_shop_products(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
            raise RuntimeError("upstream is down")

    client = _Broken(denoms=[{"id": 727, "name": "2000 Robux", "price": 22.09}])

    products, denoms, error = await shop.sync_shop_catalog(_NO_DB, _as_client(client))

    assert (products, denoms) == (0, 1)
    assert "shop sync failed" in (error or "")
    assert writes.rows == [("voucher_denom", "727", "9")]


async def test_a_denomination_call_that_fails_names_its_product(_svc: Any) -> None:
    _svc(shop, _Writes(mapped=["9"]))
    client = _ShopClient(denoms=RuntimeError("500 from upstream"))

    written, error = await shop.refresh_mapped_shop_denoms(_NO_DB, _as_client(client))

    assert written == 0
    assert (error or "").startswith("9:")


async def test_a_malformed_denomination_is_reported_not_raised(_svc: Any) -> None:
    _svc(shop, _Writes(mapped=["9"]))
    client = _ShopClient(denoms=[{"id": 727, "price": "not a number"}])

    _written, error = await shop.refresh_mapped_shop_denoms(_NO_DB, _as_client(client))

    assert "malformed denomination" in (error or "")


async def test_a_denomination_with_no_id_is_skipped(_svc: Any) -> None:
    writes = _svc(shop, _Writes(mapped=["9"]))
    client = _ShopClient(denoms=[{"name": "nameless"}, {"id": 727, "price": 22.09}])

    written, error = await shop.refresh_mapped_shop_denoms(_NO_DB, _as_client(client))

    assert (written, error) == (1, None)
    assert writes.pruned == [("9", {"727"})]


async def test_a_non_numeric_product_id_is_a_mapping_typo_not_a_crash(_svc: Any) -> None:
    """``list_shop_denominations`` takes an int. A typo'd mapping must be
    named and skipped, not allowed to raise through the sweep."""
    _svc(shop, _Writes(mapped=["roblox_global"]))
    client = _ShopClient()

    written, error = await shop.refresh_mapped_shop_denoms(_NO_DB, _as_client(client))

    assert written == 0
    assert "not a numeric shop product id" in (error or "")
    assert client.asked == []


async def test_a_failing_mapped_lookup_is_reported(_svc: Any) -> None:
    _svc(shop, _Writes(boom=True))

    written, error = await shop.refresh_mapped_shop_denoms(_NO_DB, _as_client(_ShopClient()))

    assert written == 0
    assert "mapped shop lookup failed" in (error or "")


async def test_the_mapped_product_fetch_is_capped(_svc: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(shop, "_MAPPED_FETCH_CAP", 2)
    _svc(shop, _Writes(mapped=["1", "2", "3", "4"]))
    client = _ShopClient()

    await shop.refresh_mapped_shop_denoms(_NO_DB, _as_client(client))

    assert client.asked == [1, 2]


async def test_the_on_demand_shop_pull_refuses_a_non_numeric_id(_svc: Any) -> None:
    _svc(shop, _Writes())
    client = _ShopClient()

    written, error = await shop.sync_one_shop_product_denoms(
        _NO_DB, _as_client(client), product_id="roblox_global"
    )

    assert written == 0
    assert "not a numeric" in (error or "")
    assert client.asked == []


async def test_the_on_demand_shop_pull_returns_what_it_wrote(_svc: Any) -> None:
    _svc(shop, _Writes())
    client = _ShopClient(denoms=[{"id": 727, "price": 22.09}])

    written, error = await shop.sync_one_shop_product_denoms(
        _NO_DB, _as_client(client), product_id="9"
    )

    assert (written, error) == (1, None)


# ---------- the dispatcher, and "no key configured" ----------


async def test_an_unknown_supplier_has_no_voucher_syncer() -> None:
    """The route layer refuses this with a ``Literal`` path type before it
    gets here, so reaching it means something bypassed the route — a 404 is
    the honest answer, not a KeyError."""
    from yupay.core.errors import NotFoundError
    from yupay.modules.integrations import catalog_sync

    with pytest.raises(NotFoundError):
        await catalog_sync.run_voucher_denomination_sync(
            _NO_DB, supplier_slug="g2b", product_id="1234"
        )


@pytest.mark.parametrize(
    ("module_name", "attr"),
    [
        ("catalog_sync_panel", "client_or_none"),
        ("catalog_sync_gengine", "_gengine_client_or_none"),
    ],
    ids=["panel", "gengine"],
)
async def test_an_unconfigured_supplier_reports_rather_than_syncs(
    monkeypatch: pytest.MonkeyPatch, module_name: str, attr: str
) -> None:
    """No API key is a configuration fact, not an outage. The scheduler must
    get a sentence back and keep going."""
    import importlib

    module = importlib.import_module(f"yupay.modules.integrations.{module_name}")
    if module_name == "catalog_sync_panel":
        monkeypatch.setattr(module, attr, lambda _slug: None)
        written, error = await module.sync_panel_voucher_denominations(
            _NO_DB, slug="nova", product_id="9"
        )
    else:
        monkeypatch.setattr(module, attr, lambda: None)
        written, error = await module.sync_gengine_voucher_denominations(_NO_DB, product_id="9")

    assert written == 0
    assert "not configured" in (error or "")


@pytest.mark.parametrize(
    "broken",
    ["sync_giftcard_categories", "refresh_mapped_giftcards"],
    ids=["category sweep", "mapped cards"],
)
async def test_the_whole_nova_sync_survives_a_gift_card_half_that_raises(
    monkeypatch: pytest.MonkeyPatch, broken: str
) -> None:
    """The backstop, tested rather than assumed.

    Both gift-card functions promise never to raise, and
    ``sync_panel_catalog`` catches them anyway — the route and the hourly
    scheduler depend on a report coming back, and a promise kept everywhere
    today is not a promise kept after the next edit. This pins the outer
    catch by breaking the inner promise on purpose.
    """
    from yupay.modules.integrations import catalog_sync_panel as panel

    async def _raise(*_args: Any, **_kw: Any) -> Any:
        raise RuntimeError("the inner promise broke")

    fake_nova = _NovaClient(categories=[])
    monkeypatch.setattr(panel, "client_or_none", lambda _slug: fake_nova)

    async def _no_games(_db: Any, _client: Any) -> tuple[int, int, str | None]:
        return 0, 0, None

    monkeypatch.setattr(panel, "_refresh_mapped_game_denoms", _no_games)
    monkeypatch.setattr(f"yupay.modules.integrations.catalog_sync_panel_vouchers.{broken}", _raise)

    report = await panel.sync_panel_catalog(_NO_DB, slug="nova")

    assert "gift-card" in (report.error or "")


async def test_the_whole_gengine_sync_survives_a_shop_half_that_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yupay.modules.integrations import catalog_sync_gengine as gengine

    async def _raise(*_args: Any, **_kw: Any) -> Any:
        raise RuntimeError("the inner promise broke")

    client = _ShopClient()
    monkeypatch.setattr(gengine, "_gengine_client_or_none", lambda: client)
    monkeypatch.setattr(gengine, "svc", _Writes(mapped=[]))
    monkeypatch.setattr(
        "yupay.modules.integrations.catalog_sync_gengine_vouchers.sync_shop_catalog", _raise
    )

    report = await gengine.sync_gengine_catalog(_NO_DB)

    assert "shop sync failed" in (report.error or "")
