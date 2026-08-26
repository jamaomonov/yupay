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
async def app_metrics(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Bucket bounds of the per-handler latency histogram.

    One request has to happen first: the metric carries a `handler` label, so
    its child series — and therefore its `le` samples — do not exist until
    something has been observed.
    """
    monkeypatch.setenv("ENVIRONMENT", "test")
    cfg.get_settings.cache_clear()
    from httpx import ASGITransport, AsyncClient
    from prometheus_client import REGISTRY
    from yupay.bootstrap import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        await ac.get("/healthz")

    bounds: list[float] = []
    for metric in REGISTRY.collect():
        if metric.name == "http_request_duration_seconds":
            bounds = [
                float(le)
                for sample in metric.samples
                if (le := sample.labels.get("le")) is not None
            ]
            break
    cfg.get_settings.cache_clear()
    return sorted(set(bounds))


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
