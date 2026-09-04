"""Uzum Bank Merchant API REST webhooks.

Uzum's Merchant API is five plain HTTP/JSON ``POST`` endpoints (``/check``
``/create`` ``/confirm`` ``/reverse`` ``/status``) authenticated with HTTP
Basic auth plus a ``serviceId``. This route module is the transport shell
around :mod:`yupay.modules.uzum.service`'s handlers: it parses the raw body
itself (FastAPI's request-model validation must never fire — a 422 would
read to Uzum as something other than the documented error envelope),
authenticates, validates ``serviceId`` and the endpoint's required fields,
dispatches to the matching service handler, and renders every outcome as a
JSON body — success at HTTP 200, error at HTTP 400.

**HTTP 200 on success, HTTP 400 on error.** Per Uzum's Merchant API docs
(``/check`` operation, "Vebhuki" §): "Если вебхук не может быть обработан
успешно, верните HTTP 400 и JSON-объект ошибки с полем errorCode" — on any
failure, return HTTP 400 with the error body. We never raise a raw HTTP
exception on the merchant path, though: auth failures, bad JSON, missing
fields and internal errors all come back as a normal
``{"status": "FAILED", "errorCode": ...}`` body, just wrapped in a
``JSONResponse`` at status 400 instead of FastAPI's default 200. Contrast
:mod:`yupay.modules.payme.routes`, whose JSON-RPC convention (correctly)
answers every outcome — success or error — at HTTP 200; that module is not
affected by this file.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.modules.uzum import service as uzum_svc
from yupay.modules.uzum.errors import (
    UzumError,
    access_denied,
    bad_json,
    internal_error,
    invalid_operation,
    invalid_service_id,
    missing_params,
)

router = APIRouter(prefix="/payments/uzum", tags=["uzum"])
log = get_logger("yupay.uzum.merchant")

DbSession = Annotated[AsyncSession, Depends(db_session)]

# Envelope fields that are transport plumbing, not part of the /confirm
# payment-source audit blob. Everything else in the body (paymentSource,
# tariff, processingReferenceNumber, phone, cardType, ...) is stored verbatim.
_ENVELOPE_FIELDS = frozenset({"serviceId", "timestamp", "transId"})


def _parse_body(raw: bytes) -> dict[str, Any]:
    """Parse the raw request body as a JSON object.

    Args:
        raw: The raw request bytes.

    Returns:
        The parsed JSON object.

    Raises:
        UzumError: ``10002`` if the body is not valid JSON, or is valid JSON
            that is not an object (Uzum's envelope is always an object).
    """
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        raise bad_json() from None
    if not isinstance(payload, dict):
        raise bad_json()
    return payload


def _echo(body: dict[str, Any]) -> dict[str, Any]:
    """Build the ``serviceId``/``transId`` echo kwargs for an error response.

    Args:
        body: The parsed request body.

    Returns:
        ``{"serviceId": ...}``, plus ``"transId"`` when the request carried one.
    """
    echo: dict[str, Any] = {"serviceId": body.get("serviceId")}
    if "transId" in body:
        echo["transId"] = body["transId"]
    return echo


def _fail(exc: UzumError, **echo: Any) -> JSONResponse:
    """Render a :class:`UzumError` as Uzum's documented HTTP 400 failure response.

    The JSON body is exactly :meth:`UzumError.to_response`'s
    ``{"status": "FAILED", "errorCode": ...}`` shape — unchanged from before
    this transport-level fix. Only the wire status code differs from a
    success response: 400 here, versus the implicit 200 FastAPI gives a
    plain-dict return.

    Args:
        exc: The error to render.
        **echo: Request fields to echo back verbatim, e.g. ``serviceId``,
            ``transId``.

    Returns:
        A ``JSONResponse`` carrying the error body at HTTP 400.
    """
    return JSONResponse(content=exc.to_response(**echo), status_code=400)


def _authenticate(request: Request) -> None:
    """Validate the request's HTTP Basic credentials against Uzum's config.

    Accepts a login/password pair matching either the production credentials
    (``uzum_login``/``uzum_password``) or the sandbox credentials
    (``uzum_test_login``/``uzum_test_password``). A pair with either side
    blank is never accepted, so an unconfigured acquirer rejects every
    request rather than silently matching on empty strings.

    Args:
        request: The inbound merchant request.

    Raises:
        UzumError: ``10001`` if the header is missing, malformed, or the
            credentials don't match a configured pair.
    """
    settings = get_settings()
    header = request.headers.get("Authorization", "")
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        raise access_denied()
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise access_denied() from None
    login, sep, password = decoded.partition(":")
    if not sep:
        raise access_denied()
    valid_pairs = [
        (login_, password_)
        for login_, password_ in (
            (settings.uzum_login, settings.uzum_password),
            (settings.uzum_test_login, settings.uzum_test_password),
        )
        if login_ and password_
    ]
    # Accumulate across every configured pair rather than short-circuiting on
    # the first match, so response timing doesn't leak which pair (if any)
    # matched. An empty ``valid_pairs`` (unconfigured acquirer) always fails.
    creds_ok = False
    try:
        for login_, password_ in valid_pairs:
            creds_ok |= hmac.compare_digest(login, login_) & hmac.compare_digest(
                password, password_
            )
    except TypeError:
        # ``login``/``password`` are untrusted wire input and may contain
        # non-ASCII bytes, which ``hmac.compare_digest`` rejects on ``str``
        # operands — fail closed, mirroring click/signature.py.
        raise access_denied() from None
    if not creds_ok:
        raise access_denied()


def _service_guard(body: dict[str, Any]) -> int:
    """Validate the request's ``serviceId`` matches our configured value.

    Args:
        body: The parsed request body.

    Returns:
        The configured ``uzum_service_id`` (equal, by construction, to the
        request's own ``serviceId`` — returning the config's own ``int``
        rather than the request's untyped value keeps callers strictly typed).

    Raises:
        UzumError: ``10006`` if ``serviceId`` is missing, or does not match
            the configured ``uzum_service_id`` (also raised when we have no
            ``serviceId`` configured at all).
    """
    settings = get_settings()
    service_id = body.get("serviceId")
    if settings.uzum_service_id is None or service_id != settings.uzum_service_id:
        raise invalid_service_id()
    return settings.uzum_service_id


def _req_str(source: dict[str, Any], key: str) -> str:
    """Return a required non-empty string field, else raise ``10005``."""
    value = source.get(key)
    if not isinstance(value, str) or not value:
        raise missing_params()
    return value


def _req_int(source: dict[str, Any], key: str) -> int:
    """Return a required integer field, else raise ``10005``.

    ``bool`` is excluded even though it subclasses ``int`` in Python — an
    ``amount`` of ``true`` is malformed, not the integer ``1``.
    """
    value = source.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise missing_params()
    return value


def _req_dict(source: dict[str, Any], key: str) -> dict[str, Any]:
    """Return a required object field, else raise ``10005``."""
    value = source.get(key)
    if not isinstance(value, dict):
        raise missing_params()
    return value


def _req_order_id(params: dict[str, Any]) -> str:
    """Return the order id from Uzum's ``params`` envelope, else raise ``10005``.

    Uzum sends the account field as **camelCase ``orderId``** — confirmed
    2026-09-04 against the live service, when every ``/check`` came back
    ``10005`` because we only looked for ``order_id``. That snake_case name
    was an assumption carried over from Payme's ``account.order_id`` and was
    flagged unconfirmed in the design's open items; it was never what Uzum
    actually sends.

    Their docs describe this field as configurable per service, so both
    spellings are accepted: a future cabinet change cannot break the webhook
    again, and both names denote the same value, which the service layer
    validates against a real order regardless.

    Args:
        params: The request's ``params`` object.

    Raises:
        UzumError: ``10005`` if neither spelling carries a non-empty string.
    """
    for key in ("orderId", "order_id"):
        value = params.get(key)
        if isinstance(value, str) and value:
            return value
    raise missing_params()


async def _rollback_after_internal_error(db: AsyncSession, *, endpoint: str) -> None:
    """Best-effort rollback after an unexpected exception, logging either way."""
    try:
        await db.rollback()
    except Exception:
        log.exception("uzum.merchant.rollback_failed", endpoint=endpoint)
    log.exception("uzum.merchant.internal_error", endpoint=endpoint)


@router.post("/check", summary="Uzum Merchant API: /check", response_model=None)
async def uzum_check(request: Request, db: DbSession) -> dict[str, Any] | JSONResponse:
    """Handle Uzum's ``/check``: may this order be paid for these params?

    Args:
        request: The inbound webhook request (raw body read here, not via a
            request model, so a malformed body is ``10002`` — never a 422).
        db: Active session; this route owns the commit/rollback.

    Returns:
        The response body dict at HTTP 200 on success; on failure, a
        ``JSONResponse`` with the same error-body shape at HTTP 400 (see
        module docstring).
    """
    raw = await request.body()
    try:
        body = _parse_body(raw)
    except UzumError as exc:
        return _fail(exc)

    try:
        _authenticate(request)
        service_id = _service_guard(body)
        params = _req_dict(body, "params")
        order_id = _req_order_id(params)
    except UzumError as exc:
        return _fail(exc, **_echo(body))

    try:
        result = await uzum_svc.check(db, service_id=service_id, params={"order_id": order_id})
        # The commit is INSIDE the guard on purpose: a commit-time failure
        # must still be rendered as a 99999 error body (HTTP 400), never
        # escape as a raw 500 — mirrors Payme's own commit-failure handling.
        await db.commit()
    except UzumError as exc:
        await db.rollback()
        return _fail(exc, **_echo(body))
    except Exception:  # noqa: BLE001 -- must render 99999 (HTTP 400), never a raw 500
        await _rollback_after_internal_error(db, endpoint="check")
        return _fail(internal_error(), **_echo(body))

    # ``timestamp`` is our RESPONSE time (epoch ms), not the request's echoed
    # value — Uzum wants the moment we answered, not the moment it asked.
    return {"serviceId": body.get("serviceId"), "timestamp": uzum_svc.now_ms(), **result}


@router.post("/create", summary="Uzum Merchant API: /create", response_model=None)
async def uzum_create(request: Request, db: DbSession) -> dict[str, Any] | JSONResponse:
    """Handle Uzum's ``/create``: register a pending transaction.

    Args:
        request: The inbound webhook request.
        db: Active session; this route owns the commit/rollback.

    Returns:
        The response body dict at HTTP 200 on success; on failure, a
        ``JSONResponse`` with the same error-body shape at HTTP 400 (see
        module docstring).
    """
    raw = await request.body()
    try:
        body = _parse_body(raw)
    except UzumError as exc:
        return _fail(exc)

    try:
        _authenticate(request)
        service_id = _service_guard(body)
        trans_id = _req_str(body, "transId")
        params = _req_dict(body, "params")
        order_id = _req_order_id(params)
        amount = _req_int(body, "amount")
    except UzumError as exc:
        return _fail(exc, **_echo(body))

    try:
        result = await uzum_svc.create(
            db,
            service_id=service_id,
            trans_id=trans_id,
            params={"order_id": order_id},
            amount=amount,
        )
        await db.commit()
    except UzumError as exc:
        await db.rollback()
        return _fail(exc, **_echo(body))
    except Exception:  # noqa: BLE001 -- must render 99999 (HTTP 400), never a raw 500
        await _rollback_after_internal_error(db, endpoint="create")
        return _fail(internal_error(), **_echo(body))

    return {"serviceId": body.get("serviceId"), **result}


@router.post("/confirm", summary="Uzum Merchant API: /confirm", response_model=None)
async def uzum_confirm(request: Request, db: DbSession) -> dict[str, Any] | JSONResponse:
    """Handle Uzum's ``/confirm``: Uzum debited the customer; deliver the goods.

    Args:
        request: The inbound webhook request.
        db: Active session; this route owns the commit/rollback.

    Returns:
        The response body dict at HTTP 200 on success; on failure, a
        ``JSONResponse`` with the same error-body shape at HTTP 400 (see
        module docstring).
    """
    raw = await request.body()
    try:
        body = _parse_body(raw)
    except UzumError as exc:
        return _fail(exc)

    try:
        _authenticate(request)
        _service_guard(body)
        trans_id = _req_str(body, "transId")
    except UzumError as exc:
        return _fail(exc, **_echo(body))

    payment_source = {k: v for k, v in body.items() if k not in _ENVELOPE_FIELDS}

    try:
        result = await uzum_svc.confirm(db, trans_id=trans_id, payment_source=payment_source)
        await db.commit()
    except UzumError as exc:
        await db.rollback()
        return _fail(exc, **_echo(body))
    except Exception:  # noqa: BLE001 -- must render 99999 (HTTP 400), never a raw 500
        await _rollback_after_internal_error(db, endpoint="confirm")
        return _fail(internal_error(), **_echo(body))

    return {"serviceId": body.get("serviceId"), **result}


@router.post("/reverse", summary="Uzum Merchant API: /reverse", response_model=None)
async def uzum_reverse(request: Request, db: DbSession) -> dict[str, Any] | JSONResponse:
    """Handle Uzum's ``/reverse``: cancel a pending transaction or refund a confirmed one.

    Args:
        request: The inbound webhook request.
        db: Active session; this route owns the commit/rollback.

    Returns:
        The response body dict at HTTP 200 on success; on failure, a
        ``JSONResponse`` with the same error-body shape at HTTP 400 (see
        module docstring).
    """
    raw = await request.body()
    try:
        body = _parse_body(raw)
    except UzumError as exc:
        return _fail(exc)

    try:
        _authenticate(request)
        _service_guard(body)
        trans_id = _req_str(body, "transId")
    except UzumError as exc:
        return _fail(exc, **_echo(body))

    try:
        result = await uzum_svc.reverse(db, trans_id=trans_id)
        await db.commit()
    except UzumError as exc:
        await db.rollback()
        return _fail(exc, **_echo(body))
    except Exception:  # noqa: BLE001 -- must render 99999 (HTTP 400), never a raw 500
        await _rollback_after_internal_error(db, endpoint="reverse")
        return _fail(internal_error(), **_echo(body))

    return {"serviceId": body.get("serviceId"), **result}


@router.post("/status", summary="Uzum Merchant API: /status", response_model=None)
async def uzum_status(request: Request, db: DbSession) -> dict[str, Any] | JSONResponse:
    """Handle Uzum's ``/status``: report a transaction's current state.

    Args:
        request: The inbound webhook request.
        db: Active session; this route owns the commit/rollback.

    Returns:
        The response body dict at HTTP 200 on success; on failure, a
        ``JSONResponse`` with the same error-body shape at HTTP 400 (see
        module docstring).
    """
    raw = await request.body()
    try:
        body = _parse_body(raw)
    except UzumError as exc:
        return _fail(exc)

    try:
        _authenticate(request)
        _service_guard(body)
        trans_id = _req_str(body, "transId")
    except UzumError as exc:
        return _fail(exc, **_echo(body))

    try:
        result = await uzum_svc.status(db, trans_id=trans_id)
        await db.commit()
    except UzumError as exc:
        await db.rollback()
        return _fail(exc, **_echo(body))
    except Exception:  # noqa: BLE001 -- must render 99999 (HTTP 400), never a raw 500
        await _rollback_after_internal_error(db, endpoint="status")
        return _fail(internal_error(), **_echo(body))

    return {"serviceId": body.get("serviceId"), **result}


def _reject_non_post() -> JSONResponse:
    """Answer a stray non-POST request with ``10003`` at HTTP 400, never a 405.

    Non-``POST`` is just another documented failure (``errorCode: 10003``),
    so it follows the same 400-on-error rule as every other error in this
    module — FastAPI's default 405 would not carry the documented body.
    """
    return _fail(invalid_operation())


for _path in ("/check", "/create", "/confirm", "/reverse", "/status"):
    router.add_api_route(
        _path,
        _reject_non_post,
        methods=["GET", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        include_in_schema=False,
    )
