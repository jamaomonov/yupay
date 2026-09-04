"""The two rules `yupay.core.metrics` exists to enforce, asserted rather than reviewed.

**Cardinality and PII.** Prometheus keeps one series per distinct label
combination, in memory, for the life of the process, and neither Prometheus
nor Grafana has a redactor. A steamid64, a vanity name, an invite link, a
nickname or a client IP as a label value would therefore be unbounded series
growth *and* a third party's identity — someone who is not our customer —
parked where it cannot be taken back. `gifts.profile` already refuses to put
any of that in a log line; the counters get the same discipline, and this
file is what keeps a future label from quietly widening.

**Never fail a request.** These counters sit on an unauthenticated
buyer-facing path whose whole contract is that it must not be the reason a
sale fails. A recorder that can raise would have made observability a new
failure mode on exactly the endpoint it was added to observe.
"""

from __future__ import annotations

from typing import Any, Literal, get_args

import pytest
from prometheus_client import REGISTRY
from yupay.core import metrics


class _BrokenCounter:
    """Throws on every increment — a duplicated registration, a label-name
    mismatch, a registry someone swapped out at runtime."""

    def labels(self, **_: str) -> Any:
        raise RuntimeError("registry is broken")


def _value(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


# ---------- rule 1: bounded, non-identifying labels ----------


def test_no_counter_carries_an_identifying_or_unbounded_label() -> None:
    """`_labelnames` is private and used deliberately: it is the only way to
    assert what Prometheus will really scrape, the same reason
    `test_metrics_buckets` reads `_upper_bounds`."""
    allowed = {"endpoint", "consumer", "outcome", "verdict", "source"}
    for counter in (metrics.STEAM_WEB_API_CALLS, metrics.GIFT_PROFILE_CHECKS):
        names = set(counter._labelnames)
        assert names <= allowed, (
            f"{counter._name} gained the label(s) {sorted(names - allowed)}. Every label "
            "value must be a small closed set that identifies nobody — no steamid, "
            "vanity name, invite link, nickname or IP. See docs/architecture/metrics.md."
        )


@pytest.mark.parametrize(
    "vocabulary",
    [
        metrics.SteamApiEndpoint,
        metrics.SteamApiConsumer,
        metrics.SteamApiOutcome,
        metrics.GiftProfileVerdict,
        metrics.GiftProfileSource,
    ],
)
def test_every_label_vocabulary_is_a_closed_literal(vocabulary: object) -> None:
    """Typed as `Literal`, not `str`, so mypy — not a code review — is what
    stops a caller passing a vanity name where a verdict goes."""
    values = get_args(vocabulary)
    assert values, "label vocabularies must be Literal types with explicit members"
    assert all(isinstance(v, str) for v in values)
    assert len(values) <= 8, "a label vocabulary this wide is a cardinality smell"
    assert getattr(vocabulary, "__origin__", None) is Literal, "not a Literal at all"


# ---------- rule 2: recording never raises ----------


def test_a_broken_registry_never_reaches_the_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics, "GIFT_PROFILE_CHECKS", _BrokenCounter())
    monkeypatch.setattr(metrics, "STEAM_WEB_API_CALLS", _BrokenCounter())

    # The module's own logger is swapped for a recorder rather than reading
    # `structlog.testing.capture_logs`. That helper works by reconfiguring
    # structlog globally, and `configure_logging()` sets
    # `cache_logger_on_first_use=True` — so once anything in the process has
    # bound this module-level logger, it keeps the processor chain it was
    # bound with and the capture never sees it. That is exactly what happened:
    # in a full run these two events were rendered to stdout while the capture
    # list came back empty, and the test passed alone and failed in the suite.
    # Asserting on the call this code actually makes removes the dependency on
    # global logging state entirely, and pins the fields as a bonus.
    calls: list[dict[str, str]] = []

    class _Recorder:
        def warning(self, event: str, **fields: str) -> None:
            calls.append({"event": event, **fields})

    monkeypatch.setattr(metrics, "log", _Recorder())

    metrics.record_gift_profile_check(verdict="found", source="steam")
    metrics.record_steam_web_api_call(
        endpoint="get_player_summaries", consumer="gifts_profile", outcome="ok"
    )

    assert [call["event"] for call in calls] == [
        "metrics.increment_failed",
        "metrics.increment_failed",
    ]
    # The failure log names the metric, never the labels of the call that
    # failed — the log redactor is not a reason to relax about what we hand it.
    assert all(call["error"] == "RuntimeError" for call in calls)
    assert [call["metric"] for call in calls] == [
        "yupay_gifts_steam_profile_checks_total",
        "yupay_steam_web_api_calls_total",
    ]
    assert not any("verdict" in call or "endpoint" in call for call in calls)


def test_a_broken_registry_does_not_swallow_the_work_it_wraps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The context manager is wrapped around a Steam call. If it ate the
    call's exception, an outage would read as a success."""
    monkeypatch.setattr(metrics, "STEAM_WEB_API_CALLS", _BrokenCounter())

    with (
        pytest.raises(ZeroDivisionError),
        metrics.steam_web_api_call(endpoint="resolve_vanity_url", consumer="gifts_profile"),
    ):
        _ = 1 / 0


# ---------- the call wrapper labels the outcome correctly ----------


def test_a_failed_call_is_counted_as_an_error_and_still_raises() -> None:
    labels = {"endpoint": "resolve_vanity_url", "consumer": "gifts_profile", "outcome": "error"}
    before = _value("yupay_steam_web_api_calls_total", **labels)

    with (
        pytest.raises(RuntimeError),
        metrics.steam_web_api_call(endpoint="resolve_vanity_url", consumer="gifts_profile"),
    ):
        raise RuntimeError("steam said no")

    assert _value("yupay_steam_web_api_calls_total", **labels) == before + 1


def test_a_cancelled_call_is_still_counted() -> None:
    """The gift check runs both its Steam calls under one `asyncio.timeout`,
    so the deadline arrives as `CancelledError` — a `BaseException`. A call
    that was very likely charged must not go uncounted just because the
    caller gave up on it, which is why the wrapper counts in `finally`."""
    import asyncio

    labels = {"endpoint": "get_player_summaries", "consumer": "gifts_profile", "outcome": "error"}
    before = _value("yupay_steam_web_api_calls_total", **labels)

    with (
        pytest.raises(asyncio.CancelledError),
        metrics.steam_web_api_call(endpoint="get_player_summaries", consumer="gifts_profile"),
    ):
        raise asyncio.CancelledError

    assert _value("yupay_steam_web_api_calls_total", **labels) == before + 1
