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

from datetime import UTC, datetime, timedelta

import pytest
from yupay.core.outbound_errors import (
    AddressNotAllowedError,
    ConnectFailedError,
    ContentEncodingNotAllowedError,
    Delivery,
    ExchangeFailedError,
    OutboundBrokenError,
    OutboundError,
    OutboundTimeoutError,
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


def test_every_leaf_of_the_taxonomy_has_a_decision() -> None:
    """A leaf added to ``outbound_errors`` without a branch here would be
    silently swallowed by a fallback. Walk them all and insist each is decided
    — this is the same discipline Task 2's own family test applies."""
    leaves = _leaves(OutboundError)
    assert len(leaves) >= 9, "the taxonomy shrank; check this walk still finds the leaves"
    for leaf in leaves:
        decision = retry.decide_failure(leaf("x"), attempts=1)
        assert decision.outcome in (Outcome.RETRY, Outcome.TERMINAL)


def test_a_received_delivery_is_never_retried_whatever_its_family() -> None:
    """The property, not the class list: ``RECEIVED`` means their server has
    the webhook, so a retry sends a second copy of an event they already had."""
    for leaf in _leaves(OutboundError):
        if leaf.delivery is not Delivery.RECEIVED:
            continue
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


@pytest.mark.parametrize("value", [None, "", "   ", "soon", "-5", "1e5", "12.5x", "∞"])
def test_an_unusable_retry_after_falls_back_to_the_backoff(value: str | None) -> None:
    """A third party writes this header. Anything we cannot read is ignored
    rather than allowed to schedule the retry."""
    decision = retry.decide_response(status_code=429, retry_after=value, attempts=2, now=NOW)
    assert decision.delay_seconds == retry.backoff_seconds(2)


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
