"""The `/merchant/v1` contract as a schema a reseller can generate a client from.

Spec §11 asks the cabinet's docs for an "OpenAPI-generated reference". The
app's own `/openapi.json` is the wrong thing to point at: it carries every
admin, storefront and webhook path we have, so a generated client would be a
map of our whole surface and a reseller would have to find their six endpoints
inside it.

This serves **only** the paths under `/merchant/v1`, with `components.schemas`
pruned to what those paths actually reference — transitively, because a
response model reaches others through `$ref`. The pruning is the security-
relevant half: copying the whole `components` block would publish the shape of
every admin DTO beside six public ones.

Unauthenticated on purpose. A contract is not data, it is what somebody reads
*before* they have a credential, and the whole point of publishing it is that
an integrator can start without asking us for anything.

**And therefore served at `/merchant/openapi.json`, one level above the API it
describes.** `/merchant/v1` has a defining property — everything under it is
HMAC-signed, refuses an unsigned request with a 401 and a frozen merchant with
a 403, and sits on the limiter's exemption list because it authenticates its
own caller. This document does none of that, and three sweeps in
`test_merchant_api_read.py` plus one in `test_rate_limit.py` enumerate the
prefix and assert those properties of everything they find. Putting a public
document inside that prefix broke all four, which was the right answer from
the tests: the prefix means "signed", and a schema is not.
"""

from __future__ import annotations

from typing import Any, Final

from fastapi import APIRouter, Request

from yupay.core.config import get_settings

#: Only these paths, and everything they reach. Note it is **not** this
#: router's own prefix — the document describes `/merchant/v1` and is served
#: beside it.
_PREFIX: Final = "/merchant/v1"

_REF: Final = "#/components/schemas/"

#: Built once per process. ``app.openapi()`` walks every route and model, and
#: this endpoint takes no credential — rebuilding per request would make it
#: the cheapest way to spend our CPU from the outside.
_cached: dict[str, Any] | None = None

router = APIRouter(prefix="/merchant", tags=["merchant-api"])


def _referenced(node: Any, schemas: dict[str, Any], seen: set[str]) -> None:
    """Collect schema names reachable from ``node``, following `$ref` chains."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(_REF):
            name = ref[len(_REF) :]
            if name not in seen:
                seen.add(name)
                _referenced(schemas.get(name, {}), schemas, seen)
        for value in node.values():
            _referenced(value, schemas, seen)
    elif isinstance(node, list):
        for value in node:
            _referenced(value, schemas, seen)


def build(full: dict[str, Any]) -> dict[str, Any]:
    """Narrow a complete OpenAPI document to the merchant machine API.

    Args:
        full: The app's own schema, as ``FastAPI.openapi()`` returns it.

    Returns:
        A self-contained document: the `/merchant/v1` paths, the schemas they
        reach, and nothing else. Safe to hand to a stranger — which is the
        test that matters, and the one `test_merchant_openapi` makes.
    """
    paths = {path: item for path, item in full["paths"].items() if path.startswith(_PREFIX)}
    schemas: dict[str, Any] = full.get("components", {}).get("schemas", {})
    seen: set[str] = set()
    _referenced(paths, schemas, seen)

    base = get_settings().base_url.rstrip("/")
    document: dict[str, Any] = {
        "openapi": full["openapi"],
        "info": {
            "title": "YuPay Merchant API",
            "version": full["info"]["version"],
            "description": (
                "Wholesale ordering for resellers. Every request is signed with "
                "HMAC-SHA256 over the request line; see the integration guide in "
                "the partner cabinet. Money is a decimal string, timestamps are "
                "ISO 8601 UTC, and fields are only ever added to a response."
            ),
        },
        "paths": paths,
        "components": {
            "schemas": {name: schemas[name] for name in sorted(seen) if name in schemas}
        },
    }
    if base:
        document["servers"] = [{"url": base}]
    return document


@router.get(
    "/openapi.json",
    summary="This API's own OpenAPI schema",
    include_in_schema=False,
)
async def merchant_openapi(request: Request) -> dict[str, Any]:
    """The contract, unauthenticated, so an integrator can start with it.

    ``include_in_schema=False``: a document that describes itself adds a path
    to every generated client and tells a reader nothing.
    """
    global _cached
    if _cached is None:
        _cached = build(request.app.openapi())
    return _cached


__all__ = ["build", "router"]
