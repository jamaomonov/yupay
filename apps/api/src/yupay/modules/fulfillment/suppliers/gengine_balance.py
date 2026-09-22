"""Whether G-Engine will take our money, asked before we ask them to.

Split out of ``gengine.py`` so ``gengine_gifts`` can use it too: that module is
imported *by* the adapter, so it cannot import back without a cycle. The same
shape ``nova_grading`` has, and for the same reason.

Three suppliers grade a "top up your wallet" refusal into the saga's one soft
failure, and G-Engine is the odd one out in how it knows. G2B and NOVA read
the refusal's text; we have never seen G-Engine's. Production order
``01a0c95b`` refused payment on 2026-09-22 and left behind nothing but
``g-engine HTTP 400``, because the envelope carrying their ``message`` was
never recorded. So here the balance endpoint is the mechanism and the word
list is the safety net — the reverse of NOVA, deliberately.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.base import FulfillResult
from yupay.modules.fulfillment.suppliers.gengine_client import (
    GEngineClient,
    GEngineError,
)

log = get_logger("yupay.fulfillment.gengine")

#: Must equal ``fulfillment.service._LOW_BALANCE_ERROR``. The saga keys on this
#: exact string to park the task in the admin inbox while the customer's line
#: stays ``in_progress`` — an empty wallet is not a failed sale, it is a sale
#: waiting for a top-up. Duplicated rather than imported for the same reason
#: ``nova_grading`` duplicates it: an adapter importing the saga inverts the
#: dependency.
LOW_BALANCE_ERROR = "supplier_low_balance"

#: Same pair rule as ``nova_grading._LOW_BALANCE_WORDS``, and for a weaker
#: reason: with NOVA we had their real sentence in hand, here we have never
#: seen G-Engine's. Production order ``01a0c95b`` refused payment on
#: 2026-09-22 with nothing but ``g-engine HTTP 400`` recorded, because their
#: envelope's ``message`` never reached the log — so these words are a guess.
#: That is why this is only the **backstop**: :func:`_afford` asks their
#: balance endpoint outright and does not depend on any wording at all. A
#: false positive here only demotes a hard failure to a retryable stall,
#: which is the safer mistake in both directions.
_LOW_BALANCE_WORDS = ("insufficient", "not enough", "too low", "недостаточно")
_LOW_BALANCE_PHRASES = ("insufficient funds", "no funds", "недостаточно средств")


def looks_like_low_balance(exc: GEngineError) -> bool:
    """Whether a refusal is a "top up your wallet" one.

    Reads ``exc.body`` rather than only the message because the message is
    just ``g-engine HTTP <status>`` — their reason lives in the JSON envelope
    the body carries.
    """
    text = f"{exc} {exc.body}".lower()
    if any(phrase in text for phrase in _LOW_BALANCE_PHRASES):
        return True
    return ("balance" in text or "баланс" in text) and any(
        word in text for word in _LOW_BALANCE_WORDS
    )


async def afford(client: GEngineClient, required: float) -> Decimal | None:
    """Our wallet balance when it cannot cover ``required``; ``None`` if it can.

    ``None`` also covers "we could not find out" — an unreachable balance
    endpoint, a malformed number, a price of zero. A pre-flight that blocked
    a sale because a *probe* failed would be worse than the problem it exists
    to prevent, so every uncertainty here falls through to the real call and
    lets its answer decide.

    Why pre-flight at all, when :func:`_looks_like_low_balance` would catch
    the refusal anyway: their order is created unpaid and paid a tick later,
    so a refusal at the pay step leaves a reserved order and a scary generic
    alert, and it costs a round trip to their most expensive endpoint. Asking
    a cheap ``GET /users/balance`` first turns that into a clean stall with a
    number in it.
    """
    if required <= 0:
        return None
    try:
        data = await client.get_balance()
    except Exception:  # noqa: BLE001 -- a probe must never block a sale
        # Deliberately wider than ``GEngineError | GEngineUnavailableError``,
        # for the same reason G2B's ``_check_balance_or_none`` is: this is an
        # optional question asked before the real call, and *any* way it can
        # fail — a changed payload shape, a client that does not implement it —
        # must fall through to the purchase rather than refuse a sale we could
        # have made. The refusal path below is what catches a genuinely empty
        # wallet when this cannot answer.
        return None
    raw = data.get("balance")
    if raw is None:
        return None
    try:
        current = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return current if current < Decimal(str(required)) else None


def low_balance_result(
    *,
    current_balance: Decimal | None,
    required: float | None,
    mapping: Any | None,
    source: str,
    supplier_message: str = "",
) -> FulfillResult:
    """The soft failure the saga parks in the inbox and alerts on.

    Metadata keys are the ones ``_maybe_alert_low_balance`` renders — get one
    wrong and the alert prints ``$?`` where a number belongs.
    """
    extra: dict[str, Any] = {
        "supplier": "gengine",
        "low_balance": True,
        # Two decimals, not ``str(Decimal)``: the alert renders this straight
        # after a "$" and ``Decimal("0.1")`` prints as "$0.1", which does not
        # read as money next to the "$0.60" beside it.
        "current_balance": f"{current_balance:.2f}" if current_balance is not None else None,
        "required": f"{required:.2f}" if required else None,
        "source": source,
    }
    if mapping is not None:
        extra["external_product_id"] = mapping.external_product_id
        extra["external_variant_id"] = mapping.external_variant_id
    if supplier_message:
        # Their own sentence, the only evidence about a refusal nobody can
        # reproduce. ``_maybe_alert_low_balance`` HTML-escapes it.
        extra["supplier_message"] = supplier_message[:500]
    return FulfillResult(
        outcome="failed",
        external_order_id=None,
        artifact_kind=None,
        artifact=None,
        error=LOW_BALANCE_ERROR,
        extra_metadata=extra,
        # Deliberately unclassified: nothing was spent and the order is not
        # finished failing — an operator tops up and retries it.
        money_outcome=None,
    )


__all__ = [
    "LOW_BALANCE_ERROR",
    "afford",
    "log_shortfall",
    "looks_like_low_balance",
    "low_balance_result",
]


def log_shortfall(*, order_id: int | str | None, balance: Decimal, required: float) -> None:
    """One line, one shape, wherever the pre-flight refuses.

    Four call sites wrote this by hand; a fifth would have written it slightly
    differently and the Loki query would have quietly stopped matching.
    """
    log.warning(
        "gengine.low_balance_preflight",
        order_id=order_id,
        balance=f"{balance:.2f}",
        required=required,
    )
