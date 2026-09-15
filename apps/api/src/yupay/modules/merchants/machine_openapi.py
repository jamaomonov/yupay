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

Swagger UI over it lives beside it at `/merchant/docs`, for the same reason the
schema does — same origin, so there is no CORS to configure and nothing to
rebuild when the contract moves. The app's own `/openapi.json` and `/docs` are
switched off in production (see `bootstrap`); these two are what an integrator
is meant to have.

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
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse

from yupay.core.config import get_settings
from yupay.modules.merchants import auth as merchant_auth

#: Only these paths, and everything they reach. Note it is **not** this
#: router's own prefix — the document describes `/merchant/v1` and is served
#: beside it.
_PREFIX: Final = "/merchant/v1"

_REF: Final = "#/components/schemas/"

#: Where an integrator asks a question. A person, not a queue — the B2B
#: programme is small enough that a name is faster than a ticket.
SUPPORT_TELEGRAM: Final = "jama_omonov"

#: One tag per area, so a reference page can group six endpoints into
#: something a reader scans rather than an alphabetical list. FastAPI puts
#: ``merchant-api`` on every operation; these replace it.
_TAGS: Final[dict[str, tuple[str, str]]] = {
    "/merchant/v1/me": ("Account", "Who you are and what you can spend."),
    "/merchant/v1/catalog": ("Catalog", "What you can buy, priced for your account."),
    "/merchant/v1/orders": ("Orders", "Placing an order and reading it back."),
    "/merchant/v1/transactions": ("Deposit", "Every movement of your balance."),
    "/merchant/v1/validate/player": (
        "Validation",
        "Check an end customer's id before you charge them.",
    ),
}

#: Errors every signed endpoint can answer, with the code to switch on. Kept
#: here rather than declared per route because they come from the auth
#: dependency, which sits in front of all of them — a per-route copy would be
#: five copies to forget to update.
_SHARED_ERRORS: Final[dict[str, str]] = {
    "401": (
        "Not authenticated. `code` is `missing_credentials` (a header is absent), "
        "`stale_timestamp` (not digits, or more than ±300 s from ours) or "
        "`invalid_credentials` (unknown key, revoked key, or a signature that does not "
        "match). The three are deliberately indistinguishable from outside beyond the "
        "code."
    ),
    "403": (
        "Authenticated and refused. `merchant_frozen` — the account is suspended; "
        "`ip_not_allowed` — this address is not on the key's allowlist."
    ),
    "429": (
        "Rate limited, with `Retry-After`. Two axes: per source address, charged before "
        "anything is parsed, and per key, charged only once your signature verifies — so "
        "nobody who reads your key id off a header can spend your budget."
    ),
}

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
    tags: list[dict[str, str]] = []
    for path, item in paths.items():
        named = _TAGS.get(path) or _TAGS.get(path.rsplit("/", 1)[0])
        if named is None:  # pragma: no cover -- every path above is mapped
            continue
        name, summary = named
        if not any(tag["name"] == name for tag in tags):
            tags.append({"name": name, "description": summary})
        for method, operation in item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            operation["tags"] = [name]
            # Every one of these sits behind the same signature check, so the
            # errors it can raise belong on every one of them.
            operation.setdefault("security", [{"MerchantKey": [], "MerchantSignature": []}])
            for status, text in _SHARED_ERRORS.items():
                operation["responses"].setdefault(status, {"description": text})
            # FastAPI's default is the function name plus the route —
            # `place_order_merchant_v1_orders_post` — which becomes the method
            # name in every generated client. The summary is what a reader
            # already sees, so derive from it and keep the two in step.
            operation["operationId"] = _operation_id(method, path)

    document: dict[str, Any] = {
        "openapi": full["openapi"],
        "info": {
            "title": "YuPay Merchant API",
            "version": full["info"]["version"],
            "description": (
                "Wholesale ordering for resellers.\n\n"
                "**Every request is signed.** Send `X-Merchant-Key`, "
                "`X-Merchant-Timestamp` and `X-Merchant-Signature`, where the signature "
                "is HMAC-SHA256 over\n\n"
                "```\n{timestamp}\\n{METHOD}\\n{raw_path}\\n{raw_query}\\n"
                "{sha256_hex(body)}\n```\n\n"
                "keyed by your secret. The timestamp must be within ±300 s of ours. A "
                "signature is deliberately **not** single-use, so an at-least-once retry "
                "of the same request is safe.\n\n"
                '**Money is a decimal string**, never a float — `"16.54"`. Timestamps '
                "are ISO 8601 UTC. Fields are only ever *added* to a response, so parse "
                "leniently; a breaking change would be a `/merchant/v2`.\n\n"
                "**Stuck?** Write to "
                f"[@{SUPPORT_TELEGRAM}](https://t.me/{SUPPORT_TELEGRAM}) in Telegram.\n\n"
                '**"Try it out" will not work here, and cannot.** Every call is signed '
                "with your merchant secret, and that secret belongs on your server — "
                "pasting it into a box on a web page would undo the one rule this whole "
                "auth design rests on. Ready-made cURL, Python and Node.js samples with "
                "the signature already computed are at "
                "[reseller.yupay.uz/docs](https://reseller.yupay.uz/docs); copy one into "
                "your own terminal, where your secret already lives."
            ),
            "contact": {
                "name": "Техподдержка YuPay — @jama_omonov",
                "url": f"https://t.me/{SUPPORT_TELEGRAM}",
            },
        },
        "tags": tags,
        "paths": paths,
        "components": {
            "schemas": {name: schemas[name] for name in sorted(seen) if name in schemas},
            "securitySchemes": {
                "MerchantKey": {
                    "type": "apiKey",
                    "in": "header",
                    "name": merchant_auth.KEY_HEADER,
                    "description": "Your key id, `ypm_…`. Public; it identifies the key, not you.",
                },
                "MerchantSignature": {
                    "type": "apiKey",
                    "in": "header",
                    "name": merchant_auth.SIGNATURE_HEADER,
                    "description": (
                        "Lowercase hex HMAC-SHA256 of the canonical string, keyed by your "
                        f"secret. Send `{merchant_auth.TIMESTAMP_HEADER}` beside it."
                    ),
                },
            },
        },
    }
    if base:
        document["servers"] = [{"url": base, "description": "Production"}]
    return document


def _operation_id(method: str, path: str) -> str:
    """A name a generated client can carry — `getCatalog`, not `read_catalog_merchant_v1…`."""
    parts = [p for p in path.removeprefix(_PREFIX).strip("/").split("/") if p]
    words = [w.strip("{}").replace("_", " ").title().replace(" ", "") for w in parts] or ["Root"]
    verb = {"get": "get", "post": "post", "put": "put", "patch": "patch", "delete": "delete"}[
        method
    ]
    return verb + "".join(words)


@router.get("/docs", include_in_schema=False, response_class=HTMLResponse)
async def merchant_docs() -> HTMLResponse:
    """Swagger UI over the narrowed contract, one level above the API it reads.

    Served here rather than from the cabinet because the schema it fetches is
    on this origin — no CORS to configure, and nothing to rebuild when the
    contract moves. The app's own Swagger is off in production (see
    ``bootstrap``); this is the one integrators are meant to have.

    ``Try it out`` renders but cannot succeed: a signed request needs the
    merchant's secret, which belongs on their server. The description says so
    rather than leaving somebody to discover it by pasting a credential into a
    web page.
    """
    return get_swagger_ui_html(
        openapi_url=f"{router.prefix}/openapi.json",
        title="YuPay Merchant API",
        swagger_favicon_url="https://yupay.uz/favicon.ico",
    )


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
