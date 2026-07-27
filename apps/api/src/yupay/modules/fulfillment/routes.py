"""HTTP routes for the fulfilment skeleton: customer deliveries + admin tasks."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.config import get_settings
from yupay.core.errors import UnauthorizedError, ValidationError
from yupay.core.idempotency import (
    IDEMPOTENCY_HEADER,
    load_replay,
    normalize_idempotency_key,
    save_replay,
)
from yupay.modules.admin.api import require_admin
from yupay.modules.auth import jwt as authjwt
from yupay.modules.auth.security import email_hash
from yupay.modules.fulfillment import service as svc
from yupay.modules.fulfillment.schemas import (
    AttemptAdminListOut,
    AttemptAdminOut,
    BulkRetryIn,
    BulkRetryOut,
    BulkRetrySkipped,
    DeliveryListOut,
    DeliveryOut,
    FulfillmentTaskListOut,
    FulfillmentTaskOut,
    ManualCompleteIn,
    ManualFailIn,
)
from yupay.modules.orders.models import Order
from yupay.modules.orders.service import Actor
from yupay.modules.users.models import User

router = APIRouter(prefix="/orders", tags=["fulfillment"])
admin_router = APIRouter(
    prefix="/admin/fulfillment",
    tags=["admin:fulfillment"],
    dependencies=[Depends(require_admin)],
)


async def _resolve_actor(request: Request, db: AsyncSession) -> Actor:
    auth = request.headers.get("Authorization") or ""
    scheme, _, token = auth.partition(" ")
    if scheme == "Bearer":
        from yupay.modules.auth.service import current_user as resolve_user

        user = await resolve_user(db, token)
        return Actor(user_id=user.id, email=None)
    if scheme == "Guest":
        claims = authjwt.verify(token, expected_kind="guest")
        # Header, not query param: a query param lands in Caddy / proxy
        # access logs and browser history, a header doesn't.
        email = request.headers.get("X-Guest-Email")
        if not email:
            raise ValidationError("X-Guest-Email header required for guest access")
        normalised = email.strip().lower()
        expected = email_hash(normalised, get_settings().auth_email_pepper)
        if claims.email_hash != expected:
            raise UnauthorizedError("guest token / email mismatch")
        return Actor(user_id=None, email=normalised)
    raise UnauthorizedError("authorization required")


async def _ensure_order_owner(db: AsyncSession, *, actor: Actor, order_id: str) -> Order:
    order = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    if actor.user_id is not None and order.user_id != actor.user_id:
        raise HTTPException(status_code=404, detail="order not found")
    if actor.user_id is None and (order.guest_email or "").lower() != (actor.email or "").lower():
        raise HTTPException(status_code=404, detail="order not found")
    return order


# ---------- customer ----------


# Artifact keys that are stored on ``deliveries`` for audit / chargeback
# evidence but must not leak to the customer over the public API. The DB
# row keeps them; admins still see them through ``/admin/fulfillment/tasks``
# (task.external_order_id + task.extra_metadata).
_CUSTOMER_HIDDEN_ARTIFACT_KEYS: frozenset[str] = frozenset({"external_id"})


def _to_customer_delivery_out(row: object) -> DeliveryOut:
    """Project a ``Delivery`` ORM row into the customer-facing DTO with
    internal-only keys stripped from ``artifact``."""
    artifact = {
        k: v
        for k, v in (row.artifact or {}).items()  # type: ignore[attr-defined]
        if k not in _CUSTOMER_HIDDEN_ARTIFACT_KEYS
    }
    return DeliveryOut(
        id=row.id,  # type: ignore[attr-defined]
        order_item_id=row.order_item_id,  # type: ignore[attr-defined]
        channel=row.channel,  # type: ignore[attr-defined]
        artifact_kind=row.artifact_kind,  # type: ignore[attr-defined]
        artifact=artifact,
        delivered_at=row.delivered_at,  # type: ignore[attr-defined]
    )


@router.get(
    "/{order_id}/deliveries",
    response_model=DeliveryListOut,
    summary="Owner-only list of delivery artifacts for an order",
)
async def list_order_deliveries(
    order_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> DeliveryListOut:
    actor = await _resolve_actor(request, db)
    await _ensure_order_owner(db, actor=actor, order_id=order_id)
    rows = await svc.list_deliveries_for_order(db, order_id=order_id)
    return DeliveryListOut(items=[_to_customer_delivery_out(r) for r in rows])


# ---------- admin ----------


@admin_router.get("/tasks", response_model=FulfillmentTaskListOut)
async def admin_list_tasks(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    order_id: str | None = None,
    supplier: str | None = None,
    status_filter: Annotated[str | None, "status"] = None,
    order: Literal["newest", "oldest"] = "newest",
    limit: int = 50,
    offset: int = 0,
) -> FulfillmentTaskListOut:
    rows, total = await svc.list_tasks_admin(
        db,
        order_id=order_id,
        supplier=supplier,
        status_filter=status_filter,
        order=order,
        limit=max(1, min(limit, 500)),
        offset=max(0, offset),
    )
    return FulfillmentTaskListOut(
        items=[FulfillmentTaskOut.model_validate(r) for r in rows],
        total=total,
    )


@admin_router.get("/tasks/{task_id}", response_model=FulfillmentTaskOut)
async def admin_get_task(
    task_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> FulfillmentTaskOut:
    task = await svc.get_task_admin(db, task_id)
    return FulfillmentTaskOut.model_validate(task)


@admin_router.get("/attempts", response_model=AttemptAdminListOut)
async def admin_list_attempts(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    supplier: str | None = None,
    status_filter: Annotated[str | None, "status"] = None,
    limit: int = 50,
    offset: int = 0,
) -> AttemptAdminListOut:
    """Supplier-interaction audit feed.

    Joins ``fulfillment_attempts`` with its parent task so callers see the
    supplier slug without a second lookup. Filter by ``supplier`` to e.g.
    show "everything G2B did in the last hour".
    """
    rows, total = await svc.list_attempts_admin(
        db,
        supplier=supplier,
        status_filter=status_filter,
        limit=max(1, min(limit, 500)),
        offset=max(0, offset),
    )
    return AttemptAdminListOut(
        items=[
            AttemptAdminOut(
                task_id=attempt.task_id,
                supplier=supplier_slug,
                kind=attempt.kind,
                status=attempt.status,
                payload=attempt.payload,
                error=attempt.error,
                created_at=attempt.created_at,
            )
            for attempt, supplier_slug in rows
        ],
        total=total,
    )


@admin_router.post(
    "/tasks/{task_id}/retry",
    response_model=FulfillmentTaskOut,
    status_code=status.HTTP_200_OK,
)
async def admin_retry_task(
    task_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> FulfillmentTaskOut:
    key = normalize_idempotency_key(idempotency_key)
    scope = "fulfillment.retry_task"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None:
            return FulfillmentTaskOut.model_validate(cached.body)
    task = await svc.retry_task(db, task_id=task_id)
    out = FulfillmentTaskOut.model_validate(task)
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


@admin_router.post(
    "/tasks/{task_id}/cancel",
    response_model=FulfillmentTaskOut,
    status_code=status.HTTP_200_OK,
)
async def admin_cancel_task(
    task_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> FulfillmentTaskOut:
    key = normalize_idempotency_key(idempotency_key)
    scope = "fulfillment.cancel_task"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None:
            return FulfillmentTaskOut.model_validate(cached.body)
    task = await svc.cancel_task(db, task_id=task_id)
    out = FulfillmentTaskOut.model_validate(task)
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


@admin_router.post(
    "/tasks/bulk-retry",
    response_model=BulkRetryOut,
    status_code=status.HTTP_200_OK,
    summary="Retry multiple failed / pending tasks; non-retryable ones are reported",
)
async def admin_bulk_retry_tasks(
    body: BulkRetryIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> BulkRetryOut:
    key = normalize_idempotency_key(idempotency_key)
    scope = "fulfillment.bulk_retry_tasks"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None:
            return BulkRetryOut.model_validate(cached.body)
    retried, skipped = await svc.bulk_retry_tasks(db, task_ids=body.task_ids)
    out = BulkRetryOut(
        retried=[FulfillmentTaskOut.model_validate(t) for t in retried],
        skipped=[BulkRetrySkipped(id=tid, reason=reason) for tid, reason in skipped],
    )
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


@admin_router.post(
    "/tasks/{task_id}/complete",
    response_model=FulfillmentTaskOut,
    status_code=status.HTTP_200_OK,
    summary="Manually complete a task (creates Delivery, walks order to delivered)",
)
async def admin_complete_manual_task(
    task_id: str,
    body: ManualCompleteIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> FulfillmentTaskOut:
    key = normalize_idempotency_key(idempotency_key)
    scope = "fulfillment.complete_manual_task"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None:
            return FulfillmentTaskOut.model_validate(cached.body)
    task = await svc.complete_manual_task(
        db,
        task_id=task_id,
        artifact_kind=body.artifact_kind,
        artifact=body.artifact,
        channel=body.channel,
        admin_note=body.admin_note,
        admin_id=admin.id,
        proof_url=body.proof_url,
    )
    out = FulfillmentTaskOut.model_validate(task)
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


@admin_router.post(
    "/tasks/{task_id}/force-complete",
    response_model=FulfillmentTaskOut,
    status_code=status.HTTP_200_OK,
    summary=(
        "Force-complete a non-manual task that the supplier rejected — "
        "typically used after a low-balance event when the admin "
        "topped up off-platform and delivered the code by hand."
    ),
)
async def admin_force_complete_task(
    task_id: str,
    body: ManualCompleteIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
) -> FulfillmentTaskOut:
    task = await svc.complete_manual_task(
        db,
        task_id=task_id,
        artifact_kind=body.artifact_kind,
        artifact=body.artifact,
        channel=body.channel,
        admin_note=body.admin_note,
        admin_id=admin.id,
        proof_url=body.proof_url,
        force=True,
    )
    return FulfillmentTaskOut.model_validate(task)


@admin_router.post(
    "/tasks/{task_id}/fail",
    response_model=FulfillmentTaskOut,
    status_code=status.HTTP_200_OK,
    summary="Reject a manual task with a reason (order stays in fulfilling)",
)
async def admin_fail_manual_task(
    task_id: str,
    body: ManualFailIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> FulfillmentTaskOut:
    key = normalize_idempotency_key(idempotency_key)
    scope = "fulfillment.fail_manual_task"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None:
            return FulfillmentTaskOut.model_validate(cached.body)
    task = await svc.fail_manual_task(
        db,
        task_id=task_id,
        reason=body.reason,
        admin_note=body.admin_note,
        admin_id=admin.id,
    )
    out = FulfillmentTaskOut.model_validate(task)
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out
