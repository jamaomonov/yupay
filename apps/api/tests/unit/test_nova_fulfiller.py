"""Unit tests for the NOVA fulfiller.

The money grading is the point of this file. NOVA charges on create ("Balance
is charged immediately"), so the difference between "they refused the request"
and "the call broke" is the difference between our money being here and our
money being unaccounted for.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from yupay.modules.fulfillment.suppliers.base import (
    FulfillerError,
    FulfillerNotIntegratedError,
    MoneyOutcome,
)
from yupay.modules.fulfillment.suppliers.nova import (
    STEAM_SENTINEL,
    NovaFulfiller,
    _mapping_for,
)
from yupay.modules.fulfillment.suppliers.nova_client import NovaError, NovaUnavailableError
from yupay.modules.fulfillment.suppliers.nova_grading import (
    LOW_BALANCE_ERROR,
    _order_id_of,
    _status_of,
)

pytestmark = pytest.mark.asyncio


class _FakeClient:
    """Records what was called, so "did it order at all" is answerable."""

    def __init__(
        self,
        *,
        order: dict[str, Any] | None = None,
        steam_order: dict[str, Any] | None = None,
        raises: Exception | None = None,
    ):
        self._order = order or {}
        self._steam_order = steam_order if steam_order is not None else (order or {})
        self._raises = raises
        self.calls: list[dict[str, Any]] = []
        self.steam_calls: list[dict[str, Any]] = []

    async def create_topup_order(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._order

    async def create_steam_order(self, **kwargs: Any) -> dict[str, Any]:
        self.steam_calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._steam_order

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
        "unit_price_usd": Decimal("10"),
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


async def test_a_mapping_without_a_category_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The sibling of the missing-offer case: both ids are required, and
    neither may reach a call that spends."""
    client = _FakeClient()
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfill(client, monkeypatch, mapping=_mapping(external_product_id=""))
    assert excinfo.value.money_outcome is MoneyOutcome.RETURNED
    assert client.calls == []


async def test_a_steam_mapping_sends_the_login_and_the_line_amount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sentinel routes to the Steam call, not the games one, and it never
    reads `offer_id` — there isn't one."""
    client = _FakeClient(steam_order={"id": "ord-9", "status": "processing"})
    result = await _fulfill(
        client,
        monkeypatch,
        item=_item(fulfillment_data={"steam_login": "someone"}, unit_price_usd=Decimal("10")),
        mapping=_mapping(external_product_id=STEAM_SENTINEL, external_variant_id=""),
    )
    assert result.outcome == "in_progress"
    assert result.external_order_id == "ord-9"
    assert client.steam_calls[0]["steam_login"] == "someone"
    assert client.steam_calls[0]["amount_usd"] == Decimal("10")
    assert client.steam_calls[0]["idempotency_key"] == "task-42"
    assert client.calls == []


async def test_a_games_mapping_never_reaches_the_steam_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default mapping is a games one — it must take the games path only."""
    client = _FakeClient(order={"id": "ord_1", "status": "processing"})
    await _fulfill(client, monkeypatch)
    assert len(client.calls) == 1
    assert client.steam_calls == []


async def test_a_steam_line_without_a_login_is_refused_before_any_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient()
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfill(
            client,
            monkeypatch,
            item=_item(fulfillment_data={}),
            mapping=_mapping(external_product_id=STEAM_SENTINEL, external_variant_id=""),
        )
    assert excinfo.value.money_outcome is MoneyOutcome.RETURNED
    assert client.calls == []
    assert client.steam_calls == []


async def test_a_steam_refusal_is_graded_and_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Steam branch grades a refusal exactly like the games one and
    redacts the login the same way `_without_our_inputs` redacts a player id."""
    client = _FakeClient(raises=NovaError("steam login someone-secret not found", status=400))
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfill(
            client,
            monkeypatch,
            item=_item(fulfillment_data={"steam_login": "someone-secret"}),
            mapping=_mapping(external_product_id=STEAM_SENTINEL, external_variant_id=""),
        )
    assert excinfo.value.money_outcome is MoneyOutcome.RETURNED
    message = str(excinfo.value)
    assert "someone-secret" not in message
    assert "not found" in message


async def test_a_steam_low_balance_is_a_stall_not_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(raises=NovaError("insufficient balance", status=400))
    result = await _fulfill(
        client,
        monkeypatch,
        item=_item(fulfillment_data={"steam_login": "someone"}),
        mapping=_mapping(external_product_id=STEAM_SENTINEL, external_variant_id=""),
    )
    assert result.outcome == "failed"
    assert result.error == LOW_BALANCE_ERROR
    assert result.money_outcome is None


async def test_a_steam_call_unreachable_may_have_spent(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(raises=NovaUnavailableError("boom"))
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfill(
            client,
            monkeypatch,
            item=_item(fulfillment_data={"steam_login": "someone"}),
            mapping=_mapping(external_product_id=STEAM_SENTINEL, external_variant_id=""),
        )
    assert excinfo.value.money_outcome is MoneyOutcome.UNKNOWN


async def test_the_steam_charge_reaches_extra_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """What NOVA actually took is not the face value for Steam — it is the
    number Task 2's margin report reads."""
    result = await _fulfill(
        _FakeClient(steam_order={"id": "ord-9", "status": "completed", "chargedUsd": "9.80"}),
        monkeypatch,
        item=_item(fulfillment_data={"steam_login": "someone"}),
        mapping=_mapping(external_product_id=STEAM_SENTINEL, external_variant_id=""),
    )
    assert result.extra_metadata["supplier_charged_usd"] == "9.80"


async def test_their_refusal_never_carries_back_the_player_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`task.last_error` is read by humans and written to logs (§9).

    A supplier that echoes the id it could not find would put a customer's
    identifier there, so everything we submitted is taken back out of their
    message — while the part that makes the refusal actionable survives.
    """
    client = _FakeClient(raises=NovaError("player 1313232551 not found on server 6618", status=400))
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfill(client, monkeypatch)
    message = str(excinfo.value)
    assert "1313232551" not in message
    assert "6618" not in message
    assert "not found" in message


async def test_health_reports_the_balance(monkeypatch: pytest.MonkeyPatch) -> None:
    """The admin page's probe, and the answer to "can we switch a SKU to NOVA".

    NOVA is a reserve, so nothing routes to it on an ordinary day — the key
    being dead or the balance being empty is discovered at the moment somebody
    needs it, unless the page can say so first.
    """

    class _Balance:
        async def get_balance(self) -> dict[str, Any]:
            return {"ok": True, "balance": "12.3456", "currency": "USD"}

    f = NovaFulfiller(client=_Balance())  # type: ignore[arg-type]
    monkeypatch.setattr(NovaFulfiller, "available", property(lambda _self: True))
    assert await f.health() == {"available": True, "balance": "12.35", "currency": "USD"}


async def test_health_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Broken:
        async def get_balance(self) -> dict[str, Any]:
            raise NovaUnavailableError("boom")

    f = NovaFulfiller(client=_Broken())  # type: ignore[arg-type]
    monkeypatch.setattr(NovaFulfiller, "available", property(lambda _self: True))
    out = await f.health()
    assert out["available"] is False
    assert "boom" in str(out["reason"])


async def test_health_without_a_key_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    f = NovaFulfiller(client=_FakeClient())  # type: ignore[arg-type]
    monkeypatch.setattr(NovaFulfiller, "available", property(lambda _self: False))
    assert await f.health() == {
        "available": False,
        "reason": "NOVA_API_KEY is not configured",
    }


async def test_a_create_with_no_readable_id_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An id-less "still moving" result is a task nothing can ever finish.

    `check_status` would have nothing to look the order up with, so it answers
    `in_progress` forever while the reconciler re-runs it every sixty seconds
    and NOVA keeps the money. Their order object is untyped in their own spec,
    so an unread envelope is the likeliest thing to go wrong on the first live
    order — the one a human places deliberately.
    """
    client = _FakeClient(order={"weird": "shape"})
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfill(client, monkeypatch)
    assert excinfo.value.money_outcome is MoneyOutcome.UNKNOWN
    assert "no id" in str(excinfo.value)
    # It still went out — the money question is open precisely because it did.
    assert len(client.calls) == 1


async def test_a_failure_carries_their_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    """`fail_reason` is a real field on their order, and it is the only thing
    that tells an operator why — without it the inbox says "nova order failed"
    and the next step is a shell."""
    client = _FakeClient(
        order={"id": "ord_1", "status": "failed", "fail_reason": "player not eligible"}
    )
    result = await _fulfill(client, monkeypatch)
    assert result.outcome == "failed"
    assert "player not eligible" in str(result.error)
    assert result.extra_metadata["nova_fail_reason"] == "player not eligible"
    assert result.money_outcome is MoneyOutcome.UNKNOWN
