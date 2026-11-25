"""``GET /metrics`` for one uvicorn process or several (ADR-0109).

With ``--workers N`` (``WEB_CONCURRENCY``) every worker keeps its own
``prometheus_client`` registry, and a scrape lands on whichever worker the
kernel hands the connection to — counters would jump between workers' values
and every rate would be noise. ``prometheus_client``'s multiprocess mode fixes
the HTTP and domain metrics: with ``PROMETHEUS_MULTIPROC_DIR`` set, each worker
writes its samples to files in that directory and the scrape sums them.

What multiprocess mode drops is the ``process_*`` family, because those
describe *one* process and cannot be summed. Two alerts read them
(``ApiSaturated``: CPU, ``ApiFileDescriptorsHigh``: descriptors), and both are
per-process questions — one event loop pinned on one core, one process at its
descriptor wall. :class:`WorkerProcessCollector` therefore reports them for
every Python process in the container, labelled ``pid``, so the existing rule
expressions keep meaning exactly what they say, now per worker. The label is
bounded: the container runs the supervisor plus ``N`` workers, and a pid only
changes when a worker dies and is restarted.

Without the environment variable nothing changes: the default registry, the
default process collector, one process.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from fastapi import FastAPI
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    ProcessCollector,
    generate_latest,
    multiprocess,
)
from prometheus_client.metrics_core import Metric
from prometheus_client.registry import Collector
from starlette.requests import Request
from starlette.responses import Response

MULTIPROC_ENV = "PROMETHEUS_MULTIPROC_DIR"


def _python_pids(proc: Path) -> Iterator[int]:
    """Every process in this container whose executable is a Python interpreter."""
    if not proc.is_dir():  # not Linux: nothing to report, never a failed scrape
        return
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv0 = (entry / "cmdline").read_bytes().split(b"\0", 1)[0]
        except OSError:  # it exited between listing and reading
            continue
        if b"python" in argv0 or b"uvicorn" in argv0:
            yield int(entry.name)


def _fixed(pid: int) -> Callable[[], int]:
    """``ProcessCollector`` asks for its pid through a callable."""
    return lambda: pid


class WorkerProcessCollector(Collector):
    """``process_*`` metrics for each uvicorn process, labelled by ``pid``."""

    def __init__(self, proc: Path = Path("/proc")) -> None:
        """Read processes from ``proc`` (a parameter so tests can point elsewhere)."""
        self._proc = proc

    def collect(self) -> Iterable[Metric]:
        """One family per ``process_*`` name, one sample per live process."""
        families: dict[str, Metric] = {}
        for pid in _python_pids(self._proc):
            source = ProcessCollector(pid=_fixed(pid), proc=str(self._proc), registry=None)
            for family in source.collect():
                merged = families.setdefault(
                    family.name, Metric(family.name, family.documentation, family.type)
                )
                for sample in family.samples:
                    merged.add_sample(sample.name, {**sample.labels, "pid": str(pid)}, sample.value)
        return list(families.values())


def build_registry() -> CollectorRegistry:
    """The registry one scrape is answered from."""
    if MULTIPROC_ENV not in os.environ:
        return REGISTRY
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
    registry.register(WorkerProcessCollector())
    return registry


def mount_metrics(app: FastAPI) -> None:
    """Serve ``GET /metrics`` (Caddy keeps it off the public edge)."""

    async def metrics(_request: Request) -> Response:
        return Response(generate_latest(build_registry()), media_type=CONTENT_TYPE_LATEST)

    app.add_route("/metrics", metrics, include_in_schema=False)
