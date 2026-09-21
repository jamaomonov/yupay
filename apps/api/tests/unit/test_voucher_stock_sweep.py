"""The loop inside ``refresh_voucher_stock``.

Three suppliers report stock at different levels — G2B one count per product,
G-Engine one per denomination, NOVA one per card inside a gift-card category —
so the loop dispatches per mapping and each branch is covered beside the G2B one.

``normalise_stock`` is pinned next door; this covers what wraps it — that a
withdrawn product becomes zero rather than staying unknown, that one failing id
does not stop the queue or get mistaken for empty, that a SKU with two sources
takes the count of the one its orders actually reach, and that the alert fires
on the transition into out-of-stock rather than on every tick.

A fake session rather than the integration harness: the sweep deliberately opens
its own sessions per SKU (so one failure cannot roll back the rest), which puts
its writes outside whatever transaction a test fixture is holding. Faking the
factory tests the logic that actually has branches in it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from yupay.modules.catalog.models import Sku
from yupay.modules.integrations import stock_refresh as mod

pytestmark = pytest.mark.asyncio


class _Result:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def all(self) -> Any:
        return self._payload

    def scalar_one_or_none(self) -> Any:
        return self._payload


class _Session:
    """Yields the mapping rows on the first execute, then a SKU per lookup."""

    def __init__(self, state: dict[str, Any]) -> None:
        self._state = state
        self.commits = 0

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, stmt: Any) -> _Result:
        if not self._state["targets_read"]:
            self._state["targets_read"] = True
            return _Result(self._state["targets"])
        # Per-SKU lookup: hand back the next SKU in the queue.
        return _Result(self._state["skus"].pop(0) if self._state["skus"] else None)

    async def commit(self) -> None:
        self.commits += 1
        self._state["commits"] += 1


def _sku(code: str, stock: int | None) -> Sku:
    return Sku(
        id=f"id-{code}",
        product_id="p1",
        sku_code=code,
        price_usd=Decimal("1"),
        supplier_stock=stock,
    )


class _Client:
    def __init__(self, answers: dict[str, Any], boom: set[str] | None = None) -> None:
        self.answers = answers
        self.boom = boom or set()
        self.asked: list[str] = []

    async def fetch_product(self, product_id: str) -> dict[str, Any] | None:
        self.asked.append(product_id)
        if product_id in self.boom:
            raise RuntimeError("supplier down")
        return self.answers.get(product_id)


@pytest.fixture
def _harness(monkeypatch: pytest.MonkeyPatch) -> Any:
    alerts: list[str] = []

    async def _capture(text: str, *, kind: str) -> bool:
        alerts.append(kind)
        return True

    # Patched by path: `notifications` is a module alias inside stock_refresh,
    # which mypy does not treat as an attribute of it.
    monkeypatch.setattr("yupay.modules.notifications.api.send_admin_alert", _capture, raising=False)

    def _install(targets: list[tuple[str, ...]], skus: list[Sku]) -> dict[str, Any]:
        state: dict[str, Any] = {
            "targets": targets,
            "skus": skus,
            "targets_read": False,
            "commits": 0,
        }
        monkeypatch.setattr(mod, "get_session_factory", lambda: lambda: _Session(state))
        return state

    return _install, alerts


async def test_sweep_writes_counts_and_zeroes_withdrawn_products(_harness: Any) -> None:
    install, alerts = _harness
    full, gone = _sku("roblox-800", 420), _sku("roblox-2000", 5)
    install(
        [("id-roblox-800", "g2b", "107", None), ("id-roblox-2000", "g2b", "108", None)],
        [full, gone],
    )
    client = _Client({"107": {"stock": 12}, "108": None})

    report = await mod.refresh_voucher_stock(client=client)

    assert client.asked == ["107", "108"]
    assert full.supplier_stock == 12
    assert full.supplier_stock_at is not None
    # A 404 means withdrawn upstream — zero, not "we learned nothing".
    assert gone.supplier_stock == 0
    assert gone.in_stock is False
    assert report.checked == 2
    assert report.updated == 2
    assert report.went_out_of_stock == 1
    assert alerts == ["voucher_out_of_stock"]


async def test_sweep_does_not_alert_for_an_already_empty_sku(_harness: Any) -> None:
    install, alerts = _harness
    empty = _sku("roblox-2000", 0)
    install([("id-roblox-2000", "g2b", "108", None)], [empty])

    report = await mod.refresh_voucher_stock(client=_Client({"108": {"stock": 0}}))

    # Still empty, but it did not cross over on this run: a channel that
    # repeats itself hourly stops being read.
    assert report.went_out_of_stock == 0
    assert alerts == []


async def test_sweep_survives_one_failing_product(_harness: Any) -> None:
    install, _alerts = _harness
    ok = _sku("roblox-2000", 5)
    install([("id-roblox-800", "g2b", "107", None), ("id-roblox-2000", "g2b", "108", None)], [ok])
    client = _Client({"108": {"stock": 7}}, boom={"107"})

    report = await mod.refresh_voucher_stock(client=client)

    assert report.errors == 1
    # The queue continued, and the failure was not written as a zero.
    assert ok.supplier_stock == 7
    assert report.checked == 2


async def test_sweep_treats_minus_one_as_untracked(_harness: Any) -> None:
    install, alerts = _harness
    sku = _sku("roblox-800", 5)
    install([("id-roblox-800", "g2b", "107", None)], [sku])

    report = await mod.refresh_voucher_stock(client=_Client({"107": {"stock": -1}}))

    # Sellable, not empty — the expensive mistake would be the other way.
    assert sku.supplier_stock is None
    assert sku.in_stock is True
    assert report.went_out_of_stock == 0
    assert alerts == []


async def test_sweep_without_a_registered_adapter_is_a_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No G2B key configured — the job must be quiet, not crash the scheduler."""
    monkeypatch.setattr("yupay.modules.fulfillment.suppliers.REGISTRY", {}, raising=False)
    report = await mod.refresh_voucher_stock()
    assert report.checked == 0


# ---------- G-Engine: stock lives on the denomination ----------


class _GEngineClient:
    """`GET /shop/denominations/{product}` — every denomination in one answer."""

    def __init__(self, answers: dict[int, list[dict[str, Any]]]) -> None:
        self.answers = answers
        self.asked: list[int] = []

    async def list_shop_denominations(self, product_id: int) -> list[dict[str, Any]]:
        self.asked.append(product_id)
        return self.answers.get(product_id, [])


async def test_gengine_stock_is_read_per_denomination(_harness: Any) -> None:
    install, alerts = _harness
    gold100, gold500 = _sku("so2-gold-100", 15), _sku("so2-gold-500", 5)
    install(
        [
            ("id-so2-gold-100", "gengine", "140", "788"),
            ("id-so2-gold-500", "gengine", "140", "789"),
        ],
        [gold100, gold500],
    )
    client = _GEngineClient(
        {140: [{"id": 788, "stock": 12}, {"id": 789, "stock": 0}, {"id": 790, "stock": 5}]}
    )

    report = await mod.refresh_voucher_stock(client=None, gengine_client=client)

    # One call, not one per SKU: four Standoff 2 lines sit behind one product.
    assert client.asked == [140]
    assert gold100.supplier_stock == 12
    assert gold500.supplier_stock == 0
    assert gold500.in_stock is False
    assert report.went_out_of_stock == 1
    assert alerts == ["voucher_out_of_stock"]


async def test_a_denomination_that_vanished_reads_as_empty(_harness: Any) -> None:
    """Delisted upstream cannot be delivered. Leaving it NULL would keep it on
    the shelf — the same call the G2B branch makes for a withdrawn product."""
    install, _alerts = _harness
    sku = _sku("so2-gold-3000", 5)
    install([("id-so2-gold-3000", "gengine", "140", "791")], [sku])
    client = _GEngineClient({140: [{"id": 788, "stock": 12}]})

    await mod.refresh_voucher_stock(client=None, gengine_client=client)

    assert sku.supplier_stock == 0
    assert sku.in_stock is False


async def test_the_two_suppliers_are_swept_in_one_run(_harness: Any) -> None:
    install, _alerts = _harness
    robux, gold = _sku("roblox-800", 5), _sku("so2-gold-100", 5)
    install(
        [("id-roblox-800", "g2b", "107", None), ("id-so2-gold-100", "gengine", "140", "788")],
        [robux, gold],
    )

    report = await mod.refresh_voucher_stock(
        client=_Client({"107": {"stock": 3}}),
        gengine_client=_GEngineClient({140: [{"id": 788, "stock": 9}]}),
    )

    assert (robux.supplier_stock, gold.supplier_stock) == (3, 9)
    assert report.checked == 2
    assert report.errors == 0


# ---------- NOVA: stock lives on the card, inside a category ----------


class _NovaClient:
    """`GET /api/v2/giftcards/cards?category_id=…` — a whole category at once."""

    def __init__(self, answers: dict[str, list[dict[str, Any]]]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    async def list_giftcard_cards(self, category_id: str) -> list[dict[str, Any]]:
        self.asked.append(category_id)
        return self.answers.get(category_id, [])


async def test_nova_stock_is_read_per_card(_harness: Any) -> None:
    install, alerts = _harness
    r50, r2500 = _sku("roblox-gc-50", 4), _sku("roblox-gc-2500", 9)
    install(
        [
            ("id-roblox-gc-50", "nova", "roblox_global", "c-50"),
            ("id-roblox-gc-2500", "nova", "roblox_global", "c-2500"),
        ],
        [r50, r2500],
    )
    client = _NovaClient(
        {
            "roblox_global": [
                {"card_id": "c-50", "stock": 6},
                {"card_id": "c-2500", "stock": 0},
                {"card_id": "c-100", "stock": 3},
            ]
        }
    )

    report = await mod.refresh_voucher_stock(client=None, nova_client=client)

    # One call for nine Roblox denominations, not nine.
    assert client.asked == ["roblox_global"]
    assert r50.supplier_stock == 6
    assert r2500.supplier_stock == 0
    assert r2500.in_stock is False
    assert report.went_out_of_stock == 1
    assert alerts == ["voucher_out_of_stock"]


async def test_a_nova_card_that_vanished_reads_as_empty(_harness: Any) -> None:
    """The whole point of sweeping NOVA at all.

    Before 2026-09-21 a NOVA-only voucher SKU was never asked about, so it
    kept ``supplier_stock = NULL`` — which the catalogue reads as untracked
    and therefore always sellable. A sold-out card stayed clickable and the
    order died at the supplier.
    """
    install, _alerts = _harness
    sku = _sku("roblox-gc-3000", 2)
    install([("id-roblox-gc-3000", "nova", "roblox_global", "c-3000")], [sku])
    client = _NovaClient({"roblox_global": [{"card_id": "c-50", "stock": 6}]})

    await mod.refresh_voucher_stock(client=None, nova_client=client)

    assert sku.supplier_stock == 0
    assert sku.in_stock is False


async def test_the_nova_category_is_fetched_once_per_run(_harness: Any) -> None:
    install, _alerts = _harness
    a, b, c = _sku("gc-a", 1), _sku("gc-b", 1), _sku("gc-c", 1)
    install(
        [
            ("id-gc-a", "nova", "roblox_global", "c-50"),
            ("id-gc-b", "nova", "roblox_global", "c-100"),
            ("id-gc-c", "nova", "roblox_global", "c-200"),
        ],
        [a, b, c],
    )
    client = _NovaClient(
        {
            "roblox_global": [
                {"card_id": "c-50", "stock": 6},
                {"card_id": "c-100", "stock": 7},
                {"card_id": "c-200", "stock": 8},
            ]
        }
    )

    await mod.refresh_voucher_stock(client=None, nova_client=client)

    assert client.asked == ["roblox_global"]
    assert (a.supplier_stock, b.supplier_stock, c.supplier_stock) == (6, 7, 8)


async def test_all_three_suppliers_are_swept_in_one_run(_harness: Any) -> None:
    install, _alerts = _harness
    robux, gold, card = _sku("roblox-800", 5), _sku("so2-gold-100", 5), _sku("gc-50", 5)
    install(
        [
            ("id-roblox-800", "g2b", "107", None),
            ("id-so2-gold-100", "gengine", "140", "788"),
            ("id-gc-50", "nova", "roblox_global", "c-50"),
        ],
        [robux, gold, card],
    )

    report = await mod.refresh_voucher_stock(
        client=_Client({"107": {"stock": 3}}),
        gengine_client=_GEngineClient({140: [{"id": 788, "stock": 9}]}),
        nova_client=_NovaClient({"roblox_global": [{"card_id": "c-50", "stock": 4}]}),
    )

    assert (robux.supplier_stock, gold.supplier_stock, card.supplier_stock) == (3, 9, 4)
    assert report.checked == 3
    assert report.errors == 0


@dataclass(frozen=True)
class _Decision:
    """The two fields of `sourcing.Decision` this sweep reads."""

    primary: str
    fallback: str | None


# ---------- Two suppliers on one SKU: whose count is it? ----------


def _route(monkeypatch: pytest.MonkeyPatch, decision: Any) -> None:
    """Pin what `sourcing.resolve_for_sku` answers.

    Patched rather than driven through the fake session: the fake hands out
    the next SKU on every `execute`, and a real sourcing query would eat one.
    """

    async def _resolve(db: Any, sku_id: str) -> Any:
        if isinstance(decision, Exception):
            raise decision
        return decision

    monkeypatch.setattr("yupay.modules.sourcing.service.resolve_for_sku", _resolve, raising=False)


async def test_a_pinned_sku_takes_its_own_suppliers_count(
    _harness: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Roblox 10000, the case that forced this: zero at G2B, twenty-nine at
    NOVA, and a `force_supplier` rule pointing at G2B. Writing whichever
    count the query returned last would put a line we cannot deliver back
    on the shelf."""
    install, alerts = _harness
    sku = _sku("roblox-10000", 24)
    install(
        [
            ("id-roblox-10000", "g2b", "111", None),
            ("id-roblox-10000", "nova", "roblox_global", "10000_robux"),
        ],
        [sku],
    )
    _route(monkeypatch, _Decision(primary="supplier:g2b", fallback=None))
    nova = _NovaClient({"roblox_global": [{"card_id": "10000_robux", "stock": 29}]})

    report = await mod.refresh_voucher_stock(
        client=_Client({"111": {"stock": 0}}), nova_client=nova
    )

    assert sku.supplier_stock == 0
    assert sku.in_stock is False
    # NOVA was never asked: it is not where this order would go.
    assert nova.asked == []
    # Two mappings, one SKU, one check.
    assert report.checked == 1
    assert alerts == ["voucher_out_of_stock"]


async def test_an_unrouted_sku_is_sellable_while_any_source_has_it(
    _harness: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No rule pins it, so either supplier could take the order. Hiding a
    line one of them can still deliver is the more expensive mistake."""
    install, alerts = _harness
    sku = _sku("roblox-4500", 24)
    install(
        [
            ("id-roblox-4500", "g2b", "110", None),
            ("id-roblox-4500", "nova", "roblox_global", "4500_robux"),
        ],
        [sku],
    )
    _route(monkeypatch, _Decision(primary="inventory", fallback=None))

    await mod.refresh_voucher_stock(
        client=_Client({"110": {"stock": 0}}),
        nova_client=_NovaClient({"roblox_global": [{"card_id": "4500_robux", "stock": 8}]}),
    )

    assert sku.supplier_stock == 8
    assert sku.in_stock is True
    assert alerts == []


async def test_an_untracked_source_keeps_the_sku_untracked(
    _harness: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`-1` from G2B means "not tracked", not "none left" — and the
    catalogue reads untracked as sellable. One source saying so is enough."""
    install, _alerts = _harness
    sku = _sku("roblox-800", 5)
    install(
        [
            ("id-roblox-800", "g2b", "107", None),
            ("id-roblox-800", "nova", "roblox_global", "800_robux"),
        ],
        [sku],
    )
    _route(monkeypatch, _Decision(primary="inventory", fallback=None))

    await mod.refresh_voucher_stock(
        client=_Client({"107": {"stock": -1}}),
        nova_client=_NovaClient({"roblox_global": [{"card_id": "800_robux", "stock": 4}]}),
    )

    assert sku.supplier_stock is None
    assert sku.in_stock is True


async def test_a_route_that_cannot_be_resolved_falls_back_to_asking_both(
    _harness: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken rule must not take the sweep down with it — the SKU is
    still swept, just without the narrowing."""
    install, _alerts = _harness
    sku = _sku("roblox-2000", 5)
    install(
        [
            ("id-roblox-2000", "g2b", "109", None),
            ("id-roblox-2000", "nova", "roblox_global", "2000_robux"),
        ],
        [sku],
    )
    _route(monkeypatch, RuntimeError("rule is force_supplier with no slug"))

    report = await mod.refresh_voucher_stock(
        client=_Client({"109": {"stock": 3}}),
        nova_client=_NovaClient({"roblox_global": [{"card_id": "2000_robux", "stock": 9}]}),
    )

    assert sku.supplier_stock == 9
    assert report.errors == 0
