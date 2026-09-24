"""How a NOVA order is read, and what it says about our money.

Split out of ``nova.py`` when that file passed the 500-line mark, and split
again on 2026-09-24 when a second vendor turned up publishing the same order
shape: the logic now lives in ``panel_grading``, and this module is the NOVA
**binding** of it.

Everything here is still pure — it takes their order object, or their error,
and answers a question about it. Nothing in this module talks to NOVA, to the
database, or to an order row.

``nova.py`` is its only intended consumer. The underscore names are kept as
they were so the adapter and its tests read unchanged; treat them as internals
of the pair of files rather than a public surface.

The facts these functions encode were established by the first live order on
2026-09-17 and are documented in ``docs/runbooks/nova.md``: an order walks
``created -> processing -> completed``, its id is under ``id``, a reused
idempotency key is refused rather than replayed, and what they charged us is
not always what we asked them to deliver.
"""

from __future__ import annotations

from typing import Any

from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.base import FulfillResult
from yupay.modules.fulfillment.suppliers.panel_grading import (
    _MAY_HAVE_SPENT,
    _NOTHING_SPENT,
    LOW_BALANCE_ERROR,
    SHORTFALL_OURS,
    SHORTFALL_SUPPLIER,
    PanelGrader,
    looks_like_low_balance,
    refusal_money,
    shortfall_side,
    without_our_inputs,
)

#: The same logger name the adapter uses: these events are documented in the
#: runbook as ``nova.*`` and moving them to a second name would break the one
#: table an operator greps.
log = get_logger("yupay.fulfillment.nova")

#: The NOVA-flavoured grader. Every event it logs and every sentence it writes
#: is prefixed ``nova``, exactly as before the split.
_NOVA = PanelGrader("nova")

# The refusal readers are vendor-independent — they read an exception's text
# and status, and NovaError is a PanelError — so they are re-exported rather
# than wrapped.
_looks_like_low_balance = looks_like_low_balance
_refusal_money = refusal_money
_shortfall_side = shortfall_side
_without_our_inputs = without_our_inputs


def _status_of(obj: dict[str, Any]) -> str:
    """Their order status, lowercased. ``""`` when the object carries none."""
    return _NOVA.status_of(obj)


def _order_id_of(obj: dict[str, Any]) -> str | None:
    """Their order id, as a string. ``None`` when we cannot find one."""
    return _NOVA.order_id_of(obj)


def _low_balance_result(
    *,
    message: str,
    side: str,
    our_balance: str | None = None,
    required: str | None = None,
) -> FulfillResult:
    """A soft low-balance failure the saga parks in the inbox and alerts on."""
    return _NOVA.low_balance_result(
        message=message, side=side, our_balance=our_balance, required=required
    )


def _result(obj: dict[str, Any]) -> FulfillResult:
    """Interpret one order object into a fulfilment result."""
    return _NOVA.result(obj)


def _finish(obj: dict[str, Any]) -> FulfillResult:
    """:func:`_result` plus the guard both create paths need."""
    return _NOVA.finish(obj)


#: Re-exported for ``nova.py``, which has always imported its money constants
#: from here rather than reaching into the grading layer itself.
__all__ = [
    "LOW_BALANCE_ERROR",
    "SHORTFALL_OURS",
    "SHORTFALL_SUPPLIER",
    "_MAY_HAVE_SPENT",
    "_NOTHING_SPENT",
]
