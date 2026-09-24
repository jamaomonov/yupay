"""Unit tests for the FazerCards fulfiller.

The money grading is the point of this file, as it is for NOVA's twin. They
charge on create, so the difference between "they refused the request" and
"the call broke" is the difference between our money being here and our money
being unaccounted for.

What is tested here is only what is **fzr's own**. The shared machinery — the
grader's status table, the adoption matcher, the field builder — is covered
once, against NOVA, in ``test_nova_fulfiller``, ``test_panel_adopt`` and
``test_panel_fields``. Re-asserting it here would test the same code twice and
say nothing about this adapter.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from yupay.modules.fulfillment.suppliers.base import (
    FulfillerError,
    FulfillerNotIntegratedError,
    MoneyOutcome,
)
from yupay.modules.fulfillment.suppliers.fzr import (
    STEAM_SENTINEL,
    FzrFulfiller,
    _adopt_key_for,
    _mapping_for,
)
from yupay.modules.fulfillment.suppliers.fzr_client import (
    SUBSCRIPTION_INACTIVE,
    FzrError,
    FzrUnavailableError,
)
from yupay.modules.fulfillment.suppliers.panel_grading import LOW_BALANCE_ERROR

pytestmark = pytest.mark.asyncio


class _FakeClient:
    """Records what was called, so "did it order at all" is answerable."""

    slug = "fzr"

    def __init__(
        self,
        *,
        order: dict[str, Any] | None = None,
        raises: Exception | None = None,
        offers: dict[str, Any] | None = None,
        orders: list[dict[str, Any]] | None = None,
        # `Any`, not `dict`: the balance probe has to be drivable into a
        # failure, and that is the whole point of the test that pins it.
        balance: Any = None,
        subscription: dict[str, Any] | None = None,
    ) -> None:
        self._order = order or {}
        self._raises = raises
        # No declaration by default, so tests that are not about field shapes
        # keep exercising the legacy rename — still the production fallback.
        self._offers = offers or {}
        self._orders = orders or []
        self._balance = balance if balance is not None else {"balance": "9.10", "currency": "USD"}
        self._subscription = subscription
        self.calls: list[dict[str, Any]] = []
        self.steam_calls: list[dict[str, Any]] = []
        self.giftcard_calls: list[dict[str, Any]] = []

    async def get_offers(self, category_id: str) -> dict[str, Any]:
        return self._offers

    async def create_topup_order(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._order

    async def create_giftcard_order(self, **kwargs: Any) -> dict[str, Any]:
        self.giftcard_calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._order

    async def create_steam_order(self, **kwargs: Any) -> dict[str, Any]:
        self.steam_calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._order

    async def get_balance(self) -> dict[str, Any]:
        if isinstance(self._balance, Exception):
            raise self._balance
        return self._balance

    async def get_subscription(self) -> dict[str, Any]:
        if self._subscription is None:
            raise FzrError("no subscription endpoint here")
        return self._subscription

    async def get_order(self, order_id: str) -> dict[str, Any]:
        if self._raises is not None:
            raise self._raises
        return self._order

    async def list_orders(self, *, limit: int = 50, page: int = 1) -> list[dict[str, Any]]:
        return self._orders


def _mapping(**over: Any) -> Any:
    base = {
        "kind": "game",
        "external_product_id": "free_fire_cis",
        "external_variant_id": "572_diamonds",
        "quantity": 1,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _item(**over: Any) -> Any:
    base = {
        "sku_id": "sku-1",
        "qty": 1,
        "fulfillment_data": {"player_id": "1313232551", "server": "6618"},
        "unit_price_usd": Decimal("10"),
        "sku": SimpleNamespace(cost_usdt=Decimal("3.84")),
    }
    base.update(over)
    return SimpleNamespace(**base)


def _fulfiller(
    client: _FakeClient, monkeypatch: pytest.MonkeyPatch, *, available: bool = True
) -> FzrFulfiller:
    """The adapter with its key faked in.

    ``available`` reads settings, and settings are cached for the process, so
    the house pattern patches the property rather than the environment.
    """
    monkeypatch.setattr(FzrFulfiller, "available", property(lambda _self: available))
    return FzrFulfiller(client=client)  # type: ignore[arg-type]


async def _fulfill(
    client: _FakeClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    item: Any = None,
    mapping: Any = None,
    available: bool = True,
) -> Any:
    """Run ``fulfill`` with the mapping lookup stubbed, so ``db`` is never touched."""
    import yupay.modules.fulfillment.suppliers.fzr as mod

    row = mapping if mapping is not None else _mapping()

    async def _stub(_db: Any, *, sku_id: str) -> Any:
        return row

    monkeypatch.setattr(mod, "_mapping_for", _stub)
    return await _fulfiller(client, monkeypatch, available=available).fulfill(
        db=None,  # type: ignore[arg-type]
        order=SimpleNamespace(),  # type: ignore[arg-type]
        item=item if item is not None else _item(),
        idempotency_key="task-42",
    )


# ---------- the happy path ----------


async def test_a_created_order_is_in_progress_and_keeps_its_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(order={"id": "ord-9002", "kind": "topup", "status": "processing"})
    result = await _fulfill(client, monkeypatch)

    assert result.outcome == "in_progress"
    assert result.external_order_id == "ord-9002"
    assert result.money_outcome is None
    # Our own field names are renamed to theirs: `server` -> `server_id`.
    assert client.calls[0]["fields"] == {"player_id": "1313232551", "server_id": "6618"}
    assert client.calls[0]["idempotency_key"] == "task-42"
    # Everything it writes names the vendor, so an operator reading a task
    # never has to guess which of the two panel suppliers filled it.
    assert result.extra_metadata["supplier"] == "fzr"
    assert result.extra_metadata["fzr_status"] == "processing"


async def test_a_completed_gift_card_hands_the_codes_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(
        order={
            "id": "ord-9001",
            "kind": "gift_card",
            "status": "completed",
            "category_id": "roblox_global",
            "cards": ["ROBLOX-AAAA-BBBB"],
        }
    )
    result = await _fulfill(
        client,
        monkeypatch,
        mapping=_mapping(kind="voucher", external_variant_id="800_robux"),
        item=_item(qty=2),
    )

    assert result.outcome == "succeeded"
    assert result.artifact_kind == "voucher_code"
    assert result.artifact["codes"] == ["ROBLOX-AAAA-BBBB"]
    assert result.artifact["source"] == "fzr"
    # A card order carries a real quantity; the top-up guard must not reach it.
    assert client.giftcard_calls[0]["quantity"] == 2
    assert not client.calls


async def test_steam_sends_the_face_value_and_never_the_login_anywhere_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(order={"id": "ord-9003", "status": "processing", "chargedUsd": "9.645"})
    result = await _fulfill(
        client,
        monkeypatch,
        mapping=_mapping(external_product_id=STEAM_SENTINEL, external_variant_id=""),
        item=_item(fulfillment_data={"steam_login": "someplayer"}, unit_price_usd=Decimal("10")),
    )

    assert client.steam_calls[0]["steam_login"] == "someplayer"
    # Face value, not what it costs us: their rebate is tiered, and what they
    # actually took comes back on the order.
    assert client.steam_calls[0]["amount_usd"] == Decimal("10")
    assert result.extra_metadata["supplier_charged_usd"] == "9.645"


# ---------- refusals, and what they say about the money ----------


async def test_a_lapsed_subscription_says_so_instead_of_being_a_bare_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one refusal an operator can fix in a minute.

    As an anonymous 403 it reads like a permissions bug in our own code, which
    is the wrong place to start looking.
    """
    client = _FakeClient(
        raises=FzrError("Subscription is not active", status=403, code=SUBSCRIPTION_INACTIVE)
    )
    with pytest.raises(FulfillerError) as exc:
        await _fulfill(client, monkeypatch)

    assert "subscription is not active" in str(exc.value).lower()
    assert "renew the plan" in str(exc.value)
    # A 403 is a refusal of the request itself — nothing was charged.
    assert exc.value.money_outcome is MoneyOutcome.RETURNED


async def test_a_rate_limit_is_recoverable_not_a_money_mystery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """They publish a 60/min ceiling on order creates and reject at the edge.

    Grading that UNKNOWN would put a fully recoverable retry in front of a
    human instead of letting the saga handle it.
    """
    client = _FakeClient(raises=FzrError("Too many requests", status=429))
    with pytest.raises(FulfillerError) as exc:
        await _fulfill(client, monkeypatch)

    assert exc.value.money_outcome is MoneyOutcome.RETURNED


async def test_a_refusal_never_echoes_the_player_id_back_into_the_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§9: a supplier's "player 1313232551 not found" must not land in
    ``task.last_error``. We know exactly what we sent, so it is redacted
    exactly rather than guessed at."""
    client = _FakeClient(
        raises=FzrError("player 1313232551 not found for this category", status=400)
    )
    with pytest.raises(FulfillerError) as exc:
        await _fulfill(client, monkeypatch)

    assert "1313232551" not in str(exc.value)
    assert "…" in str(exc.value)


async def test_a_steam_refusal_redacts_the_login_too(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(raises=FzrError("account someplayer cannot be refilled", status=400))
    with pytest.raises(FulfillerError) as exc:
        await _fulfill(
            client,
            monkeypatch,
            mapping=_mapping(external_product_id=STEAM_SENTINEL, external_variant_id=""),
            item=_item(fulfillment_data={"steam_login": "someplayer"}),
        )

    assert "someplayer" not in str(exc.value)


async def test_a_low_balance_refusal_parks_the_order_and_carries_both_numbers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The soft failure: the customer keeps waiting, ops get paged to top up.

    Both figures travel, because the alert used to print "$?" on one side and
    an operator learned the wallet was short without learning by how much.
    """
    client = _FakeClient(raises=FzrError("Insufficient internal balance", status=400))
    result = await _fulfill(client, monkeypatch)

    assert result.outcome == "failed"
    assert result.error == LOW_BALANCE_ERROR
    # Deliberately unclassified: the order is not finished failing.
    assert result.money_outcome is None
    assert result.extra_metadata["supplier"] == "fzr"
    assert result.extra_metadata["shortfall"] == "ours"
    assert result.extra_metadata["current_balance"] == "9.10"
    assert result.extra_metadata["required"] == "3.84"


async def test_the_alert_still_lands_when_the_balance_probe_itself_is_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing number is a worse alert, not a worse outcome."""
    client = _FakeClient(
        raises=FzrError("Insufficient internal balance", status=400),
        balance=FzrUnavailableError("ReadTimeout"),
    )
    result = await _fulfill(client, monkeypatch)

    assert result.error == LOW_BALANCE_ERROR
    assert "current_balance" not in result.extra_metadata


async def test_a_lost_create_is_parked_for_adoption_not_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """They charge on create, so a lost response must not be declared either
    way: failing it invites a human to retry and buy the thing twice."""
    client = _FakeClient(raises=FzrUnavailableError("ReadTimeout"))
    result = await _fulfill(client, monkeypatch)

    assert result.outcome == "in_progress"
    assert result.external_order_id is None
    assert result.money_outcome is None
    assert result.extra_metadata["fzr_create_unresolved"] == "ReadTimeout"


# ---------- guards that refuse before spending ----------


async def test_an_unconfigured_key_refuses_before_calling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient()
    with pytest.raises(FulfillerError) as exc:
        await _fulfill(client, monkeypatch, available=False)

    assert exc.value.money_outcome is MoneyOutcome.RETURNED
    assert not client.calls


async def test_a_multi_unit_top_up_is_refused_rather_than_under_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One call buys one offer. Without this the customer pays for three and
    gets one."""
    client = _FakeClient()
    with pytest.raises(FulfillerError) as exc:
        await _fulfill(client, monkeypatch, item=_item(qty=3))

    assert exc.value.money_outcome is MoneyOutcome.RETURNED
    assert not client.calls


async def test_a_mapping_with_no_offer_id_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient()
    with pytest.raises(FulfillerError) as exc:
        await _fulfill(client, monkeypatch, mapping=_mapping(external_variant_id=""))

    assert exc.value.money_outcome is MoneyOutcome.RETURNED
    assert not client.calls


async def test_a_voucher_mapping_with_no_card_id_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient()
    with pytest.raises(FulfillerError) as exc:
        await _fulfill(
            client, monkeypatch, mapping=_mapping(kind="voucher", external_variant_id="")
        )

    assert exc.value.money_outcome is MoneyOutcome.RETURNED
    assert not client.giftcard_calls


async def test_steam_without_a_login_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The message names the missing field: the G2B version of this bug cost
    an evening because it did not."""
    client = _FakeClient()
    with pytest.raises(FulfillerError) as exc:
        await _fulfill(
            client,
            monkeypatch,
            mapping=_mapping(external_product_id=STEAM_SENTINEL, external_variant_id=""),
            item=_item(fulfillment_data={}),
        )

    assert "fulfillment_data.steam_login" in str(exc.value)
    assert exc.value.money_outcome is MoneyOutcome.RETURNED


async def test_a_line_with_nothing_to_identify_the_player_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient()
    with pytest.raises(FulfillerError) as exc:
        await _fulfill(client, monkeypatch, item=_item(fulfillment_data={}))

    assert "fzr fields" in str(exc.value)
    assert not client.calls


# ---------- the fields the category actually asks for ----------


async def test_their_declaration_beats_our_rename(monkeypatch: pytest.MonkeyPatch) -> None:
    """A category that wants ``server`` must get ``server``, not ``server_id``
    — the rename is what refused a NOVA Honkai order outright."""
    client = _FakeClient(
        order={"id": "ord-1", "status": "processing"},
        offers={
            "fields": [
                {"key": "player_id", "type": "text"},
                {
                    "key": "server",
                    "type": "select",
                    "options": [{"value": "europe", "label": "Europe"}],
                },
            ]
        },
    )
    await _fulfill(
        client, monkeypatch, item=_item(fulfillment_data={"player_id": "42", "server": "Europe"})
    )

    assert client.calls[0]["fields"] == {"player_id": "42", "server": "europe"}


async def test_an_outage_on_the_spec_call_falls_back_instead_of_blocking_a_sale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An optional question asked before the real call must never refuse an
    order we could have placed — however it fails."""

    class _NoOffers(_FakeClient):
        async def get_offers(self, category_id: str) -> dict[str, Any]:
            raise RuntimeError("something entirely unexpected")

    client = _NoOffers(order={"id": "ord-1", "status": "processing"})
    result = await _fulfill(client, monkeypatch)

    assert result.outcome == "in_progress"
    assert client.calls[0]["fields"] == {"player_id": "1313232551", "server_id": "6618"}


async def test_an_empty_declaration_is_not_read_as_needs_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "Told nothing" and "needs nothing" look identical here and mean
    opposite things."""
    client = _FakeClient(order={"id": "ord-1", "status": "processing"}, offers={"fields": []})
    await _fulfill(client, monkeypatch)

    assert client.calls[0]["fields"] == {"player_id": "1313232551", "server_id": "6618"}


# ---------- polling, adoption and cancellation ----------


def _task(**over: Any) -> Any:
    base = {
        "order_item_id": "oi-1",
        "external_order_id": "ord-9002",
        "extra_metadata": {},
        "created_at": datetime.now(UTC),
    }
    base.update(over)
    return SimpleNamespace(**base)


async def test_check_status_reads_the_order_and_grades_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(order={"id": "ord-9002", "kind": "topup", "status": "completed"})
    status = await _fulfiller(client, monkeypatch).check_status(
        db=None,  # type: ignore[arg-type]
        task=_task(),
    )

    assert status.outcome == "succeeded"
    assert status.artifact_kind == "topup_receipt"
    assert (status.artifact or {})["supplier"] == "fzr"


async def test_check_status_reads_an_id_adopted_on_an_earlier_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reconciler merges ``extra_metadata`` but never moves the id into
    the column, so both have to be read."""
    client = _FakeClient(order={"id": "ord-77", "status": "completed"})
    status = await _fulfiller(client, monkeypatch).check_status(
        db=None,  # type: ignore[arg-type]
        task=_task(external_order_id=None, extra_metadata={"fzr_order_id": "ord-77"}),
    )

    assert status.outcome == "succeeded"


async def test_check_status_without_a_key_cannot_claim_the_money_came_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """By the time anything polls, the order has been placed."""
    with pytest.raises(FulfillerError) as exc:
        await _fulfiller(_FakeClient(), monkeypatch, available=False).check_status(
            db=None,  # type: ignore[arg-type]
            task=_task(),
        )

    assert exc.value.money_outcome is MoneyOutcome.UNKNOWN


async def test_an_id_less_task_keeps_looking_inside_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import yupay.modules.fulfillment.suppliers.fzr as mod

    async def _no_key(_db: Any, _task: Any) -> Any:
        return None

    monkeypatch.setattr(mod, "_adopt_key_for", _no_key)
    status = await _fulfiller(_FakeClient(), monkeypatch).check_status(
        db=None,  # type: ignore[arg-type]
        task=_task(external_order_id=None),
    )

    assert status.outcome == "in_progress"
    assert status.money_outcome is None


async def test_an_id_less_task_past_the_window_fails_undecided_on_the_money(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evidence of absence is not proof: a wrong RETURNED here would refund a
    customer who already has their goods."""
    import yupay.modules.fulfillment.suppliers.fzr as mod

    async def _no_key(_db: Any, _task: Any) -> Any:
        return None

    monkeypatch.setattr(mod, "_adopt_key_for", _no_key)
    with pytest.raises(FulfillerError) as exc:
        await _fulfiller(_FakeClient(), monkeypatch).check_status(
            db=None,  # type: ignore[arg-type]
            task=_task(external_order_id=None, created_at=datetime.now(UTC) - timedelta(hours=2)),
        )

    assert exc.value.money_outcome is MoneyOutcome.UNKNOWN
    assert "docs/runbooks/fzr.md" in str(exc.value)


async def test_an_id_less_task_adopts_the_order_it_paid_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import yupay.modules.fulfillment.suppliers.fzr as mod
    from yupay.modules.fulfillment.suppliers.panel_adopt import AdoptKey

    async def _key(_db: Any, _task: Any) -> Any:
        return AdoptKey(
            kind="topup",
            category_id="free_fire_cis",
            offer_id="572_diamonds",
            player_id="1313232551",
        )

    monkeypatch.setattr(mod, "_adopt_key_for", _key)
    client = _FakeClient(
        orders=[
            {
                "id": "ord-9100",
                "kind": "topup",
                "status": "completed",
                "category_id": "free_fire_cis",
                "offer_id": "572_diamonds",
                "fields": {"player_id": "1313232551"},
                "created_at": datetime.now(UTC).isoformat(),
            }
        ]
    )
    status = await _fulfiller(client, monkeypatch).check_status(
        db=None,  # type: ignore[arg-type]
        task=_task(external_order_id=None, created_at=datetime.now(UTC) - timedelta(minutes=1)),
    )

    assert status.outcome == "succeeded"
    assert status.extra_metadata["fzr_order_id"] == "ord-9100"
    assert status.extra_metadata["fzr_adopted"] is True


async def test_a_refusal_while_polling_leaves_the_money_undecided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(raises=FzrUnavailableError("ConnectTimeout"))
    with pytest.raises(FulfillerError) as exc:
        await _fulfiller(client, monkeypatch).check_status(
            db=None,  # type: ignore[arg-type]
            task=_task(),
        )

    assert exc.value.money_outcome is MoneyOutcome.UNKNOWN


async def test_cancel_refuses_without_claiming_anything_about_the_money(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The order it would have cancelled was already bought, and this call
    learns nothing about what became of that money."""
    with pytest.raises(FulfillerNotIntegratedError) as exc:
        await _fulfiller(_FakeClient(), monkeypatch).cancel(
            db=None,  # type: ignore[arg-type]
            task=_task(),
        )

    assert exc.value.money_outcome is MoneyOutcome.UNKNOWN


# ---------- health ----------


async def test_health_reports_the_plan_beside_the_balance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalogue access expires with the subscription, so "can we route here
    tomorrow" is half the answer."""
    client = _FakeClient(
        balance={"balance": "0.0000", "currency": "USD"},
        subscription={
            "plan": "gold",
            "planExpiresAt": "2026-09-29T05:50:20.696Z",
            "subscriptionActive": True,
        },
    )
    out = await _fulfiller(client, monkeypatch).health()

    assert out == {
        "available": True,
        "balance": "0.00",
        "currency": "USD",
        "plan": "gold",
        "plan_expires_at": "2026-09-29T05:50:20.696Z",
        "subscription_active": True,
    }


async def test_health_without_a_key_says_so_rather_than_calling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = await _fulfiller(_FakeClient(), monkeypatch, available=False).health()
    assert out == {"available": False, "reason": "FZR_API_KEY is not configured"}


async def test_health_never_raises_when_the_supplier_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator opening the integrations page must not meet an error
    boundary because a supplier is down."""
    client = _FakeClient(balance=FzrUnavailableError("ReadTimeout"))
    out = await _fulfiller(client, monkeypatch).health()

    assert out["available"] is False
    assert "ReadTimeout" in out["reason"]


async def test_health_still_answers_when_only_the_plan_call_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(balance={"balance": "12.50", "currency": "USD"}, subscription=None)
    out = await _fulfiller(client, monkeypatch).health()

    assert out["available"] is True
    assert out["balance"] == "12.50"
    assert "plan" not in out


# ---------- the database-facing helpers ----------


class _Result:
    def __init__(self, row: Any) -> None:
        self._row = row

    def scalar_one_or_none(self) -> Any:
        return self._row


class _Db:
    """Returns each queued row in turn, so a two-query helper can be driven."""

    def __init__(self, *rows: Any) -> None:
        self._rows = list(rows)

    async def execute(self, *_args: Any, **_kw: Any) -> Any:
        return _Result(self._rows.pop(0) if self._rows else None)


async def test_a_missing_mapping_refuses_with_a_message_an_operator_can_act_on() -> None:
    with pytest.raises(FulfillerError) as exc:
        await _mapping_for(_Db(None), sku_id="sku-1")  # type: ignore[arg-type]

    assert "kind=game or kind=voucher" in str(exc.value)
    assert exc.value.money_outcome is MoneyOutcome.RETURNED


async def test_the_adopt_key_for_a_top_up_names_the_offer_and_the_player() -> None:
    key = await _adopt_key_for(
        _Db(_item(), _mapping()),  # type: ignore[arg-type]
        _task(),
    )

    assert key is not None
    assert (key.kind, key.category_id, key.offer_id) == ("topup", "free_fire_cis", "572_diamonds")
    assert key.player_id == "1313232551"


async def test_the_adopt_key_for_a_gift_card_names_the_card_and_the_count() -> None:
    key = await _adopt_key_for(
        _Db(_item(qty=3), _mapping(kind="voucher", external_variant_id="800_robux")),  # type: ignore[arg-type]
        _task(),
    )

    assert key is not None
    assert (key.kind, key.card_id, key.quantity) == ("gift_card", "800_robux", 3)


async def test_the_adopt_key_for_steam_names_the_login() -> None:
    key = await _adopt_key_for(
        _Db(  # type: ignore[arg-type]
            _item(fulfillment_data={"steam_login": "someplayer"}),
            _mapping(external_product_id=STEAM_SENTINEL, external_variant_id=""),
        ),
        _task(),
    )

    assert key is not None
    assert (key.kind, key.steam_login) == ("steam_topup", "someplayer")


async def test_an_unidentifiable_line_yields_no_adopt_key_at_all() -> None:
    """A key missing its identifying half still compares equal to *some*
    order, and adopting the wrong one reports a delivery that never happened
    for this line."""
    key = await _adopt_key_for(
        _Db(_item(fulfillment_data={}), _mapping()),  # type: ignore[arg-type]
        _task(),
    )

    assert key is None


async def test_no_order_item_means_no_adopt_key() -> None:
    assert await _adopt_key_for(_Db(None), _task()) is None  # type: ignore[arg-type]


async def test_no_mapping_means_no_adopt_key() -> None:
    assert await _adopt_key_for(_Db(_item(), None), _task()) is None  # type: ignore[arg-type]


# ---------- the branches each product path owns separately ----------


async def test_a_gift_card_low_balance_parks_the_order_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three product paths, three copies of the same two except-branches. Each
    is tested, because a miss in one is a hard failure where the other two
    would have waited for a top-up."""
    client = _FakeClient(raises=FzrError("Insufficient internal balance", status=400))
    result = await _fulfill(
        client, monkeypatch, mapping=_mapping(kind="voucher", external_variant_id="800_robux")
    )

    assert result.error == LOW_BALANCE_ERROR
    assert result.extra_metadata["current_balance"] == "9.10"


async def test_a_gift_card_refusal_is_terminal_with_the_money_answered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(raises=FzrError("card is out of stock", status=400))
    with pytest.raises(FulfillerError) as exc:
        await _fulfill(
            client, monkeypatch, mapping=_mapping(kind="voucher", external_variant_id="800_robux")
        )

    assert exc.value.money_outcome is MoneyOutcome.RETURNED


async def test_a_lost_gift_card_create_is_parked_for_adoption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(raises=FzrUnavailableError("PoolTimeout"))
    result = await _fulfill(
        client, monkeypatch, mapping=_mapping(kind="voucher", external_variant_id="800_robux")
    )

    assert result.outcome == "in_progress"
    assert result.extra_metadata["fzr_create_unresolved"] == "PoolTimeout"


async def _steam(client: _FakeClient, monkeypatch: pytest.MonkeyPatch) -> Any:
    return await _fulfill(
        client,
        monkeypatch,
        mapping=_mapping(external_product_id=STEAM_SENTINEL, external_variant_id=""),
        item=_item(fulfillment_data={"steam_login": "someplayer"}),
    )


async def test_a_steam_low_balance_parks_the_order_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(raises=FzrError("Insufficient internal balance", status=400))
    result = await _steam(client, monkeypatch)

    assert result.error == LOW_BALANCE_ERROR


async def test_a_lost_steam_create_is_parked_for_adoption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(raises=FzrUnavailableError("ReadTimeout"))
    result = await _steam(client, monkeypatch)

    assert result.outcome == "in_progress"
    assert result.external_order_id is None


async def test_a_supplier_shortfall_is_not_reported_as_our_empty_wallet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Printing "пополни счёт" for their dry upstream sent a real operator to
    look at a balance that was already fine."""
    client = _FakeClient(
        raises=FzrError("Service balance is insufficient to complete this order", status=400)
    )
    result = await _fulfill(client, monkeypatch)

    assert result.extra_metadata["shortfall"] == "supplier"


# ---------- the alert's figures, when they cannot be worked out ----------


async def test_the_required_figure_is_omitted_rather_than_guessed() -> None:
    """It only ever decorates a refusal that already happened, so it must not
    be able to raise — the alert renders a missing number as "$?"."""
    assert FzrFulfiller._required_or_none(_item(sku=None)) is None
    assert FzrFulfiller._required_or_none(_item(sku=SimpleNamespace(cost_usdt=None))) is None
    assert (
        FzrFulfiller._required_or_none(_item(sku=SimpleNamespace(cost_usdt="not a number"))) is None
    )


async def test_the_required_figure_multiplies_the_per_unit_cost_out() -> None:
    assert FzrFulfiller._required_or_none(_item(qty=4)) == "15.36"


# ---------- the client the adapter builds when nothing is injected ----------


async def test_the_client_is_built_from_settings_so_a_rotated_key_needs_no_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Built per call, not per process: the house pattern every adapter uses."""
    import yupay.modules.fulfillment.suppliers.fzr as mod

    monkeypatch.setattr(
        mod,
        "get_settings",
        lambda: SimpleNamespace(
            fzr_api_key="fc_test",
            fzr_base_url="https://api.fzr.cards",
            fzr_request_timeout_seconds=7.0,
        ),
    )
    client = FzrFulfiller().client_for_reads()

    assert client.slug == "fzr"
    assert client._base_url == "https://api.fzr.cards"
    assert client._timeout == 7.0
