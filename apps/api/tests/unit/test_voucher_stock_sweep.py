"""The loop inside ``refresh_voucher_stock``.

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

    monkeypatch.setattr(mod.notifications, "send_admin_alert", _capture)

    def _install(targets: list[tuple[str, str]], skus: list[Sku]) -> dict[str, Any]:
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
    install([("id-roblox-800", "107"), ("id-roblox-2000", "108")], [full, gone])
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
    install([("id-roblox-2000", "108")], [empty])

    report = await mod.refresh_voucher_stock(client=_Client({"108": {"stock": 0}}))

    # Still empty, but it did not cross over on this run: a channel that
    # repeats itself hourly stops being read.
    assert report.went_out_of_stock == 0
    assert alerts == []


async def test_sweep_survives_one_failing_product(_harness: Any) -> None:
    install, _alerts = _harness
    ok = _sku("roblox-2000", 5)
    install([("id-roblox-800", "107"), ("id-roblox-2000", "108")], [ok])
    client = _Client({"108": {"stock": 7}}, boom={"107"})

    report = await mod.refresh_voucher_stock(client=client)

    assert report.errors == 1
    # The queue continued, and the failure was not written as a zero.
    assert ok.supplier_stock == 7
    assert report.checked == 2


async def test_sweep_treats_minus_one_as_untracked(_harness: Any) -> None:
    install, alerts = _harness
    sku = _sku("roblox-800", 5)
    install([("id-roblox-800", "107")], [sku])

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
    monkeypatch.setattr(
        "yupay.modules.fulfillment.suppliers.REGISTRY", {}, raising=False
    )
    report = await mod.refresh_voucher_stock()
    assert report.checked == 0
