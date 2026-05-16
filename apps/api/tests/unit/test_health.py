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
