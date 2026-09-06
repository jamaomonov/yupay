"""Application-level error types and a global RFC 7807 problem+json handler."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


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
