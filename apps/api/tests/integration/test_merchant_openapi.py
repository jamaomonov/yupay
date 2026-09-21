"""The published `/merchant/v1` contract, and what it must not publish.

This document is handed to strangers — that is its whole purpose — so the test
that matters is not "does it describe the six endpoints" but "does it describe
*only* them". The app's own `/openapi.json` carries every admin and storefront
path we have, and a filter that copied `components` wholesale would put the
shape of every internal DTO beside the six public ones without any path
pointing at them.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

#: Served **outside** `/merchant/v1`. That prefix means "signed, and exempt
#: from the coarse limiter because it authenticates its own caller", and four
#: sweeps enumerate it to assert exactly that of everything they find; a
#: public document inside it fails all four, correctly.
SCHEMA = "/merchant/openapi.json"

#: The whole machine API (spec §9.1). A seventh appearing here without a line
#: in the module README is the failure this pins.
DOCUMENTED = {
    "/merchant/v1/me",
    "/merchant/v1/catalog",
    "/merchant/v1/orders",
    "/merchant/v1/orders/{merchant_order_id}",
    "/merchant/v1/transactions",
    "/merchant/v1/validate/player",
}


async def test_the_published_schema_is_the_machine_api_and_nothing_else(
    integration_client: AsyncClient,
) -> None:
    """Six paths, no credential required, and no path from anywhere else."""
    r = await integration_client.get(SCHEMA)

    assert r.status_code == 200, "the contract is what somebody reads before they have a key"
    document = r.json()
    assert set(document["paths"]) == DOCUMENTED
    assert document["info"]["title"] == "YuPay Merchant API"


async def test_every_operation_documents_the_failures_it_can_answer(
    integration_client: AsyncClient,
) -> None:
    """The two statuses that decide whether an order happened.

    The contract promised only `401/403/422/429`, so a client generated from
    it had no branch for a `404` on a SKU that cannot be sold or a `409` for
    a deposit that does not cover the order — both documented in prose on the
    site and in the module README, and in neither machine-readable place.

    `_ROUTE_ERRORS` is keyed by `(method, path)` and raises at build time when
    a key matches nothing, which is how the first draft shipped with the order
    read left out: Starlette's `:path` convertor is in the route and not in
    the document.
    """
    document = (await integration_client.get(SCHEMA)).json()

    def codes(method: str, path: str) -> set[str]:
        return set(document["paths"][path][method]["responses"])

    assert {"404", "409"} <= codes("post", "/merchant/v1/orders")
    assert "404" in codes("get", "/merchant/v1/orders/{merchant_order_id}")
    assert "404" in codes("post", "/merchant/v1/validate/player")
    # Every one of them still carries the shared four, which come from the
    # auth dependency in front of all six.
    for path, item in document["paths"].items():
        for method in item:
            assert {"401", "403", "422", "429"} <= codes(method, path), (method, path)


async def test_no_internal_schema_rides_along(integration_client: AsyncClient) -> None:
    """Every exported schema is reachable from an exported path.

    Checked by name *and* by reachability: a name filter alone would pass a
    future `MerchantAdminThing`, and a reachability check alone would pass a
    leak whose name is innocent.
    """
    document = (await integration_client.get(SCHEMA)).json()
    schemas: dict[str, object] = document["components"]["schemas"]

    rendered = repr(document["paths"]) + repr(schemas)
    for name in schemas:
        assert f"#/components/schemas/{name}" in rendered, f"{name} is referenced by nothing"
    # The app's full schema has these and this document must not.
    full = (await integration_client.get("/openapi.json")).json()
    assert len(full["paths"]) > len(document["paths"])
    assert not any(path.startswith("/api/v1/admin") for path in document["paths"])
    assert not any("Admin" in name for name in schemas)


async def test_the_contract_does_not_document_itself(integration_client: AsyncClient) -> None:
    """A path that serves the document adds a method to every generated client
    and tells its reader nothing."""
    document = (await integration_client.get(SCHEMA)).json()

    assert SCHEMA not in document["paths"]


async def test_the_swagger_ui_renders_the_narrowed_contract(
    integration_client: AsyncClient,
) -> None:
    """`/merchant/docs` is the UI an integrator is meant to have.

    It reads the schema from its own origin, so there is no CORS to configure
    and nothing to rebuild when the contract changes.
    """
    r = await integration_client.get("/merchant/docs")

    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert SCHEMA in r.text
    # Never the full schema: that is the document this whole module exists to
    # avoid handing out.
    assert "/openapi.json'" not in r.text.replace(SCHEMA, "")


async def test_support_is_a_person_a_reader_can_reach(integration_client: AsyncClient) -> None:
    # A contract nobody can ask a question about is half a contract, and the
    # B2B programme is small enough that a name beats a ticket queue.
    body = (await integration_client.get(SCHEMA)).json()

    assert body["info"]["contact"]["url"] == "https://t.me/jama_omonov"
    assert "jama_omonov" in body["info"]["description"]


async def test_production_does_not_serve_the_full_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The app's own `/openapi.json` and Swagger are off in production.

    The full document lists every path we have, `/api/v1/admin/*` included.
    Publishing it is a map of the admin surface for anyone who asks, and no
    integrator has a use for it — they get the narrowed contract instead,
    which stays on in prod.

    Asserted on a freshly built app rather than over HTTP, because the test
    suite runs as `ENVIRONMENT=test`, where both routes are deliberately live.
    """
    from yupay.bootstrap import create_app
    from yupay.core import config as cfg

    monkeypatch.setenv("ENVIRONMENT", "prod")
    cfg.get_settings.cache_clear()
    try:
        paths = {route.path for route in create_app().routes}  # type: ignore[attr-defined]
    finally:
        monkeypatch.undo()
        cfg.get_settings.cache_clear()

    assert "/openapi.json" not in paths
    assert "/docs" not in paths
    # …and the two an integrator needs are still there.
    assert SCHEMA in paths
    assert "/merchant/docs" in paths
