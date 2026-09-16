"""The G-Engine order state machine.

A sale here is not one call. G-Engine creates the order unpaid, verifies the
player account itself, and only a ``verified`` order may be paid — so the
adapter has to carry a sale across several polls without ever paying twice or
declaring success early.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, ClassVar

import pytest
from yupay.modules.fulfillment.suppliers.base import FulfillerError
from yupay.modules.fulfillment.suppliers.gengine import PAY_REQUESTED_KEY, GEngineFulfiller
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


class _FakeDb:
    """Stands in for the session `fulfill` uses to look the SKU up.

    An amount-priced line re-derives its quantity from the SKU, so the adapter
    now reads one. `sku=None` means "not found", which falls back to the
    mapping's quantity — the package case.
    """

    def __init__(self, sku: Any = None) -> None:
        self._sku = sku

    async def execute(self, _stmt: Any) -> Any:
        sku = self._sku

        class _Result:
            def scalar_one_or_none(self) -> Any:
                return sku

        return _Result()


class _Task:
    def __init__(self, external_order_id: str | None) -> None:
        self.external_order_id = external_order_id
        # `check_status` now reads this before the id-less early-return, to
        # route a gift task there — real tasks always carry it (the column
        # is NOT NULL with a `'{}'::jsonb` default).
        self.extra_metadata: dict[str, Any] = {}


async def test_a_fresh_order_is_in_progress_not_a_delivery() -> None:
    """It has not been paid yet, and the account is still being verified.
    Reporting success here would tell the customer their diamonds arrived."""
    f = GEngineFulfiller(FakeClient(created=_order("pending")))  # type: ignore[arg-type]
    result = await f._advance(_order("pending"), first_call=True)

    assert result.outcome == "in_progress"
    assert result.external_order_id == "9001"
    assert result.artifact is None


async def test_a_verified_order_banks_the_intent_before_it_pays() -> None:
    """`verified` is the only state that opens payment, and every minute it
    waits is a minute the customer is staring at "в обработке" — so this used
    to pay on the first sight of it.

    It now costs one extra 60-second tick, bought deliberately: the record that
    we are about to spend must be committed by a transaction that does *not*
    spend, or an abort anywhere in the paying tick (the metadata merge,
    ``_try_settle_order``'s blocking lock, the COMMIT) rolls the record back
    while the money stays gone. See ``gengine.PAY_REQUESTED_KEY``.
    """
    client = FakeClient(paid=_order("shipped"))
    f = GEngineFulfiller(client)  # type: ignore[arg-type]

    banked = await f._advance(_order("verified"), first_call=False)

    assert client.pay_calls == 0, "nothing is spent on the tick that records the intent"
    assert banked.outcome == "in_progress"
    assert banked.extra_metadata[PAY_REQUESTED_KEY] is True

    result = await f._advance(_order("verified"), first_call=False, paid_before=True)

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

    result = await f._advance(_order("verified"), first_call=False, paid_before=True)

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


async def test_a_telegram_username_travels_in_the_account_slot() -> None:
    from yupay.modules.fulfillment.suppliers.gengine import _params_from

    class Item:
        def __init__(self) -> None:
            self.fulfillment_data = {"username": "@durov"}

    assert _params_from(Item()) == {"Account": "@durov"}  # type: ignore[arg-type]


async def _sent_params(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mapping: Any,
    data: dict[str, str] | None = None,
    item: Any = None,
    sku: Any = None,
) -> dict[str, Any]:
    """Run `fulfill` against a stub client and report what it put on the wire.

    ``item`` lets a caller supply a line with its own ``qty`` (a unit SKU);
    the default is the plain package line most tests want. ``create_calls``
    rides along in the same dict so a test can assert "one create" without a
    second mock style.
    """
    import yupay.modules.fulfillment.suppliers.gengine as mod

    sent: dict[str, Any] = {"create_calls": 0}

    class Client:
        async def create_recharge_order(self, **kw: Any) -> GEngineOrder:
            sent["create_calls"] += 1
            sent.update(kw)
            return _order("pending")

    class DefaultItem:
        sku_id = "sku-1"
        qty = 1
        fulfillment_data: ClassVar[dict[str, str]] = data or {}

    async def _mapping_for(_db: Any, *, sku_id: str) -> Any:
        return mapping

    monkeypatch.setattr(mod, "_mapping_for", _mapping_for)
    # The key is absent in tests; `available` is not what is under test here.
    monkeypatch.setattr(GEngineFulfiller, "available", property(lambda _self: True))

    f = GEngineFulfiller(Client())  # type: ignore[arg-type]
    await f.fulfill(
        db=_FakeDb(sku),  # type: ignore[arg-type]
        order=None,  # type: ignore[arg-type]
        item=item if item is not None else DefaultItem(),  # type: ignore[arg-type]
        idempotency_key="k",
    )
    return sent


async def test_an_unfixed_service_is_sent_the_quantity_it_requires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Telegram Stars has no denominations — G-Engine wants `Quantity`, and
    refuses the order without one. We sell fixed packages, so the count comes
    from the mapping and is never the customer's to type."""

    class Mapping:
        kind = "game"
        external_product_id = "72"
        external_variant_id = None
        quantity = 250

    sent = await _sent_params(monkeypatch, mapping=Mapping(), data={"username": "durov"})

    assert sent["params"] == {"Account": "durov", "Quantity": "250"}
    # No denomination for an unfixed service — sending one would be rejected.
    assert sent["denomination_id"] is None


async def test_an_unfixed_unit_sku_sends_item_qty(monkeypatch: pytest.MonkeyPatch) -> None:
    """A unit SKU (Telegram Stars) carries its own count on the order line —
    the mapping's `quantity` stays pinned at 1 for these until the seed
    (Task 10), so `Quantity` must come from `item.qty`, not the mapping."""
    from decimal import Decimal

    class Mapping:
        kind = "game"
        external_product_id = "72"
        external_variant_id = None
        quantity = 1

    class Item:
        sku_id = "sku-stars"
        qty = 500
        fulfillment_data: ClassVar[dict[str, str]] = {"username": "durov"}
        unit_price_usd = Decimal("0.02")

    class Sku:
        variable_amount = False
        units_per_usd = None
        amount_unit = "Stars"
        min_qty = 50
        max_qty = 2500

    sent = await _sent_params(monkeypatch, mapping=Mapping(), item=Item(), sku=Sku())

    assert sent["params"]["Quantity"] == "500"
    assert sent["create_calls"] == 1  # one create, not 500


async def test_a_zero_quantity_is_refused_rather_than_creating_an_order() -> None:
    """`item.qty` and `mapping.quantity` each carry a DB `CHECK (... > 0)`, so
    a real order can never reach this — the guard is belt-and-suspenders
    against a duck-typed caller that skips those constraints, not a state a
    persisted row can be in."""
    from yupay.modules.fulfillment.suppliers.gengine import _quantity_for

    class Mapping:
        quantity = 0

    class Item:
        sku_id = "sku-1"
        qty = 5

    with pytest.raises(FulfillerError, match="quantity resolves to zero"):
        await _quantity_for(_FakeDb(), item=Item(), mapping=Mapping())  # type: ignore[arg-type]


async def test_a_fixed_service_is_not_given_a_quantity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Premium picks a denomination instead. `quantity` defaults to 1 on every
    mapping, so forwarding it unconditionally would attach a meaningless
    parameter to every game top-up we already sell."""

    class Mapping:
        kind = "game"
        external_product_id = "79"
        external_variant_id = "740"
        quantity = 1

    sent = await _sent_params(monkeypatch, mapping=Mapping(), data={"username": "durov"})

    assert sent["params"] == {"Account": "durov"}
    assert sent["denomination_id"] == 740


async def test_a_non_numeric_mapping_is_named_rather_than_crashing() -> None:
    from yupay.modules.fulfillment.suppliers.gengine import _int_or_fail

    with pytest.raises(FulfillerError, match="must be numeric"):
        _int_or_fail("mlbb_ru", field="external_product_id")


# ---------- shop: gift codes and keys ----------


def _shop(status: str, *, codes: list[str] | None = None, refunded: bool = False) -> Any:
    from yupay.modules.fulfillment.suppliers.gengine_client import GEngineShopOrder

    return GEngineShopOrder(
        id=7001, status=status, price=3.5, is_refunded=refunded, codes=codes or []
    )


class FakeShopClient:
    """Counts reserve/pay separately — the whole safety argument rests on
    which of the two ran."""

    def __init__(self, *, reserved: Any = None, paid: Any = None, fetched: Any = None) -> None:
        self._reserved = reserved
        self._paid = paid
        self._fetched = fetched
        self.reserve_calls = 0
        self.pay_calls = 0

    async def create_shop_order(self, **_kw: Any) -> Any:
        self.reserve_calls += 1
        if isinstance(self._reserved, Exception):
            raise self._reserved
        return self._reserved

    async def pay_shop_order(self, _order_id: int) -> Any:
        self.pay_calls += 1
        if isinstance(self._paid, Exception):
            raise self._paid
        return self._paid

    async def get_shop_order(self, _order_id: int) -> Any:
        if isinstance(self._fetched, Exception):
            raise self._fetched
        return self._fetched


class _Mapping:
    def __init__(self) -> None:
        self.kind = "voucher"
        self.external_product_id = "140"
        self.external_variant_id = "555"


class _ShopItem:
    def __init__(self) -> None:
        self.sku_id = "sku-1"
        self.qty = 2
        self.fulfillment_data: dict[str, str] = {}


async def test_a_paid_shop_order_delivers_its_codes() -> None:
    client = FakeShopClient(
        reserved=_shop("pending"), paid=_shop("shipped", codes=["AAA-111", "BBB-222"])
    )
    f = GEngineFulfiller(client)  # type: ignore[arg-type]

    result = await f._fulfill_shop(mapping=_Mapping(), item=_ShopItem())  # type: ignore[arg-type]

    assert (client.reserve_calls, client.pay_calls) == (1, 1)
    assert result.outcome == "succeeded"
    assert result.artifact_kind == "voucher_code"
    assert result.artifact is not None
    assert result.artifact["code"] == "AAA-111"
    assert result.artifact["codes"] == ["AAA-111", "BBB-222"]


async def test_a_shipped_order_with_no_codes_yet_is_not_a_delivery() -> None:
    """Handing over an empty voucher is worse than making the customer wait —
    the same rule the G2B adapter follows."""
    client = FakeShopClient(reserved=_shop("pending"), paid=_shop("shipped", codes=[]))
    f = GEngineFulfiller(client)  # type: ignore[arg-type]

    result = await f._fulfill_shop(mapping=_Mapping(), item=_ShopItem())  # type: ignore[arg-type]

    assert result.outcome == "in_progress"
    assert result.artifact is None


async def test_an_unreachable_supplier_after_reserving_keeps_the_order_id() -> None:
    """This is the case the two-step flow exists for. The shop API takes no
    client-supplied id, so losing the order id would mean losing the sale —
    but the reservation costs nothing until it is paid."""
    client = FakeShopClient(reserved=_shop("pending"), paid=GEngineUnavailableError("timeout"))
    f = GEngineFulfiller(client)  # type: ignore[arg-type]

    result = await f._fulfill_shop(mapping=_Mapping(), item=_ShopItem())  # type: ignore[arg-type]

    assert result.outcome == "in_progress"
    assert result.external_order_id == "7001"
    # And the task is tagged so the poller knows to use the shop endpoints.
    assert result.extra_metadata["gengine_kind"] == "voucher"


async def test_the_poller_pays_a_reservation_that_was_never_settled() -> None:
    client = FakeShopClient(fetched=_shop("pending"), paid=_shop("shipped", codes=["CCC-333"]))
    f = GEngineFulfiller(client)  # type: ignore[arg-type]

    status = await f._shop_status(_Task("7001"))  # type: ignore[arg-type]

    assert client.pay_calls == 1
    assert status.outcome == "succeeded"
    assert status.artifact is not None
    assert status.artifact["code"] == "CCC-333"


async def test_the_poller_does_not_pay_an_order_that_is_already_shipped() -> None:
    client = FakeShopClient(fetched=_shop("shipped", codes=["DDD-444"]))
    f = GEngineFulfiller(client)  # type: ignore[arg-type]

    status = await f._shop_status(_Task("7001"))  # type: ignore[arg-type]

    assert client.pay_calls == 0
    assert status.outcome == "succeeded"


async def test_a_cancelled_shop_order_fails_and_says_whether_money_came_back() -> None:
    client = FakeShopClient(fetched=_shop("canceled", refunded=True))
    f = GEngineFulfiller(client)  # type: ignore[arg-type]

    status = await f._shop_status(_Task("7001"))  # type: ignore[arg-type]

    assert status.outcome == "failed"
    assert status.extra_metadata["supplier_refunded"] is True


# ---------- the health probe on the integrations page ----------


async def test_health_without_a_key_says_so_instead_of_probing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(GEngineFulfiller, "available", property(lambda _self: False))
    assert await GEngineFulfiller().health() == {
        "available": False,
        "reason": "GENGINE_API_KEY is not configured",
    }


async def test_health_reports_the_wallet_balance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(GEngineFulfiller, "available", property(lambda _self: True))

    class Client:
        async def get_balance(self) -> dict[str, Any]:
            return {"balance": 54.0512, "currency": "USD"}

    health = await GEngineFulfiller(Client()).health()  # type: ignore[arg-type]

    # Two decimals: a balance is money, and 54.0512 on a dashboard reads as a bug.
    assert health == {"available": True, "balance": "54.05", "currency": "USD"}


async def test_a_supplier_that_is_down_does_not_break_the_admin_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator opening the integrations page must not meet an error
    boundary because a supplier is unreachable."""
    monkeypatch.setattr(GEngineFulfiller, "available", property(lambda _self: True))

    class Client:
        async def get_balance(self) -> dict[str, Any]:
            raise GEngineUnavailableError("connection refused")

    health = await GEngineFulfiller(Client()).health()  # type: ignore[arg-type]

    assert health["available"] is False
    assert "connection refused" in str(health["reason"])


async def test_an_unexpected_fault_in_the_probe_is_still_caught(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(GEngineFulfiller, "available", property(lambda _self: True))

    class Client:
        async def get_balance(self) -> dict[str, Any]:
            raise ValueError("something we did not anticipate")

    health = await GEngineFulfiller(Client()).health()  # type: ignore[arg-type]
    assert health["available"] is False


# ---------- polling routes to the right half of the API ----------


class _TaskWithKind:
    def __init__(self, order_id: str, kind: str | None) -> None:
        self.external_order_id = order_id
        self.extra_metadata = {"gengine_kind": kind} if kind else {}


async def test_a_voucher_task_is_polled_against_the_shop_endpoints() -> None:
    """Recharge and shop are separate order spaces upstream — id 7001 exists in
    both and means different things. The tag written at fulfil time is what
    keeps the poller on the right one."""
    client = FakeShopClient(fetched=_shop("shipped", codes=["EEE-555"]))
    f = GEngineFulfiller(client)  # type: ignore[arg-type]

    status = await f.check_status(db=None, task=_TaskWithKind("7001", "voucher"))  # type: ignore[arg-type]

    assert status.outcome == "succeeded"
    assert status.artifact is not None
    assert status.artifact["code"] == "EEE-555"


async def test_a_top_up_task_is_polled_against_the_recharge_endpoints() -> None:
    client = FakeClient(fetched=_order("shipped"))
    f = GEngineFulfiller(client)  # type: ignore[arg-type]

    status = await f.check_status(db=None, task=_TaskWithKind("9001", None))  # type: ignore[arg-type]

    assert status.outcome == "succeeded"


async def test_an_unreachable_supplier_while_polling_is_raised_not_swallowed() -> None:
    # Swallowing it would read as "still pending" forever; the caller retries.
    client = FakeClient(fetched=GEngineUnavailableError("timeout"))
    f = GEngineFulfiller(client)  # type: ignore[arg-type]

    with pytest.raises(FulfillerError):
        await f.check_status(db=None, task=_TaskWithKind("9001", None))  # type: ignore[arg-type]


async def test_a_uuid_with_no_order_behind_it_recovers_nothing() -> None:
    f = GEngineFulfiller(FakeClient(fetched=GEngineError("not found")))  # type: ignore[arg-type]
    assert await f._recover("uuid-unknown") is None


# ---------- the mapping is what makes a SKU sellable ----------


async def test_a_sku_with_no_mapping_is_named_rather_than_silently_failing() -> None:
    from yupay.modules.fulfillment.suppliers.gengine import _mapping_for

    class _Empty:
        def scalar_one_or_none(self) -> None:
            return None

    class _Db:
        async def execute(self, _stmt: Any) -> _Empty:
            return _Empty()

    with pytest.raises(FulfillerError, match="no active g-engine mapping"):
        await _mapping_for(_Db(), sku_id="sku-unmapped")  # type: ignore[arg-type]


async def test_fulfill_without_a_key_refuses_before_touching_the_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(GEngineFulfiller, "available", property(lambda _self: False))
    with pytest.raises(FulfillerError, match="GENGINE_API_KEY"):
        await GEngineFulfiller().fulfill(
            db=None,  # type: ignore[arg-type]
            order=None,  # type: ignore[arg-type]
            item=None,  # type: ignore[arg-type]
            idempotency_key="k",
        )


# ---------- the create-was-lost window ----------


async def test_a_lost_create_response_is_recovered_instead_of_bought_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of minting our own uuid. G-Engine rejects the second
    create; recovering the first is the difference between one top-up and two,
    and a top-up cannot be un-bought."""

    class Mapping:
        kind = "game"
        external_product_id = "72"
        external_variant_id = None
        quantity = 50

    class Item:
        sku_id = "sku-1"
        qty = 1
        fulfillment_data: ClassVar[dict[str, str]] = {"username": "durov"}

    client = FakeClient(
        created=GEngineError("uuid already used"),
        fetched=_order("verified"),
        paid=_order("shipped"),
    )
    import yupay.modules.fulfillment.suppliers.gengine as mod

    async def _mapping_for(_db: Any, *, sku_id: str) -> Any:
        return Mapping()

    monkeypatch.setattr(mod, "_mapping_for", _mapping_for)
    monkeypatch.setattr(GEngineFulfiller, "available", property(lambda _self: True))

    result = await GEngineFulfiller(client).fulfill(  # type: ignore[arg-type]
        db=_FakeDb(),  # type: ignore[arg-type]
        order=None,  # type: ignore[arg-type]
        item=Item(),  # type: ignore[arg-type]
        idempotency_key="uuid-1",
    )

    assert client.create_calls == 1
    # The recovered order is already `verified`, so this lands on the same
    # rule as any other: bank the intent now, pay on the next tick. What this
    # test is about — one create, not two — is unchanged.
    assert client.pay_calls == 0
    assert result.outcome == "in_progress"
    assert result.extra_metadata[PAY_REQUESTED_KEY] is True


async def test_a_create_that_truly_failed_is_reported_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Mapping:
        kind = "game"
        external_product_id = "72"
        external_variant_id = None
        quantity = 50

    class Item:
        sku_id = "sku-1"
        qty = 1
        fulfillment_data: ClassVar[dict[str, str]] = {"username": "durov"}

    # Nothing to recover: the refusal was real, not a lost response.
    client = FakeClient(created=GEngineError("insufficient funds"), fetched=GEngineError("404"))
    import yupay.modules.fulfillment.suppliers.gengine as mod

    async def _mapping_for(_db: Any, *, sku_id: str) -> Any:
        return Mapping()

    monkeypatch.setattr(mod, "_mapping_for", _mapping_for)
    monkeypatch.setattr(GEngineFulfiller, "available", property(lambda _self: True))

    with pytest.raises(FulfillerError, match="insufficient funds"):
        await GEngineFulfiller(client).fulfill(  # type: ignore[arg-type]
            db=_FakeDb(),  # type: ignore[arg-type]
            order=None,  # type: ignore[arg-type]
            item=Item(),  # type: ignore[arg-type]
            idempotency_key="uuid-2",
        )


# ---------- shop failure modes ----------


async def test_a_reservation_that_never_happened_is_an_error() -> None:
    client = FakeShopClient(reserved=GEngineUnavailableError("timeout"))
    f = GEngineFulfiller(client)  # type: ignore[arg-type]

    with pytest.raises(FulfillerError, match="timeout"):
        await f._fulfill_shop(mapping=_Mapping(), item=_ShopItem())  # type: ignore[arg-type]

    assert client.pay_calls == 0


async def test_a_refused_shop_payment_fails_with_the_supplier_s_words() -> None:
    client = FakeShopClient(reserved=_shop("pending"), paid=GEngineError("out of stock"))
    f = GEngineFulfiller(client)  # type: ignore[arg-type]

    result = await f._fulfill_shop(mapping=_Mapping(), item=_ShopItem())  # type: ignore[arg-type]

    assert result.outcome == "failed"
    assert "out of stock" in (result.error or "")


async def test_a_shop_poll_that_cannot_reach_the_supplier_is_raised() -> None:
    client = FakeShopClient(fetched=GEngineUnavailableError("timeout"))
    f = GEngineFulfiller(client)  # type: ignore[arg-type]

    with pytest.raises(FulfillerError):
        await f._shop_status(_Task("7001"))  # type: ignore[arg-type]


async def test_cancel_says_plainly_that_there_is_no_such_endpoint() -> None:
    """A task cancelled here cannot be withdrawn upstream. Saying so beats
    pretending it was, which would leave money spent and nobody looking."""
    from yupay.modules.fulfillment.suppliers.base import FulfillerNotIntegratedError

    with pytest.raises(FulfillerNotIntegratedError):
        await GEngineFulfiller().cancel(db=None, task=_Task("9001"))  # type: ignore[arg-type]


async def test_an_unreachable_supplier_during_create_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Distinct from a refusal: nothing was decided upstream, so the caller is
    told to retry rather than the sale being written off."""

    class Mapping:
        kind = "game"
        external_product_id = "72"
        external_variant_id = None
        quantity = 50

    class Item:
        sku_id = "sku-1"
        qty = 1
        fulfillment_data: ClassVar[dict[str, str]] = {"username": "durov"}

    import yupay.modules.fulfillment.suppliers.gengine as mod

    async def _mapping_for(_db: Any, *, sku_id: str) -> Any:
        return Mapping()

    monkeypatch.setattr(mod, "_mapping_for", _mapping_for)
    monkeypatch.setattr(GEngineFulfiller, "available", property(lambda _self: True))

    client = FakeClient(created=GEngineUnavailableError("connection reset"))
    with pytest.raises(FulfillerError, match="connection reset"):
        await GEngineFulfiller(client).fulfill(  # type: ignore[arg-type]
            db=_FakeDb(),  # type: ignore[arg-type]
            order=None,  # type: ignore[arg-type]
            item=Item(),  # type: ignore[arg-type]
            idempotency_key="uuid-3",
        )


async def test_an_empty_checkout_form_is_refused_before_any_purchase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sending no parameters would have G-Engine credit nobody, having spent
    our money — so the adapter stops first."""

    class Mapping:
        kind = "game"
        external_product_id = "72"
        external_variant_id = None
        quantity = 50

    class Item:
        sku_id = "sku-1"
        fulfillment_data: ClassVar[dict[str, str]] = {}

    import yupay.modules.fulfillment.suppliers.gengine as mod

    async def _mapping_for(_db: Any, *, sku_id: str) -> Any:
        return Mapping()

    monkeypatch.setattr(mod, "_mapping_for", _mapping_for)
    monkeypatch.setattr(GEngineFulfiller, "available", property(lambda _self: True))

    client = FakeClient()
    with pytest.raises(FulfillerError, match="no G-Engine parameters"):
        await GEngineFulfiller(client).fulfill(  # type: ignore[arg-type]
            db=_FakeDb(),  # type: ignore[arg-type]
            order=None,  # type: ignore[arg-type]
            item=Item(),  # type: ignore[arg-type]
            idempotency_key="uuid-4",
        )
    assert client.create_calls == 0


async def test_a_voucher_mapping_routes_to_the_shop_half(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Mapping:
        kind = "voucher"
        external_product_id = "140"
        external_variant_id = "788"

    class Item:
        sku_id = "so2-gold-100"
        qty = 1
        fulfillment_data: ClassVar[dict[str, str]] = {}

    import yupay.modules.fulfillment.suppliers.gengine as mod

    async def _mapping_for(_db: Any, *, sku_id: str) -> Any:
        return Mapping()

    monkeypatch.setattr(mod, "_mapping_for", _mapping_for)
    monkeypatch.setattr(GEngineFulfiller, "available", property(lambda _self: True))

    client = FakeShopClient(reserved=_shop("pending"), paid=_shop("shipped", codes=["SO2-AAA"]))
    result = await GEngineFulfiller(client).fulfill(  # type: ignore[arg-type]
        db=_FakeDb(),  # type: ignore[arg-type]
        order=None,  # type: ignore[arg-type]
        item=Item(),  # type: ignore[arg-type]
        idempotency_key="uuid-5",
    )

    assert result.artifact_kind == "voucher_code"
    assert result.artifact is not None
    assert result.artifact["code"] == "SO2-AAA"


async def test_an_active_mapping_is_returned_as_found() -> None:
    from yupay.modules.fulfillment.suppliers.gengine import _mapping_for

    sentinel = object()

    class _Row:
        def scalar_one_or_none(self) -> object:
            return sentinel

    class _Db:
        async def execute(self, _stmt: Any) -> _Row:
            return _Row()

    assert await _mapping_for(_Db(), sku_id="sku-1") is sentinel  # type: ignore[arg-type]


async def test_the_read_client_is_the_adapter_s_own() -> None:
    """The stock sweep borrows it rather than rebuilding one from settings,
    so credentials and timeouts cannot drift apart."""

    class Client:
        pass

    f = GEngineFulfiller(Client())  # type: ignore[arg-type]
    assert f.client_for_reads() is f._client_override


async def test_a_variable_line_sends_the_amount_that_was_paid_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not the mapping's quantity, and not the checkout form either. The star
    count is re-derived from the money actually charged, so it cannot drift
    from what the customer paid."""
    from decimal import Decimal

    import yupay.modules.fulfillment.suppliers.gengine as mod

    class Mapping:
        kind = "game"
        external_product_id = "72"
        external_variant_id = None
        quantity = 1  # the package default, and wrong for this line

    class Sku:
        variable_amount = True
        units_per_usd = Decimal("64.705882")

    class Item:
        sku_id = "sku-stars-any"
        unit_price_usd = Decimal("7.727273")  # 500 stars
        fulfillment_data: ClassVar[dict[str, str]] = {"username": "durov"}

    class Result:
        def scalar_one_or_none(self) -> Sku:
            return Sku()

    class Db:
        async def execute(self, _stmt: Any) -> Result:
            return Result()

    sent: dict[str, Any] = {}

    class Client:
        async def create_recharge_order(self, **kw: Any) -> GEngineOrder:
            sent.update(kw)
            return _order("pending")

    async def _mapping_for(_db: Any, *, sku_id: str) -> Any:
        return Mapping()

    monkeypatch.setattr(mod, "_mapping_for", _mapping_for)
    monkeypatch.setattr(GEngineFulfiller, "available", property(lambda _self: True))

    await GEngineFulfiller(Client()).fulfill(  # type: ignore[arg-type]
        db=Db(),  # type: ignore[arg-type]
        order=None,  # type: ignore[arg-type]
        item=Item(),  # type: ignore[arg-type]
        idempotency_key="uuid-var",
    )

    assert sent["params"]["Quantity"] == "500"


async def test_a_money_denominated_variable_sku_sends_its_face_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Steam wallet in USD — G-Engine service 2, ``unfixed``, ``Quantity: Float``.

    The SKU is ``variable_amount`` with no ``units_per_usd``: it is denominated
    in money itself, so the quantity *is* the amount the customer chose, cents
    kept. Before this branch the line fell through to ``item.qty *
    mapping.quantity`` and a $37.50 top-up would have been ordered as ``1``.
    """

    class Mapping:
        kind = "game"
        external_product_id = "2"
        external_variant_id = None
        quantity = 1

    class Item:
        sku_id = "sku-steam"
        qty = 1
        unit_price_usd = Decimal("37.50")
        fulfillment_data: ClassVar[dict[str, str]] = {"steam_login": "jama"}

    class Sku:
        variable_amount = True
        units_per_usd = None
        amount_unit = None

    sent = await _sent_params(monkeypatch, mapping=Mapping(), item=Item(), sku=Sku())

    assert sent["params"] == {"Account": "jama", "Quantity": "37.50"}
    assert sent["denomination_id"] is None


async def test_a_money_denominated_line_of_nothing_is_refused() -> None:
    from yupay.modules.fulfillment.suppliers.gengine import _quantity_for

    class Mapping:
        quantity = 1

    class Item:
        sku_id = "sku-steam"
        qty = 1
        unit_price_usd = Decimal("0.004")

    class Sku:
        variable_amount = True
        units_per_usd = None

    with pytest.raises(FulfillerError, match="resolves to nothing"):
        await _quantity_for(_FakeDb(Sku()), item=Item(), mapping=Mapping())  # type: ignore[arg-type]
