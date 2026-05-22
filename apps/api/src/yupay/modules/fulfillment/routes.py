"""HTTP routes for the fulfilment skeleton: customer deliveries + admin tasks."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.config import get_settings
from yupay.core.errors import UnauthorizedError, ValidationError
from yupay.modules.admin.api import require_admin
from yupay.modules.auth import jwt as authjwt
from yupay.modules.auth.security import email_hash
from yupay.modules.fulfillment import service as svc
from yupay.modules.fulfillment.schemas import (
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
        from yupay.modules.auth.service import current_user as resolve_user  # noqa: PLC0415

        user = await resolve_user(db, token)
        return Actor(user_id=user.id, email=None)
    if scheme == "Guest":
        claims = authjwt.verify(token, expected_kind="guest")
        email = request.query_params.get("email")
        if not email:
            raise ValidationError("email query param required for guest access")
        expected = email_hash(email.strip().lower(), get_settings().auth_email_pepper)
        if claims.email_hash != expected:
            raise UnauthorizedError("guest token / email mismatch")
        return Actor(user_id=None, email=email.strip().lower())
    raise UnauthorizedError("authorization required")


async def _ensure_order_owner(db: AsyncSession, *, actor: Actor, order_id: str) -> Order:
    order = (
        await db.execute(select(Order).where(Order.id == order_id))
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    if actor.user_id is not None and order.user_id != actor.user_id:
        raise HTTPException(status_code=404, detail="order not found")
    if actor.user_id is None and (order.guest_email or "").lower() != (
        actor.email or ""
    ).lower():
        raise HTTPException(status_code=404, detail="order not found")
    return order


# ---------- customer ----------


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
    return DeliveryListOut(items=[DeliveryOut.model_validate(r) for r in rows])


# ---------- admin ----------


@admin_router.get("/tasks", response_model=FulfillmentTaskListOut)
async def admin_list_tasks(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    order_id: str | None = None,
    supplier: str | None = None,
    status_filter: Annotated[str | None, "status"] = None,
    limit: int = 50,
    offset: int = 0,
) -> FulfillmentTaskListOut:
    rows, total = await svc.list_tasks_admin(
        db,
        order_id=order_id,
        supplier=supplier,
        status_filter=status_filter,
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


@admin_router.post(
    "/tasks/{task_id}/retry",
    response_model=FulfillmentTaskOut,
    status_code=status.HTTP_200_OK,
)
async def admin_retry_task(
    task_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> FulfillmentTaskOut:
    task = await svc.retry_task(db, task_id=task_id)
    return FulfillmentTaskOut.model_validate(task)


@admin_router.post(
    "/tasks/{task_id}/cancel",
    response_model=FulfillmentTaskOut,
    status_code=status.HTTP_200_OK,
)
async def admin_cancel_task(
    task_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> FulfillmentTaskOut:
    task = await svc.cancel_task(db, task_id=task_id)
    return FulfillmentTaskOut.model_validate(task)


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
) -> FulfillmentTaskOut:
    task = await svc.complete_manual_task(
        db,
        task_id=task_id,
        artifact_kind=body.artifact_kind,
        artifact=body.artifact,
        channel=body.channel,
        admin_note=body.admin_note,
        admin_id=admin.id,
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
) -> FulfillmentTaskOut:
    task = await svc.fail_manual_task(
        db,
        task_id=task_id,
        reason=body.reason,
        admin_note=body.admin_note,
        admin_id=admin.id,
    )
    return FulfillmentTaskOut.model_validate(task)
