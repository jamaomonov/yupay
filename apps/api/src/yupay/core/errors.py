"""Application-level error types and a global RFC 7807 problem+json handler."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base class for all expected, user-facing application errors."""

    status_code: int = 500
    type_uri: str = "https://yupay.io/errors/internal"
    title: str = "Internal error"

    def __init__(self, detail: str | None = None, **extra: Any) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.extra = extra


class NotFoundError(AppError):
    """Resource not found."""

    status_code = 404
    type_uri = "https://yupay.io/errors/not-found"
    title = "Not found"


class ConflictError(AppError):
    """State conflict — e.g. attempt to double-spend an idempotency key."""

    status_code = 409
    type_uri = "https://yupay.io/errors/conflict"
    title = "Conflict"


class ValidationError(AppError):
    """Request validation failed beyond Pydantic's structural checks."""

    status_code = 422
    type_uri = "https://yupay.io/errors/validation"
    title = "Validation failed"


class UnauthorizedError(AppError):
    """Auth missing or invalid."""

    status_code = 401
    type_uri = "https://yupay.io/errors/unauthorized"
    title = "Unauthorized"


class ForbiddenError(AppError):
    """Auth present but insufficient."""

    status_code = 403
    type_uri = "https://yupay.io/errors/forbidden"
    title = "Forbidden"


class UpstreamUnavailableError(AppError):
    """A third-party service we depend on (FX, supplier API, payment gateway)
    couldn't be reached. Maps to RFC 7807 with HTTP 502."""

    status_code = 502
    type_uri = "https://yupay.io/errors/upstream-unavailable"
    title = "Upstream unavailable"


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    """Render an :class:`AppError` as an RFC 7807 problem+json response."""
    body: dict[str, Any] = {
        "type": exc.type_uri,
        "title": exc.title,
        "status": exc.status_code,
        "detail": exc.detail,
    }
    body.update(exc.extra)
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        media_type="application/problem+json",
    )
