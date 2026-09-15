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
