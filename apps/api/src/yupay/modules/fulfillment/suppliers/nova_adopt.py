"""Finding a NOVA order whose create response we never saw.

NOVA charges on create. When that call times out the money is already gone,
the order may or may not exist yet, and until 2026-09-23 we had no way to ask
— so the task failed, the customer's line failed, and an operator had to find
the order in NOVA's panel and settle it by hand.

Production order ``01a0cd88`` is the case this exists for. Our request went
out at 09:11:51 and timed out at 09:12:11; NOVA created the order at
**09:12:19** — eight seconds *after* we gave up — and delivered it. A one-shot
lookup at timeout time would have missed it, which is why adoption belongs on
the poll path and not only at create time.

``GET /api/v2/orders`` takes ``page`` and ``limit`` and no filters at all, so
the matching happens here. Every order kind carries enough to identify one of
ours exactly:

- ``topup`` — ``category_id`` + ``offer_id`` + ``fields.player_id``
- ``gift_card`` — ``category_id`` + ``card_id`` + ``quantity``
- ``steam_topup`` — ``steamLogin``
- ``STARS`` / ``PREMIUM`` — ``idempotency_key``, the one we sent, which makes
  those two exact rather than inferred

The time bound is what stops a match being a *previous* order for the same
player and offer. That is not hypothetical either: on the same morning the
same customer bought the same 110 Diamonds twice, 90 seconds apart, and both
NOVA orders were completed. Matching without a lower bound would have let the
second task adopt the first order and report a delivery that belonged to
somebody else's line.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.nova_client import NovaError

if TYPE_CHECKING:
    from yupay.modules.fulfillment.suppliers.nova_client import NovaClient

log = get_logger("yupay.fulfillment.nova_adopt")

#: How far back a probe reads. Fifty is two pages of a busy morning and one
#: request; the orders we look for are minutes old, never hours.
_PAGE_SIZE = 50

#: How long an id-less task keeps looking. NOVA produced the order eight
#: seconds after our timeout, so this is generous by two orders of magnitude
#: on purpose: the cost of looking is one request per poll, and the cost of
#: giving up early is a delivered order recorded as a failure.
ADOPT_WINDOW_MINUTES = 30


@dataclass(frozen=True, slots=True)
class AdoptKey:
    """What identifies one of our orders in NOVA's list.

    ``kind`` picks the predicate; the rest are the values that kind matches
    on. A key with nothing to match on is never built — see
    :func:`key_is_usable` — because a predicate that compares two ``None``\\ s
    matches every order NOVA has.
    """

    kind: str
    category_id: str = ""
    offer_id: str = ""
    player_id: str = ""
    card_id: str = ""
    quantity: int = 1
    steam_login: str = ""
    idempotency_key: str = ""


def key_is_usable(key: AdoptKey) -> bool:
    """Whether this key names an order precisely enough to adopt on.

    The guard exists because the alternative is silent: a key missing its
    identifying half still compares equal to some order, and adopting the
    wrong one reports a delivery that never happened for this line.
    """
    if key.kind in ("STARS", "PREMIUM"):
        return bool(key.idempotency_key)
    if key.kind == "steam_topup":
        return bool(key.steam_login)
    if key.kind == "gift_card":
        return bool(key.category_id and key.card_id)
    if key.kind == "topup":
        return bool(key.category_id and key.offer_id and key.player_id)
    return False


def _matches(order: dict[str, Any], key: AdoptKey) -> bool:
    """Whether one of NOVA's orders is the one this key describes."""
    if str(order.get("kind") or "") != key.kind:
        return False
    if key.kind in ("STARS", "PREMIUM"):
        return str(order.get("idempotency_key") or "") == key.idempotency_key
    if key.kind == "steam_topup":
        return str(order.get("steamLogin") or "") == key.steam_login
    if key.kind == "gift_card":
        return (
            str(order.get("category_id") or "") == key.category_id
            and str(order.get("card_id") or "") == key.card_id
            and int(order.get("quantity") or 1) == key.quantity
        )
    fields = order.get("fields")
    player = str((fields or {}).get("player_id") or "") if isinstance(fields, dict) else ""
    return (
        str(order.get("category_id") or "") == key.category_id
        and str(order.get("offer_id") or "") == key.offer_id
        and player == key.player_id
    )


def _created_at(order: dict[str, Any]) -> datetime | None:
    """Their timestamp, under whichever of the two names this kind uses."""
    raw = order.get("created_at") or order.get("createdAt")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


async def find_order(
    client: NovaClient, *, key: AdoptKey, since: datetime
) -> dict[str, Any] | None:
    """The order this key describes, created at or after ``since``.

    ``since`` is the bound that makes a match *this* line's order rather than
    an earlier identical purchase — see the module docstring for the morning
    that made the point.

    A clean refusal (:class:`NovaError`) reads as not-found: the supplier
    answered and its answer was "no". :class:`NovaUnavailableError` is left to
    propagate, because an outage and a genuine absence mean opposite things to
    a caller deciding whether an order was ever placed.

    Raises:
        NovaUnavailableError: NOVA could not be reached at all.
    """
    if not key_is_usable(key):
        return None
    try:
        orders = await client.list_orders(limit=_PAGE_SIZE)
    except NovaError:
        return None
    for order in orders:
        if not _matches(order, key):
            continue
        created = _created_at(order)
        if created is not None and created < since:
            # An older order that looks identical — a repeat purchase, not
            # ours. Keep scanning rather than stopping: the list is newest
            # first, so anything past here is older still, but the loop stays
            # honest about what it rejected.
            continue
        log.info(
            "nova.adopted_order",
            order_id=str(order.get("id") or ""),
            kind=key.kind,
            status=str(order.get("status") or ""),
        )
        return order
    return None


__all__ = ["ADOPT_WINDOW_MINUTES", "AdoptKey", "find_order", "key_is_usable"]
