"""``/metrics`` across uvicorn workers (ADR-0109)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Two "workers" each count one request into the shared directory; a third
# process answers the scrape. Run as subprocesses because prometheus_client
# reads PROMETHEUS_MULTIPROC_DIR once, at import.
_SCRIPT = """
import os, sys
from multiprocessing import get_context
from prometheus_client import Counter, generate_latest

C = Counter("yupay_test_requests", "test", ["route"])

def work() -> None:
    C.labels(route="/x").inc()

if __name__ == "__main__":
    ctx = get_context("spawn")
    for _ in range(2):
        p = ctx.Process(target=work)
        p.start()
        p.join()
    from yupay.core.metrics_export import build_registry
    sys.stdout.write(generate_latest(build_registry()).decode())
"""


def _scrape(tmp_path: Path) -> str:
    script = tmp_path / "scrape.py"
    script.write_text(_SCRIPT)
    metrics_dir = tmp_path / "prom"
    metrics_dir.mkdir()
    env = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": str(metrics_dir)}
    out = subprocess.run(
        [sys.executable, str(script)], env=env, capture_output=True, text=True, check=True
    )
    return out.stdout


def test_the_scrape_sums_every_worker(tmp_path: Path) -> None:
    assert 'yupay_test_requests_total{route="/x"} 2.0' in _scrape(tmp_path)


@pytest.mark.skipif(not Path("/proc/self/stat").exists(), reason="needs Linux /proc")
def test_process_metrics_are_kept_per_worker(tmp_path: Path) -> None:
    text = _scrape(tmp_path)
    assert 'process_cpu_seconds_total{pid="' in text
    assert 'process_open_fds{pid="' in text
    assert 'process_max_fds{pid="' in text


def test_single_process_mode_is_untouched() -> None:
    from prometheus_client import REGISTRY
    from yupay.core.metrics_export import MULTIPROC_ENV, build_registry

    assert MULTIPROC_ENV not in os.environ
    assert build_registry() is REGISTRY
