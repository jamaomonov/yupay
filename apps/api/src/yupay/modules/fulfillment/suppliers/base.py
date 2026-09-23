"""Fulfiller protocol.

Every supplier (mock, Steam, Riot, PUBG/Tencent, Spotify, Apple, in-house voucher
warehouse) implements this contract. The saga in ``fulfillment.service`` is
otherwise supplier-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.fulfillment.models import FulfillmentTask
    from yupay.modules.orders.models import Order, OrderItem


FulfillOutcome = Literal["succeeded", "in_progress", "failed"]
ArtifactKind = Literal["voucher_code", "topup_receipt", "license_key"]


class MoneyOutcome(StrEnum):
    """What became of the money we spend upstream, on an order that failed.

    **This is the source of truth.** Two adapters have recorded the same
    distinction for a while in ``extra_metadata`` — G-Engine writes
    ``supplier_refunded`` from a real ``is_refunded`` field, Waxpeer writes
    ``supplier_refunded`` for a ``canceled`` top-up and ``needs_reconciliation``
    for an ``error`` one. Those keys are still written, because runbooks and
    the admin inbox read them, but they are the older, untyped spelling of
    this enum and only cover the two adapters that happened to think of it.
    Anything deciding what to do about the money reads this value.

    The one thing that must not blur is the difference between the last two.
    ``UNKNOWN`` is not a polite ``SPENT``: M3a shipped an ``attempt_delivered``
    boolean that read "no" where the truth was "we cannot tell", and a retry
    policy acted on it. Neither value may drive an automatic refund, but they
    say different things to the human who ends up looking at the order.

    Attributes:
        RETURNED: Our money is with us. Either the supplier refunded it, or
            the failure happened before anything was ever debited. The only
            value an automatic refund may fire on.
        SPENT: We know the money is gone — the supplier kept it, or delivered
            something partial and will not give the rest back. A human decides
            what the customer or merchant gets.
        UNKNOWN: We cannot tell. The supplier exposes no refund field, or the
            call that spends failed in a way that leaves both answers open. A
            human finds out; nothing is refunded on a guess.
    """

    RETURNED = "returned"
    SPENT = "spent"
    UNKNOWN = "unknown"


class FulfillerError(Exception):
    """Non-recoverable supplier error.

    ``fulfillment.service.process_task`` catches this and marks the task
    ``failed``, so raising one ends an order exactly as terminally as
    returning ``outcome="failed"`` does — which is why the money question is
    answered here too, and why it has no default.

    Args:
        message: What went wrong, as it will land in ``task.last_error``.
        money_outcome: What became of our money at this exit. Most raise sites
            are refusals that happen before any call goes out, and those are
            :attr:`MoneyOutcome.RETURNED`; a failure on or after the call that
            spends is usually :attr:`MoneyOutcome.UNKNOWN`.
    """

    def __init__(self, message: str, *, money_outcome: MoneyOutcome) -> None:
        super().__init__(message)
        self.money_outcome = money_outcome


class FulfillerNotIntegratedError(NotImplementedError):
    """Raised by stub suppliers that haven't been hooked up yet.

    The rule for every site, ``cancel`` included: **answer for the exit you
    are standing at, not for the method's name.** A cancel refusal never ends
    a task — ``fulfillment.service._apply_cancel`` records it and cancels
    locally — so the value is unread today, and picking one word for all three
    ``cancel`` sites would mean writing the same answer over two different
    facts. A stub has never contacted anyone on any method, so nothing it
    raises can have spent our money; G-Engine and Waxpeer have already bought
    the thing this call is declining to unbuy, and cannot say what became of
    it. That is the same grading the rest of the package uses, applied
    somewhere it happens not to be read yet.

    Args:
        message: The "not built yet" note the admin inbox shows.
        money_outcome: As :class:`FulfillerError`, under the rule above.
    """

    def __init__(self, message: str, *, money_outcome: MoneyOutcome) -> None:
        super().__init__(message)
        self.money_outcome = money_outcome


@dataclass(frozen=True)
class FulfillResult:
    """Return type of :meth:`Fulfiller.fulfill`.

    Attributes:
        money_outcome: What became of our money, on a terminal failure only.
            It has no default on purpose: every adapter decides for every
            failure it can produce, and mypy refuses a construction that
            forgets. ``None`` is the answer for a success, for something still
            in progress, and for the low-balance stall — which is a "failed"
            result the saga keeps the customer waiting on rather than a
            finished order (M3b Task 4 owns that one).
    """

    outcome: FulfillOutcome
    external_order_id: str | None
    artifact_kind: ArtifactKind | None
    artifact: dict[str, Any] | None
    error: str | None
    extra_metadata: dict[str, Any]
    money_outcome: MoneyOutcome | None

    def __post_init__(self) -> None:
        _reject_money_on_a_non_failure(self.outcome, self.money_outcome)


@dataclass(frozen=True)
class FulfillStatus:
    """Return type of :meth:`Fulfiller.check_status`."""

    outcome: FulfillOutcome
    artifact_kind: ArtifactKind | None
    artifact: dict[str, Any] | None
    error: str | None
    #: As :attr:`FulfillResult.money_outcome`. A status discovered by the
    #: webhook/poll path ends a task just as a synchronous one does, so it
    #: answers the same question — and a re-wrap of another call's result must
    #: pass this through, not re-derive it.
    money_outcome: MoneyOutcome | None
    # Structured flags the reconciler merges onto ``task.extra_metadata`` — e.g.
    # ``needs_reconciliation`` / ``supplier_refunded`` / ``give_amount_shortfall_units``.
    # Mirrors ``FulfillResult.extra_metadata`` so a status discovered by the
    # webhook/poll path (the only path Waxpeer has) surfaces the same queryable
    # flags as one discovered synchronously, instead of only in ``last_error``.
    extra_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _reject_money_on_a_non_failure(self.outcome, self.money_outcome)


def _reject_money_on_a_non_failure(
    outcome: FulfillOutcome, money_outcome: MoneyOutcome | None
) -> None:
    """Refuse a money outcome on anything but a failure.

    A delivered order has no money question to answer — the goods arrived and
    the spend was the point. Claiming one here would put a value in front of
    M3b's refund path that nothing on the failure path ever wrote.
    """
    if money_outcome is not None and outcome != "failed":
        raise ValueError(f"money_outcome is only meaningful on a failure, not on {outcome!r}")


@runtime_checkable
class Fulfiller(Protocol):
    """Contract every supplier adapter must satisfy."""

    supplier: str

    @property
    def available(self) -> bool: ...

    async def fulfill(
        self,
        *,
        db: AsyncSession,
        order: Order,
        item: OrderItem,
        idempotency_key: str,
    ) -> FulfillResult: ...

    async def check_status(
        self,
        *,
        db: AsyncSession,
        task: FulfillmentTask,
    ) -> FulfillStatus: ...

    async def cancel(
        self,
        *,
        db: AsyncSession,
        task: FulfillmentTask,
    ) -> None: ...


def transport_error_text(exc: BaseException) -> str:
    """A readable description of a transport failure, never an empty string.

    Every ``httpx`` transport exception stringifies to ``""`` — ``ReadTimeout``,
    ``ConnectTimeout``, ``PoolTimeout`` and ``ReadError`` alike carry the fact
    in their *class*, not their message. Four supplier clients raised
    ``…UnavailableError(str(exc))`` on one, so the whole diagnosis was thrown
    away at the only point it existed.

    That is not cosmetic. On 2026-09-23 a NOVA top-up timed out after 20 s;
    NOVA had taken the money and delivered the diamonds, our task failed with
    ``last_error = ''``, and the ops alert said nothing at all — no supplier
    fault, no timeout, no clue. Reading the database was the only way to learn
    that the call had even left the building.

    Returns the exception's own message when it has one, and its class name
    when it does not, so "ReadTimeout" reaches the task row and the alert.
    """
    text = str(exc).strip()
    return text or type(exc).__name__
