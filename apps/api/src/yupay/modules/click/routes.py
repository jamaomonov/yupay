"""Click Shop API webhooks: ``POST /prepare`` and ``POST /complete``.

Click's Shop API is two ``application/x-www-form-urlencoded`` ``POST``
endpoints, MD5-signed (a ``sign_string`` over the raw wire field values,
see :mod:`yupay.modules.click.signature`) rather than HTTP Basic auth. This
route module is the transport shell around
:mod:`yupay.modules.click.service`'s handlers: it reads the raw form fields
itself (FastAPI's request-model validation must never fire — a 422 would
read to Click as a transport failure), verifies the signature, validates
``action``, applies the negative-inbound-``error`` cancel rule, dispatches to
the matching service handler, and renders every outcome — success *or*
error — as an HTTP 200 JSON body.

**HTTP 200 always.** Click reads any non-200 as a transport failure, so we
never raise an HTTP exception here: signature failures, bad fields, and
internal errors all come back 200 with an ``{"error": <int>, "error_note":
<str>, ...echo}`` body. This is the same rule :mod:`yupay.modules.uzum.routes`
and :mod:`yupay.modules.payme.routes` follow for their own webhooks — see
those modules for the template this one mirrors, adapted for Click's
form-encoded + MD5-signed transport.

See ``docs/superpowers/specs/2026-07-23-click-shop-api-design.md`` §6
(transport + signature) and §7 (the two webhooks' exact contract).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import FormData

from yupay.api.v1.deps import db_session
from yupay.core.logging import get_logger
from yupay.modules.click import service as click_svc
from yupay.modules.click import signature
from yupay.modules.click.errors import (
    ClickError,
    action_not_found,
    bad_request,
    failed_to_update,
    sign_check_failed,
    transaction_cancelled,
)

router = APIRouter(prefix="/payments/click", tags=["click"])
log = get_logger("yupay.click.webhook")

DbSession = Annotated[AsyncSession, Depends(db_session)]


def _req_str(form: FormData, key: str) -> str:
    """Return a required non-empty form field as a raw string, else ``-8``.

    Args:
        form: The parsed ``application/x-www-form-urlencoded`` body.
        key: The field name to read.

    Returns:
        The field's raw string value, exactly as Click sent it.

    Raises:
        ClickError: ``-8`` (``bad_request``) if the field is missing, empty,
            or (in the multipart case) not a plain string.
    """
    value = form.get(key)
    if not isinstance(value, str) or not value:
        raise bad_request()
    return value


def _req_int(form: FormData, key: str) -> int:
    """Return a required form field parsed as an ``int``, else ``-8``.

    Args:
        form: The parsed request body.
        key: The field name to read.

    Returns:
        The field's value parsed as an ``int``.

    Raises:
        ClickError: ``-8`` (``bad_request``) if the field is missing, empty,
            or not a valid integer literal.
    """
    raw = _req_str(form, key)
    try:
        return int(raw)
    except ValueError:
        raise bad_request() from None


def _echo(form: FormData) -> dict[str, Any]:
    """Build the ``click_trans_id``/``merchant_trans_id`` echo kwargs.

    Args:
        form: The parsed request body.

    Returns:
        A dict with ``click_trans_id`` and/or ``merchant_trans_id`` (as the
        RAW strings Click sent), whichever the request actually carried.
        Never raises — used to enrich error responses even when the field
        that was being validated is itself missing.
    """
    echo: dict[str, Any] = {}
    click_trans_id = form.get("click_trans_id")
    if isinstance(click_trans_id, str) and click_trans_id:
        echo["click_trans_id"] = click_trans_id
    merchant_trans_id = form.get("merchant_trans_id")
    if isinstance(merchant_trans_id, str) and merchant_trans_id:
        echo["merchant_trans_id"] = merchant_trans_id
    return echo


async def _rollback_after_internal_error(db: AsyncSession, *, endpoint: str) -> None:
    """Best-effort rollback after an unexpected exception, logging either way."""
    try:
        await db.rollback()
    except Exception:
        log.exception("click.webhook.rollback_failed", endpoint=endpoint)
    log.exception("click.webhook.internal_error", endpoint=endpoint)


@router.post("/prepare", summary="Click Shop API: /prepare")
async def click_prepare(request: Request, db: DbSession) -> dict[str, Any]:
    """Handle Click's ``/prepare``: validate the order, allocate a transaction.

    Args:
        request: The inbound webhook request (form fields read here, not via
            a request model, so a missing/malformed field is ``-8`` — never
            a 422).
        db: Active session; this route owns the commit/rollback.

    Returns:
        The response body dict — always HTTP 200 (see module docstring).
    """
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001 -- any unparseable body is -8, never a 500
        return bad_request().to_response()

    try:
        click_trans_id_raw = _req_str(form, "click_trans_id")
        service_id_raw = _req_str(form, "service_id")
        _req_str(form, "click_paydoc_id")  # required by contract; validated, re-read below
        merchant_trans_id_raw = _req_str(form, "merchant_trans_id")
        amount_raw = _req_str(form, "amount")
        action_raw = _req_str(form, "action")
        _req_str(form, "error_note")  # required by contract; not used for any decision
        sign_time_raw = _req_str(form, "sign_time")
        sign_string_raw = _req_str(form, "sign_string")

        click_trans_id = _req_int(form, "click_trans_id")
        service_id = _req_int(form, "service_id")
        click_paydoc_id = _req_int(form, "click_paydoc_id")
        action = _req_int(form, "action")
        error_code = _req_int(form, "error")

        secret = signature.secret_for_service(service_id)
        if secret is None:
            raise sign_check_failed()
        expected = signature.prepare_sign(
            click_trans_id=click_trans_id_raw,
            service_id=service_id_raw,
            secret=secret,
            merchant_trans_id=merchant_trans_id_raw,
            amount=amount_raw,
            action=action_raw,
            sign_time=sign_time_raw,
        )
        if not signature.verify(expected, sign_string_raw):
            raise sign_check_failed()
        if action != 0:
            raise action_not_found()
    except ClickError as exc:
        return exc.to_response(**_echo(form))

    try:
        if error_code < 0:
            await click_svc.cancel(db, click_trans_id=click_trans_id, service_id=service_id)
            # The commit is INSIDE the guard on purpose: a commit-time failure
            # must still be rendered as -7 at HTTP 200, never escape as a 500
            # — Click reads any non-200 as a transport error (mirrors Uzum).
            await db.commit()
            return transaction_cancelled().to_response(**_echo(form))

        result = await click_svc.prepare(
            db,
            click_trans_id=click_trans_id,
            service_id=service_id,
            click_paydoc_id=click_paydoc_id,
            merchant_trans_id=merchant_trans_id_raw,
            amount=amount_raw,
            sign_time=sign_time_raw,
        )
        await db.commit()
    except ClickError as exc:
        await db.rollback()
        return exc.to_response(**_echo(form))
    except Exception:  # noqa: BLE001 -- must render -7 at HTTP 200, never a 500
        await _rollback_after_internal_error(db, endpoint="prepare")
        return failed_to_update().to_response(**_echo(form))

    return result


@router.post("/complete", summary="Click Shop API: /complete")
async def click_complete(request: Request, db: DbSession) -> dict[str, Any]:
    """Handle Click's ``/complete``: Click debited the customer; settle the payment.

    Args:
        request: The inbound webhook request.
        db: Active session; this route owns the commit/rollback.

    Returns:
        The response body dict — always HTTP 200.
    """
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001 -- any unparseable body is -8, never a 500
        return bad_request().to_response()

    try:
        click_trans_id_raw = _req_str(form, "click_trans_id")
        service_id_raw = _req_str(form, "service_id")
        _req_str(form, "click_paydoc_id")  # required by contract; not used by complete()
        merchant_trans_id_raw = _req_str(form, "merchant_trans_id")
        merchant_prepare_id_raw = _req_str(form, "merchant_prepare_id")
        amount_raw = _req_str(form, "amount")
        action_raw = _req_str(form, "action")
        _req_str(form, "error_note")  # required by contract; not used for any decision
        sign_time_raw = _req_str(form, "sign_time")
        sign_string_raw = _req_str(form, "sign_string")

        click_trans_id = _req_int(form, "click_trans_id")
        service_id = _req_int(form, "service_id")
        merchant_prepare_id = _req_int(form, "merchant_prepare_id")
        action = _req_int(form, "action")
        error_code = _req_int(form, "error")

        secret = signature.secret_for_service(service_id)
        if secret is None:
            raise sign_check_failed()
        expected = signature.complete_sign(
            click_trans_id=click_trans_id_raw,
            service_id=service_id_raw,
            secret=secret,
            merchant_trans_id=merchant_trans_id_raw,
            merchant_prepare_id=merchant_prepare_id_raw,
            amount=amount_raw,
            action=action_raw,
            sign_time=sign_time_raw,
        )
        if not signature.verify(expected, sign_string_raw):
            raise sign_check_failed()
        if action != 1:
            raise action_not_found()
    except ClickError as exc:
        return exc.to_response(**_echo(form))

    try:
        if error_code < 0:
            await click_svc.cancel(db, merchant_prepare_id=merchant_prepare_id)
            # See click_prepare(): commit is INSIDE the guard on purpose.
            await db.commit()
            return transaction_cancelled().to_response(**_echo(form))

        result = await click_svc.complete(
            db,
            click_trans_id=click_trans_id,
            service_id=service_id,
            merchant_trans_id=merchant_trans_id_raw,
            merchant_prepare_id=merchant_prepare_id,
            amount=amount_raw,
            sign_time=sign_time_raw,
        )
        await db.commit()
    except ClickError as exc:
        await db.rollback()
        return exc.to_response(**_echo(form))
    except Exception:  # noqa: BLE001 -- must render -7 at HTTP 200, never a 500
        await _rollback_after_internal_error(db, endpoint="complete")
        return failed_to_update().to_response(**_echo(form))

    return result


def _reject_non_post() -> dict[str, Any]:
    """Answer a stray non-POST request with ``-8`` (HTTP 200, never a 405).

    Click's error catalogue has no dedicated "wrong HTTP method" code: ``-3``
    (action not found) is reserved for the request body's ``action`` field
    being neither ``0`` nor ``1``, not for the transport verb itself. ``-8``
    ("Error in request from click") is the closer semantic fit for "this
    wasn't a valid Click webhook call at all" — mirrors Uzum's
    ``_reject_non_post`` pattern (HTTP 200, ``include_in_schema=False``,
    never a 405).
    """
    return bad_request().to_response()


for _path in ("/prepare", "/complete"):
    router.add_api_route(
        _path,
        _reject_non_post,
        methods=["GET", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        include_in_schema=False,
    )
