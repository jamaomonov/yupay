"""The gift branch of the G-Engine adapter: adopt-don't-rebuy.

A gift order is a single call with no client-supplied id and no unpaid
reservation step to fall back on, unlike the recharge/shop halves of
``gengine.py`` (see ``test_gengine_fulfiller.py``). These tests exist to
prove the one rule that matters: a retried task never places a second gift
order for the same line.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import pytest
from yupay.modules.fulfillment.suppliers.base import FulfillerError
from yupay.modules.fulfillment.suppliers.gengine_client import (
    GEngineError,
    GEngineGiftOrder,
    GEngineUnavailableError,
)
from yupay.modules.fulfillment.suppliers.gengine_gifts import (
    _DELIVERY_MESSAGE,
    _PARK_ERROR,
    GIFT_ADOPT_WINDOW_MINUTES,
    fulfill_gift,
    gift_status,
)

pytestmark = pytest.mark.asyncio

_INVITE_URL = "https://steamcommunity.com/profiles/76561198000000001"
_SEARCH_TERM = "76561198000000001"
_PACKAGE_ID = 42


def _gift(
    *,
    order_id: int = 501,
    status: str = "processing",
    refunded: bool = False,
    invite_url: str = _INVITE_URL,
    package_id: int = _PACKAGE_ID,
    package_name: str = "Standard Edition",
    error: str | None = None,
) -> GEngineGiftOrder:
    return GEngineGiftOrder(
        id=order_id,
        uuid="gift-uuid-1",
        status=status,
        purchase_price=9.99,
        is_refunded=refunded,
        invite_url=invite_url,
        region="RU",
        package_id=package_id,
        package_name=package_name,
        error=error,
    )


class FakeGiftClient:
    """Records what was called, so "did it buy twice" is answerable."""

    def __init__(
        self,
        *,
        created: Any = None,
        fetched: Any = None,
        listed: Any = None,
    ) -> None:
        self._created = created
        self._fetched = fetched
        self._listed = listed if listed is not None else []
        self.create_calls = 0
        self.get_calls = 0
        self.list_calls = 0
        self.last_create_kwargs: dict[str, Any] | None = None

    async def create_gift_order(self, **kw: Any) -> GEngineGiftOrder:
        self.create_calls += 1
        self.last_create_kwargs = kw
        if isinstance(self._created, Exception):
            raise self._created
        return self._created

    async def get_gift_order(self, _order_id: int) -> GEngineGiftOrder:
        self.get_calls += 1
        if isinstance(self._fetched, Exception):
            raise self._fetched
        return self._fetched

    async def list_gift_orders(self, **_kw: Any) -> list[GEngineGiftOrder]:
        self.list_calls += 1
        if isinstance(self._listed, Exception):
            raise self._listed
        return list(self._listed)


class _Item:
    def __init__(self, data: dict[str, Any]) -> None:
        self.fulfillment_data = data


def _item(**overrides: Any) -> _Item:
    data: dict[str, Any] = {
        "invite_url": _INVITE_URL,
        "package_id": _PACKAGE_ID,
        "region": "RU",
    }
    data.update(overrides)
    return _Item(data)


class _Task:
    def __init__(
        self,
        *,
        external_order_id: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self.external_order_id = external_order_id
        self.extra_metadata = extra_metadata or {}
        self.created_at = created_at or datetime.now(UTC)


# ---------- fulfill_gift: the money-safety rules ----------


async def test_a_fresh_line_creates_a_gift_order_in_progress() -> None:
    client = FakeGiftClient(created=_gift(order_id=501, status="processing"))

    result = await fulfill_gift(
        client,  # type: ignore[arg-type]
        item=_item(),  # type: ignore[arg-type]
        order_created_at=datetime.now(UTC),  # type: ignore[arg-type]
    )

    assert client.create_calls == 1
    assert client.list_calls == 1  # the adopt-before-create probe always runs first
    assert result.outcome == "in_progress"
    assert result.external_order_id == "501"
    assert result.artifact is None
    assert result.extra_metadata == {
        "supplier": "gengine",
        "gengine_kind": "gift",
        "gift_package_id": _PACKAGE_ID,
        "gift_search": _SEARCH_TERM,
        "gift_invite_url": _INVITE_URL,
        "gengine_status": "processing",
    }


async def test_create_prefers_the_checkout_derived_country_code_over_the_zone() -> None:
    """G-Engine's `POST /gifts/orders` wants the 2-letter country code off
    the package's own price entry, not our "RU"/"CIS" zone label — a zone
    label there gets G-Engine's «Price not found». Checkout (hotfix)
    resolves and stores that code as `region_code`; it must win over the
    legacy `region` zone value whenever both are present."""
    client = FakeGiftClient(created=_gift(order_id=501, status="processing"))

    await fulfill_gift(
        client,  # type: ignore[arg-type]
        item=_item(region_code="ge"),  # type: ignore[arg-type]
        order_created_at=datetime.now(UTC),  # type: ignore[arg-type]
    )

    assert client.last_create_kwargs is not None
    assert client.last_create_kwargs["region"] == "ge"


async def test_create_falls_back_to_the_legacy_zone_when_region_code_is_absent() -> None:
    """Pre-hotfix order rows never got a `region_code` written — those must
    still fulfil, using the old zone value exactly as before."""
    client = FakeGiftClient(created=_gift(order_id=501, status="processing"))

    await fulfill_gift(
        client,  # type: ignore[arg-type]
        item=_item(),  # type: ignore[arg-type]
        order_created_at=datetime.now(UTC),  # type: ignore[arg-type]
    )

    assert client.last_create_kwargs is not None
    assert client.last_create_kwargs["region"] == "RU"


async def test_an_existing_order_is_adopted_instead_of_bought_twice() -> None:
    """The finder hits before any create is attempted."""
    existing = _gift(order_id=777, status="processing")
    client = FakeGiftClient(listed=[existing])

    result = await fulfill_gift(
        client,  # type: ignore[arg-type]
        item=_item(),  # type: ignore[arg-type]
        order_created_at=datetime.now(UTC),  # type: ignore[arg-type]
    )

    assert client.create_calls == 0
    assert result.outcome == "in_progress"
    assert result.external_order_id == "777"


async def test_an_ambiguous_create_is_parked_id_less_not_retried_blind() -> None:
    """The create may have landed upstream even though we never saw the
    response. Parking id-less — not raising, not creating again — is what
    lets a later retry adopt it instead of buying a second gift."""
    client = FakeGiftClient(created=GEngineUnavailableError("timeout"))

    result = await fulfill_gift(
        client,  # type: ignore[arg-type]
        item=_item(),  # type: ignore[arg-type]
        order_created_at=datetime.now(UTC),  # type: ignore[arg-type]
    )

    assert result.outcome == "in_progress"
    assert result.external_order_id is None
    assert result.extra_metadata == {
        "supplier": "gengine",
        "gengine_kind": "gift",
        "gift_package_id": _PACKAGE_ID,
        "gift_search": _SEARCH_TERM,
        "gift_invite_url": _INVITE_URL,
    }
    assert client.create_calls == 1


async def test_a_retried_task_adopts_the_landed_create_instead_of_rebuying() -> None:
    """The whole point of this module. A retry after an ambiguous create must
    never place a second order for the same line."""
    client = FakeGiftClient(created=GEngineUnavailableError("timeout"), listed=[])

    first = await fulfill_gift(
        client,  # type: ignore[arg-type]
        item=_item(),  # type: ignore[arg-type]
        order_created_at=datetime.now(UTC),  # type: ignore[arg-type]
    )
    assert first.outcome == "in_progress"
    assert first.external_order_id is None
    assert client.create_calls == 1

    # The create had in fact landed; a fresh probe now finds it.
    client._listed = [_gift(order_id=999, status="processing")]
    second = await fulfill_gift(
        client,  # type: ignore[arg-type]
        item=_item(),  # type: ignore[arg-type]
        order_created_at=datetime.now(UTC),  # type: ignore[arg-type]
    )

    assert second.external_order_id == "999"
    assert client.create_calls == 1  # unchanged — no second create


async def test_a_probe_error_falls_through_to_create() -> None:
    """The adopt-before-create probe is best-effort: its own failure must not
    block a genuinely new line from ever being bought — the create call
    carries its own ambiguous-failure guard."""
    client = FakeGiftClient(
        created=_gift(order_id=321, status="processing"),
        listed=GEngineUnavailableError("timeout"),
    )

    result = await fulfill_gift(
        client,  # type: ignore[arg-type]
        item=_item(),  # type: ignore[arg-type]
        order_created_at=datetime.now(UTC),  # type: ignore[arg-type]
    )

    assert client.create_calls == 1
    assert result.external_order_id == "321"


async def test_a_clean_refusal_to_create_is_reported_not_retried() -> None:
    client = FakeGiftClient(created=GEngineError("region not offered"))

    with pytest.raises(FulfillerError, match="region not offered"):
        await fulfill_gift(
            client,  # type: ignore[arg-type]
            item=_item(),  # type: ignore[arg-type]
            order_created_at=datetime.now(UTC),  # type: ignore[arg-type]
        )


async def test_a_line_missing_a_required_field_is_refused() -> None:
    """Checkout makes this impossible, so a missing field here is data
    corruption, not weather — non-retryable."""
    client = FakeGiftClient()

    with pytest.raises(FulfillerError, match="missing invite_url"):
        await fulfill_gift(
            client,  # type: ignore[arg-type]
            item=_item(invite_url=""),  # type: ignore[arg-type]
            order_created_at=datetime.now(UTC),  # type: ignore[arg-type]
        )
    assert client.create_calls == 0


async def test_a_non_numeric_package_id_is_named_rather_than_crashing() -> None:
    client = FakeGiftClient()

    with pytest.raises(FulfillerError, match="must be numeric"):
        await fulfill_gift(
            client,  # type: ignore[arg-type]
            item=_item(package_id="not-a-number"),  # type: ignore[arg-type]
            order_created_at=datetime.now(UTC),  # type: ignore[arg-type]
        )


# ---------- gift_status: the full outcome map ----------


async def test_gift_status_shipped_is_a_delivery() -> None:
    order = _gift(order_id=501, status="shipped", package_name="Deluxe Edition")
    client = FakeGiftClient(fetched=order)

    status = await gift_status(client, task=_Task(external_order_id="501"))  # type: ignore[arg-type]

    assert status.outcome == "succeeded"
    assert status.artifact_kind == "topup_receipt"
    assert status.artifact == {
        "supplier": "gengine",
        "kind": "gift",
        "external_order_id": "501",
        "status": "shipped",
        "app_name": "Deluxe Edition",  # falls back to package_name — no app_name in task metadata
        "package_name": "Deluxe Edition",
        "message": _DELIVERY_MESSAGE,
    }


async def test_gift_status_delivered_is_also_a_delivery() -> None:
    """A fast recipient can accept before we ever see `shipped`."""
    order = _gift(order_id=502, status="delivered")
    client = FakeGiftClient(fetched=order)

    status = await gift_status(client, task=_Task(external_order_id="502"))  # type: ignore[arg-type]

    assert status.outcome == "succeeded"


async def test_gift_status_a_refund_seen_on_the_very_first_poll_is_not_a_delivery() -> None:
    """If the very first poll already shows `shipped` with `is_refunded=True`,
    the money has already come back — report failed, not succeeded. (A
    refund landing only after we already recorded success is the existing
    stuck/refund manual path and unaffected here.)"""
    order = _gift(order_id=510, status="shipped", refunded=True)
    client = FakeGiftClient(fetched=order)

    status = await gift_status(client, task=_Task(external_order_id="510"))  # type: ignore[arg-type]

    assert status.outcome == "failed"
    assert status.error == "supplier status shipped"


async def test_gift_status_reads_app_name_from_task_metadata_when_present() -> None:
    order = _gift(order_id=509, status="shipped", package_name="Standard Edition")
    client = FakeGiftClient(fetched=order)
    task = _Task(external_order_id="509", extra_metadata={"app_name": "Elden Ring"})

    status = await gift_status(client, task=task)  # type: ignore[arg-type]

    assert status.artifact is not None
    assert status.artifact["app_name"] == "Elden Ring"


async def test_gift_status_the_refunded_flag_fails_even_off_the_dead_status_list() -> None:
    order = _gift(order_id=503, status="processing", refunded=True)
    client = FakeGiftClient(fetched=order)

    status = await gift_status(client, task=_Task(external_order_id="503"))  # type: ignore[arg-type]

    assert status.outcome == "failed"
    assert status.error == "supplier status processing"


async def test_gift_status_canceled_fails_with_the_suppliers_own_words() -> None:
    order = _gift(order_id=504, status="canceled", error="invalid invite link")
    client = FakeGiftClient(fetched=order)

    status = await gift_status(client, task=_Task(external_order_id="504"))  # type: ignore[arg-type]

    assert status.outcome == "failed"
    assert status.error == "invalid invite link"


async def test_gift_status_in_progress_passes_through_with_supplier_status() -> None:
    order = _gift(order_id=505, status="processing")
    client = FakeGiftClient(fetched=order)

    status = await gift_status(client, task=_Task(external_order_id="505"))  # type: ignore[arg-type]

    assert status.outcome == "in_progress"
    assert status.extra_metadata == {"gengine_status": "processing"}


async def test_gift_status_reads_a_previously_adopted_id_before_probing() -> None:
    order = _gift(order_id=606, status="processing")
    client = FakeGiftClient(fetched=order)
    task = _Task(extra_metadata={"gift_order_id": "606"})

    status = await gift_status(client, task=task)  # type: ignore[arg-type]

    assert status.outcome == "in_progress"
    assert client.list_calls == 0  # went straight to the id, no finder run


async def test_gift_status_adopts_by_search_metadata_when_the_finder_hits() -> None:
    found = _gift(order_id=707, status="shipped")
    client = FakeGiftClient(listed=[found], fetched=found)
    task = _Task(
        extra_metadata={
            "gift_search": _SEARCH_TERM,
            "gift_package_id": _PACKAGE_ID,
            "gift_invite_url": _INVITE_URL,
        }
    )

    status = await gift_status(client, task=task)  # type: ignore[arg-type]

    assert status.outcome == "succeeded"
    assert status.extra_metadata == {"gift_order_id": "707"}


async def test_gift_status_stays_in_progress_within_the_adopt_window() -> None:
    client = FakeGiftClient(listed=[])
    task = _Task(
        extra_metadata={
            "gift_search": _SEARCH_TERM,
            "gift_package_id": _PACKAGE_ID,
            "gift_invite_url": _INVITE_URL,
        },
        created_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    status = await gift_status(client, task=task)  # type: ignore[arg-type]

    assert status.outcome == "in_progress"


async def test_gift_status_with_no_metadata_at_all_stays_in_progress_until_the_window() -> None:
    client = FakeGiftClient()
    task = _Task(created_at=datetime.now(UTC) - timedelta(minutes=1))

    status = await gift_status(client, task=task)  # type: ignore[arg-type]

    assert status.outcome == "in_progress"
    assert client.list_calls == 0


async def test_gift_status_parks_for_manual_review_after_the_adopt_window() -> None:
    """By this point a landed create is findable, so its absence means the
    create never happened — and a human confirms that before any second
    spend, which is why this parks rather than re-buying."""
    client = FakeGiftClient(listed=[])
    task = _Task(
        extra_metadata={
            "gift_search": _SEARCH_TERM,
            "gift_package_id": _PACKAGE_ID,
            "gift_invite_url": _INVITE_URL,
        },
        created_at=datetime.now(UTC) - timedelta(minutes=GIFT_ADOPT_WINDOW_MINUTES + 1),
    )

    status = await gift_status(client, task=task)  # type: ignore[arg-type]

    assert status.outcome == "failed"
    assert status.error == _PARK_ERROR


async def test_gift_status_a_finder_outage_stays_pending_even_past_the_window() -> None:
    """An outage during the poll-time adopt probe must never be conflated
    with "genuinely not found" — that would park a task failed purely
    because G-Engine was unreachable. The 60s reconcile sweep retries."""
    client = FakeGiftClient(listed=GEngineUnavailableError("timeout"))
    task = _Task(
        extra_metadata={
            "gift_search": _SEARCH_TERM,
            "gift_package_id": _PACKAGE_ID,
            "gift_invite_url": _INVITE_URL,
        },
        created_at=datetime.now(UTC) - timedelta(minutes=GIFT_ADOPT_WINDOW_MINUTES + 1),
    )

    status = await gift_status(client, task=task)  # type: ignore[arg-type]

    assert status.outcome == "in_progress"


async def test_gift_status_a_clean_refusal_from_the_finder_still_parks_after_the_window() -> None:
    """Unlike an outage, a refusal means the supplier answered and its
    answer was "no" — the park-for-review rule still applies."""
    client = FakeGiftClient(listed=GEngineError("bad search"))
    task = _Task(
        extra_metadata={
            "gift_search": _SEARCH_TERM,
            "gift_package_id": _PACKAGE_ID,
            "gift_invite_url": _INVITE_URL,
        },
        created_at=datetime.now(UTC) - timedelta(minutes=GIFT_ADOPT_WINDOW_MINUTES + 1),
    )

    status = await gift_status(client, task=task)  # type: ignore[arg-type]

    assert status.outcome == "failed"
    assert status.error == _PARK_ERROR


async def test_gift_status_treats_supplier_unavailable_as_still_pending() -> None:
    """The reconcile sweep retries every 60s — nothing was decided upstream,
    so failing here would abandon a sale that may yet complete."""
    client = FakeGiftClient(fetched=GEngineUnavailableError("timeout"))

    status = await gift_status(client, task=_Task(external_order_id="900"))  # type: ignore[arg-type]

    assert status.outcome == "in_progress"


async def test_gift_status_raises_on_a_clean_refusal_while_polling() -> None:
    client = FakeGiftClient(fetched=GEngineError("order not found"))

    with pytest.raises(FulfillerError, match="order not found"):
        await gift_status(client, task=_Task(external_order_id="901"))  # type: ignore[arg-type]


# ---------- routing: gengine.py dispatches to this module ----------


async def test_the_fulfiller_routes_a_gift_mapping_to_the_gift_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import yupay.modules.fulfillment.suppliers.gengine as gengine_mod
    from yupay.modules.fulfillment.suppliers.gengine import GEngineFulfiller

    class Mapping:
        kind = "gift"

    class Item:
        sku_id = "sku-gift"
        fulfillment_data: ClassVar[dict[str, Any]] = {
            "invite_url": _INVITE_URL,
            "package_id": _PACKAGE_ID,
            "region": "RU",
        }

    class Order:
        created_at = datetime.now(UTC)

    async def _mapping_for(_db: Any, *, sku_id: str) -> Any:
        return Mapping()

    monkeypatch.setattr(gengine_mod, "_mapping_for", _mapping_for)
    monkeypatch.setattr(GEngineFulfiller, "available", property(lambda _self: True))

    client = FakeGiftClient(created=_gift(order_id=1234, status="processing"))
    f = GEngineFulfiller(client)  # type: ignore[arg-type]

    result = await f.fulfill(
        db=None,  # type: ignore[arg-type]
        order=Order(),  # type: ignore[arg-type]
        item=Item(),  # type: ignore[arg-type]
        idempotency_key="k-gift",
    )

    assert result.external_order_id == "1234"
    assert client.create_calls == 1


async def test_the_fulfiller_routes_an_id_less_gift_task_before_the_early_return() -> None:
    """The id-less early-return in `check_status` would answer `in_progress`
    without ever touching the client — the gift branch has to run first, or
    an ambiguous create could never be adopted."""
    from yupay.modules.fulfillment.suppliers.gengine import GEngineFulfiller

    class Task:
        external_order_id = None
        extra_metadata: ClassVar[dict[str, Any]] = {
            "gengine_kind": "gift",
            "gift_search": _SEARCH_TERM,
            "gift_package_id": _PACKAGE_ID,
            "gift_invite_url": _INVITE_URL,
        }
        created_at = datetime.now(UTC)

    client = FakeGiftClient(listed=[])
    f = GEngineFulfiller(client)  # type: ignore[arg-type]

    status = await f.check_status(db=None, task=Task())  # type: ignore[arg-type]

    assert status.outcome == "in_progress"
    # Proves the gift branch ran (it probes the finder) rather than the
    # id-less early-return, which would answer without touching the client.
    assert client.list_calls == 1


# ---------- the customer-facing artifact allow-list ----------


async def test_customer_safe_artifact_keys_include_the_new_gift_fields() -> None:
    # The list moved from ``fulfillment.routes`` to ``fulfillment.service`` in
    # M2 Task 5, when the machine API's order read became its second consumer.
    # ``service`` is a leaf, so this no longer has to import the v1 route stack
    # first to break the ``fulfillment.api`` <-> ``fulfillment.routes`` cycle.
    from yupay.modules.fulfillment.service import BUYER_SAFE_ARTIFACT_KEYS

    assert {"kind", "app_name", "package_name", "status"} <= BUYER_SAFE_ARTIFACT_KEYS
