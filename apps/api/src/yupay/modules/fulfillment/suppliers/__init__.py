"""Fulfiller registry.

Add a new supplier:
  1. Implement :class:`Fulfiller` in a new file under this package.
  2. Register it in :data:`REGISTRY` below.

Stubs (``steam``, ``riot``, ``pubg``, ``spotify``, ``apple``,
``voucher_inventory``) reserve their slugs so routes / docs / admin UI don't
need to shift when the real adapter arrives.
"""

from __future__ import annotations

from yupay.core.errors import NotFoundError
from yupay.modules.fulfillment.suppliers._stub import StubFulfiller
from yupay.modules.fulfillment.suppliers.base import (
    Fulfiller,
    FulfillerError,
    FulfillerNotIntegratedError,
    FulfillResult,
    FulfillStatus,
)
from yupay.modules.fulfillment.suppliers.g2b import G2bFulfiller
from yupay.modules.fulfillment.suppliers.manual import ManualFulfiller
from yupay.modules.fulfillment.suppliers.mock import MockFulfiller
from yupay.modules.fulfillment.suppliers.waxpeer import WaxpeerFulfiller

REGISTRY: dict[str, Fulfiller] = {
    "mock": MockFulfiller(),
    # Not a stub — manual fulfilment is a real path: the customer's order
    # parks in ``in_progress`` until an admin completes it via
    # ``/admin/fulfillment/tasks/{id}/complete``.
    "manual": ManualFulfiller(),
    # First real supplier — G2Bulk. ``available`` reads
    # ``settings.g2b_api_key`` at request time, so a hot-reloaded key flips
    # the adapter on without a process restart.
    "g2b": G2bFulfiller(),
    # Steam wallet top-ups. ``available`` reads ``settings.waxpeer_api_key``
    # at request time, same hot-reload behaviour as g2b above.
    "waxpeer": WaxpeerFulfiller(),
    "steam": StubFulfiller(
        supplier="steam",
        todo_message="Steam supplier not integrated yet; see ADR-0013.",
    ),
    "riot": StubFulfiller(
        supplier="riot",
        todo_message="Riot supplier not integrated yet; see ADR-0013.",
    ),
    "pubg": StubFulfiller(
        supplier="pubg",
        todo_message="PUBG/Tencent supplier not integrated yet; see ADR-0013.",
    ),
    "spotify": StubFulfiller(
        supplier="spotify",
        todo_message="Spotify supplier not integrated yet; see ADR-0013.",
    ),
    "apple": StubFulfiller(
        supplier="apple",
        todo_message="Apple supplier not integrated yet; see ADR-0013.",
    ),
    "voucher_inventory": StubFulfiller(
        supplier="voucher_inventory",
        todo_message=(
            "In-house voucher warehouse not built yet; see ADR-0013 and the "
            "future `inventory` module."
        ),
    ),
}


def get_fulfiller(supplier: str) -> Fulfiller:
    """Look up a fulfiller by slug. 404 if unknown."""
    f = REGISTRY.get(supplier.lower())
    if f is None:
        raise NotFoundError(f"unknown fulfilment supplier: {supplier}")
    return f


def available_suppliers() -> list[str]:
    """Return slugs of suppliers that can actually run right now."""
    return [slug for slug, f in REGISTRY.items() if f.available]


__all__ = [
    "REGISTRY",
    "FulfillResult",
    "FulfillStatus",
    "Fulfiller",
    "FulfillerError",
    "FulfillerNotIntegratedError",
    "G2bFulfiller",
    "ManualFulfiller",
    "MockFulfiller",
    "StubFulfiller",
    "WaxpeerFulfiller",
    "available_suppliers",
    "get_fulfiller",
]
