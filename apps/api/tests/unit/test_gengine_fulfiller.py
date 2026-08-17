"""The G-Engine order state machine.

A sale here is not one call. G-Engine creates the order unpaid, verifies the
player account itself, and only a ``verified`` order may be paid — so the
adapter has to carry a sale across several polls without ever paying twice or
declaring success early.
"""

from __future__ import annotations

from typing import Any

import pytest
from yupay.modules.fulfillment.suppliers.base import FulfillerError
from yupay.modules.fulfillment.suppliers.gengine import GEngineFulfiller
from yupay.modules.fulfillment.suppliers.gengine_client import (
    GEngineError,
    GEngineOrder,
    GEngineUnavailableError,
)

pytestmark = pytest.mark.asyncio


def _order(status: str, *, order_id: int = 9001, refunded: bool = False) -> GEngineOrder:
    return GEngineOrder(
        id=order_id,
        uuid="uuid-1",
        status=status,
        price=0.6018,
        currency="USD",
        is_refunded=refunded,
    )


class FakeClient:
    """Records what was called, so "did it pay twice" is answerable."""

    def __init__(self, *, created: Any = None, fetched: Any = None, paid: Any = None) -> None:
        self._created = created
        self._fetched = fetched
        self._paid = paid
        self.pay_calls = 0
        self.create_calls = 0

    async def create_recharge_order(self, **_kw: Any) -> GEngineOrder:
        self.create_calls += 1
        if isinstance(self._created, Exception):
            raise self._created
        return self._created

    async def get_recharge_order(self, _order_id: int) -> GEngineOrder:
        if isinstance(self._fetched, Exception):
            raise self._fetched
        return self._fetched

    async def get_recharge_order_by_uuid(self, _uuid: str) -> GEngineOrder:
        if isinstance(self._fetched, Exception):
            raise self._fetched
        return self._fetched

    async def pay_recharge_order(self, _order_id: int) -> GEngineOrder:
        self.pay_calls += 1
        if isinstance(self._paid, Exception):
            raise self._paid
        return self._paid


class _Task:
    def __init__(self, external_order_id: str | None) -> None:
        self.external_order_id = external_order_id


async def test_a_fresh_order_is_in_progress_not_a_delivery() -> None:
    """It has not been paid yet, and the account is still being verified.
    Reporting success here would tell the customer their diamonds arrived."""
    f = GEngineFulfiller(FakeClient(created=_order("pending")))  # type: ignore[arg-type]
    result = await f._advance(_order("pending"), first_call=True)

    assert result.outcome == "in_progress"
    assert result.external_order_id == "9001"
    assert result.artifact is None


async def test_a_verified_order_is_paid_immediately() -> None:
    # `verified` is the only state that opens payment, and every minute it
    # waits is a minute the customer is staring at "в обработке".
    client = FakeClient(paid=_order("shipped"))
    f = GEngineFulfiller(client)  # type: ignore[arg-type]

    result = await f._advance(_order("verified"), first_call=False)

    assert client.pay_calls == 1
    assert result.outcome == "succeeded"
    assert result.artifact == {
        "supplier": "gengine",
        "external_order_id": "9001",
        "status": "shipped",
    }


async def test_an_already_shipped_order_is_not_paid_again() -> None:
    """The poller sees `shipped` on every later tick; paying again would be
    buying the same top-up twice."""
    client = FakeClient()
    f = GEngineFulfiller(client)  # type: ignore[arg-type]

    result = await f._advance(_order("shipped"), first_call=False)

    assert client.pay_calls == 0
    assert result.outcome == "succeeded"


async def test_a_wrong_player_id_is_the_customers_mistake_not_a_fault() -> None:
    # G-Engine catches this *before* our money moves — the whole reason the
    # flow has a verification step.
    f = GEngineFulfiller(FakeClient())  # type: ignore[arg-type]

    result = await f._advance(_order("invalid_account"), first_call=False)

    assert result.outcome == "failed"
    assert result.error == "invalid_account"
    assert result.extra_metadata["supplier_refunded"] is False


async def test_a_refunded_failure_says_so_so_nobody_chases_the_money() -> None:
    f = GEngineFulfiller(FakeClient())  # type: ignore[arg-type]

    result = await f._advance(_order("cancelled", refunded=True), first_call=False)

    assert result.outcome == "failed"
    assert result.extra_metadata["supplier_refunded"] is True


async def test_an_unreachable_supplier_mid_payment_stays_in_progress() -> None:
    """Nothing was decided upstream. Failing here would abandon a sale that
    may already have gone through."""
    client = FakeClient(paid=GEngineUnavailableError("timeout"))
    f = GEngineFulfiller(client)  # type: ignore[arg-type]

    result = await f._advance(_order("verified"), first_call=False)

    assert result.outcome == "in_progress"


async def test_a_refused_payment_fails_with_the_supplier_s_own_words() -> None:
    client = FakeClient(paid=GEngineError("insufficient funds"))
    f = GEngineFulfiller(client)  # type: ignore[arg-type]

    result = await f._advance(_order("verified"), first_call=False)

    assert result.outcome == "failed"
    assert "insufficient funds" in (result.error or "")


async def test_check_status_before_an_order_exists_is_not_an_error() -> None:
    f = GEngineFulfiller(FakeClient())  # type: ignore[arg-type]

    status = await f.check_status(db=None, task=_Task(None))  # type: ignore[arg-type]

    assert status.outcome == "in_progress"


async def test_a_create_that_already_happened_is_recovered_not_repeated() -> None:
    """The create response can be lost to a timeout. Retrying blind would buy
    the top-up twice, which for a top-up cannot be undone."""
    client = FakeClient(
        created=GEngineError("uuid already used"),
        fetched=_order("verified"),
        paid=_order("shipped"),
    )
    f = GEngineFulfiller(client)  # type: ignore[arg-type]

    # `fulfill` needs a mapping and an item; exercise the recovery seam
    # directly — the mapping lookup is covered by its own integration test.
    recovered = await f._recover("uuid-1")

    assert recovered is not None
    assert recovered.id == 9001
    assert client.create_calls == 0


async def test_form_fields_are_translated_to_the_supplier_s_parameter_names() -> None:
    from yupay.modules.fulfillment.suppliers.gengine import _params_from

    class Item:
        def __init__(self) -> None:
            self.fulfillment_data = {
                "player_id": "1313232551",
                "server": "6618",
                "note": "ignored",
            }

    # Ours are `player_id`/`server`; G-Engine wants `Account`/`Region`. An
    # unmapped key is dropped rather than forwarded — the API rejects unknown
    # params, and a stray note is more likely our form than their contract.
    assert _params_from(Item()) == {  # type: ignore[arg-type]
        "Account": "1313232551",
        "Region": "6618",
    }


async def test_a_non_numeric_mapping_is_named_rather_than_crashing() -> None:
    from yupay.modules.fulfillment.suppliers.gengine import _int_or_fail

    with pytest.raises(FulfillerError, match="must be numeric"):
        _int_or_fail("mlbb_ru", field="external_product_id")
