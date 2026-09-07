"""The retry table for merchant webhook deliveries (M3a, Task 4).

The table is a **consequence** of ``core.outbound_errors``' taxonomy, not an
independent design: every failure carries a three-valued
:class:`~yupay.core.outbound_errors.Delivery` fact saying whether the merchant's
server got the request, and a two-wide family saying whose side the attempt
ended on. This file pins the derivation, so a new leaf added to that taxonomy
without a decision fails here rather than being retried into a merchant's
provisioning twice.

Pure functions only — no DB, no sockets. The drain that consumes them is
covered in ``tests/integration/test_merchant_webhook_delivery.py``.
"""

from __future__ import annotations

import gc
from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest
from yupay.core.outbound_errors import (
    AddressNotAllowedError,
    ConnectFailedError,
    ContentEncodingNotAllowedError,
    Delivery,
    ExchangeFailedError,
    OutboundBrokenError,
    OutboundError,
    OutboundRefusedError,
    OutboundTimeoutError,
    OutboundUnreachableError,
    ResolutionFailedError,
    ResponseTooLargeError,
    UrlNotAllowedError,
)
from yupay.modules.merchants import webhook_retry as retry
from yupay.modules.merchants.webhook_retry import Outcome

NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)


def _leaves(cls: type[OutboundError]) -> list[type[OutboundError]]:
    """Every concrete leaf under ``cls``, the way Task 2's taxonomy test walks it."""
    subs = cls.__subclasses__()
    if not subs:
        return [cls]
    return [leaf for sub in subs for leaf in _leaves(sub)]


# ---------- the failure table, derived from the taxonomy ----------


@pytest.mark.parametrize(
    ("error", "outcome", "counts"),
    [
        # RECEIVED — their server has it. Retrying re-delivers. Terminal, and
        # their server is the reason, so it counts against them.
        (ResponseTooLargeError("x"), Outcome.TERMINAL, True),
        (ContentEncodingNotAllowedError("x"), Outcome.TERMINAL, True),
        # Our bug. Terminal, and it must never reach the failure budget.
        (OutboundBrokenError("x"), Outcome.TERMINAL, False),
        # We refused their destination. Deterministic for this row's URL
        # snapshot, so terminal — and it is their configuration.
        (UrlNotAllowedError("x"), Outcome.TERMINAL, True),
        (AddressNotAllowedError("x"), Outcome.TERMINAL, True),
        # They did not answer. Retry.
        (ResolutionFailedError("x"), Outcome.RETRY, True),
        (ConnectFailedError("x"), Outcome.RETRY, True),
        (ExchangeFailedError("x"), Outcome.RETRY, True),
        (OutboundTimeoutError("x"), Outcome.RETRY, True),
    ],
)
def test_each_outbound_failure_gets_the_decision_its_taxonomy_implies(
    error: OutboundError, outcome: Outcome, counts: bool
) -> None:
    decision = retry.decide_failure(error, attempts=1)
    assert decision.outcome is outcome
    assert decision.counts_toward_streak is counts


def test_every_leaf_of_the_taxonomy_is_decided_by_what_it_says_about_itself() -> None:
    """A leaf added to ``outbound_errors`` without a branch here must not be
    quietly swallowed by the fallback.

    The obvious spelling of this test — ``outcome in (RETRY, TERMINAL)`` — has
    **no falsifying input**: ``decide_failure`` structurally cannot return
    anything else, so it passes for a leaf that reaches the fallback and is
    given the wrong answer. What is checked instead is that each leaf gets the
    decision *its own* ``delivery`` and family imply, which is exactly the
    promise the module docstring makes:

    - ``RECEIVED`` -> terminal, whatever the family says;
    - refused -> terminal;
    - unreachable -> retryable below the ceiling;
    - and a leaf in **neither** family is the case the fallback exists for: it
      must be terminal *and* streak-exempt, because a leaf nobody classified is
      our omission and not a merchant's fault. A ``NOT_SENT`` leaf outside both
      families reads as "blindly safe to retry" and would silently be given up
      on instead — which is what the old assertion could not see.
    """
    leaves = _leaves(OutboundError)
    assert len(leaves) >= 9, "the taxonomy shrank; check this walk still finds the leaves"
    for leaf in leaves:
        decision = retry.decide_failure(leaf("x"), attempts=1)
        if leaf.delivery is Delivery.RECEIVED:
            expected, exempt = Outcome.TERMINAL, False
        elif issubclass(leaf, OutboundBrokenError):
            expected, exempt = Outcome.TERMINAL, True
        elif issubclass(leaf, OutboundRefusedError):
            expected, exempt = Outcome.TERMINAL, False
        elif issubclass(leaf, OutboundUnreachableError):
            expected, exempt = Outcome.RETRY, False
        else:
            # Unfamilied: the fallback's own case, and the one the assertion
            # exists for.
            expected, exempt = Outcome.TERMINAL, True
        assert decision.outcome is expected, leaf.__name__
        assert decision.counts_toward_streak is not exempt, leaf.__name__


def test_a_leaf_in_neither_family_is_blamed_on_us_not_on_the_merchant() -> None:
    """The fallback, exercised directly rather than hoped for.

    A leaf declared outside both families with ``delivery = NOT_SENT`` — the
    value that means "nothing was written, blindly safe to retry" — is the
    input that makes the walk above discriminating. It must come back terminal
    (we cannot retry what we have not classified) and **streak-exempt** (an
    unclassified leaf is our omission, not a merchant's fault).

    The class is torn down explicitly. ``__subclasses__()`` is a process-global
    registry keyed on liveness, and a throwaway leaf left in it is walked by
    every later taxonomy test in the session — including
    ``test_outbound_ssrf.py``'s, which asserts every leaf belongs to **exactly
    one** family and would fail on this one. ``.remove()`` on the list
    ``__subclasses__()`` hands back does nothing: it is a fresh list each call.
    """

    class _UnfamiliedError(OutboundError):
        delivery: ClassVar[Delivery] = Delivery.NOT_SENT

    try:
        decision = retry.decide_failure(_UnfamiliedError("x"), attempts=1)
        assert decision.outcome is Outcome.TERMINAL
        assert decision.counts_toward_streak is False
        # And the walk above would see it: it really is a leaf right now.
        assert _UnfamiliedError in _leaves(OutboundError)
    finally:
        del _UnfamiliedError
        gc.collect()  # a class sits in reference cycles; refcounting alone won't do it
    assert not any(leaf.__name__ == "_UnfamiliedError" for leaf in _leaves(OutboundError)), (
        "the throwaway leaf outlived its test and will contaminate every later "
        "taxonomy walk in this process"
    )


def test_a_received_delivery_is_never_retried_whatever_its_family() -> None:
    """The property, not the class list: ``RECEIVED`` means their server has
    the webhook, so a retry sends a second copy of an event they already had."""
    received = [leaf for leaf in _leaves(OutboundError) if leaf.delivery is Delivery.RECEIVED]
    # Without this the loop below passes on an empty list, which is exactly
    # what a taxonomy edit that dropped the value would produce.
    assert received, "no RECEIVED leaf found — this test would pass vacuously"
    for leaf in received:
        assert retry.decide_failure(leaf("x"), attempts=1).outcome is Outcome.TERMINAL


def test_an_unknown_delivery_is_still_retried_because_a_webhook_is_at_least_once() -> None:
    """``UNKNOWN`` may double-deliver. We retry anyway and say so in the
    contract; the delivery id in the signed material is what lets a receiver
    act on it."""
    decision = retry.decide_failure(OutboundTimeoutError("x"), attempts=1)
    assert OutboundTimeoutError.delivery is Delivery.UNKNOWN
    assert decision.outcome is Outcome.RETRY


def test_our_own_bug_never_counts_toward_the_merchants_failure_budget() -> None:
    """``OutboundBrokenError`` means the attempt broke in a way neither side
    chose. Counting it auto-disables a working endpoint and tells the merchant,
    in their own delivery log, that we refused their URL."""
    assert retry.decide_failure(OutboundBrokenError("x"), attempts=1).counts_toward_streak is False


def test_a_transport_failure_becomes_terminal_at_the_attempt_ceiling() -> None:
    assert retry.decide_failure(ConnectFailedError("x"), attempts=1).outcome is Outcome.RETRY
    ceiling = retry.decide_failure(ConnectFailedError("x"), attempts=retry.MAX_ATTEMPTS)
    assert ceiling.outcome is Outcome.TERMINAL
    assert ceiling.counts_toward_streak is True


# ---------- the response table ----------


@pytest.mark.parametrize("status", [200, 201, 202, 204, 299])
def test_a_2xx_is_delivered(status: int) -> None:
    assert retry.decide_response(status_code=status, retry_after=None, attempts=1, now=NOW) == (
        retry.Decision(outcome=Outcome.DELIVERED, counts_toward_streak=False, delay_seconds=0.0)
    )


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410, 422, 301, 302, 307])
def test_a_4xx_or_a_redirect_is_terminal(status: int) -> None:
    """Their endpoint rejected it, or pointed us elsewhere and we do not follow
    redirects. Retrying will not change either answer."""
    decision = retry.decide_response(status_code=status, retry_after=None, attempts=1, now=NOW)
    assert decision.outcome is Outcome.TERMINAL
    assert decision.counts_toward_streak is True


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_a_5xx_and_the_two_retryable_4xx_back_off(status: int) -> None:
    decision = retry.decide_response(status_code=status, retry_after=None, attempts=1, now=NOW)
    assert decision.outcome is Outcome.RETRY
    assert decision.counts_toward_streak is True
    assert decision.delay_seconds == retry.backoff_seconds(1)


def test_a_retryable_status_becomes_terminal_at_the_attempt_ceiling() -> None:
    decision = retry.decide_response(
        status_code=500, retry_after=None, attempts=retry.MAX_ATTEMPTS, now=NOW
    )
    assert decision.outcome is Outcome.TERMINAL


# ---------- backoff ----------


def test_backoff_doubles_from_the_base_and_stops_at_the_cap() -> None:
    assert retry.backoff_seconds(1) == retry.BACKOFF_BASE_SECONDS
    assert retry.backoff_seconds(2) == retry.BACKOFF_BASE_SECONDS * 2
    assert retry.backoff_seconds(3) == retry.BACKOFF_BASE_SECONDS * 4
    assert retry.backoff_seconds(50) == retry.BACKOFF_CAP_SECONDS
    # Monotone, and never past the cap — the property that matters more than
    # any one row of the table.
    delays = [retry.backoff_seconds(n) for n in range(1, 40)]
    assert delays == sorted(delays)
    assert max(delays) == retry.BACKOFF_CAP_SECONDS


def test_backoff_of_a_first_attempt_is_never_zero() -> None:
    """A zero delay would re-claim the row on the same tick and spin."""
    assert retry.backoff_seconds(1) > 0


# ---------- Retry-After ----------


def test_a_sane_retry_after_in_seconds_is_honoured_on_a_429() -> None:
    decision = retry.decide_response(status_code=429, retry_after="120", attempts=1, now=NOW)
    assert decision.outcome is Outcome.RETRY
    assert decision.delay_seconds == 120.0


def test_a_retry_after_http_date_is_honoured() -> None:
    later = NOW + timedelta(seconds=90)
    header = later.strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert retry.parse_retry_after(header, now=NOW) == pytest.approx(90.0, abs=1.0)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        "soon",
        "-5",
        "1e5",
        "12.5x",
        "∞",
        # ``str.isdigit()`` is not ASCII-only. Superscript two is a digit to
        # Python and a ``ValueError`` to ``float()``; the Eastern Arabic form
        # is a digit ``float()`` *does* parse, which is worse — a header read
        # far more liberally than a wire format should be.
        "²",
        "١٢٠",
    ],
)
def test_an_unusable_retry_after_falls_back_to_the_backoff(value: str | None) -> None:
    """A third party writes this header. Anything we cannot read is ignored
    rather than allowed to schedule the retry."""
    decision = retry.decide_response(status_code=429, retry_after=value, attempts=2, now=NOW)
    assert decision.delay_seconds == retry.backoff_seconds(2)


@pytest.mark.parametrize("value", ["²", "١٢٠", "٢"])
def test_a_non_ascii_digit_header_never_escapes_as_an_exception(value: str) -> None:
    """This runs inside the drain's per-row savepoint. A ``ValueError`` here is
    caught by the poison belt and the delivery is written **terminally
    failed** — never retried, streak untouched, nobody told — over a header a
    third party chose. ``str.isdigit()`` is true for all three."""
    assert value.isdigit()
    assert retry.parse_retry_after(value, now=NOW) is None
    decision = retry.decide_response(status_code=429, retry_after=value, attempts=1, now=NOW)
    assert decision.outcome is Outcome.RETRY
    assert decision.delay_seconds == retry.backoff_seconds(1)


def test_a_retry_after_in_the_past_is_floored_rather_than_ignored() -> None:
    """The docstring's other edge, spelled out: a stale HTTP-date parses, so it
    is honoured and clamped up to the floor — one second, not the backoff."""
    stale = (NOW - timedelta(hours=2)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert retry.parse_retry_after(stale, now=NOW) == retry.RETRY_AFTER_FLOOR_SECONDS


def test_a_retry_after_of_zero_is_floored_so_it_cannot_become_a_hot_loop() -> None:
    decision = retry.decide_response(status_code=429, retry_after="0", attempts=1, now=NOW)
    assert decision.delay_seconds == retry.RETRY_AFTER_FLOOR_SECONDS


def test_an_enormous_retry_after_is_capped() -> None:
    decision = retry.decide_response(status_code=503, retry_after="99999999", attempts=1, now=NOW)
    assert decision.delay_seconds == retry.BACKOFF_CAP_SECONDS


def test_retry_after_is_read_only_where_the_rfc_defines_it() -> None:
    """429 and 503 mean "come back later" and carry the header by definition.
    A 500 with one is a server improvising; the backoff decides instead."""
    assert frozenset({429, 503}) == retry.RETRY_AFTER_STATUSES
    decision = retry.decide_response(status_code=500, retry_after="1", attempts=1, now=NOW)
    assert decision.delay_seconds == retry.backoff_seconds(1)
