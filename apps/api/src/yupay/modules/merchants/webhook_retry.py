"""What to do after one delivery attempt — the retry table, and nothing else.

Pure: no DB, no clock of its own, no sockets. :mod:`.webhook_delivery` owns
the I/O and calls in here for the decision, which is what makes the table
cheap to pin (``tests/unit/test_merchant_webhook_retry.py``) and impossible to
get subtly different between the success path and the crash path.

## The table is derived, not designed

:mod:`yupay.core.outbound_errors` already answers the only two questions a
retry policy has, and this module reads its answers rather than re-deriving
them from exception names:

- :attr:`~yupay.core.outbound_errors.OutboundError.delivery` — did their
  server get the request? ``RECEIVED`` means a retry **re-delivers** an event
  they already have, so it is terminal whatever else is true of the error.
  ``UNKNOWN`` means a retry *may* double-deliver: we retry anyway, because a
  webhook is at-least-once by nature, and the delivery id in the signed
  material (:func:`..signing.webhook_canonical_message`) is what lets the
  receiver act on that. ``NOT_SENT`` is blindly safe.
- the **family** — :class:`~yupay.core.outbound_errors.OutboundRefusedError`
  means the attempt ended on our side, so nothing about *this* row will change
  by trying again: the delivery row carries a ``url`` snapshot taken at
  enqueue, so even a merchant who fixes their endpoint does not fix this row.
  Terminal. :class:`~yupay.core.outbound_errors.OutboundUnreachableError`
  means their server did not answer, which is exactly the case a backoff is
  for.

The ``RECEIVED`` branch is **redundant today**, deliberately and not by
accident: both RECEIVED leaves happen to be refusals, so the family branch
under it reaches the same verdict and deleting it would change nothing. It is
kept for the configuration it exists for — a RECEIVED leaf in the *unreachable*
family, which the family branch would happily retry — and
``falsify_merchant_webhook_delivery.py``'s ``received_in_the_wrong_family``
moves one there to prove the branch bites. Same discipline as
``core.outbound._read_capped``'s two mitigations.

One class is special-cased against its own family, and it is the only one:
:class:`~yupay.core.outbound_errors.OutboundBrokenError` means the attempt
broke in a way neither side chose — **our** bug. It is terminal like its
siblings, but it must never reach the merchant's failure budget: counting it
auto-disables a working endpoint and tells the merchant, in the delivery log
they read, that we refused their URL.

## The status table

A ``2xx`` is delivered. ``408``, ``429`` and every ``5xx`` back off. Everything
else — a ``4xx`` that is not those two, and a redirect we deliberately do not
follow — is terminal: their endpoint rejected the delivery, and repeating it
changes nothing except how much of their error log we fill.

``Retry-After`` is honoured on the two statuses RFC 9110 defines it for
(``429`` and ``503``), clamped into ``[RETRY_AFTER_FLOOR_SECONDS,
BACKOFF_CAP_SECONDS]``. The clamp is not politeness: the header is written by
a third party, and ``Retry-After: 0`` on every answer would turn the drain
into a hot loop against their server.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Final

from yupay.core.outbound_errors import (
    Delivery,
    OutboundBrokenError,
    OutboundError,
    OutboundRefusedError,
    OutboundUnreachableError,
)

#: How many attempts one delivery row gets before it is given up on. The
#: failure-streak auto-disable (a setting) normally fires long before this on a
#: dead endpoint — this is the ceiling for the *intermittent* case, where a
#: streak keeps being reset by other merchants' successes and one row would
#: otherwise be retried for ever.
MAX_ATTEMPTS: Final = 10

#: First retry delay. Doubles per attempt.
BACKOFF_BASE_SECONDS: Final = 30.0

#: Ceiling on any single wait, ``Retry-After`` included. With the base above,
#: :data:`MAX_ATTEMPTS` spans a little over three hours.
BACKOFF_CAP_SECONDS: Final = 3600.0

#: Floor under an honoured ``Retry-After``. See the module docstring.
RETRY_AFTER_FLOOR_SECONDS: Final = 1.0

#: Where ``Retry-After`` is read. RFC 9110 §10.2.3 / RFC 6585 §4 define it for
#: exactly these; a ``500`` carrying one is a server improvising, and the
#: backoff is the better answer because it is ours.
RETRY_AFTER_STATUSES: Final[frozenset[int]] = frozenset({429, 503})

#: Statuses that mean "not now" rather than "no". Everything outside this set
#: and outside ``2xx`` is terminal.
_RETRYABLE_CLIENT_STATUSES: Final[frozenset[int]] = frozenset({408, 429})

#: Guard on the doubling so a pathological ``attempts`` cannot build a huge
#: integer before ``min`` throws it away.
_MAX_DOUBLINGS: Final = 20


class Outcome(StrEnum):
    """What this attempt did to the delivery row.

    Attributes:
        DELIVERED: Their server took it. The row is done.
        RETRY: Try again after :attr:`Decision.delay_seconds`.
        TERMINAL: The row is done and it did not arrive. Never retried.
    """

    DELIVERED = "delivered"
    RETRY = "retry"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class Decision:
    """The whole answer for one attempt.

    Attributes:
        outcome: What happens to the delivery row.
        counts_toward_streak: Whether this failure reaches the merchant's
            ``failure_streak`` and therefore the auto-disable. False for a
            success and for our own bugs.
        delay_seconds: How long until the next attempt. ``0.0`` unless
            :attr:`outcome` is :attr:`Outcome.RETRY`.
    """

    outcome: Outcome
    counts_toward_streak: bool
    delay_seconds: float


_DELIVERED: Final = Decision(
    outcome=Outcome.DELIVERED, counts_toward_streak=False, delay_seconds=0.0
)
_TERMINAL_THEIRS: Final = Decision(
    outcome=Outcome.TERMINAL, counts_toward_streak=True, delay_seconds=0.0
)
_TERMINAL_OURS: Final = Decision(
    outcome=Outcome.TERMINAL, counts_toward_streak=False, delay_seconds=0.0
)


def backoff_seconds(attempts: int) -> float:
    """Exponential backoff after ``attempts`` attempts, capped.

    No jitter, deliberately. Jitter exists to spread a herd of clients across
    a recovering server; here the herd is one merchant's own backlog, which the
    drain's concurrency dial already bounds — and a deterministic schedule is
    one a support engineer can predict from ``attempts_count`` alone.

    Args:
        attempts: Attempts made so far, this one included. ``1`` on the first.

    Returns:
        Seconds to wait, at least :data:`BACKOFF_BASE_SECONDS` and at most
        :data:`BACKOFF_CAP_SECONDS`.
    """
    doublings = min(max(attempts, 1) - 1, _MAX_DOUBLINGS)
    return min(BACKOFF_BASE_SECONDS * (2.0**doublings), BACKOFF_CAP_SECONDS)


def parse_retry_after(value: str | None, *, now: datetime) -> float | None:
    """Read a ``Retry-After`` header into a clamped number of seconds.

    Both RFC forms are accepted: a decimal count of seconds, and an HTTP-date.
    Anything else — a float, an empty string, prose, a date in the past — is
    ``None`` rather than an approximation, because the caller has a backoff of
    its own and a header we half-understood is worse than one we ignored.

    Args:
        value: The header exactly as it arrived, or ``None``.
        now: The reference instant for the HTTP-date form.

    Returns:
        Seconds clamped into ``[RETRY_AFTER_FLOOR_SECONDS,
        BACKOFF_CAP_SECONDS]``, or ``None`` when the header is unusable.
    """
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.isdigit():  # ASCII digits only: no sign, no exponent, no dot
        seconds = float(candidate)
    else:
        try:
            when = parsedate_to_datetime(candidate)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            # An HTTP-date is GMT by definition, but a lenient parser can hand
            # back a naive datetime; subtracting it from an aware ``now``
            # raises, and a delivery must not fail on a header.
            return None
        seconds = (when - now).total_seconds()
    return min(max(seconds, RETRY_AFTER_FLOOR_SECONDS), BACKOFF_CAP_SECONDS)


def decide_response(
    *, status_code: int, retry_after: str | None, attempts: int, now: datetime
) -> Decision:
    """Decide what one answered attempt means for the delivery row.

    Args:
        status_code: What their server answered, redirects included — the
            client never follows one, so a ``30x`` is an outcome here.
        retry_after: Their ``Retry-After`` header, if any.
        attempts: Attempts made so far, this one included.
        now: Reference instant for an HTTP-date ``Retry-After``.

    Returns:
        The decision for this row.
    """
    if 200 <= status_code < 300:
        return _DELIVERED
    retryable = status_code in _RETRYABLE_CLIENT_STATUSES or status_code >= 500
    if not retryable or attempts >= MAX_ATTEMPTS:
        return _TERMINAL_THEIRS
    asked = parse_retry_after(retry_after, now=now) if status_code in RETRY_AFTER_STATUSES else None
    return Decision(
        outcome=Outcome.RETRY,
        counts_toward_streak=True,
        delay_seconds=asked if asked is not None else backoff_seconds(attempts),
    )


def decide_failure(error: OutboundError, *, attempts: int) -> Decision:
    """Decide what one failed attempt means for the delivery row.

    The order of the branches is the argument in the module docstring, made
    executable: the delivery fact outranks the family, our own bug outranks the
    family it was deliberately filed under, and the family answers the rest.

    Args:
        error: What :func:`yupay.core.outbound.post_json` raised. Every path
            out of it is one of these, so there is no untyped case.
        attempts: Attempts made so far, this one included.

    Returns:
        The decision for this row.
    """
    if error.delivery is Delivery.RECEIVED:
        # They have it. A retry sends a second copy of an event they already
        # processed — the one failure mode a retry policy must never cause.
        return _TERMINAL_THEIRS
    if isinstance(error, OutboundBrokenError):
        return _TERMINAL_OURS
    if isinstance(error, OutboundRefusedError):
        # We refused their destination, and the row's ``url`` is a snapshot —
        # fixing the endpoint does not fix this row.
        return _TERMINAL_THEIRS
    if isinstance(error, OutboundUnreachableError):
        if attempts >= MAX_ATTEMPTS:
            return _TERMINAL_THEIRS
        return Decision(
            outcome=Outcome.RETRY,
            counts_toward_streak=True,
            delay_seconds=backoff_seconds(attempts),
        )
    # An ``OutboundError`` in neither family cannot exist today (a test walks
    # the taxonomy to keep it that way). If one ever does, blame ourselves
    # rather than a merchant: a leaf nobody classified is our omission.
    return _TERMINAL_OURS


__all__ = [
    "BACKOFF_BASE_SECONDS",
    "BACKOFF_CAP_SECONDS",
    "MAX_ATTEMPTS",
    "RETRY_AFTER_FLOOR_SECONDS",
    "RETRY_AFTER_STATUSES",
    "Decision",
    "Outcome",
    "backoff_seconds",
    "decide_failure",
    "decide_response",
    "parse_retry_after",
]
