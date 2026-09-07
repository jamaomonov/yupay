"""The scoped ``RequestValidationError`` handler (`core.errors`).

``/merchant/v1`` publishes an RFC 7807 error table to third parties, so a
request the schema itself refuses has to answer problem+json there. Every
other surface must keep FastAPI's own ``{"detail": [ … ]}``: the generated
TypeScript client types every operation from the ``HTTPValidationError``
schema, so changing the runtime body app-wide would make the client wrong
everywhere without moving the schema ``openapi-drift`` compares.

Both halves are pinned here — the merchant half by its HTTP behaviour (in the
two merchant suites, which own the signing fixtures) and the delegation half
byte for byte, because "unchanged elsewhere" is the claim that is easy to
believe and hard to notice breaking.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from httpx import AsyncClient
from starlette.requests import Request
from starlette.responses import Response
from yupay.core.errors import CODE_INVALID_REQUEST, problem_json_validation_handler

pytestmark = pytest.mark.asyncio

_HANDLER = problem_json_validation_handler(prefixes=["/merchant/v1"])

#: A ``value_error`` entry as pydantic really builds one. ``ctx["error"]`` is
#: the original exception **object**, which ``json.dumps`` refuses — so this is
#: also the fixture that proves the handler encodes rather than dumps. A
#: non-UUID ``sku_id`` is the shape a real integrator hits first.
_ERRORS: list[Any] = [
    {
        "type": "value_error",
        "loc": ("body", "sku_id"),
        "msg": "Value error, sku_id must be a UUID",
        "input": "not-a-uuid",
        "ctx": {"error": ValueError("sku_id must be a UUID")},
    }
]


def _request(path: str) -> Request:
    """A minimal ASGI request the handler can read a path off."""
    return Request(
        {"type": "http", "method": "POST", "path": path, "headers": [], "query_string": b""}
    )


def _payload(response: Response) -> dict[str, Any]:
    """The rendered body, parsed. ``Response.body`` is typed loosely."""
    body = response.body
    return json.loads(bytes(body))  # type: ignore[no-any-return]


async def test_outside_the_merchant_prefix_the_body_is_fastapis_own_byte_for_byte() -> None:
    """The delegation is the load-bearing half: every other surface is untouched."""
    exc = RequestValidationError(_ERRORS)
    path = "/api/v1/orders"

    ours = await _HANDLER(_request(path), exc)
    theirs = await request_validation_exception_handler(_request(path), exc)

    assert ours.body == theirs.body
    assert ours.status_code == theirs.status_code
    assert ours.media_type == theirs.media_type


@pytest.mark.parametrize(
    "path",
    ["/merchant/v1beta/orders", "/merchant/v10/orders", "/merchant/v2/orders", "/merchant/v1x"],
)
async def test_a_neighbouring_prefix_does_not_inherit_the_merchant_contract(path: str) -> None:
    """The scope is a path segment, not a string prefix.

    ``startswith("/merchant/v1")`` is true of ``/merchant/v1beta`` and
    ``/merchant/v10`` as well. Nothing is mounted at either today, so this
    pins the rule before something is: a surface joins this contract by being
    put under the prefix, never by being spelled like it.
    """
    exc = RequestValidationError(_ERRORS)

    ours = await _HANDLER(_request(path), exc)
    theirs = await request_validation_exception_handler(_request(path), exc)

    assert ours.body == theirs.body
    assert ours.media_type == theirs.media_type


async def test_the_prefix_itself_is_in_scope() -> None:
    """The other edge of the same rule: the prefix is not only its children."""
    response = await _HANDLER(_request("/merchant/v1"), RequestValidationError(_ERRORS))

    assert response.media_type == "application/problem+json"


async def test_inside_the_merchant_prefix_the_body_is_problem_json() -> None:
    """And it renders the ``ctx`` a naive ``json.dumps`` handler would die on."""
    response = await _HANDLER(_request("/merchant/v1/orders"), RequestValidationError(_ERRORS))

    assert response.status_code == 422
    assert response.media_type == "application/problem+json"
    payload = _payload(response)
    assert payload["type"] == "https://app.yupay.uz/errors/validation"
    assert payload["status"] == 422
    assert payload["code"] == CODE_INVALID_REQUEST
    # ``detail`` stays a string on every error this API returns; the per-field
    # list moved to ``errors`` rather than retyping it (RFC 7807 §3.1).
    assert isinstance(payload["detail"], str)
    assert payload["detail"] == "body.sku_id: Value error, sku_id must be a UUID"
    assert payload["errors"][0]["loc"] == ["body", "sku_id"]


async def test_the_summary_counts_the_failures_it_does_not_spell_out() -> None:
    """``detail`` is a sentence, not a report — a body can fail every field."""
    many = [
        {"type": "missing", "loc": ("body", f"f{n}"), "msg": "Field required", "input": {}}
        for n in range(5)
    ]
    payload = _payload(
        await _HANDLER(_request("/merchant/v1/orders"), RequestValidationError(many))
    )

    assert payload["detail"].endswith("and 2 more")
    assert len(payload["errors"]) == 5


async def test_a_retail_endpoint_answers_the_shape_the_generated_client_expects(
    integration_client: AsyncClient,
) -> None:
    """Through the real app, not the handler in isolation.

    ``?limit=0`` fails before the route body runs, so the brand slug never has
    to exist. If this ever answers problem+json, every operation in
    ``packages/api-client`` is mistyped and nothing in CI would say so.
    """
    r = await integration_client.get("/api/v1/reviews/brands/whatever?limit=0")

    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert isinstance(body["detail"], list)
    assert set(body) == {"detail"}
