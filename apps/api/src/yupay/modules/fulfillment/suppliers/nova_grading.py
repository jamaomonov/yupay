"""How a NOVA order is read, and what it says about our money.

Split out of ``nova.py`` when that file passed the 500-line mark: everything
here is **pure** — it takes their order object, or their error, and answers a
question about it. Nothing in this module talks to NOVA, to the database, or to
an order row, which is exactly why it is the half that moved.

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
from yupay.modules.fulfillment.suppliers.base import (
    FulfillerError,
    FulfillResult,
    MoneyOutcome,
)
from yupay.modules.fulfillment.suppliers.nova_client import NovaError

#: The same logger name the adapter uses: these events are documented in the
#: runbook as ``nova.*`` and moving them to a second name would break the one
#: table an operator greps.
log = get_logger("yupay.fulfillment.nova")


#: Must equal ``fulfillment.service._LOW_BALANCE_ERROR`` — the saga keys on
#: this exact string to keep the customer on "processing", park the task in the
#: admin inbox and alert ops instead of failing the order. A guard test locks
#: the match (see ``test_supplier_money_outcome.py``).
LOW_BALANCE_ERROR = "supplier_low_balance"


#: Phrases that mean "top up your wallet", matched against their refusal text.
#:
#: **Observed, not guessed**: NOVA answers `400 "Insufficient internal balance"`
#: — confirmed on 2026-09-18 by asking for a $39.78 top-up against a $9.10
#: wallet, which costs nothing because it is refused. The three substrings this
#: started with were copied from Waxpeer's sniffer and **none of them match
#: that sentence**: "insufficient balance" is not in "insufficient internal
#: balance". So the first time a Free Fire order outran the wallet, the refusal
#: would have been graded `RETURNED` and the order hard-failed — a customer
#: blocked, where the whole point of this path is to park the order and page
#: ops for a top-up.
#:
#: Hence a pair rule rather than a phrase list: "balance" plus a word that says
#: there is not enough of it. A false positive only demotes a hard failure to a
#: retryable stall, which is the safer mistake.
_LOW_BALANCE_WORDS = ("insufficient", "not enough", "too low")
_LOW_BALANCE_PHRASES = ("insufficient funds", "no funds")

#: Their sentence when the shortfall is **theirs**, not ours: `400 "Service
#: balance is insufficient to complete this order"`. Observed 2026-09-20 in
#: NOVA's own dashboard, which refused a $19 Steam top-up while showing a
#: $112.75 wallet — so it cannot be read as "top up your wallet".
#:
#: Both sentences park the order the same way; what differs is the only thing
#: the operator actually needs, which is whether there is anything for them to
#: do. Calling "their upstream is dry" a low balance and printing "пополни
#: счёт" sent a real operator to look at a balance that was already fine.
_SERVICE_SHORTFALL_PHRASES = ("service balance",)

#: Who is short. ``ours`` is actionable — top up. ``supplier`` is not.
SHORTFALL_OURS = "ours"
SHORTFALL_SUPPLIER = "supplier"

_IN_FLIGHT = frozenset(
    {
        "pending",
        "preparing",
        "prepared",
        "debited",
        "processing",
        "in_progress",
        "created",
        "queued",
        "new",
    }
)
_SUCCESS = frozenset({"completed", "success", "delivered", "done"})
_REFUNDED = frozenset({"refunded", "refund"})
_FAILED = frozenset({"failed", "error", "cancelled", "canceled"})

#: A refusal raised before any call, or one their API answered with — nothing
#: was charged.
_NOTHING_SPENT = MoneyOutcome.RETURNED
#: A failure on or after the call that spends.
_MAY_HAVE_SPENT = MoneyOutcome.UNKNOWN


def _status_of(obj: dict[str, Any]) -> str:
    """Their order status, lowercased. ``""`` when the object carries none.

    Reads ``status`` then ``state``. The warning is how we learn their real
    shape from the first live order — their spec types this object as ``{}``.
    """
    raw = obj.get("status") or obj.get("state") or ""
    text = str(raw).strip().lower()
    if not text:
        log.warning("nova.order_without_status", keys=sorted(str(k) for k in obj)[:10])
    return text


def _order_id_of(obj: dict[str, Any]) -> str | None:
    """Their order id, as a string. ``None`` when we cannot find one."""
    for key in ("id", "order_id", "public_id", "uuid"):
        value = obj.get(key)
        if value not in (None, ""):
            return str(value)
    log.warning("nova.order_without_id", keys=sorted(str(k) for k in obj)[:10])
    return None


def _looks_like_low_balance(exc: NovaError) -> bool:
    """Whether a refusal is a "top up your balance" one.

    They document no code for it, so the message is all there is. See
    :data:`_LOW_BALANCE_WORDS` for why this is a pair rule and not a list of
    whole phrases — the phrase list it replaced missed their real sentence.
    """
    text = f"{exc} {exc.body} {exc.code}".lower()
    if any(phrase in text for phrase in _LOW_BALANCE_PHRASES):
        return True
    return "balance" in text and any(word in text for word in _LOW_BALANCE_WORDS)


def _refusal_money(exc: NovaError) -> MoneyOutcome:
    """What a refusal says about our money.

    400/403/404 are refusals of the request itself — an unknown category or
    offer, a malformed field, an inactive subscription — and they happen before
    anything is charged. A 409 is their idempotency refusal, and their two
    descriptions of it disagree (the endpoint says a reused key returns the
    original order, the parameter says it is rejected), so it cannot tell us
    whether the first attempt charged us. 5xx is the same kind of open
    question with a different cause.
    """
    return _NOTHING_SPENT if exc.status in (400, 403, 404) else _MAY_HAVE_SPENT


def _receipt(order_id: str | None, status: str) -> dict[str, Any]:
    """What the customer sees. Deliberately thin: a top-up has no code to hand
    over, only proof that it happened."""
    return {"supplier": "nova", "external_order_id": order_id, "status": status}


def _charged_usd(obj: dict[str, Any]) -> str | None:
    """What they say they took, as a decimal string, or ``None``.

    ``chargedUsd`` is what a fetched order carries and what the client folds a
    create's ``novaDebit`` into; ``charged_usd`` is the snake-case twin their
    API also returns. For a game these equal the price; for Steam they do not,
    which is the whole point of recording them.
    """
    for key in ("chargedUsd", "charged_usd"):
        value = obj.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _meta(status: str, obj: dict[str, Any]) -> dict[str, Any]:
    charged = _charged_usd(obj)
    return {
        "supplier": "nova",
        "nova_status": status,
        **({"supplier_charged_usd": charged} if charged else {}),
    }


def _without_our_inputs(text: str, fields: dict[str, str]) -> str:
    """Their refusal text with everything we submitted taken back out.

    Their message is the one thing that makes a refusal actionable — "offer not
    available for this category" is worth putting in front of an operator. But
    it travels into ``task.last_error`` and the attempt log, and a supplier's
    "player 1313232551 not found" would put a customer's id there, which §9
    forbids. We know the exact values we sent, so this is an exact redaction
    rather than a guess at what an identifier looks like.

    Args:
        text: The refusal as the client reported it.
        fields: Exactly what we sent them, by their field name.

    Returns:
        The same text with each submitted value replaced by an ellipsis. Values
        shorter than three characters are left alone — they are server ids like
        ``"1"`` whose substring would blank half the sentence.
    """
    for value in fields.values():
        if len(value) >= 3:
            text = text.replace(value, "…")
    return text


def _shortfall_side(exc: NovaError) -> str:
    """Whose balance is short — see :data:`_SERVICE_SHORTFALL_PHRASES`."""
    text = f"{exc} {exc.body} {exc.code}".lower()
    if any(phrase in text for phrase in _SERVICE_SHORTFALL_PHRASES):
        return SHORTFALL_SUPPLIER
    return SHORTFALL_OURS


def _low_balance_result(
    *, message: str, side: str, our_balance: str | None = None
) -> FulfillResult:
    """A soft low-balance failure the saga parks in the inbox and alerts on.

    Carries three things it used to throw away, and the throwing away is why
    an operator with a funded wallet spent an evening wondering why we said
    it was empty:

    * ``supplier_message`` — their own sentence, which is the only evidence
      anyone has about a refusal they cannot reproduce;
    * ``shortfall`` — whether the missing money is ours or theirs;
    * ``current_balance`` — what our wallet actually held, so the alert can
      print a number instead of the ``$?`` it printed before.
    """
    extra: dict[str, Any] = {
        "supplier": "nova",
        "shortfall": side,
        "supplier_message": message[:500],
    }
    if our_balance is not None:
        extra["current_balance"] = our_balance
    return FulfillResult(
        outcome="failed",
        external_order_id=None,
        artifact_kind=None,
        artifact=None,
        error=LOW_BALANCE_ERROR,
        extra_metadata=extra,
        # Deliberately unclassified: the order is not finished failing.
        money_outcome=None,
    )


def _result(obj: dict[str, Any]) -> FulfillResult:
    """Interpret one order object into a fulfilment result."""
    status = _status_of(obj)
    order_id = _order_id_of(obj)
    if status in _SUCCESS:
        return FulfillResult(
            outcome="succeeded",
            external_order_id=order_id,
            artifact_kind="topup_receipt",
            artifact=_receipt(order_id, status),
            error=None,
            extra_metadata=_meta(status, obj),
            money_outcome=None,
        )
    if status in _REFUNDED:
        return FulfillResult(
            outcome="failed",
            external_order_id=order_id,
            artifact_kind=None,
            artifact=None,
            error=f"nova refunded the order ({status})",
            extra_metadata={**_meta(status, obj), "supplier_refunded": True},
            money_outcome=MoneyOutcome.RETURNED,
        )
    if status in _FAILED:
        # `fail_reason` is a real field on their order (null on a healthy one,
        # observed on the first live order) and it is the only thing that tells
        # an operator *why* — without it the inbox says "nova order failed" and
        # the next step is a shell.
        reason = str(obj.get("fail_reason") or "").strip()
        return FulfillResult(
            outcome="failed",
            external_order_id=order_id,
            artifact_kind=None,
            artifact=None,
            error=f"nova order {status}" + (f": {reason}" if reason else ""),
            extra_metadata={
                **_meta(status, obj),
                "needs_reconciliation": True,
                **({"nova_fail_reason": reason} if reason else {}),
            },
            money_outcome=_MAY_HAVE_SPENT,
        )
    if status and status not in _IN_FLIGHT:
        # The one signal that our allow-list is out of date. Their order object
        # is untyped in their own spec, so these four sets are a guess made from
        # their prose — this line is what turns the guess into a fact the first
        # time a real order walks a word we did not anticipate, and it is what
        # the runbook's "first live order" step reads. Still `in_progress`
        # either way: an unknown word must not end a task in either direction.
        log.warning(
            "nova.unknown_order_status",
            status=status,
            hint="not in nova.py's status allow-list; treating it as still in "
            "flight. Add it to the right set once its meaning is known.",
        )
    # Everything else, including a status we have never seen: still moving.
    return FulfillResult(
        outcome="in_progress",
        external_order_id=order_id,
        artifact_kind=None,
        artifact=None,
        error=None,
        extra_metadata=_meta(status, obj),
        money_outcome=None,
    )


def _finish(obj: dict[str, Any]) -> FulfillResult:
    """``_result`` plus the guard both create paths need.

    Their create spends. An id-less "still moving" result would be a task
    nothing can ever finish: ``check_status`` has nothing to look the order up
    with, so it answers ``in_progress`` forever, the reconciler re-runs it
    every sixty seconds without changing anything, and the customer sits on
    "в обработке" while NOVA keeps the money. Their order object is untyped in
    their own spec, so this is not hypothetical — it is what an unread
    envelope looks like. Fail loudly instead: the inbox is where a human can
    chase it, and ``UNKNOWN`` is the honest grade because the charge may well
    have landed.
    """
    result = _result(obj)
    if result.outcome == "in_progress" and result.external_order_id is None:
        raise FulfillerError(
            "nova accepted the order but returned no id we could read — "
            "the charge may have landed; reconcile it by hand",
            money_outcome=_MAY_HAVE_SPENT,
        )
    return result
