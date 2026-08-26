"""The latency histogram has to be able to see past one second.

Its buckets were `0.1 / 0.5 / 1 / +Inf`, which makes `histogram_quantile`
unable to return anything above 1.0 — the highest finite bound is the ceiling.
Two consequences, both measured on production:

* several handlers reported a p95 of exactly "1000ms", which really meant
  "somewhere above a second, unmeasurable" — `check-player` alone averages
  1.69s;
* the `ApiHighLatency` rule fires above 1.5s, so it was dead code. The alert
  meant to warn about load could never fire.

Buckets are cheap here: the series count is handlers x buckets, and this is a
service with a couple of hundred routes.
"""

from __future__ import annotations

import pytest
from yupay.core import config as cfg


@pytest.fixture
def app_metrics(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Bucket bounds of the per-handler latency histogram, as registered.

    Read from the collector rather than from collected samples, for two
    reasons discovered the hard way when the full suite ran:

    * the metric carries a `handler` label, so no `le` sample exists until some
      request has been observed;
    * and observing one is not something a test can arrange, because **only the
      first `create_app()` in a process is actually instrumented**. Prometheus'
      registry is global, so a second app hits a duplicate registration and
      silently ends up with no instrumentation at all. Harmless in production —
      one process builds one app — but it means a test that builds its own app
      and hits it records nothing whenever another module got there first.

    `_upper_bounds` is private, and used deliberately: it is the only way to
    assert what Prometheus will actually scrape without depending on test
    ordering.
    """
    monkeypatch.setenv("ENVIRONMENT", "test")
    cfg.get_settings.cache_clear()
    from prometheus_client import REGISTRY
    from yupay.bootstrap import create_app

    create_app()
    collector = REGISTRY._names_to_collectors.get("http_request_duration_seconds")
    assert collector is not None, "the latency histogram is not registered at all"
    bounds = getattr(collector, "_upper_bounds", None)
    assert bounds, "the registered collector is not a histogram"
    cfg.get_settings.cache_clear()
    return sorted(float(b) for b in bounds)


def test_the_histogram_can_measure_a_slow_request(app_metrics: list[float]) -> None:
    finite = [b for b in app_metrics if b != float("inf")]
    assert finite, "no histogram buckets found — is the instrumentator still wired up?"
    assert max(finite) >= 5, (
        f"the highest finite bucket is {max(finite)}s, so any request slower than that is "
        "indistinguishable from one that took a minute — and no quantile can exceed it"
    )


def test_the_alert_threshold_sits_inside_the_measurable_range(app_metrics: list[float]) -> None:
    """`ApiHighLatency` fires above 1.5s. A threshold above the top finite
    bucket is a rule that cannot fire."""
    finite = [b for b in app_metrics if b != float("inf")]
    assert max(finite) > 1.5


def test_there_is_resolution_below_a_quarter_second(app_metrics: list[float]) -> None:
    """Most traffic is fast — a catalog read is tens of milliseconds — so the
    lower end needs enough bounds for a p50 to mean something."""
    assert len([b for b in app_metrics if b <= 0.25]) >= 3
