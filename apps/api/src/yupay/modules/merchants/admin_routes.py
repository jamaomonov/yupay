"""Admin HTTP routes for the merchant B2B programme (M1, Task 6).

Two routers, both admin-gated like ``affiliate.routes.admin_router``:

- ``admin_router`` under ``/admin/merchants`` — create/list/freeze/unfreeze
  and the deposit credit;
- ``catalog_b2b_router`` under ``/admin/catalog`` — the B2B knobs that live
  on catalog rows (per-SKU markup/visibility, bulk markup, brand visibility).

Business logic is imported through the ``merchants.api`` facade only —
routers parse and dispatch (AGENTS.md §6). Every write accepts
``Idempotency-Key`` (§9): the deposit credit REQUIRES it (the header is the
client half of the namespaced ledger key, ``merchant-credit:{merchant_id}:
{client_key}`` — wallet-gateway style, so one client's key can never replay
another merchant's transaction), while the rest replay through the generic
``(scope, key)`` store the other admin write endpoints use.

``api/v1`` imports the routers from here, not from the facade — the facade
is imported by service-layer callers, and a router re-exported from it would
close a cycle back through the v1 route stack (the ``affiliate.routes``
precedent, same comment there).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.errors import ValidationError
from yupay.core.idempotency import (
    IDEMPOTENCY_HEADER,
    MIN_IDEMPOTENCY_KEY_LENGTH,
    load_replay,
    normalize_idempotency_key,
    save_replay,
)
from yupay.modules.admin.api import require_admin
from yupay.modules.merchants import api as merchants
from yupay.modules.merchants.schemas import (
    ApiKeyCreatedOut,
    ApiKeyCreateIn,
    ApiKeyListOut,
    ApiKeyOut,
    BrandB2bOut,
    BrandB2bPatchIn,
    BulkMarkupIn,
    BulkMarkupOut,
    DepositCreditIn,
    DepositCreditOut,
    MerchantCreateIn,
    MerchantListOut,
    MerchantOut,
    MerchantTxnListOut,
    MerchantTxnOut,
    SkuB2bOut,
    SkuB2bPatchIn,
)
from yupay.modules.users.models import User

admin_router = APIRouter(
    prefix="/admin/merchants",
    tags=["admin:merchants"],
    dependencies=[Depends(require_admin)],
)

catalog_b2b_router = APIRouter(
    prefix="/admin/catalog",
    tags=["admin:catalog-b2b"],
    dependencies=[Depends(require_admin)],
)

IdempotencyKeyHeader = Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)]

#: Cap on the CLIENT half of the deposit-credit key. The ledger column is
#: ``String(160)`` and the ``merchant-credit:{uuid}:`` prefix consumes 53
#: chars, so anything over 107 overflows into a ``DataError`` — which
#: ``post()``'s ``except IntegrityError`` does not catch — i.e. a
#: deterministic 500 on every retry of the same long key. 100 leaves margin
#: under that ceiling; reject at the parse boundary with a readable 422.
MAX_DEPOSIT_CLIENT_KEY_LENGTH = 100


async def _replayed[ModelT: BaseModel](
    db: AsyncSession, *, scope: str, key: str | None, model: type[ModelT]
) -> ModelT | None:
    """Return the stored response for ``(scope, key)``, or ``None`` to proceed."""
    if key is None:
        return None
    cached = await load_replay(db, scope=scope, idempotency_key=key)
    if cached is None:
        return None
    return model.model_validate(cached.body)


async def _remember(
    db: AsyncSession, *, scope: str, key: str | None, body: dict[str, Any], status_code: int = 200
) -> None:
    """Store a response for replay when a key was supplied."""
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=body, status_code=status_code)


def _merchant_out(merchant: merchants.Merchant, balance: Decimal) -> MerchantOut:
    return MerchantOut(
        id=merchant.id,
        title=merchant.title,
        status=merchant.status,
        created_at=merchant.created_at,
        deposit_balance=balance,
    )


@admin_router.post(
    "",
    response_model=MerchantOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a reseller account",
)
async def create_merchant(
    body: MerchantCreateIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> MerchantOut:
    """Create a merchant; a retried key replays the original row."""
    # Known limitation of piggybacking the generic replay store on a CREATE:
    # ``save_replay`` swallows the losing side of a same-key race ("the
    # caller's own response is equivalent"), which is true for the
    # mutate-existing endpoints it was built for and NOT here — two
    # concurrent same-key creates can both insert, one snapshot silently
    # loses, and two merchant rows exist. Admin-only surface, sequential
    # replays (the actual retry case) are correct, so this is accepted —
    # not a bug to rediscover in production.
    key = normalize_idempotency_key(idempotency_key)
    scope = "merchants.create"
    cached = await _replayed(db, scope=scope, key=key, model=MerchantOut)
    if cached is not None:
        return cached
    merchant = await merchants.create_merchant(db, title=body.title)
    out = _merchant_out(merchant, Decimal("0"))
    await _remember(
        db,
        scope=scope,
        key=key,
        body=out.model_dump(mode="json"),
        status_code=status.HTTP_201_CREATED,
    )
    return out


@admin_router.get(
    "",
    response_model=MerchantListOut,
    summary="Every merchant, with its USD deposit balance",
)
async def list_merchants(
    db: Annotated[AsyncSession, Depends(db_session)],
) -> MerchantListOut:
    """One grouped query, not a balance read per merchant (AGENTS.md §10)."""
    rows = await merchants.list_merchants_with_balances(db)
    return MerchantListOut(items=[_merchant_out(m, balance) for m, balance in rows])


@admin_router.post(
    "/{merchant_id}/freeze",
    response_model=MerchantOut,
    summary="Freeze a merchant (blocks orders in M2, never money in)",
)
async def freeze_merchant(
    merchant_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> MerchantOut:
    """Persist ``status=frozen``. In M1 nothing is blocked yet — see the module README."""
    return await _set_status(db, merchant_id=merchant_id, to="frozen", key=idempotency_key)


@admin_router.post(
    "/{merchant_id}/unfreeze",
    response_model=MerchantOut,
    summary="Reactivate a frozen merchant",
)
async def unfreeze_merchant(
    merchant_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> MerchantOut:
    """Persist ``status=active``."""
    return await _set_status(db, merchant_id=merchant_id, to="active", key=idempotency_key)


async def _set_status(
    db: AsyncSession, *, merchant_id: str, to: str, key: str | None
) -> MerchantOut:
    """Shared freeze/unfreeze body: replay, mutate, remember."""
    normalized = normalize_idempotency_key(key)
    scope = f"merchants.set_status.{to}:{merchant_id}"
    cached = await _replayed(db, scope=scope, key=normalized, model=MerchantOut)
    if cached is not None:
        return cached
    merchant = await merchants.set_status(db, merchant_id=merchant_id, status=to)
    balance = await merchants.deposit_balance(db, merchant_id=merchant_id)
    out = _merchant_out(merchant, balance)
    # The snapshot freezes ``deposit_balance`` as of the FIRST call — a
    # replayed response can show a stale balance if credits landed in
    # between. ``GET /admin/merchants`` is the authoritative balance read.
    await _remember(db, scope=scope, key=normalized, body=out.model_dump(mode="json"))
    return out


@admin_router.post(
    "/{merchant_id}/deposit-credits",
    response_model=DepositCreditOut,
    status_code=status.HTTP_201_CREATED,
    summary="Credit a merchant's USD deposit (idempotent via key)",
)
async def credit_deposit(
    merchant_id: str,
    body: DepositCreditIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> DepositCreditOut:
    """Book ``D merchant_deposit / C house_payments_received`` on the ledger.

    The ``Idempotency-Key`` header is REQUIRED: it is the client half of the
    namespaced ledger key, so an admin retry after a timeout replays the
    original transaction instead of crediting twice. The ledger replays by
    key WITHOUT comparing parameters — a reused key with an amended amount
    returns the old transaction and books nothing — so the response's
    ``amount`` is the replayed transaction's amount, making the mismatch
    visible to the admin UI.
    """
    if not idempotency_key or len(idempotency_key) < MIN_IDEMPOTENCY_KEY_LENGTH:
        raise ValidationError(
            f"Idempotency-Key header is required (>={MIN_IDEMPOTENCY_KEY_LENGTH} chars)",
            extra={"header": IDEMPOTENCY_HEADER},
        )
    if len(idempotency_key) > MAX_DEPOSIT_CLIENT_KEY_LENGTH:
        raise ValidationError(
            f"Idempotency-Key header must be <={MAX_DEPOSIT_CLIENT_KEY_LENGTH} chars "
            "on this endpoint — it is namespaced into a bounded ledger column",
            extra={"header": IDEMPOTENCY_HEADER},
        )
    txn = await merchants.credit_deposit(
        db,
        merchant_id=merchant_id,
        amount=body.amount,
        actor=f"admin:{admin.id}",
        idempotency_key=f"merchant-credit:{merchant_id}:{idempotency_key}",
        note=body.note,
    )
    balance = await merchants.deposit_balance(db, merchant_id=merchant_id)
    # Both legs carry the same amount; either one is the transaction's amount —
    # on a replay this is the ORIGINAL amount, not the request's.
    return DepositCreditOut(
        transaction_id=txn.id,
        merchant_id=merchant_id,
        amount=txn.postings[0].amount,
        balance=balance,
    )


@admin_router.get(
    "/{merchant_id}/transactions",
    response_model=MerchantTxnListOut,
    summary="A merchant's deposit ledger, newest first",
)
async def list_merchant_transactions(
    merchant_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> MerchantTxnListOut:
    """Every ledger movement of this merchant's deposit — the detail screen's audit trail.

    Read-only, one grouped query; ``amount`` is the signed deposit delta
    (positive = balance up). ``limit`` is bounded 1..200 in the contract —
    out-of-range values are a 422, not a silent clamp.
    """
    rows = await merchants.list_deposit_transactions(db, merchant_id=merchant_id, limit=limit)
    items: list[MerchantTxnOut] = []
    for txn, amount in rows:
        note = txn.extra_metadata.get("note")
        items.append(
            MerchantTxnOut(
                transaction_id=txn.id,
                kind=txn.kind,
                amount=amount,
                note=note if isinstance(note, str) else None,
                actor=txn.actor,
                created_at=txn.created_at,
            )
        )
    return MerchantTxnListOut(items=items)


@admin_router.post(
    "/{merchant_id}/api-keys",
    response_model=ApiKeyCreatedOut,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a machine credential for /merchant/v1",
)
async def create_api_key(
    merchant_id: str,
    body: ApiKeyCreateIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiKeyCreatedOut:
    """Mint a key. The secret is in this response and nowhere else, ever.

    Several live keys per merchant are supported so rotation has no downtime
    window (spec §9.2): issue, deploy, then revoke the old one.

    A retry carrying the same ``Idempotency-Key`` replays the original
    ``key_id`` but with ``secret: null`` — the stored snapshot deliberately
    omits it, because ``idempotent_responses`` has no reaper and a usable
    credential must not sit there in the clear. If the first response was
    lost, revoke the key and issue another.
    """
    key = normalize_idempotency_key(idempotency_key)
    scope = f"merchants.api_key_create:{merchant_id}"
    cached = await _replayed(db, scope=scope, key=key, model=ApiKeyCreatedOut)
    if cached is not None:
        return cached
    issued = await merchants.create_api_key(
        db, merchant_id=merchant_id, label=body.label, ip_allowlist=body.ip_allowlist
    )
    out = ApiKeyCreatedOut(
        **ApiKeyOut.model_validate(issued.key).model_dump(), secret=issued.secret
    )
    await _remember(
        db,
        scope=scope,
        key=key,
        body=out.model_copy(update={"secret": None}).model_dump(mode="json"),
        status_code=status.HTTP_201_CREATED,
    )
    return out


@admin_router.get(
    "/{merchant_id}/api-keys",
    response_model=ApiKeyListOut,
    summary="A merchant's machine credentials, newest first",
)
async def list_api_keys(
    merchant_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> ApiKeyListOut:
    """Never returns a secret — the response model has no such field.

    Revoked keys stay listed: "which credential was live at the time" is the
    question this screen answers.
    """
    rows = await merchants.list_api_keys(db, merchant_id=merchant_id)
    return ApiKeyListOut(items=[ApiKeyOut.model_validate(row) for row in rows])


@admin_router.delete(
    "/{merchant_id}/api-keys/{key_id}",
    response_model=ApiKeyOut,
    summary="Revoke a machine credential",
)
async def revoke_api_key(
    merchant_id: str,
    key_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiKeyOut:
    """Set ``revoked_at``; the key stops authenticating immediately.

    Naturally idempotent — a second call returns the row with the FIRST
    revocation timestamp rather than moving it — and the key is matched on
    ``(merchant_id, key_id)``, so one merchant's id in the path cannot revoke
    another's credential (404 instead).
    """
    replay_key = normalize_idempotency_key(idempotency_key)
    scope = f"merchants.api_key_revoke:{merchant_id}:{key_id}"
    cached = await _replayed(db, scope=scope, key=replay_key, model=ApiKeyOut)
    if cached is not None:
        return cached
    row = await merchants.revoke_api_key(db, merchant_id=merchant_id, key_id=key_id)
    out = ApiKeyOut.model_validate(row)
    await _remember(db, scope=scope, key=replay_key, body=out.model_dump(mode="json"))
    return out


@catalog_b2b_router.patch(
    "/skus/{sku_id}/b2b",
    response_model=SkuB2bOut,
    summary="Set a SKU's B2B markup and/or visibility",
)
async def patch_sku_b2b(
    sku_id: str,
    body: SkuB2bPatchIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> SkuB2bOut:
    """Absent fields stay untouched; no pricing math here (AGENTS.md §6)."""
    key = normalize_idempotency_key(idempotency_key)
    scope = f"merchants.sku_b2b:{sku_id}"
    cached = await _replayed(db, scope=scope, key=key, model=SkuB2bOut)
    if cached is not None:
        return cached
    sku = await merchants.set_sku_b2b(
        db, sku_id=sku_id, markup_pct=body.markup_pct, visible_b2b=body.visible_b2b
    )
    out = SkuB2bOut.model_validate(sku)
    await _remember(db, scope=scope, key=key, body=out.model_dump(mode="json"))
    return out


@catalog_b2b_router.post(
    "/b2b/bulk-markup",
    response_model=BulkMarkupOut,
    summary="Set the B2B markup for a whole brand or category in one action",
)
async def bulk_markup(
    body: BulkMarkupIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> BulkMarkupOut:
    """One UPDATE over the brand's (or category's) SKUs; returns the affected count."""
    key = normalize_idempotency_key(idempotency_key)
    # Discriminated by target KIND, not just its name: a brand slug and a
    # category name can be the same string ("steam"), and a bare name would
    # let one reused key replay the brand update for the category one and
    # silently never apply it.
    scope = (
        f"merchants.bulk_markup:brand:{body.brand_slug}"
        if body.brand_slug is not None
        else f"merchants.bulk_markup:category:{body.category}"
    )
    cached = await _replayed(db, scope=scope, key=key, model=BulkMarkupOut)
    if cached is not None:
        return cached
    affected = await merchants.bulk_set_markup(
        db,
        markup_pct=body.markup_pct,
        brand_slug=body.brand_slug,
        category_slug=body.category,
    )
    out = BulkMarkupOut(affected=affected)
    await _remember(db, scope=scope, key=key, body=out.model_dump(mode="json"))
    return out


@catalog_b2b_router.patch(
    "/brands/{brand_id}/b2b",
    response_model=BrandB2bOut,
    summary="Show or hide a whole brand in the merchant catalog",
)
async def patch_brand_b2b(
    brand_id: str,
    body: BrandB2bPatchIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> BrandB2bOut:
    """Effective B2B visibility is ``brand.visible_b2b AND sku.visible_b2b``."""
    key = normalize_idempotency_key(idempotency_key)
    scope = f"merchants.brand_b2b:{brand_id}"
    cached = await _replayed(db, scope=scope, key=key, model=BrandB2bOut)
    if cached is not None:
        return cached
    brand = await merchants.set_brand_b2b(db, brand_id=brand_id, visible_b2b=body.visible_b2b)
    out = BrandB2bOut.model_validate(brand)
    await _remember(db, scope=scope, key=key, body=out.model_dump(mode="json"))
    return out


__all__ = ["admin_router", "catalog_b2b_router"]
