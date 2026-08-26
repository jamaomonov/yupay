"""Alert rules must be able to fire, and must be delivered somewhere.

Both halves failed silently before. Every rule evaluated into a UI nobody
watches — `/api/v1/alertmanagers` returned an empty list — and two of the rules
could not have fired even so: `ApiHighLatency` had a threshold above the
histogram's top bucket, and `QueueBacklog` watched a metric nothing emits.

A dashboard of green rules reads as coverage, which is why this is asserted
rather than reviewed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]  # types-PyYAML is not a project dep

ROOT = Path(__file__).resolve().parents[4]
ALERTS = ROOT / "infra" / "prometheus" / "alerts"
PROM = ROOT / "infra" / "prometheus" / "prometheus.yml"
AM_TEMPLATE = ROOT / "infra" / "alertmanager" / "alertmanager.tmpl.yml"


def _rules() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(ALERTS.glob("*.yml")):
        for group in yaml.safe_load(path.read_text())["groups"]:
            out.extend(group["rules"])
    return out


def test_prometheus_knows_where_to_send_alerts() -> None:
    cfg = yaml.safe_load(PROM.read_text())
    targets = cfg.get("alerting", {}).get("alertmanagers", [])
    assert targets, "no alerting block — every rule below evaluates into nothing"


def test_every_rule_has_a_severity_and_a_summary() -> None:
    missing = [
        r["alert"]
        for r in _rules()
        if not r.get("labels", {}).get("severity") or not r.get("annotations", {}).get("summary")
    ]
    assert not missing, f"unlabelled or unexplained: {missing}"


def test_no_rule_watches_a_metric_nothing_emits() -> None:
    """`redis_list_length` was the one: the exporter only reports it for keys
    named in REDIS_EXPORTER_CHECK_KEYS, and Dramatiq does not store its queues
    as plain lists — so no configuration could have made that rule fire."""
    banned = ("redis_list_length",)
    offenders = [r["alert"] for r in _rules() if any(metric in r["expr"] for metric in banned)]
    assert not offenders, f"{offenders} watch a metric that is never produced"


def test_the_latency_threshold_is_inside_the_histogram_range() -> None:
    """Cross-checks the rule against the buckets in `bootstrap`. A threshold
    above the top finite bucket is a rule that can never fire, which is what
    `ApiHighLatency > 1.5` was against buckets ending at 1.0."""
    from yupay.bootstrap import _LATENCY_BUCKETS

    latency = [r for r in _rules() if "histogram_quantile" in r["expr"]]
    assert latency, "no latency rule found"
    for rule in latency:
        threshold = float(rule["expr"].rsplit(">", 1)[1].strip())
        assert threshold < max(_LATENCY_BUCKETS), (
            f"{rule['alert']} fires above {threshold}s but the histogram tops out at "
            f"{max(_LATENCY_BUCKETS)}s — it can never fire"
        )


def test_a_ratio_rule_guards_against_a_zero_denominator() -> None:
    """`redis_memory_used / redis_memory_max` is +Inf when maxmemory is unset,
    so without a guard the rule fires forever on any stack that has not
    configured a ceiling — a false alarm about the very thing it detects."""
    redis_ratio = [
        r for r in _rules() if "redis_memory_max_bytes" in r["expr"] and "/" in r["expr"]
    ]
    assert redis_ratio, "no redis memory ratio rule found"
    for rule in redis_ratio:
        assert "redis_memory_max_bytes > 0" in rule["expr"], (
            f"{rule['alert']} divides by a value that is 0 when maxmemory is unset"
        )


@pytest.mark.parametrize("placeholder", ["__ALERT_BOT_TOKEN__", "__ALERT_CHAT_ID__"])
def test_the_alertmanager_template_uses_substitutable_placeholders(placeholder: str) -> None:
    """Guarding a mistake already made once: the template first carried
    `${ALERT_BOT_TOKEN}`, which Alertmanager does not expand — it would have
    loaded happily, validated happily, and authenticated to Telegram as the
    literal string, so every alert would have vanished with no error here."""
    lines = AM_TEMPLATE.read_text().splitlines()
    config = [ln for ln in lines if not ln.lstrip().startswith("#")]
    assert any(placeholder in ln for ln in config)
    # Comments are excluded on purpose: the file explains this trap in prose,
    # and the prose has to be allowed to name the thing it warns about.
    offenders = [ln.strip() for ln in config if "${ALERT_" in ln]
    assert not offenders, (
        "Alertmanager performs no environment expansion; `${...}` is taken "
        f"literally: {offenders}"
    )
