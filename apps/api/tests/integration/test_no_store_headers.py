"""The real app answers live endpoints with ``Cache-Control: no-store`` (plan 3a, Task 0)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "path",
    ["/api/v1/health", "/api/v1/orders/does-not-exist", "/api/v1/skins/facets"],
)
async def test_live_endpoints_are_never_cached(integration_client: AsyncClient, path: str) -> None:
    r = await integration_client.get(path)
    assert r.headers["cache-control"] == "no-store", (path, r.status_code)
