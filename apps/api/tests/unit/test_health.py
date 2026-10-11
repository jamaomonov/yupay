"""Smoke tests for the health/readiness endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_healthz(client: AsyncClient) -> None:
    """``/healthz`` returns 200 with ``{"status": "ok"}``."""
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readyz(client: AsyncClient) -> None:
    """``/readyz`` returns 200 with ``{"status": "ready"}``."""
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_health_probes_answer_head(client: AsyncClient) -> None:
    """Uptime monitors probe with HEAD; a 405 would read as the API being down."""
    for path in ("/healthz", "/readyz"):
        response = await client.head(path)
        assert response.status_code == 200, path
