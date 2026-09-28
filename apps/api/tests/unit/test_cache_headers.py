"""Live data is never cached by Cloudflare, a browser or a proxy (plan 3a, Task 0)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Response
from httpx import ASGITransport, AsyncClient
from yupay.core.cache_headers import NoStoreByDefault

pytestmark = pytest.mark.asyncio


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/live")
    async def live() -> dict[str, str]:
        return {"state": "offer_sent"}

    @app.get("/opted-in")
    async def opted_in(response: Response) -> dict[str, str]:
        response.headers["Cache-Control"] = "public, max-age=60"
        return {"ok": "yes"}

    app.add_middleware(NoStoreByDefault)
    return app


async def _get(path: str) -> dict[str, str]:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        return dict((await c.get(path)).headers)


async def test_a_response_without_a_policy_is_no_store() -> None:
    assert (await _get("/live"))["cache-control"] == "no-store"


async def test_a_route_that_sets_its_own_policy_keeps_it() -> None:
    assert (await _get("/opted-in"))["cache-control"] == "public, max-age=60"


async def test_errors_are_not_cached_either() -> None:
    assert (await _get("/nope"))["cache-control"] == "no-store"
