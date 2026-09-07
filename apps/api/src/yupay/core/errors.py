"""Application-level error types and a global RFC 7807 problem+json handler."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from collections.abc import Awaitable, Callable, Sequence


class AppError(Exception):
    """Base class for all expected, user-facing application errors."""

    status_code: int = 500
    type_uri: str = "https://app.yupay.uz/errors/internal"
    title: str = "Internal error"

    def __init__(self, detail: str | None = None, **extra: Any) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.extra = extra


class NotFoundError(AppError):
    """Resource not found."""

    status_code = 404
    type_uri = "https://app.yupay.uz/errors/not-found"
    title = "Not found"


class ConflictError(AppError):
    """State conflict — e.g. attempt to double-spend an idempotency key."""

    status_code = 409
    type_uri = "https://app.yupay.uz/errors/conflict"
    title = "Conflict"


class ValidationError(AppError):
    """Request validation failed beyond Pydantic's structural checks."""

    status_code = 422
    type_uri = "https://app.yupay.uz/errors/validation"
    title = "Validation failed"


class UnauthorizedError(AppError):
    """Auth missing or invalid."""

    status_code = 401
    type_uri = "https://app.yupay.uz/errors/unauthorized"
    title = "Unauthorized"


class ForbiddenError(AppError):
    """Auth present but insufficient."""

    status_code = 403
    type_uri = "https://app.yupay.uz/errors/forbidden"
    title = "Forbidden"


class EmailUnverifiedError(AppError):
    """Login attempted before the account's email was verified."""

    status_code = 403
    type_uri = "https://app.yupay.uz/errors/email-unverified"
    title = "Email not verified"


class AccountSuspendedError(AppError):
    """The account has been banned by an administrator.

    403 and not 401 on purpose: both frontends treat 401 as "the session
    expired" and answer it by refreshing, which for a banned account would loop
    and then log the customer out with no explanation at all. A distinct
    ``type_uri`` lets the storefront say what actually happened.
    """

    status_code = 403
    type_uri = "https://app.yupay.uz/errors/account-suspended"
    title = "Account suspended"


class PaymentUnavailableAbroadError(AppError):
    """The pre-charge geo veto refused this checkout (ADR-0063).

    422, not 403: the request itself is fine, but this particular buyer —
    a guest or fresh account whose evidence puts them outside the
    storefront's home countries/timezones — cannot complete it right now.
    The message is a slug only; the frontends carry the actual wording so
    it can be translated (see ``web.store.errAbroad`` / ``topup.errAbroad``).
    """

    status_code = 422
    type_uri = "https://app.yupay.uz/errors/payment-unavailable-abroad"
    title = "Payment unavailable from this location"


class RateLimitedError(AppError):
    """Request rate limit exceeded — client should slow down."""

    status_code = 429
    type_uri = "https://app.yupay.uz/errors/rate-limited"
    title = "Too many requests"


class UpstreamUnavailableError(AppError):
    """A third-party service we depend on (FX, supplier API, payment gateway)
    couldn't be reached. Maps to RFC 7807 with HTTP 502."""

    status_code = 502
    type_uri = "https://app.yupay.uz/errors/upstream-unavailable"
    title = "Upstream unavailable"


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    """Render an :class:`AppError` as an RFC 7807 problem+json response.

    Every key in ``exc.extra`` joins the body. One of them is also promoted to
    a header: an integer ``retry_after`` becomes ``Retry-After`` (RFC 9110
    §10.2.3), because a machine client throttled by a fixed-window counter has
    no other way to learn how long to wait — and the alternative it picks
    without one is "retry immediately", which is the traffic that tripped the
    limit. The global slowapi tier already sets the header
    (``headers_enabled=True``); this makes the application-level 429s agree.
    """
    body: dict[str, Any] = {
        "type": exc.type_uri,
        "title": exc.title,
        "status": exc.status_code,
        "detail": exc.detail,
    }
    body.update(exc.extra)
    retry_after = exc.extra.get("retry_after")
    headers = {"Retry-After": str(retry_after)} if isinstance(retry_after, int) else None
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        media_type="application/problem+json",
        headers=headers,
    )


#: RFC 7807 ``code`` for a request the schema itself refused — a missing or
#: unknown field, a value of the wrong shape, a query parameter out of range.
#: Distinct from every business ``code`` because the cause is different in kind:
#: nothing about the account or the catalog is wrong, the bytes were.
CODE_INVALID_REQUEST = "invalid_request"

#: How many individual failures :func:`_summarise` spells out before it counts
#: the rest. A body can fail every field at once and ``detail`` is a sentence,
#: not a report — the full list rides in ``errors``.
_SUMMARY_LIMIT = 3


def _summarise(errors: list[Any]) -> str:
    """One human sentence for a list of validation failures.

    ``detail`` stays a **string** (RFC 7807 §3.1). The machine-readable list
    is a separate field, which is the whole reason this function is short: it
    exists so a human reading a log line knows what broke, not so a client can
    parse it.

    Args:
        errors: ``exc.errors()`` after :func:`jsonable_encoder`.

    Returns:
        ``"body.sku_id: Value error, sku_id must be a UUID"``, several such
        joined by ``"; "``, or a bare fallback when the list is empty.
    """
    parts: list[str] = []
    for error in errors[:_SUMMARY_LIMIT]:
        if not isinstance(error, dict):  # pragma: no cover -- defensive
            continue
        location = ".".join(str(part) for part in error.get("loc", ()))
        message = str(error.get("msg", "invalid value"))
        parts.append(f"{location}: {message}" if location else message)
    if len(errors) > _SUMMARY_LIMIT:
        parts.append(f"and {len(errors) - _SUMMARY_LIMIT} more")
    return "; ".join(parts) or "request validation failed"


def problem_json_validation_handler(
    *, prefixes: Sequence[str]
) -> Callable[[Request, RequestValidationError], Awaitable[Response]]:
    """Build the app-wide ``RequestValidationError`` handler.

    FastAPI's own handler answers ``422`` with ``{"detail": [ … ]}`` —
    ``application/json``, no ``type``, no ``code``. That is fine everywhere the
    consumer is our own generated TypeScript client, and it is **not** fine on
    ``/merchant/v1``, whose error table is published to third parties as RFC
    7807.

    So this is scoped rather than app-wide in effect: paths under ``prefixes``
    get problem+json, and **every other path is delegated to FastAPI's own
    handler**, byte for byte. Two reasons it is not simply replaced everywhere:

    - FastAPI documents each route's 422 as ``HTTPValidationError`` and
      ``packages/api-client`` types every operation from that schema. Changing
      the runtime body without changing the schema would make the generated
      client wrong for nearly every endpoint in the repo — and ``openapi-drift``
      could not catch it, because the schema would not have moved.
    - The storefront and the admin SPA already read ``detail[]``. Retyping it
      is a breaking change to them for no gain.

    ``exc.errors()`` goes through :func:`jsonable_encoder` and not
    ``json.dumps``: a ``value_error`` entry carries the original exception
    object under ``ctx["error"]``, which ``json.dumps`` refuses with a
    ``TypeError`` — and a non-UUID ``sku_id`` is one of the likeliest
    integrator mistakes, so a handler that raised on it would turn a clean 422
    into a 500 on the most-hit path. FastAPI's own handler encodes for exactly
    the same reason.

    Args:
        prefixes: Path prefixes that receive problem+json. Pass the router's
            own ``prefix`` rather than a literal, so the two cannot drift.

    Returns:
        The handler to register with ``app.add_exception_handler``.
    """
    scoped = tuple(prefixes)

    def in_scope(path: str) -> bool:
        """True if ``path`` is a scoped prefix or a path segment under one.

        Segment-wise, not string-wise. A bare ``startswith`` also matches
        ``/merchant/v10/…`` and ``/merchant/v1beta/…`` — nothing is mounted
        there today, and ``/merchant/v2`` correctly falls out of scope either
        way, but a future ``/merchant/v1beta`` would silently inherit this
        prefix's published error contract without anyone choosing it.
        """
        return any(path == prefix or path.startswith(f"{prefix}/") for prefix in scoped)

    async def handler(request: Request, exc: RequestValidationError) -> Response:
        """Render a validation failure for whoever asked."""
        if not in_scope(request.url.path):
            return await request_validation_exception_handler(request, exc)
        errors = jsonable_encoder(exc.errors())
        return JSONResponse(
            status_code=ValidationError.status_code,
            content={
                "type": ValidationError.type_uri,
                "title": ValidationError.title,
                "status": ValidationError.status_code,
                "detail": _summarise(errors),
                "code": CODE_INVALID_REQUEST,
                # The machine-readable list, under its own key. ``detail`` is a
                # string in RFC 7807 and FastAPI's ``detail`` is an array, so
                # one of the two names had to move; moving ours keeps the
                # published contract's ``detail`` the same type on every error
                # this API can return.
                "errors": errors,
            },
            media_type="application/problem+json",
        )

    return handler
