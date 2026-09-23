"""Finding a NOVA order whose create response we never saw.

Production order ``01a0cd88`` (2026-09-23): our create went out at 09:11:51
and timed out at 09:12:11. NOVA created the order at **09:12:19** — eight
seconds after we gave up — charged us and delivered it. Our task recorded a
failure and an operator settled it by hand.

The same morning supplies the trap these tests mostly guard. The same
customer bought the same 110 Diamonds twice, 90 seconds apart, and both NOVA
orders completed. A matcher without a lower time bound would let the second
task adopt the first order and report a delivery belonging to another line.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from yupay.modules.fulfillment.suppliers.nova_adopt import (
    AdoptKey,
    find_order,
    key_is_usable,
)
from yupay.modules.fulfillment.suppliers.nova_client import NovaError, NovaUnavailableError

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 23, 9, 12, 19, tzinfo=UTC)
TASK_STARTED = NOW - timedelta(seconds=28)


def _topup(order_id: str, *, created: datetime, player: str = "10619597246") -> dict[str, Any]:
    return {
        "id": order_id,
        "kind": "topup",
        "category_id": "free_fire_cis",
        "offer_id": "110_diamonds",
        "offer_name": "110 Diamonds",
        "fields": {"player_id": player},
        "status": "completed",
        "created_at": created.isoformat().replace("+00:00", "Z"),
    }


TOPUP_KEY = AdoptKey(
    kind="topup",
    category_id="free_fire_cis",
    offer_id="110_diamonds",
    player_id="10619597246",
)


class _Client:
    def __init__(self, orders: list[dict[str, Any]] | Exception) -> None:
        self._orders = orders
        self.calls = 0

    async def list_orders(self, *, limit: int = 50, page: int = 1) -> list[dict[str, Any]]:
        self.calls += 1
        if isinstance(self._orders, Exception):
            raise self._orders
        return self._orders


async def test_it_finds_the_order_that_appeared_after_we_gave_up() -> None:
    """The whole point: the create landed, late, and is findable."""
    client = _Client([_topup("ord-1525578", created=NOW)])

    found = await find_order(_as_client(client), key=TOPUP_KEY, since=TASK_STARTED)

    assert found is not None
    assert found["id"] == "ord-1525578"


async def test_it_refuses_an_earlier_identical_purchase() -> None:
    """Two identical orders 90 seconds apart, both completed — the real case.

    Without the ``since`` bound the second task would adopt the first order
    and report somebody else's delivery as its own.
    """
    earlier = _topup("ord-1525556", created=TASK_STARTED - timedelta(seconds=62))
    client = _Client([earlier])

    found = await find_order(_as_client(client), key=TOPUP_KEY, since=TASK_STARTED)

    assert found is None


async def test_it_picks_ours_when_both_are_listed() -> None:
    """Newest first, as NOVA returns them — the recent one wins and the older
    identical one is passed over rather than stopping the scan."""
    client = _Client(
        [
            _topup("ord-1525578", created=NOW),
            _topup("ord-1525556", created=TASK_STARTED - timedelta(seconds=62)),
        ]
    )

    found = await find_order(_as_client(client), key=TOPUP_KEY, since=TASK_STARTED)

    assert found is not None
    assert found["id"] == "ord-1525578"


async def test_a_different_player_is_not_a_match() -> None:
    """Same game, same offer, same minute, different buyer."""
    client = _Client([_topup("ord-9", created=NOW, player="99999999")])

    assert await find_order(_as_client(client), key=TOPUP_KEY, since=TASK_STARTED) is None


async def test_a_refusal_reads_as_not_found_but_an_outage_propagates() -> None:
    """They mean opposite things to a caller deciding whether an order exists.

    A refusal is an answer: "no such thing". An outage is the absence of an
    answer, and treating it as "never happened" would fail a task because
    NOVA was unreachable — inviting the second purchase this path prevents.
    """
    refused = _Client(NovaError("nope", status=400))
    assert await find_order(_as_client(refused), key=TOPUP_KEY, since=TASK_STARTED) is None

    down = _Client(NovaUnavailableError("ReadTimeout"))
    with pytest.raises(NovaUnavailableError):
        await find_order(_as_client(down), key=TOPUP_KEY, since=TASK_STARTED)


async def test_an_unusable_key_never_reaches_the_supplier() -> None:
    """A half-built key matches somebody else's order rather than none, so it
    is refused before the request rather than after the match."""
    client = _Client([_topup("ord-1", created=NOW)])

    found = await find_order(
        _as_client(client),
        key=AdoptKey(kind="topup", category_id="free_fire_cis", offer_id="110_diamonds"),
        since=TASK_STARTED,
    )

    assert found is None
    assert client.calls == 0


async def test_fragment_orders_match_on_the_key_we_sent() -> None:
    """Stars and Premium carry ``idempotency_key`` back, which makes those two
    exact rather than inferred from what the order looks like."""
    assert key_is_usable(AdoptKey(kind="STARS", idempotency_key="task-1"))
    assert not key_is_usable(AdoptKey(kind="STARS"))


async def test_every_kind_states_what_it_needs() -> None:
    assert key_is_usable(AdoptKey(kind="steam_topup", steam_login="someone"))
    assert not key_is_usable(AdoptKey(kind="steam_topup"))
    assert key_is_usable(
        AdoptKey(kind="gift_card", category_id="roblox_global", card_id="50_robux")
    )
    assert not key_is_usable(AdoptKey(kind="gift_card", category_id="roblox_global"))
    # An unknown kind is never usable — a new NOVA order kind must be taught
    # how to match before it can be adopted, not adopted on a guess.
    assert not key_is_usable(AdoptKey(kind="something_new"))


def _as_client(client: _Client) -> Any:
    """The real parameter is a ``NovaClient``; the fake only implements the one
    method this module calls, and typing it as the real thing would be a lie."""
    return client


async def test_a_gift_card_matches_on_card_and_quantity() -> None:
    """Quantity is part of the match: their gift-card endpoint takes a real
    one, so two orders for the same card can differ only by it."""
    order = {
        "id": "ord-1527495",
        "kind": "gift_card",
        "category_id": "roblox_global",
        "card_id": "50_robux",
        "quantity": 2,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    key = AdoptKey(kind="gift_card", category_id="roblox_global", card_id="50_robux", quantity=2)

    assert await find_order(_as_client(_Client([order])), key=key, since=TASK_STARTED) is not None

    wrong = AdoptKey(kind="gift_card", category_id="roblox_global", card_id="50_robux", quantity=1)
    assert await find_order(_as_client(_Client([order])), key=wrong, since=TASK_STARTED) is None


async def test_steam_matches_on_the_login_and_its_own_timestamp_key() -> None:
    """Steam orders spell it ``createdAt``, not ``created_at`` — reading only
    one of the two would make every Steam order look undatable and adoptable
    regardless of when it happened."""
    order = {
        "id": "ord-1526612",
        "kind": "steam_topup",
        "steamLogin": "HurrySDM",
        "createdAt": NOW.isoformat().replace("+00:00", "Z"),
    }
    key = AdoptKey(kind="steam_topup", steam_login="HurrySDM")

    assert await find_order(_as_client(_Client([order])), key=key, since=TASK_STARTED) is not None

    old = dict(order, createdAt=(TASK_STARTED - timedelta(minutes=5)).isoformat())
    assert await find_order(_as_client(_Client([old])), key=key, since=TASK_STARTED) is None


async def test_fragment_matches_on_the_key_we_sent_not_on_looks() -> None:
    """Stars and Premium echo the ``Idempotency-Key`` back, which makes these
    exact — two identical Stars orders are told apart by it and nothing else."""
    mine = {
        "id": "ord-1",
        "kind": "STARS",
        "idempotency_key": "task-1",
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    theirs = dict(mine, id="ord-2", idempotency_key="task-2")
    key = AdoptKey(kind="STARS", idempotency_key="task-1")

    found = await find_order(_as_client(_Client([theirs, mine])), key=key, since=TASK_STARTED)

    assert found is not None
    assert found["id"] == "ord-1"


async def test_an_order_with_no_readable_timestamp_is_still_adoptable() -> None:
    """The time bound can only reject what it can read.

    A missing or malformed timestamp must not silently drop an order that
    matches on every identifying field — that would leave a delivered order
    unadopted, which is the failure this whole path exists to prevent.
    """
    undated = {
        "id": "ord-1",
        "kind": "topup",
        "category_id": "free_fire_cis",
        "offer_id": "110_diamonds",
        "fields": {"player_id": "10619597246"},
    }
    assert (
        await find_order(_as_client(_Client([undated])), key=TOPUP_KEY, since=TASK_STARTED)
        is not None
    )

    malformed = dict(undated, created_at="the day before yesterday")
    assert (
        await find_order(_as_client(_Client([malformed])), key=TOPUP_KEY, since=TASK_STARTED)
        is not None
    )


async def test_a_different_kind_never_matches() -> None:
    """A gift card and a top-up can share a category id; the kind is what
    keeps one from being adopted as the other."""
    card = {
        "id": "ord-1",
        "kind": "gift_card",
        "category_id": "free_fire_cis",
        "offer_id": "110_diamonds",
        "fields": {"player_id": "10619597246"},
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }

    assert await find_order(_as_client(_Client([card])), key=TOPUP_KEY, since=TASK_STARTED) is None
