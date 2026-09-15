"""Paynet UWS endpoint: one POST speaking JSON-RPC 2.0 over HTTP Basic auth.

The transport shell around :mod:`yupay.modules.paynet.service`. It reads the
raw body itself — FastAPI's request-model validation must never fire, because a
422 reads to Paynet as a transport failure rather than as the ``-32600`` their
spec asks for.

**Auth is the one place this is not Payme.** Payme's spec demands HTTP 200 with
an error body for bad credentials; Paynet's demands the opposite, in as many
words: *"При отсутствии или неверных данных авторизации система должна
возвращать HTTP 401 Unauthorized (а не 200 OK с JSON-RPC ошибкой)"*. So an
unauthenticated call gets a bare 401 here, and everything past the auth check
gets a 200 with a JSON-RPC body — success or error alike.

Their SLA is 500 ms per transaction, one second in exception, and they cut the
connection at 30. Nothing on this path may call an upstream.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.modules.paynet import service as paynet_svc
from yupay.modules.paynet.errors import (
    PaynetError,
    bad_json,
    bad_rpc_fields,
    internal_error,
    method_not_found,
    method_not_post,
)

router = APIRouter(prefix="/payments/paynet", tags=["paynet"])
log = get_logger("yupay.paynet.uws")

DbSession = Annotated[AsyncSession, Depends(db_session)]


def _is_authorized(request: Request) -> bool:
    """Validate HTTP Basic credentials against the configured Paynet pair.

    An unconfigured integration (either half empty) always fails, so a blank
    deployment never accepts a blank presented credential.
    """
    settings = get_settings()
    username, password = settings.paynet_username, settings.paynet_password
    if not username or not password:
        return False
    header = request.headers.get("Authorization", "")
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return False
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return False
    presented_user, sep, presented_pass = decoded.partition(":")
    if not sep:
        return False
    try:
        # Both halves are compared, and both comparisons run — short-circuiting
        # on the username would leak through response timing which half was
        # wrong. ``compare_digest`` rejects non-ASCII ``str``, and the wire is
        # untrusted, so a TypeError fails closed.
        user_ok = hmac.compare_digest(presented_user, username)
        pass_ok = hmac.compare_digest(presented_pass, password)
    except TypeError:
        return False
    return user_ok and pass_ok


def _req_int(params: dict[str, Any], key: str) -> int:
    """A required integer param. ``bool`` is not an integer here."""
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_rpc_fields()
    return value


def _req_str(params: dict[str, Any], key: str) -> str:
    """A required string param."""
    value = params.get(key)
    if not isinstance(value, str):
        raise bad_rpc_fields()
    return value


def _req_dict(params: dict[str, Any], key: str) -> dict[str, Any]:
    """A required object param."""
    value = params.get(key)
    if not isinstance(value, dict):
        raise bad_rpc_fields()
    return value


_Handler = Callable[[AsyncSession, dict[str, Any]], Awaitable[dict[str, Any]]]

#: ``method`` → handler, translating Paynet's ``params`` names to the service
#: signature. The ``_req_*`` extractors raise ``-32600`` on a missing or
#: mistyped field, and each lambda evaluates them at call time.
_HANDLERS: dict[str, _Handler] = {
    "GetInformation": lambda db, p: paynet_svc.get_information(
        db, service_id=_req_int(p, "serviceId"), fields=_req_dict(p, "fields")
    ),
    "PerformTransaction": lambda db, p: paynet_svc.perform_transaction(
        db,
        service_id=_req_int(p, "serviceId"),
        transaction_id=_req_int(p, "transactionId"),
        amount=_req_int(p, "amount"),
        fields=_req_dict(p, "fields"),
    ),
    # ``timestamp`` is required by the spec and deliberately not read: on this
    # method alone it arrives as ``Mon Jun 16 06:12:41 UZT 2021``, and it is
    # Paynet's own processing time. Demanding it keeps us honest about the
    # contract without making us parse a format that exists for history's sake.
    "CheckTransaction": lambda db, p: paynet_svc.check_transaction(
        db,
        service_id=_req_int(p, "serviceId"),
        transaction_id=_req_int(p, "transactionId"),
    ),
    "CancelTransaction": lambda db, p: paynet_svc.cancel_transaction(
        db,
        service_id=_req_int(p, "serviceId"),
        transaction_id=_req_int(p, "transactionId"),
    ),
    "GetStatement": lambda db, p: paynet_svc.get_statement(
        db,
        service_id=_req_int(p, "serviceId"),
        date_from=_req_str(p, "dateFrom"),
        date_to=_req_str(p, "dateTo"),
    ),
}


async def _dispatch(db: AsyncSession, method: str, params: dict[str, Any]) -> dict[str, Any]:
    handler = _HANDLERS.get(method)
    if handler is None:
        raise method_not_found()
    return await handler(db, params)


@router.post("/uws", summary="Paynet UWS (JSON-RPC 2.0)")
async def paynet_uws(request: Request, response: Response, db: DbSession) -> dict[str, Any]:
    """Handle one Paynet UWS call.

    Returns HTTP 401 with no body when the credentials are absent or wrong —
    the spec requires that, and only that, as a non-200. Everything else is a
    200 carrying a JSON-RPC ``result`` or ``error``, with the request ``id``
    echoed verbatim.
    """
    if not _is_authorized(request):
        response.status_code = 401
        return {}

    raw = await request.body()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {"jsonrpc": "2.0", "error": bad_json().to_rpc_error(), "id": None}

    envelope: dict[str, Any] = payload if isinstance(payload, dict) else {}
    req_id = envelope.get("id")
    method = envelope.get("method")
    params = envelope.get("params")
    if params is None:
        params = {}
    if not isinstance(method, str) or not isinstance(params, dict):
        return {"jsonrpc": "2.0", "error": bad_rpc_fields().to_rpc_error(), "id": req_id}

    try:
        result = await _dispatch(db, method, params)
        # Inside the guard on purpose: a failure at commit time — the
        # connection dropping between the handler's flush and here — must still
        # render as an error at HTTP 200, never escape as a 500.
        await db.commit()
    except PaynetError as exc:
        await db.rollback()
        return {"jsonrpc": "2.0", "error": exc.to_rpc_error(), "id": req_id}
    except Exception:
        try:
            await db.rollback()
        except Exception:
            log.exception("paynet.uws.rollback_failed", method=method)
        log.exception("paynet.uws.internal_error", method=method)
        return {"jsonrpc": "2.0", "error": internal_error().to_rpc_error(), "id": req_id}

    return {"jsonrpc": "2.0", "result": result, "id": req_id}


@router.get("/uws", include_in_schema=False)
async def paynet_uws_get() -> dict[str, Any]:
    """Answer a stray ``GET`` with ``-32300`` in the body, not FastAPI's 405."""
    return {"jsonrpc": "2.0", "error": method_not_post().to_rpc_error(), "id": None}
