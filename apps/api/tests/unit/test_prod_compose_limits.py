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
