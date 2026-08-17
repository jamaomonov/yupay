"""The loop inside ``refresh_voucher_stock``.

Two suppliers report stock at different levels — G2B one count per product,
G-Engine one per denomination — so the loop dispatches per mapping and the
G-Engine branch is covered alongside the G2B one.

``normalise_stock`` is pinned next door; this covers what wraps it — that a
withdrawn product becomes zero rather than staying unknown, that one failing id
does not stop the queue or get mistaken for empty, and that the alert fires on
the transition into out-of-stock rather than on every tick.

A fake session rather than the integration harness: the sweep deliberately opens
its own sessions per SKU (so one failure cannot roll back the rest), which puts
its writes outside whatever transaction a test fixture is holding. Faking the
factory tests the logic that actually has branches in it.
"""

from __future__ import annotations

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
