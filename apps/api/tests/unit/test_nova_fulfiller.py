"""Unit tests for the NOVA fulfiller.

The money grading is the point of this file. NOVA charges on create ("Balance
is charged immediately"), so the difference between "they refused the request"
and "the call broke" is the difference between our money being here and our
money being unaccounted for.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from yupay.modules.fulfillment.suppliers.base import (
    FulfillerError,
    FulfillerNotIntegratedError,
    MoneyOutcome,
)
from yupay.modules.fulfillment.suppliers.nova import (
    FRAGMENT_PREMIUM,
    FRAGMENT_STARS,
    STEAM_SENTINEL,
    NovaFulfiller,
    _mapping_for,
)
from yupay.modules.fulfillment.suppliers.nova_adopt import ADOPT_WINDOW_MINUTES
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
        offers: dict[str, Any] | None = None,
    ):
        self._order = order or {}
        self._steam_order = steam_order if steam_order is not None else (order or {})
        self._raises = raises
        # No declaration by default, so every test that is not about field
        # shapes keeps exercising the legacy rename — which is still the
        # fallback in production when NOVA will not answer.
        self._offers = offers or {}
        self.calls: list[dict[str, Any]] = []
        self.steam_calls: list[dict[str, Any]] = []
        self.fragment_calls: list[tuple[str, dict[str, Any]]] = []
        self.giftcard_calls: list[dict[str, Any]] = []

    async def get_offers(self, category_id: str) -> dict[str, Any]:
        return self._offers

    async def create_topup_order(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._order

    async def get_balance(self) -> dict[str, Any]:
        """The read the low-balance path makes to say whose money is missing."""
        return {"ok": True, "balance": "112.7547", "currency": "USD"}

    async def create_steam_order(self, **kwargs: Any) -> dict[str, Any]:
        self.steam_calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._steam_order

    async def create_fragment_stars_order(self, **kwargs: Any) -> dict[str, Any]:
        self.fragment_calls.append(("stars", kwargs))
        if self._raises is not None:
            raise self._raises
        return self._order

    async def create_fragment_premium_order(self, **kwargs: Any) -> dict[str, Any]:
        self.fragment_calls.append(("premium", kwargs))
        if self._raises is not None:
            raise self._raises
        return self._order

    async def create_giftcard_order(self, **kwargs: Any) -> dict[str, Any]:
        self.giftcard_calls.append(kwargs)
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


async def test_a_lost_create_response_parks_instead_of_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NOVA charges on create, so a lost response is the one moment we must
    not decide anything.

    This used to raise with ``UNKNOWN``, which was honest about the money and
    wrong about the outcome: it failed the task, and a failed task invites a
    human to retry it and buy a second time. Production order 01a0cd88 is the
    case — NOVA created the order eight seconds *after* our timeout and
    delivered it, while our books said failed.

    Parking keeps the task in flight so ``check_status`` can go looking
    (``nova_adopt``). ``money_outcome`` is ``None`` because an ``in_progress``
    result is not a failure and the saga refuses a verdict on one — the money
    question is answered when the order is found or the window closes.
    """
    client = _FakeClient(raises=NovaUnavailableError("ReadTimeout"))

    result = await _fulfill(client, monkeypatch)

    assert result.outcome == "in_progress"
    assert result.external_order_id is None
    assert result.money_outcome is None
    # The transport reason survives, and since `transport_error_text` it is
    # no longer the empty string it was on the night this happened.
    assert "ReadTimeout" in str(result.extra_metadata.get("nova_create_unresolved"))


async def test_the_order_is_built_from_novas_own_field_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Order 01a0ce52, the other way round.

    Honkai Star Rail declares ``server`` as a select of lower-case values; we
    used to send ``server_id`` with our capitalised one and were refused with
    ``Field "server" is required.`` Now the payload is built from what they
    declare, so the key and the value are both theirs.
    """
    client = _FakeClient(
        order={"id": "ord-1", "status": "completed"},
        offers={
            "fields": [
                {"key": "player_id", "type": "text"},
                {
                    "key": "server",
                    "type": "select",
                    "options": [
                        {"label": "Europe", "value": "europe"},
                        {"label": "Asia", "value": "asia"},
                    ],
                },
            ]
        },
    )

    await _fulfill(
        client,
        monkeypatch,
        item=_item(fulfillment_data={"player_id": "801234567", "server": "Europe"}),
        mapping=_mapping(
            external_product_id="honkai_star_rail_global",
            external_variant_id="express_supply_pass",
        ),
    )

    assert client.calls[0]["fields"] == {"player_id": "801234567", "server": "europe"}


async def test_a_silent_spec_call_falls_back_rather_than_refusing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probe is optional; the sale is not.

    With no declaration the old rename still runs, which is exactly right for
    the categories it always suited — Mobile Legends among them.
    """
    client = _FakeClient(order={"id": "ord-1", "status": "completed"})

    await _fulfill(
        client,
        monkeypatch,
        item=_item(fulfillment_data={"player_id": "123456789", "server": "12345"}),
        mapping=_mapping(
            external_product_id="mobile_legends_ru", external_variant_id="86_diamonds"
        ),
    )

    assert client.calls[0]["fields"] == {"player_id": "123456789", "server_id": "12345"}


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


class _NoLineDB:
    """A session whose every lookup comes back empty.

    Enough for the adoption path: with no order line there is nothing to
    rebuild a search key from, so the probe is skipped and the task falls
    through to the wait-or-give-up decision these two tests are about. A task
    whose line has been deleted behaves exactly this way in production.
    """

    async def execute(self, *_args: Any, **_kw: Any) -> Any:
        return SimpleNamespace(scalar_one_or_none=lambda: None, scalars=lambda: iter(()))


async def test_check_status_without_an_id_looks_for_the_order_then_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An id-less task has work to do before it can say anything.

    It stays ``in_progress`` as before — but now because the search came back
    empty and the window is still open, not because nobody looked.
    """
    task = SimpleNamespace(
        id="task-1",
        order_item_id="item-1",
        external_order_id=None,
        extra_metadata={},
        created_at=datetime.now(UTC),
    )
    status = await _fulfiller(_FakeClient(), monkeypatch).check_status(
        db=cast(Any, _NoLineDB()),
        task=task,  # type: ignore[arg-type]
    )
    assert status.outcome == "in_progress"


async def test_an_id_less_task_gives_up_once_the_window_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A landed create is findable within minutes, so its absence after the
    window is evidence the create never happened.

    Evidence, not proof — the money stays ``UNKNOWN`` rather than
    ``RETURNED``, because a wrong ``RETURNED`` refunds a customer who already
    has their goods.
    """
    task = SimpleNamespace(
        id="task-1",
        order_item_id="item-1",
        external_order_id=None,
        extra_metadata={},
        created_at=datetime.now(UTC) - timedelta(minutes=ADOPT_WINDOW_MINUTES + 1),
    )

    with pytest.raises(FulfillerError) as excinfo:
        await _fulfiller(_FakeClient(), monkeypatch).check_status(
            db=cast(Any, _NoLineDB()),
            task=task,  # type: ignore[arg-type]
        )

    assert excinfo.value.money_outcome is MoneyOutcome.UNKNOWN
    assert "nova.md" in str(excinfo.value)


class _LineDB:
    """A session that answers the two lookups adoption makes: the order line,
    then its NOVA mapping. Enough to rebuild a search key without a database.
    """

    def __init__(self, item: Any, mapping: Any) -> None:
        self._answers = [item, mapping]

    async def execute(self, *_args: Any, **_kw: Any) -> Any:
        answer = self._answers.pop(0) if self._answers else None
        return SimpleNamespace(scalar_one_or_none=lambda: answer)


class _AdoptClient(_FakeClient):
    """A client whose order list carries one finished order."""

    def __init__(self, orders: list[dict[str, Any]], **kw: Any) -> None:
        super().__init__(**kw)
        self._orders = orders

    async def list_orders(self, *, limit: int = 50, page: int = 1) -> list[dict[str, Any]]:
        return self._orders


async def test_an_id_less_task_adopts_the_order_it_paid_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The feature, end to end.

    The create's response was lost, so the task has no id. The poll finds the
    order NOVA made anyway, reports its real state, and records the id so the
    next poll goes straight to it instead of searching again.
    """
    started = datetime.now(UTC) - timedelta(seconds=30)
    task = SimpleNamespace(
        id="task-1",
        order_item_id="item-1",
        external_order_id=None,
        extra_metadata={},
        created_at=started,
    )
    client = _AdoptClient(
        [
            {
                "id": "ord-1525578",
                "kind": "topup",
                "category_id": "free_fire_cis",
                "offer_id": "110_diamonds",
                "fields": {"player_id": "10619597246"},
                "status": "completed",
                "created_at": datetime.now(UTC).isoformat(),
            }
        ]
    )
    db = _LineDB(
        item=SimpleNamespace(sku_id="sku-1", qty=1, fulfillment_data={"player_id": "10619597246"}),
        mapping=SimpleNamespace(
            kind="game",
            external_product_id="free_fire_cis",
            external_variant_id="110_diamonds",
        ),
    )

    status = await _fulfiller(client, monkeypatch).check_status(
        db=cast(Any, db),
        task=cast(Any, task),
    )

    assert status.outcome == "succeeded"
    assert status.extra_metadata["nova_order_id"] == "ord-1525578"
    assert status.extra_metadata["nova_adopted"] is True


async def test_an_already_adopted_id_is_not_searched_for_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The id lives in metadata because the reconciler merges that and does
    not move it into the ``external_order_id`` column — so the next poll has
    to read both or it would search forever."""
    _games_task(monkeypatch)
    task = SimpleNamespace(
        id="task-1",
        order_item_id="item-1",
        external_order_id=None,
        extra_metadata={"nova_order_id": "ord-1525578"},
        created_at=datetime.now(UTC),
    )
    client = _FakeClient(order={"id": "ord-1525578", "status": "completed"})

    status = await _fulfiller(client, monkeypatch).check_status(
        db=cast(Any, _NoLineDB()),
        task=cast(Any, task),
    )

    assert status.outcome == "succeeded"


async def test_check_status_that_cannot_read_says_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _games_task(monkeypatch)
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


def _games_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """`check_status` now asks which of NOVA's two APIs owns the order, which
    means a session. These older tests hand it `db=None`, so the question is
    answered directly instead — they are about reading a v2 order, not about
    the namespace lookup, which has its own tests below."""
    import yupay.modules.fulfillment.suppliers.nova as mod

    async def _no(_db: Any, _task: Any) -> bool:
        return False

    monkeypatch.setattr(mod, "_is_fragment_task", _no)


async def test_check_status_reads_a_finished_order(monkeypatch: pytest.MonkeyPatch) -> None:
    _games_task(monkeypatch)
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
    """Stands in for the session ``_mapping_for`` uses to look the SKU up.

    **It answers whatever it was handed, whatever was asked.** That is fine
    for "does a missing row raise" and useless for "does the WHERE clause
    select the right rows" — and the second question is the one that bit:
    ``_mapping_for`` filtered ``kind == "game"``, which made the gift-card
    branch in ``fulfill`` unreachable, and no test here could see it because
    none of them run SQL. The filter is pinned against a real database in
    ``tests/integration/test_nova_mapping_lookup.py``.
    """

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


async def test_a_lost_steam_create_parks_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every create spends, so every one of them parks — not just top-ups."""
    client = _FakeClient(raises=NovaUnavailableError("ReadTimeout"))

    result = await _fulfill(
        client,
        monkeypatch,
        item=_item(fulfillment_data={"steam_login": "someone"}),
        mapping=_mapping(external_product_id=STEAM_SENTINEL, external_variant_id=""),
    )

    assert result.outcome == "in_progress"
    assert result.money_outcome is None


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


@pytest.mark.parametrize(
    "sentence",
    [
        "Insufficient internal balance",  # their real one, observed 2026-09-18
        "insufficient balance",
        "not enough balance",
        "Insufficient funds",
        "your balance is too low",
    ],
)
async def test_every_way_they_say_top_up_your_wallet_is_a_stall(
    monkeypatch: pytest.MonkeyPatch, sentence: str
) -> None:
    """The refusal that must never hard-fail an order.

    Their real sentence is "Insufficient internal balance", and the phrase list
    this started with — copied from Waxpeer — did not contain it: "insufficient
    balance" is not a substring of "insufficient internal balance". So the first
    Free Fire order to outrun the wallet would have been graded RETURNED and
    failed, blocking a customer, where this path exists to park the order and
    page ops instead.
    """
    client = _FakeClient(raises=NovaError(sentence, status=400))
    result = await _fulfill(client, monkeypatch)
    assert result.error == LOW_BALANCE_ERROR
    assert result.money_outcome is None


async def test_an_ordinary_refusal_is_still_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pair rule stays narrow: a message has to be about a balance AND
    about there not being enough of it."""
    client = _FakeClient(raises=NovaError("offer not available in this region", status=400))
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfill(client, monkeypatch)
    assert excinfo.value.money_outcome is MoneyOutcome.RETURNED


# ---------------------------------------------------------------------------
# Whose balance is short
# ---------------------------------------------------------------------------


async def test_their_service_shortfall_is_not_reported_as_our_empty_wallet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NOVA's own dashboard refused a $19 Steam top-up on 2026-09-20 with
    "Service balance is insufficient to complete this order" while showing a
    $112.75 wallet. Both that and "Insufficient internal balance" park the
    order; only the second is anything the operator can act on, and telling
    them to top up a funded wallet is how an evening gets spent on the wrong
    question."""
    client = _FakeClient(
        raises=NovaError("Service balance is insufficient to complete this order", status=400)
    )
    result = await _fulfill(client, monkeypatch)

    assert result.error == LOW_BALANCE_ERROR
    assert result.extra_metadata["shortfall"] == "supplier"
    assert "Service balance" in result.extra_metadata["supplier_message"]


async def test_our_empty_wallet_still_reads_as_ours(monkeypatch: pytest.MonkeyPatch) -> None:
    """Their other sentence, confirmed 2026-09-18 against a $9.10 wallet."""
    client = _FakeClient(raises=NovaError("Insufficient internal balance", status=400))
    result = await _fulfill(client, monkeypatch)

    assert result.error == LOW_BALANCE_ERROR
    assert result.extra_metadata["shortfall"] == "ours"


async def test_the_refusal_carries_their_sentence_and_our_balance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both used to be thrown away, which left the alert printing "$?" and
    nobody able to check whether the grading was even right."""
    client = _FakeClient(raises=NovaError("Insufficient internal balance", status=400))
    result = await _fulfill(client, monkeypatch)

    assert result.extra_metadata["supplier_message"] == "Insufficient internal balance"
    assert result.extra_metadata["current_balance"] == "112.7547"


# ---------------------------------------------------------------------------
# Fragment: Telegram Stars and Premium
# ---------------------------------------------------------------------------


def _fragment_item(**over: Any) -> Any:
    base = {
        "sku_id": "sku-tg",
        "qty": 1,
        "fulfillment_data": {"username": "@someone"},
        "unit_price_usd": Decimal("0.93"),
    }
    base.update(over)
    return SimpleNamespace(**base)


def _patch_quantity(monkeypatch: pytest.MonkeyPatch, value: int) -> list[tuple[Any, Any]]:
    """Replace the shared counter and record what NOVA handed it.

    The point of the assertion is not the number — `quantity_for` has its own
    tests — it is that NOVA *asks* rather than counting Stars itself.
    """
    import yupay.modules.fulfillment.suppliers.nova as mod

    seen: list[tuple[Any, Any]] = []

    async def _fake(_db: Any, *, item: Any, mapping: Any) -> int:
        seen.append((item, mapping))
        return value

    monkeypatch.setattr(mod, "quantity_for", _fake)
    return seen


async def test_the_alert_can_say_how_much_was_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The right-hand half of "Баланс: $X · Нужно: $Y".

    Until 2026-09-22 NOVA filled in only the balance, so an operator learned
    the wallet was short without learning by how much. ``required`` comes from
    the same place G2B's pre-flight takes it: ``Sku.cost_usdt``, per unit,
    multiplied by the line quantity.
    """
    client = _FakeClient(raises=NovaError("Insufficient internal balance", status=400))
    item = _item(sku=SimpleNamespace(cost_usdt=Decimal("3.75")))

    result = await _fulfill(client, monkeypatch, item=item)

    assert result.error == LOW_BALANCE_ERROR
    assert result.extra_metadata["required"] == "3.75"


@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
async def test_the_needed_figure_multiplies_out_a_stars_line() -> None:
    """``qty`` is the star count on a Fragment line, and cost is per star.

    Tested against the helper rather than through ``fulfill`` because every
    other NOVA path refuses ``qty > 1`` outright — one call buys one offer —
    so Stars is the only place the multiplication can ever matter.
    """
    item = _item(qty=5000, sku=SimpleNamespace(cost_usdt=Decimal("0.0154")))

    assert NovaFulfiller._required_or_none(item) == "77.00"


async def test_a_line_without_a_loaded_sku_still_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing number is a worse alert; an exception would be a worse outcome."""
    client = _FakeClient(raises=NovaError("Insufficient internal balance", status=400))

    result = await _fulfill(client, monkeypatch)

    assert result.error == LOW_BALANCE_ERROR
    assert result.extra_metadata.get("required") is None


async def test_a_stars_line_buys_the_count_the_shared_counter_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _patch_quantity(monkeypatch, 5000)
    client = _FakeClient(order={"id": "frg_1", "status": "PROCESSING"})
    item = _fragment_item(qty=5000)

    result = await _fulfill(
        client,
        monkeypatch,
        item=item,
        mapping=_mapping(external_product_id="fragment-stars", external_variant_id=None),
    )

    kind, kwargs = client.fragment_calls[0]
    assert kind == "stars"
    assert kwargs["stars_amount"] == 5000
    assert kwargs["username"] == "@someone"
    # It delegated, with this order's own row — not a count of its own.
    assert seen
    assert seen[0][0] is item
    assert result.outcome == "in_progress"


async def test_a_premium_line_takes_its_months_from_the_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(order={"id": "frg_2", "status": "SUCCESS"})

    result = await _fulfill(
        client,
        monkeypatch,
        item=_fragment_item(unit_price_usd=Decimal("14.77")),
        mapping=_mapping(external_product_id="fragment-premium", external_variant_id="12"),
    )

    kind, kwargs = client.fragment_calls[0]
    assert kind == "premium"
    assert kwargs["months"] == 12
    assert result.outcome == "succeeded"


async def test_a_premium_mapping_without_months_is_refused_before_any_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three Premium products differ only by their month count, so a mapping
    that lost it would otherwise gift whatever NOVA defaults to."""
    client = _FakeClient(order={"id": "frg_3", "status": "SUCCESS"})

    with pytest.raises(FulfillerError) as err:
        await _fulfill(
            client,
            monkeypatch,
            item=_fragment_item(),
            mapping=_mapping(external_product_id="fragment-premium", external_variant_id=None),
        )

    assert client.fragment_calls == []
    assert err.value.money_outcome == MoneyOutcome.RETURNED


async def test_a_missing_username_is_refused_before_any_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_quantity(monkeypatch, 50)
    client = _FakeClient(order={"id": "frg_4", "status": "SUCCESS"})

    with pytest.raises(FulfillerError) as err:
        await _fulfill(
            client,
            monkeypatch,
            item=_fragment_item(fulfillment_data={}),
            mapping=_mapping(external_product_id="fragment-stars", external_variant_id=None),
        )

    assert client.fragment_calls == []
    assert err.value.money_outcome == MoneyOutcome.RETURNED


async def test_the_older_field_name_still_names_the_recipient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G-Engine's mapper accepts `telegram_username` beside `username`; a line
    carrying the older one must not fail here."""
    _patch_quantity(monkeypatch, 50)
    client = _FakeClient(order={"id": "frg_5", "status": "PROCESSING"})

    await _fulfill(
        client,
        monkeypatch,
        item=_fragment_item(fulfillment_data={"telegram_username": "@other"}),
        mapping=_mapping(external_product_id="fragment-stars", external_variant_id=None),
    )

    assert client.fragment_calls[0][1]["username"] == "@other"


async def test_a_dry_run_answer_is_a_failure_that_cost_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Their sandbox returns a complete-looking order that bought nothing.
    Read as an unknown word it would sit in-flight waiting for a delivery that
    is never coming."""
    _patch_quantity(monkeypatch, 50)
    client = _FakeClient(order={"id": "frg_6", "status": "DRY_RUN"})

    result = await _fulfill(
        client,
        monkeypatch,
        item=_fragment_item(),
        mapping=_mapping(external_product_id="fragment-stars", external_variant_id=None),
    )

    assert result.outcome == "failed"
    assert result.money_outcome == MoneyOutcome.RETURNED
    assert "dry-run" in (result.error or "")


async def test_the_fragment_charge_is_recorded_from_their_own_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fragment calls it `customer_amount_usd`; the v2 orders call it
    `chargedUsd`. Miss it and a Telegram line has no real cost basis."""
    _patch_quantity(monkeypatch, 1000)
    client = _FakeClient(
        order={"id": "frg_7", "status": "SUCCESS", "customer_amount_usd": "15.225000"}
    )

    result = await _fulfill(
        client,
        monkeypatch,
        item=_fragment_item(qty=1000),
        mapping=_mapping(external_product_id="fragment-stars", external_variant_id=None),
    )

    assert result.extra_metadata.get("supplier_charged_usd") == "15.225000"


async def test_a_fragment_order_is_polled_on_the_fragment_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`/api/v2/orders/{id}` does not know a Fragment order, and asking it
    anyway does not 404: the answer comes back without the `ok` envelope
    `_request` demands, so a delivered order reported itself as
    `nova HTTP 200` and the task sat in processing while the customer already
    had their Stars. Observed in production 2026-09-20."""
    import yupay.modules.fulfillment.suppliers.nova as mod

    asked: list[str] = []

    class _Client:
        async def get_order(self, order_id: str) -> dict[str, Any]:
            asked.append("v2")
            raise AssertionError("a Fragment order must not be polled on /api/v2/orders")

        async def get_fragment_order(self, order_id: str) -> dict[str, Any]:
            asked.append("fragment")
            return {"id": order_id, "status": "SUCCESS"}

    async def _is_fragment(_db: Any, _task: Any) -> bool:
        return True

    monkeypatch.setattr(mod, "_is_fragment_task", _is_fragment)
    fulfiller = _fulfiller(_Client(), monkeypatch)  # type: ignore[arg-type]

    status = await fulfiller.check_status(
        db=None,  # type: ignore[arg-type]
        task=SimpleNamespace(external_order_id="frg-9", order_item_id="oi-1"),  # type: ignore[arg-type]
    )

    assert asked == ["fragment"]
    assert status.outcome == "succeeded"


async def test_a_games_order_still_polls_the_v2_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fix must not move every other NOVA order onto Fragment."""
    import yupay.modules.fulfillment.suppliers.nova as mod

    asked: list[str] = []

    class _Client:
        async def get_order(self, order_id: str) -> dict[str, Any]:
            asked.append("v2")
            return {"id": order_id, "status": "completed"}

        async def get_fragment_order(self, order_id: str) -> dict[str, Any]:
            asked.append("fragment")
            raise AssertionError("a games order must not be polled on Fragment")

    async def _is_fragment(_db: Any, _task: Any) -> bool:
        return False

    monkeypatch.setattr(mod, "_is_fragment_task", _is_fragment)
    fulfiller = _fulfiller(_Client(), monkeypatch)  # type: ignore[arg-type]

    status = await fulfiller.check_status(
        db=None,  # type: ignore[arg-type]
        task=SimpleNamespace(external_order_id="1770085", order_item_id="oi-2"),  # type: ignore[arg-type]
    )

    assert asked == ["v2"]
    assert status.outcome == "succeeded"


# ---------- gift cards ----------
#
# NOVA sells Roblox (and 575 other) gift cards through a second endpoint that
# takes a category, a denomination and a count — and no player fields, because
# a card has nobody to credit. Until this path existed the adapter could only
# call `/topups/order`, so a voucher mapping refused every order with "no nova
# fields could be built": mapping a card to NOVA would have looked like it
# worked and failed at purchase.
#
# Shapes below are the first live order (2026-09-21, `roblox_global` /
# `50_robux`, $0.87873): the create answers `created` with `cards: []` and the
# money already gone; the codes appear on the order about a second later.


def _card_mapping(**over: Any) -> Any:
    base: dict[str, Any] = {
        "kind": "voucher",
        "external_product_id": "roblox_global",
        "external_variant_id": "50_robux",
        "quantity": 1,
    }
    base.update(over)
    return _mapping(**base)


def _card_item(**over: Any) -> Any:
    # No `fulfillment_data`: a gift card has no player id, and the default
    # path's `_fields_from` would have refused this order outright.
    return _item(fulfillment_data={}, **over)


async def test_a_card_order_goes_to_the_giftcard_endpoint_with_no_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(order={"id": "ord-1", "kind": "gift_card", "status": "created"})

    await _fulfill(client, monkeypatch, item=_card_item(), mapping=_card_mapping())

    assert client.calls == [], "a card must not go to the top-ups endpoint"
    assert len(client.giftcard_calls) == 1
    call = client.giftcard_calls[0]
    assert call["category_id"] == "roblox_global"
    assert call["card_id"] == "50_robux"
    assert call["quantity"] == 1
    assert "fields" not in call


async def test_buying_several_cards_is_one_call_with_a_quantity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Their endpoint takes 1-100, so the top-up guard must not reach a card.

    That guard sits one line below the dispatch for exactly this reason: it is
    right for a top-up, where one call buys one offer, and would refuse every
    multi-card purchase.
    """
    client = _FakeClient(order={"id": "ord-1", "kind": "gift_card", "status": "created"})

    await _fulfill(client, monkeypatch, item=_card_item(qty=3), mapping=_card_mapping())

    assert client.giftcard_calls[0]["quantity"] == 3


async def test_a_completed_card_order_hands_over_the_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(
        order={
            "id": "ord-1481455",
            "kind": "gift_card",
            "category_id": "roblox_global",
            "status": "completed",
            "cards": ["AAAA-BBBB-CCCC", "DDDD-EEEE-FFFF"],
        }
    )

    result = await _fulfill(client, monkeypatch, item=_card_item(qty=2), mapping=_card_mapping())

    assert result.outcome == "succeeded"
    assert result.artifact_kind == "voucher_code"
    # Same shape G2B's voucher artifact uses, so a delivery reads identically
    # whichever supplier filled it.
    assert result.artifact["code"] == "AAAA-BBBB-CCCC"
    assert result.artifact["codes"] == ["AAAA-BBBB-CCCC", "DDDD-EEEE-FFFF"]
    assert result.artifact["source"] == "nova"
    assert result.artifact["external_order_id"] == "ord-1481455"


async def test_completed_with_no_codes_fails_loudly_instead_of_succeeding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Charged, marked complete, nothing to hand over.

    Graded a success this would close the order with an empty code, and the
    customer would be the one to discover it. UNKNOWN money, because the
    charge did land.
    """
    client = _FakeClient(order={"id": "ord-1", "kind": "gift_card", "status": "completed"})

    with pytest.raises(FulfillerError) as exc:
        await _fulfill(client, monkeypatch, item=_card_item(), mapping=_card_mapping())

    assert exc.value.money_outcome is MoneyOutcome.UNKNOWN


async def test_a_created_card_order_waits_for_the_reconciler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Their create answers `created` with the money already gone — the codes
    arrive on the order a moment later, which is `check_status`'s job."""
    client = _FakeClient(order={"id": "ord-1", "kind": "gift_card", "status": "created"})

    result = await _fulfill(client, monkeypatch, item=_card_item(), mapping=_card_mapping())

    assert result.outcome == "in_progress"
    assert result.external_order_id == "ord-1"


async def test_a_card_mapping_without_a_denomination_is_refused_before_paying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(order={"id": "ord-1", "kind": "gift_card", "status": "created"})

    with pytest.raises(FulfillerError) as exc:
        await _fulfill(
            client,
            monkeypatch,
            item=_card_item(),
            mapping=_card_mapping(external_variant_id=""),
        )

    assert exc.value.money_outcome is MoneyOutcome.RETURNED
    assert client.giftcard_calls == []


async def test_a_top_up_is_still_a_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gift-card branch keys on the mapping kind, so nothing else moved."""
    result = await _fulfill(_FakeClient(order={"id": "ord_1", "status": "completed"}), monkeypatch)

    assert result.artifact_kind == "topup_receipt"


@pytest.mark.parametrize(
    ("mapping_kind", "category", "variant", "expected_kind"),
    [
        ("voucher", "roblox_global", "50_robux", "gift_card"),
        ("game", STEAM_SENTINEL, "", "steam_topup"),
        ("game", FRAGMENT_STARS, "", "STARS"),
        ("game", FRAGMENT_PREMIUM, "3", "PREMIUM"),
    ],
)
async def test_every_order_kind_can_be_searched_for(
    monkeypatch: pytest.MonkeyPatch,
    mapping_kind: str,
    category: str,
    variant: str,
    expected_kind: str,
) -> None:
    """A lost create is possible on all four paths, so all four must be
    findable — the top-up is only the one that happened first.

    Asserted through ``check_status``: with nothing in NOVA's list the task
    stays in flight, which is the honest answer and the one that proves a
    usable key was built. An unusable key would have skipped the search
    entirely and looked identical from outside, which is why the client
    records whether it was asked.
    """
    task = SimpleNamespace(
        id="task-1",
        order_item_id="item-1",
        external_order_id=None,
        extra_metadata={},
        created_at=datetime.now(UTC),
    )
    client = _AdoptClient([])
    db = _LineDB(
        item=SimpleNamespace(
            sku_id="sku-1",
            qty=1,
            fulfillment_data={"player_id": "1", "steam_login": "someone", "username": "@who"},
        ),
        mapping=SimpleNamespace(
            kind=mapping_kind, external_product_id=category, external_variant_id=variant
        ),
    )

    status = await _fulfiller(client, monkeypatch).check_status(
        db=cast(Any, db), task=cast(Any, task)
    )

    assert status.outcome == "in_progress"


async def test_a_task_whose_line_is_gone_cannot_be_searched_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No line, no key, no search — and the task waits rather than claiming
    anything about an order nobody can describe."""
    task = SimpleNamespace(
        id="task-1",
        order_item_id="item-1",
        external_order_id=None,
        extra_metadata={},
        created_at=datetime.now(UTC),
    )

    status = await _fulfiller(_AdoptClient([]), monkeypatch).check_status(
        db=cast(Any, _NoLineDB()), task=cast(Any, task)
    )

    assert status.outcome == "in_progress"
