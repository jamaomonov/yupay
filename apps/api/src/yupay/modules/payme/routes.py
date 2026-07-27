"""Payme (Paycom) Merchant API JSON-RPC endpoint.

Payme's Merchant API is a single POST endpoint speaking JSON-RPC 2.0 over HTTP
Basic auth. This route is the transport shell around :mod:`yupay.modules.payme`'s
service handlers: it authenticates the request, parses the raw body itself
(FastAPI's request-model validation must never fire — a 422 would read to Payme
as a transport failure), dispatches ``method`` to the right handler while
translating Payme's ``params`` field names, and renders every outcome — success
*or* error — as an HTTP 200 with a JSON-RPC body.

**HTTP 200 always.** Payme interprets any non-200 (including a 405 or 422) as
``-32400``. So we never raise an HTTP exception on the merchant path: auth
failures, bad JSON, unknown methods and internal errors all come back 200 with
an ``{"error": ...}`` body. A stray ``GET`` is answered ``-32300`` in the body
rather than FastAPI's default 405.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.modules.payme import service as payme_svc
from yupay.modules.payme.errors import (
    PaymeError,
    bad_json,
    bad_rpc_fields,
    internal_error,
    method_not_found,
    method_not_post,
    unauthorized,
)

router = APIRouter(prefix="/payments/payme", tags=["payme"])
log = get_logger("yupay.payme.merchant")

DbSession = Annotated[AsyncSession, Depends(db_session)]


def _is_authorized(request: Request) -> bool:
    """Validate the request's HTTP Basic credentials against Payme's config.

    Payme presents ``Authorization: Basic base64("<login>:<key>")``. The login
    must equal the configured ``payme_login`` and the key must match either the
    production cabinet key or the sandbox test key. Empty configured keys are
    ignored so a blank config never accepts a blank presented key.

    Args:
        request: The inbound merchant request.

    Returns:
        ``True`` when the credentials are valid, ``False`` otherwise.
    """
    settings = get_settings()
    header = request.headers.get("Authorization", "")
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return False
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return False
    login, sep, key = decoded.partition(":")
    if not sep or login != settings.payme_login:
        return False
    valid_keys = [k for k in (settings.payme_key, settings.payme_test_key) if k]
    # Accumulate across every configured key rather than short-circuiting on
    # the first match, so response timing doesn't leak which key (if any)
    # matched. An empty ``valid_keys`` (unconfigured acquirer) always fails.
    key_ok = False
    try:
        for valid_key in valid_keys:
            key_ok |= hmac.compare_digest(key, valid_key)
    except TypeError:
        # ``key`` is untrusted wire input and may contain non-ASCII bytes,
        # which ``hmac.compare_digest`` rejects on ``str`` operands — fail
        # closed instead of propagating, mirroring click/signature.py.
        return False
    return key_ok


def _req_str(params: dict[str, Any], key: str) -> str:
    """Return a required string param, raising ``-32600`` if missing/mistyped."""
    value = params.get(key)
    if not isinstance(value, str):
        raise bad_rpc_fields()
    return value


def _req_int(params: dict[str, Any], key: str) -> int:
    """Return a required integer param, raising ``-32600`` if missing/mistyped.

    ``bool`` is excluded even though it subclasses ``int`` — an amount or reason
    of ``true`` is malformed, not the integer ``1``.
    """
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_rpc_fields()
    return value


def _req_dict(params: dict[str, Any], key: str) -> dict[str, Any]:
    """Return a required object param, raising ``-32600`` if missing/mistyped."""
    value = params.get(key)
    if not isinstance(value, dict):
        raise bad_rpc_fields()
    return value


_Handler = Callable[[AsyncSession, dict[str, Any]], Awaitable[dict[str, Any]]]

# Method name -> handler that translates Payme's ``params`` field names to the
# service signature. The ``_req_*`` extractors raise ``-32600`` on a
# missing/mistyped required field; each lambda evaluates them at call time.
_HANDLERS: dict[str, _Handler] = {
    "CheckPerformTransaction": lambda db, p: payme_svc.check_perform_transaction(
        db, amount=_req_int(p, "amount"), account=_req_dict(p, "account")
    ),
    "CreateTransaction": lambda db, p: payme_svc.create_transaction(
        db,
        payme_id=_req_str(p, "id"),
        time=_req_int(p, "time"),
        amount=_req_int(p, "amount"),
        account=_req_dict(p, "account"),
    ),
    "PerformTransaction": lambda db, p: payme_svc.perform_transaction(
        db, payme_id=_req_str(p, "id")
    ),
    "CancelTransaction": lambda db, p: payme_svc.cancel_transaction(
        db, payme_id=_req_str(p, "id"), reason=_req_int(p, "reason")
    ),
    "CheckTransaction": lambda db, p: payme_svc.check_transaction(db, payme_id=_req_str(p, "id")),
    "GetStatement": lambda db, p: payme_svc.get_statement(
        db, from_ms=_req_int(p, "from"), to_ms=_req_int(p, "to")
    ),
    "SetFiscalData": lambda db, p: payme_svc.set_fiscal_data(
        db,
        payme_id=_req_str(p, "id"),
        type_=_req_str(p, "type"),
        fiscal_data=_req_dict(p, "fiscal_data"),
    ),
}


async def _dispatch(db: AsyncSession, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Route a JSON-RPC ``method`` to its service handler, translating params.

    Args:
        db: Active session (the caller owns the commit/rollback).
        method: The JSON-RPC method name.
        params: The request's ``params`` object.

    Returns:
        The handler's result dict, to be wrapped in ``{"result": ...}``.

    Raises:
        PaymeError: ``-32600`` for a missing/mistyped param, ``-32601`` for an
            unknown method, or any business error the handler raises.
    """
    handler = _HANDLERS.get(method)
    if handler is None:
        raise method_not_found()
    return await handler(db, params)


@router.post("/merchant", summary="Payme Merchant API (JSON-RPC 2.0)")
async def payme_merchant(request: Request, db: DbSession) -> dict[str, Any]:
    """Handle one Payme Merchant API JSON-RPC call.

    Always returns HTTP 200 with a JSON-RPC ``result`` or ``error`` body; the
    top-level request ``id`` is echoed verbatim (or ``null`` when absent /
    unparseable).

    Args:
        request: The inbound merchant request (raw body read here, not via a
            request model, so a malformed body is ``-32700`` — never a 422).
        db: Active session; this route owns the commit/rollback.

    Returns:
        The JSON-RPC response body dict.
    """
    if not _is_authorized(request):
        return {"error": unauthorized().to_rpc_error(), "id": None}

    raw = await request.body()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {"error": bad_json().to_rpc_error(), "id": None}

    # A non-object payload has no id/method — it collapses into the same
    # ``-32600`` invalid-envelope branch below (with a null id).
    envelope: dict[str, Any] = payload if isinstance(payload, dict) else {}
    req_id = envelope.get("id")
    method = envelope.get("method")
    params = envelope.get("params")
    if params is None:
        params = {}
    if not isinstance(method, str) or not isinstance(params, dict):
        return {"error": bad_rpc_fields().to_rpc_error(), "id": req_id}

    try:
        result = await _dispatch(db, method, params)
        # The commit is INSIDE the guard on purpose: a commit-time failure (e.g.
        # the connection drops between the handler's flush and here) must still
        # be rendered as ``-32400`` at HTTP 200, never escape as a 500 — Payme
        # reads any non-200 as a transport error.
        await db.commit()
    except PaymeError as exc:
        # A failed validation must not half-commit — roll back before echoing.
        await db.rollback()
        return {"error": exc.to_rpc_error(), "id": req_id}
    except Exception:
        # Best-effort rollback; the session may already be unusable.
        try:
            await db.rollback()
        except Exception:
            log.exception("payme.merchant.rollback_failed", method=method)
        log.exception("payme.merchant.internal_error", method=method)
        return {"error": internal_error().to_rpc_error(), "id": req_id}

    return {"result": result, "id": req_id}


@router.get("/merchant", include_in_schema=False)
async def payme_merchant_get() -> dict[str, Any]:
    """Answer a stray ``GET`` with ``-32300`` in the body (HTTP 200, not 405)."""
    return {"error": method_not_post().to_rpc_error(), "id": None}
