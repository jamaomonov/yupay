"""Every production container must declare a memory ceiling.

This VPS is shared with an unrelated production stack and has no swap, so
memory pressure goes straight to the OOM killer — which chooses by size, not by
owner. A single unbounded container of ours can therefore evict the neighbour's
database. That is a cross-tenant outage caused by us, and the only thing
standing between here and there is that somebody remembered to add four words
to a YAML file.

So it is asserted rather than remembered. A new service added without a ceiling
fails this test instead of being discovered during an incident.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]  # types-PyYAML is not a project dep

COMPOSE = Path(__file__).resolve().parents[4] / "docker-compose.prod.yml"

#: Sockets accumulate here, and the inherited default of 1024 is a hard wall
#: rather than a slowdown: past it uvicorn stops accepting every connection.
NEEDS_FD_LIMIT = ("api", "web")


@pytest.fixture(scope="module")
def services() -> dict[str, Any]:
    assert COMPOSE.exists(), f"missing {COMPOSE}"
    return yaml.safe_load(COMPOSE.read_text())["services"]


def test_the_file_parses(services) -> None:
    assert len(services) > 10, "suspiciously few services — did the parse go wrong?"


def test_every_service_declares_a_memory_ceiling(services) -> None:
    missing = sorted(name for name, cfg in services.items() if not cfg.get("mem_limit"))
    assert not missing, (
        "no mem_limit on: " + ", ".join(missing) + " — on a shared host with no swap, "
        "an unbounded container can OOM-kill the neighbour stack"
    )


@pytest.mark.parametrize("name", NEEDS_FD_LIMIT)
def test_socket_heavy_services_raise_the_descriptor_limit(services, name) -> None:
    nofile = (services[name].get("ulimits") or {}).get("nofile")
    assert nofile, f"{name} inherits the 1024 default"
    soft = nofile["soft"] if isinstance(nofile, dict) else nofile
    assert soft >= 65536, f"{name} soft nofile is {soft}"


def test_redis_is_bounded_but_never_evicts(services) -> None:
    """Both halves matter. Unbounded, a queue backlog walks the host into the
    OOM killer. Evicting, it would drop Dramatiq jobs for orders already paid
    for — so refusing writes is the correct failure, and the alert is what
    makes it survivable."""
    command = " ".join(services["redis"]["command"])
    assert "--maxmemory " in command, "redis has no ceiling"
    assert "--maxmemory-policy noeviction" in command, (
        "an eviction policy would silently drop paid orders' fulfilment jobs"
    )


def test_postgres_is_not_running_on_stock_defaults(services: dict[str, Any]) -> None:
    """The image ships settings sized for a laptop.

    Measured on production before this was set: `shared_buffers` 128MB on a
    23GB host, `random_page_cost` 4 (a spinning-disk assumption that biases the
    planner away from the indexes migration 0055 exists to provide), and no
    `pg_stat_statements` — so "the database got slow" was a conversation with
    no evidence available.
    """
    command = " ".join(services["postgres"].get("command") or [])
    assert command, "postgres has no command override — it is on stock defaults"

    required = {
        "shared_buffers": "128MB of cache on a 23GB host",
        "effective_cache_size": "the planner cannot judge index vs scan without it",
        "random_page_cost": "the default assumes a spinning disk",
        "max_connections": "the pools alone can reach the old ceiling of 100",
        "idle_in_transaction_session_timeout": "this is the pool-exhaustion shape",
        "shared_preload_libraries": "no query-level observability without it",
    }
    missing = {k: why for k, why in required.items() if k not in command}
    assert not missing, "unset: " + "; ".join(f"{k} ({w})" for k, w in missing.items())


def test_postgres_has_room_for_parallel_query_shared_memory(services: dict[str, Any]) -> None:
    """Docker's default /dev/shm is 64MB. Parallel query results go there, so
    once tables are big enough for the planner to pick a parallel plan it fails
    with "could not resize shared memory segment" — at exactly the scale where
    reproducing it is hardest."""
    assert services["postgres"].get("shm_size"), "no shm_size on postgres"


def test_statement_timeout_stays_off(services: dict[str, Any]) -> None:
    """Deliberate, and worth stating so nobody "fixes" it in a hurry.

    It would apply to migrations too, which run as the same role — and killing
    a CREATE INDEX halfway is a worse outcome than the runaway query it
    prevents. `idle_in_transaction_session_timeout` covers the case that
    actually exhausts the pool: a transaction left open while a request waits
    on a supplier.
    """
    command = " ".join(services["postgres"].get("command") or [])
    assert "statement_timeout" not in command, (
        "statement_timeout also applies to migrations; see the comment in "
        "docker-compose.prod.yml before enabling it"
    )
