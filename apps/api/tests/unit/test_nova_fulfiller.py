"""Unit tests for the NOVA fulfiller.

The money grading is the point of this file. NOVA charges on create ("Balance
is charged immediately"), so the difference between "they refused the request"
and "the call broke" is the difference between our money being here and our
money being unaccounted for.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from yupay.modules.fulfillment.suppliers.base import (
    FulfillerError,
    FulfillerNotIntegratedError,
    MoneyOutcome,
)
from yupay.modules.fulfillment.suppliers.nova import (
    LOW_BALANCE_ERROR,
    NovaFulfiller,
    _mapping_for,
    _order_id_of,
    _status_of,
)
from yupay.modules.fulfillment.suppliers.nova_client import NovaError, NovaUnavailableError

pytestmark = pytest.mark.asyncio


class _FakeClient:
    """Records what was called, so "did it order at all" is answerable."""

    def __init__(self, *, order: dict[str, Any] | None = None, raises: Exception | None = None):
        self._order = order or {}
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    async def create_topup_order(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._order

    async def get_order(self, order_id: str) -> dict[str, Any]:
        if self._raises is not None:
            raise self._raises
        return self._order


def _mapping(**over: Any) -> Any:
    base = {
        "kind": "game",
        "external_product_id": "mobile_legends_ru",
        "external_variant_id": "275_diamonds",
    }
    base.update(over)
    return SimpleNamespace(**base)


def _item(**over: Any) -> Any:
    base = {
        "sku_id": "sku-1",
        "qty": 1,
        "fulfillment_data": {"player_id": "1313232551", "server": "6618"},
    }
    base.update(over)
    return SimpleNamespace(**base)


def _fulfiller(
    client: _FakeClient, monkeypatch: pytest.MonkeyPatch, *, available: bool = True
) -> NovaFulfiller:
    """The adapter with its key faked in.

    ``available`` reads settings, and settings are cached for the process, so
    the house pattern (see ``test_gengine_fulfiller.py``) patches the property
    rather than the environment.
    """
    monkeypatch.setattr(NovaFulfiller, "available", property(lambda _self: available))
    return NovaFulfiller(client=client)  # type: ignore[arg-type]


async def _fulfill(
    client: _FakeClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    item: Any = None,
    mapping: Any = None,
    available: bool = True,
) -> Any:
    """Run ``fulfill`` with the mapping lookup stubbed, so ``db`` is never touched."""
    import yupay.modules.fulfillment.suppliers.nova as mod

    row = mapping if mapping is not None else _mapping()

    async def _mapping_for(_db: Any, *, sku_id: str) -> Any:
        return row

    monkeypatch.setattr(mod, "_mapping_for", _mapping_for)
    return await _fulfiller(client, monkeypatch, available=available).fulfill(
        db=None,  # type: ignore[arg-type]
        order=SimpleNamespace(),  # type: ignore[arg-type]
        item=item if item is not None else _item(),
        idempotency_key="task-42",
    )


async def test_a_created_order_is_in_progress_and_keeps_its_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(order={"id": "ord_1", "status": "processing"})
    result = await _fulfill(client, monkeypatch)
    assert result.outcome == "in_progress"
    assert result.external_order_id == "ord_1"
    assert result.money_outcome is None
    # Our own field names are renamed to theirs: `server` -> `server_id`.
    assert client.calls[0]["fields"] == {"player_id": "1313232551", "server_id": "6618"}
    assert client.calls[0]["idempotency_key"] == "task-42"
    assert client.calls[0]["category_id"] == "mobile_legends_ru"
    assert client.calls[0]["offer_id"] == "275_diamonds"


async def test_a_completed_order_delivers_a_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    result = await _fulfill(_FakeClient(order={"id": "ord_1", "status": "completed"}), monkeypatch)
    assert result.outcome == "succeeded"
    assert result.artifact_kind == "topup_receipt"
    assert result.money_outcome is None


async def test_an_unknown_status_stays_in_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    """Their order object is untyped; a word we have never seen must not end
    the task in either direction."""
    result = await _fulfill(_FakeClient(order={"id": "ord_1", "status": "half_done"}), monkeypatch)
    assert result.outcome == "in_progress"


async def test_a_refunded_order_says_the_money_came_back(monkeypatch: pytest.MonkeyPatch) -> None:
    result = await _fulfill(_FakeClient(order={"id": "ord_1", "status": "refunded"}), monkeypatch)
    assert result.outcome == "failed"
    assert result.money_outcome is MoneyOutcome.RETURNED


async def test_a_failed_order_without_a_refund_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = await _fulfill(_FakeClient(order={"id": "ord_1", "status": "failed"}), monkeypatch)
    assert result.outcome == "failed"
    assert result.money_outcome is MoneyOutcome.UNKNOWN


@pytest.mark.parametrize(
    ("status", "money"),
    [
        (400, MoneyOutcome.RETURNED),
        (403, MoneyOutcome.RETURNED),
        (404, MoneyOutcome.RETURNED),
        (409, MoneyOutcome.UNKNOWN),
        (500, MoneyOutcome.UNKNOWN),
    ],
)
async def test_refusals_are_graded_by_status(
    monkeypatch: pytest.MonkeyPatch, status: int, money: MoneyOutcome
) -> None:
    client = _FakeClient(raises=NovaError("no", status=status))
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfill(client, monkeypatch)
    assert excinfo.value.money_outcome is money


async def test_unreachable_on_the_create_may_have_spent(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(raises=NovaUnavailableError("boom"))
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfill(client, monkeypatch)
    assert excinfo.value.money_outcome is MoneyOutcome.UNKNOWN


async def test_low_balance_is_a_stall_not_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """The saga keys on this exact string to park the task and alert ops."""
    client = _FakeClient(raises=NovaError("insufficient balance", status=400))
    result = await _fulfill(client, monkeypatch)
    assert result.outcome == "failed"
    assert result.error == LOW_BALANCE_ERROR
    assert result.money_outcome is None


async def test_a_multi_quantity_item_is_refused_before_any_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One call buys one offer: their order endpoint has no quantity."""
    client = _FakeClient(order={"id": "ord_1", "status": "processing"})
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfill(client, monkeypatch, item=_item(qty=2))
    assert excinfo.value.money_outcome is MoneyOutcome.RETURNED
    assert client.calls == []


async def test_a_mapping_without_an_offer_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient()
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfill(client, monkeypatch, mapping=_mapping(external_variant_id=None))
    assert excinfo.value.money_outcome is MoneyOutcome.RETURNED
    assert client.calls == []


async def test_no_usable_fields_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient()
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfill(client, monkeypatch, item=_item(fulfillment_data={"email": "a@b.c"}))
    assert excinfo.value.money_outcome is MoneyOutcome.RETURNED
    assert client.calls == []


async def test_an_unconfigured_key_never_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient()
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfill(client, monkeypatch, available=False)
    assert excinfo.value.money_outcome is MoneyOutcome.RETURNED
    assert client.calls == []


async def test_check_status_without_an_id_stays_in_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = SimpleNamespace(external_order_id=None, extra_metadata={})
    status = await _fulfiller(_FakeClient(), monkeypatch).check_status(
        db=None,  # type: ignore[arg-type]
        task=task,  # type: ignore[arg-type]
    )
    assert status.outcome == "in_progress"


async def test_check_status_that_cannot_read_says_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = SimpleNamespace(external_order_id="ord_1", extra_metadata={})
    client = _FakeClient(raises=NovaUnavailableError("boom"))
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfiller(client, monkeypatch).check_status(db=None, task=task)  # type: ignore[arg-type]
    assert excinfo.value.money_outcome is MoneyOutcome.UNKNOWN


async def test_the_same_task_always_sends_the_same_key_and_never_retries_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The idempotent re-call leg AGENTS.md §8 requires of a supplier adapter.

    Their two descriptions of a reused `Idempotency-Key` disagree — one says it
    returns the original order, the other says it is rejected — so the only
    behaviour we can assert, and the only one that is safe under either, is
    this: one `fulfill` call makes exactly one create, and a second `fulfill`
    for the same task sends the same key rather than a fresh one. A retry that
    minted a new key would be a second purchase whichever way their server
    behaves.
    """
    client = _FakeClient(order={"id": "ord_1", "status": "processing"})
    await _fulfill(client, monkeypatch)
    await _fulfill(client, monkeypatch)
    assert len(client.calls) == 2
    assert {c["idempotency_key"] for c in client.calls} == {"task-42"}


async def test_check_status_reads_a_finished_order(monkeypatch: pytest.MonkeyPatch) -> None:
    task = SimpleNamespace(external_order_id="ord_1", extra_metadata={})
    client = _FakeClient(order={"id": "ord_1", "status": "completed"})
    status = await _fulfiller(client, monkeypatch).check_status(
        db=None,  # type: ignore[arg-type]
        task=task,  # type: ignore[arg-type]
    )
    assert status.outcome == "succeeded"
    assert status.artifact_kind == "topup_receipt"


async def test_check_status_with_no_key_never_calls_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """By the time anything polls, the order has already been placed — a key
    that went missing since says nothing about the money it was spent with."""
    task = SimpleNamespace(external_order_id="ord_1", extra_metadata={})
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfiller(_FakeClient(), monkeypatch, available=False).check_status(
            db=None,  # type: ignore[arg-type]
            task=task,  # type: ignore[arg-type]
        )
    assert excinfo.value.money_outcome is MoneyOutcome.UNKNOWN


async def test_cancel_is_not_integrated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nova exposes no cancel endpoint. Refusing the cancellation is not the
    same claim as refusing the purchase it would have cancelled — the order
    this call declines to unbuy was already bought, and it cannot say what
    became of that money."""
    with pytest.raises(FulfillerNotIntegratedError) as excinfo:
        await _fulfiller(_FakeClient(), monkeypatch).cancel(
            db=None,  # type: ignore[arg-type]
            task=SimpleNamespace(),  # type: ignore[arg-type]
        )
    assert excinfo.value.money_outcome is MoneyOutcome.UNKNOWN


async def test_status_of_an_object_with_no_recognisable_key_is_blank() -> None:
    """Their spec types the order object as ``{}`` — a shape we have never
    seen must not crash the reader."""
    assert _status_of({"foo": "bar"}) == ""


async def test_order_id_of_an_object_with_no_recognisable_key_is_none() -> None:
    assert _order_id_of({"foo": "bar"}) is None


class _FakeDb:
    """Stands in for the session ``_mapping_for`` uses to look the SKU up."""

    def __init__(self, row: Any = None) -> None:
        self._row = row

    async def execute(self, _stmt: Any) -> Any:
        row = self._row

        class _Result:
            def scalar_one_or_none(self) -> Any:
                return row

        return _Result()


async def test_mapping_for_returns_the_active_row() -> None:
    row = _mapping()
    assert await _mapping_for(_FakeDb(row), sku_id="sku-1") is row  # type: ignore[arg-type]


async def test_mapping_for_with_no_row_is_refused() -> None:
    with pytest.raises(FulfillerError) as excinfo:
        await _mapping_for(_FakeDb(None), sku_id="sku-1")  # type: ignore[arg-type]
    assert excinfo.value.money_outcome is MoneyOutcome.RETURNED
