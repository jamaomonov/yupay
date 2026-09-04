"""Domain Prometheus counters, and the two rules every one of them obeys.

Everything the API exported before this module came from
``prometheus_fastapi_instrumentator``, registered once in
:func:`~yupay.bootstrap.create_app`: per-route request counts, status
classes and latencies. That answers "how often was this route called and how
fast was it", and nothing else — a route can answer ``200`` in 30 ms while
quietly spending a shared third-party quota, and the HTTP metrics cannot see
it. That was the gap behind ``POST /gifts/steam-profile``: it is
unauthenticated, it spends a **Steam Web API key with a 100k/day ceiling
that Steam sign-in shares**, and until this module nothing counted the
calls, so a quota burn was something nobody could explain after the fact.

Domain counters live here rather than next to the code that increments them,
so that the whole set — and therefore the whole label vocabulary — is
reviewable in one file. ``docs/architecture/metrics.md`` is its prose
counterpart.

**Rule 1: a label value is bounded, and is never about a person.**
Prometheus keeps one time series per distinct label combination, in memory,
for the lifetime of the process, and Grafana/Prometheus have no redactor, no
TTL and no access control worth the name. A steamid64, a vanity name, an
invite link, a nickname or an IP as a label value is therefore two bugs at
once: unbounded series growth, and a third party's identity — someone who is
not even our customer — parked somewhere it can never be taken back from.
``gifts.profile`` is scrupulous about this in its logs (it records
``hash_short(identifier)`` and never the identifier); metrics get the same
discipline. The label values in this file are closed ``Literal`` sets chosen
by us — verdicts, cache origin, endpoint and consumer names — which is why
they are typed as ``Literal`` rather than ``str``: mypy is the thing that
stops a future caller passing a vanity name where ``verdict`` goes.

**Rule 2: recording never fails a request.** These counters sit on a path
whose entire contract is that it must not be the reason a sale fails. A
counter is an observation *about* the work, never part of it, so every
increment here is wrapped: a broken registry (a duplicate registration, a
label mismatch, anything at all) degrades to one warning log and a missing
data point, never a 500 on a buyer's pre-purchase check.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

from prometheus_client import Counter

from yupay.core.logging import get_logger

log = get_logger("yupay.metrics")

#: Which Steam Web API method was called. Both are keyed calls, so both are
#: charged against the daily ceiling; the OpenID ``check_authentication``
#: round trip in ``auth.steam.verify_callback`` is **not** here on purpose —
#: it carries no API key and costs no quota.
SteamApiEndpoint = Literal["resolve_vanity_url", "get_player_summaries"]

#: Which feature spent the quota. There is one key and two consumers, so the
#: useful denominator for "are we near the ceiling" is the sum across this
#: label; the split is what says *which* of the two is burning it.
SteamApiConsumer = Literal["gifts_profile", "auth_signin"]

#: Whether the call landed. ``ok`` is a 2xx response; ``error`` is a non-2xx,
#: a transport failure, a timeout, or a cancellation (the gift check runs
#: both its calls under one deadline). Deliberately about the *call*, not
#: about whether we liked the body: a 200 whose JSON we could not trust still
#: spent quota, and shows up as an ``unavailable`` verdict instead.
SteamApiOutcome = Literal["ok", "error"]

#: The four statuses of :class:`~yupay.modules.gifts.schemas.GiftProfileOut`.
GiftProfileVerdict = Literal["found", "not_found", "unsupported", "unavailable"]

#: Where a verdict came from. ``cache`` is a Redis hit (no quota spent),
#: ``steam`` means at least one keyed call was made, ``local`` is a verdict
#: reached without either — an ``s.team`` friend link (``unsupported``) or an
#: unset API key (``unavailable``). Cache hit rate is
#: ``cache / (cache + steam)``: ``local`` is excluded because those requests
#: never consult the cache at all, so counting them as misses would make an
#: attacker pasting friend links look like a cache collapse.
GiftProfileSource = Literal["cache", "steam", "local"]

STEAM_WEB_API_CALLS = Counter(
    "yupay_steam_web_api_calls_total",
    "Calls charged against the shared Steam Web API key (100k/day ceiling).",
    ("endpoint", "consumer", "outcome"),
)

GIFT_PROFILE_CHECKS = Counter(
    "yupay_gifts_steam_profile_checks_total",
    "Pre-purchase Steam recipient checks, by verdict and by where the verdict came from.",
    ("verdict", "source"),
)


def _inc(counter: Counter, name: str, labels: dict[str, str]) -> None:
    """Increment one labelled counter, swallowing anything the registry throws.

    Args:
        counter: the collector to increment.
        name: its metric name, for the failure log — ``counter`` may be a
            test double with no name of its own.
        labels: the label set, already validated by the caller's ``Literal``
            types.
    """
    try:
        counter.labels(**labels).inc()
    except Exception as exc:  # noqa: BLE001 -- see "Rule 2" in the module docstring
        # No `raise`: a metric is an observation about the work, not part of
        # it. The one thing that must not happen here is an unauthenticated
        # buyer-facing check turning into a 500 because a counter broke.
        log.warning("metrics.increment_failed", metric=name, error=type(exc).__name__)


def record_steam_web_api_call(
    *, endpoint: SteamApiEndpoint, consumer: SteamApiConsumer, outcome: SteamApiOutcome
) -> None:
    """Count one call against the shared Steam Web API key. Never raises.

    Args:
        endpoint: the Steam Web API method called.
        consumer: the feature that spent the quota.
        outcome: whether the call landed with a 2xx.
    """
    _inc(
        STEAM_WEB_API_CALLS,
        "yupay_steam_web_api_calls_total",
        {"endpoint": endpoint, "consumer": consumer, "outcome": outcome},
    )


@contextmanager
def steam_web_api_call(*, endpoint: SteamApiEndpoint, consumer: SteamApiConsumer) -> Iterator[None]:
    """Count the keyed Steam call made in the block, however it ends.

    Wrap only the request and its status check — not the body parsing, which
    is about the answer rather than about the quota the call already spent.
    The block's exception (or cancellation) propagates untouched; all this
    does is decide the ``outcome`` label first.

    Args:
        endpoint: the Steam Web API method being called.
        consumer: the feature spending the quota.

    Yields:
        Nothing; the block does the call.
    """
    outcome: SteamApiOutcome = "error"
    try:
        yield
        outcome = "ok"
    finally:
        # `finally`, not `except`: the gift check runs both its Steam calls
        # under one `asyncio.timeout`, and a cancellation is a `BaseException`
        # — a call that was probably charged and would otherwise go uncounted.
        record_steam_web_api_call(endpoint=endpoint, consumer=consumer, outcome=outcome)


def record_gift_profile_check(*, verdict: GiftProfileVerdict, source: GiftProfileSource) -> None:
    """Count one answer from the pre-purchase recipient check. Never raises.

    Args:
        verdict: the status the buyer was shown.
        source: where that verdict came from — see :data:`GiftProfileSource`.
    """
    _inc(
        GIFT_PROFILE_CHECKS,
        "yupay_gifts_steam_profile_checks_total",
        {"verdict": verdict, "source": source},
    )


__all__ = [
    "GIFT_PROFILE_CHECKS",
    "STEAM_WEB_API_CALLS",
    "GiftProfileSource",
    "GiftProfileVerdict",
    "SteamApiConsumer",
    "SteamApiEndpoint",
    "SteamApiOutcome",
    "record_gift_profile_check",
    "record_steam_web_api_call",
    "steam_web_api_call",
]
