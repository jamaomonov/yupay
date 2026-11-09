"""The cabinet's API access screen: keys and the IP allowlist (ADR-0103).

A third router over the same prefix as :mod:`cabinet_routes`, carved off for the
same reason :mod:`cabinet_webhook_routes` was: that file sits at AGENTS.md §6's
soft limit, and "who may call the machine API" is a seam that costs nothing.

A new key is one ``ypk_…`` string, shown once. The allowlist belongs to the
merchant, not to a key: one list, edited here, guards every key it holds.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from yupay.core.idempotency import normalize_idempotency_key
from yupay.core.logging import get_logger
from yupay.modules.merchants import cabinet_notify, credentials
from yupay.modules.merchants.cabinet_deps import CurrentUser, Db, merchant_of
from yupay.modules.merchants.cabinet_schemas import (
    CabinetApiKeyCreateIn,
    CabinetApiKeyOut,
    CabinetIpAllowlistIn,
    CabinetIpAllowlistOut,
    CabinetIssuedKeyOut,
)
from yupay.modules.merchants.route_replay import IdempotencyKeyHeader, remember, replayed

log = get_logger("yupay.merchants.cabinet_key_routes")

router = APIRouter(prefix="/merchant/cabinet", tags=["merchant-cabinet"])


@router.get("/api-keys", response_model=list[CabinetApiKeyOut], summary="Machine credentials")
async def list_keys(user: CurrentUser, db: Db) -> list[CabinetApiKeyOut]:
    merchant = await merchant_of(db, user)
    rows = await credentials.list_api_keys(db, merchant_id=merchant.id)
    return [CabinetApiKeyOut.model_validate(row) for row in rows]


@router.post(
    "/api-keys",
    response_model=CabinetIssuedKeyOut,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a machine credential",
)
async def create_key(body: CabinetApiKeyCreateIn, user: CurrentUser, db: Db) -> CabinetIssuedKeyOut:
    """The API key is in this response and nowhere else, ever again.

    Self-serve rather than a support request, which is what makes rotation —
    issue, deploy, revoke — something a reseller can do at 3am during an
    incident instead of waiting for our morning.
    """
    merchant = await merchant_of(db, user)
    issued = await credentials.create_api_key(db, merchant_id=merchant.id, label=body.label)
    log.info("merchant.cabinet.key_created", merchant_id=merchant.id, key_id=issued.key.key_id)
    await cabinet_notify.notify_security(
        db, merchant_id=merchant.id, event="api_key_created", detail=issued.key.key_id
    )
    return CabinetIssuedKeyOut(
        api_key=issued.api_key,
        key_id=issued.key.key_id,
        label=issued.key.label,
        created_at=issued.key.created_at,
    )


@router.delete(
    "/api-keys/{key_id}",
    response_model=CabinetApiKeyOut,
    summary="Revoke a machine credential",
)
async def revoke_key(key_id: str, user: CurrentUser, db: Db) -> CabinetApiKeyOut:
    merchant = await merchant_of(db, user)
    row = await credentials.revoke_api_key(db, merchant_id=merchant.id, key_id=key_id)
    log.info("merchant.cabinet.key_revoked", merchant_id=merchant.id, key_id=key_id)
    await cabinet_notify.notify_security(
        db, merchant_id=merchant.id, event="api_key_revoked", detail=row.key_id
    )
    return CabinetApiKeyOut.model_validate(row)


@router.get(
    "/api-ip-allowlist",
    response_model=CabinetIpAllowlistOut,
    summary="Addresses allowed to call the API",
)
async def read_ip_allowlist(user: CurrentUser, db: Db) -> CabinetIpAllowlistOut:
    """Empty means no filter: any address may call with a valid key."""
    merchant = await merchant_of(db, user)
    return CabinetIpAllowlistOut(entries=list(merchant.api_ip_allowlist or []))


@router.put(
    "/api-ip-allowlist",
    response_model=CabinetIpAllowlistOut,
    summary="Replace the addresses allowed to call the API",
)
async def set_ip_allowlist(
    body: CabinetIpAllowlistIn,
    user: CurrentUser,
    db: Db,
    idempotency_key: IdempotencyKeyHeader = None,
) -> CabinetIpAllowlistOut:
    """Replace the whole list; it applies to every key at once, immediately.

    A ``PUT`` of the full list is idempotent by construction; the header is
    honoured anyway (AGENTS.md §9). Every operator is mailed, because widening
    the list is what an intruder in the cabinet would do first.
    """
    merchant = await merchant_of(db, user)
    key = normalize_idempotency_key(idempotency_key)
    scope = f"merchants.cabinet_ip_allowlist:{merchant.id}"
    cached = await replayed(db, scope=scope, key=key, model=CabinetIpAllowlistOut)
    if cached is not None:
        return cached
    updated = await credentials.set_ip_allowlist(db, merchant_id=merchant.id, entries=body.entries)
    out = CabinetIpAllowlistOut(entries=list(updated.api_ip_allowlist or []))
    log.info("merchant.cabinet.ip_allowlist_set", merchant_id=merchant.id, entries=len(out.entries))
    await cabinet_notify.notify_security(
        db,
        merchant_id=merchant.id,
        event="api_ip_allowlist_changed",
        detail=f"адресов: {len(out.entries)}" if out.entries else "фильтр выключен",
    )
    await remember(db, scope=scope, key=key, body=out.model_dump(mode="json"))
    return out


__all__ = ["router"]
