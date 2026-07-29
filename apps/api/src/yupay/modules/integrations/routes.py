"""Admin-only HTTP routes for supplier integrations.

CRUD over ``sku_supplier_mapping``, real-time health probes against the
supplier API, and on-demand catalog sync that populates
``supplier_catalog_cache`` for autocomplete in the mapping editor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from yupay.modules.fulfillment.suppliers.g2b import G2bFulfiller
    from yupay.modules.fulfillment.suppliers.waxpeer import WaxpeerFulfiller

from yupay.api.v1.deps import db_session
from yupay.core.clock import now
from yupay.core.idempotency import (
    IDEMPOTENCY_HEADER,
    load_replay,
    normalize_idempotency_key,
    save_replay,
)
from yupay.core.logging import get_logger
from yupay.modules.admin.api import require_admin
from yupay.modules.auth.ip_guard import guard_ip
from yupay.modules.integrations import service as svc
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.integrations.player_check import check_player_for_product
from yupay.modules.integrations.schemas import (
    CatalogEntryOut,
    CatalogKind,
    CatalogListOut,
    CatalogSyncOut,
    CheckPlayerIn,
    CheckPlayerOut,
    CostSyncResult,
    GameDenomListOut,
    GameDenomOut,
    GameFieldsOut,
    GameImportIn,
    GameImportOut,
    PlayerCheckIn,
    PlayerCheckOut,
    PriceHistoryOut,
    PricePointOut,
    PriceRefreshOut,
    SupplierHealthOut,
    SupplierMappingIn,
    SupplierMappingListOut,
    SupplierMappingOut,
    SupplierMappingUpsertOut,
)
from yupay.modules.inventory import service as inv_svc
from yupay.modules.users.models import User

log = get_logger("yupay.integrations.routes")

admin_router = APIRouter(
    prefix="/admin/integrations",
    tags=["admin:integrations"],
    dependencies=[Depends(require_admin)],
)

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.post(
    "/products/{product_id}/check-player",
    response_model=PlayerCheckOut,
    summary="Verify a player id for a product (advisory nickname lookup)",
)
async def check_player(
    product_id: str,
    body: PlayerCheckIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> PlayerCheckOut:
    """Storefront-facing. Advisory — folds upstream errors into
    ``{valid: false}``; never blocks checkout. Rate-limited per IP. See ADR-0031.
    """
    await guard_ip(request, bucket="check_player")
    return await check_player_for_product(
        db, product_id=product_id, player_id=body.player_id, server_id=body.server_id
    )


_KNOWN_SUPPLIERS = {"g2b"}


def _mapping_out(row: SkuSupplierMapping, sku_code: str) -> SupplierMappingOut:
    """Build ``SupplierMappingOut`` from the ORM row plus a separately
    resolved ``sku_code`` (no ORM relationship to ``Sku`` to pull it from —
    see ``svc.sku_codes_for``)."""
    return SupplierMappingOut.model_validate({**row.__dict__, "sku_code": sku_code})


@admin_router.get(
    "/mappings",
    response_model=SupplierMappingListOut,
    summary="List supplier mappings",
)
async def list_mappings(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    supplier_slug: Annotated[str | None, Query(min_length=2, max_length=32)] = None,
    sku_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> SupplierMappingListOut:
    rows = await svc.list_mappings(db, supplier_slug=supplier_slug, sku_id=sku_id, limit=limit)
    sku_codes = await svc.sku_codes_for(db, (r.sku_id for r in rows))
    return SupplierMappingListOut(
        items=[_mapping_out(r, sku_codes.get(r.sku_id, r.sku_id)) for r in rows]
    )


@admin_router.put(
    "/mappings/{sku_id}",
    response_model=SupplierMappingUpsertOut,
    summary="Upsert the mapping for ``(sku_id, supplier_slug)``",
)
async def upsert_mapping(
    sku_id: str,
    body: SupplierMappingIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> SupplierMappingUpsertOut:
    """Create or update the SKU↔supplier mapping.

    After persisting the row we ask the supplier for the current upstream
    price and write it to ``Sku.cost_usdt``. The mutation is best-effort
    and reported back through ``cost_sync`` so the admin UI can flash
    whether the cost actually moved.
    """
    key = normalize_idempotency_key(idempotency_key)
    scope = "integrations.upsert_mapping"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None:
            return SupplierMappingUpsertOut.model_validate(cached.body)
    await inv_svc.get_sku_or_404(db, sku_id)
    row = await svc.upsert_mapping(
        db,
        svc.MappingUpsert(
            sku_id=sku_id,
            supplier_slug=body.supplier_slug,
            kind=body.kind,
            external_product_id=body.external_product_id,
            external_variant_id=body.external_variant_id,
            quantity=body.quantity,
            extra=body.extra,
            is_active=body.is_active,
            updated_by=admin.id,
        ),
    )
    cost_sync = await _refresh_sku_cost(db, row)
    sku_codes = await svc.sku_codes_for(db, [sku_id])
    out = SupplierMappingUpsertOut(
        mapping=_mapping_out(row, sku_codes.get(sku_id, sku_id)),
        cost_sync=cost_sync,
    )
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    await db.commit()
    return out


async def _refresh_sku_cost(db: AsyncSession, mapping: object) -> CostSyncResult:
    """HTTP-layer adapter around :func:`svc.refresh_sku_cost_for_mapping`.

    The shared logic lives in the service module so the scheduler can
    reuse it from a background actor; this wrapper exists only to map
    the strongly-typed ``CostRefreshOutcome`` back into the DTO the
    admin SPA expects.
    """
    from yupay.modules.integrations.models import SkuSupplierMapping

    assert isinstance(mapping, SkuSupplierMapping)
    outcome = await svc.refresh_sku_cost_for_mapping(db, mapping=mapping)
    return CostSyncResult(
        updated=outcome.updated,
        old_cost=str(outcome.old_cost) if outcome.old_cost is not None else None,
        new_cost=str(outcome.new_cost) if outcome.new_cost is not None else None,
        source=outcome.source,
        reason=outcome.reason,
    )


@admin_router.delete(
    "/mappings/{sku_id}/{supplier_slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Drop the mapping for ``(sku_id, supplier_slug)``",
)
async def delete_mapping(
    sku_id: str,
    supplier_slug: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> None:
    key = normalize_idempotency_key(idempotency_key)
    scope = "integrations.delete_mapping"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None:
            return
    await svc.delete_mapping(db, sku_id=sku_id, supplier_slug=supplier_slug)
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=None)
    return


@admin_router.get(
    "/catalog",
    response_model=CatalogListOut,
    summary="Cached supplier catalog (autocomplete for mappings UI)",
)
async def list_catalog(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    supplier_slug: Annotated[str, Query(min_length=2, max_length=32)],
    kind: Annotated[CatalogKind | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> CatalogListOut:
    rows = await svc.list_catalog(
        db,
        supplier_slug=supplier_slug,
        kind=kind,
        search=search,
        limit=limit,
    )
    return CatalogListOut(items=[CatalogEntryOut.model_validate(r) for r in rows])


@admin_router.post(
    "/g2b/sync-catalog",
    response_model=CatalogSyncOut,
    summary="Refresh ``supplier_catalog_cache`` from the G2B API",
)
async def sync_g2b_catalog(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> CatalogSyncOut:
    """Pulls G2B's product + game catalog into our cache.

    Best-effort: partial failures are logged but the endpoint never raises
    so the admin UI gets a definitive answer instead of a 5xx. Live
    fulfilment does NOT depend on this cache — the source of truth is
    ``sku_supplier_mapping``.
    """
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.g2b import G2bFulfiller

    fulfiller = REGISTRY.get("g2b")
    if not isinstance(fulfiller, G2bFulfiller) or not fulfiller.available:
        return CatalogSyncOut(
            supplier="g2b",
            error="G2B_API_KEY is not configured",
        )

    client = fulfiller._client()
    vouchers = 0
    games = 0
    error: str | None = None
    try:
        products = await client.fetch_products(page=1, limit=200)
        for item in products:
            external_id = str(item.get("id") or item.get("product_id") or "").strip()
            if not external_id:
                continue
            title = str(
                item.get("title") or item.get("name") or external_id,
            )[:255]
            await svc.upsert_catalog_entry(
                db,
                supplier_slug="g2b",
                kind="voucher",
                external_id=external_id,
                title=title,
                raw=item,
            )
            vouchers += 1
    except Exception as exc:  # noqa: BLE001 -- best-effort sync
        error = f"voucher sync failed: {exc!s}"[:200]
        log.warning("integrations.g2b.sync.voucher_failed", error=str(exc))

    try:
        games_payload = await client.fetch_games()
        for item in games_payload:
            external_id = str(item.get("code") or item.get("id") or "").strip()
            if not external_id:
                continue
            title = str(item.get("name") or external_id)[:255]
            await svc.upsert_catalog_entry(
                db,
                supplier_slug="g2b",
                kind="game",
                external_id=external_id,
                title=title,
                raw=item,
            )
            games += 1
    except Exception as exc:  # noqa: BLE001
        err = f"game sync failed: {exc!s}"[:200]
        error = f"{error}; {err}" if error else err
        log.warning("integrations.g2b.sync.games_failed", error=str(exc))

    await db.commit()
    return CatalogSyncOut(
        supplier="g2b",
        vouchers_synced=vouchers,
        games_synced=games,
        error=error,
    )


@admin_router.post(
    "/g2b/import",
    response_model=GameImportOut,
    status_code=status.HTTP_201_CREATED,
    summary="Import a G2B game as a Brand + Product + SKUs + mappings",
)
async def import_g2b_game(
    body: GameImportIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> GameImportOut:
    """Atomic import. Idempotency is structural — re-importing a denomination
    whose ``sku_code`` already exists skips it (reported in ``skipped``); the
    ``Idempotency-Key`` header is accepted for client convenience and logged.

    Errors propagate as the module's standard mapping: duplicate brand/product
    slug -> 409, unknown brand_id/category_id -> 404, bad price/payload -> 422.
    """
    result = await svc.import_game(db, body, admin_id=admin.id)
    await db.commit()
    log.info(
        "integrations.g2b.import",
        game_code=body.game_code,
        created_skus=result.created_skus,
        skipped=len(result.skipped),
        idempotency_key=idempotency_key,
    )
    return GameImportOut(
        brand_id=result.brand_id,
        product_id=result.product_id,
        created_skus=result.created_skus,
        created_mappings=result.created_mappings,
        skipped=result.skipped,
    )


def _g2b_fulfiller_or_none() -> G2bFulfiller | None:
    """Return the registered G2B adapter iff ``G2B_API_KEY`` is set.

    Centralised so the three game-side endpoints below share the same
    short-circuit when the operator hits them on an unconfigured stack.
    """
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.g2b import G2bFulfiller

    fulfiller = REGISTRY.get("g2b")
    if isinstance(fulfiller, G2bFulfiller) and fulfiller.available:
        return fulfiller
    return None


def _waxpeer_fulfiller_or_none() -> WaxpeerFulfiller | None:
    """Return the registered Waxpeer adapter iff ``WAXPEER_API_KEY`` is set.

    Mirrors :func:`_g2b_fulfiller_or_none` above — used by the Steam-login
    branch of ``player_check.check_player_for_product``.
    """
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.waxpeer import WaxpeerFulfiller

    fulfiller = REGISTRY.get("waxpeer")
    if isinstance(fulfiller, WaxpeerFulfiller) and fulfiller.available:
        return fulfiller
    return None


@admin_router.get(
    "/g2b/games/{game_code}/catalogue",
    response_model=GameDenomListOut,
    summary="G2B game denominations (catalogue) for the mapping picker",
)
async def g2b_game_catalogue(
    game_code: str,
    _admin: Annotated[User, Depends(require_admin)],
) -> GameDenomListOut:
    fulfiller = _g2b_fulfiller_or_none()
    if fulfiller is None:
        return GameDenomListOut(items=[])
    client = fulfiller._client()
    try:
        rows = await client.games_catalogue(game_code)
    except Exception as exc:  # noqa: BLE001 -- best-effort
        log.warning("integrations.g2b.catalogue_failed", game_code=game_code, error=str(exc))
        return GameDenomListOut(items=[])
    out: list[GameDenomOut] = []
    for item in rows:
        catalogue_name = str(item.get("name") or item.get("catalogue_name") or "").strip()
        if not catalogue_name:
            continue
        # G2B uses ``amount`` for the upstream USD price. Some games may
        # also surface a separate ``price`` (none we've seen so far). Keep
        # both fields in the DTO so the UI can pick whichever exists.
        raw_amount = item.get("amount")
        raw_price = item.get("price") or item.get("unit_price") or raw_amount
        out.append(
            GameDenomOut(
                catalogue_name=catalogue_name,
                name=catalogue_name,
                amount=str(raw_amount) if raw_amount is not None else None,
                price=str(raw_price) if raw_price is not None else None,
                raw=item,
            )
        )
    return GameDenomListOut(items=out)


@admin_router.get(
    "/g2b/games/{game_code}/fields",
    response_model=GameFieldsOut,
    summary="Required fields the customer must enter for this game",
)
async def g2b_game_fields(
    game_code: str,
    _admin: Annotated[User, Depends(require_admin)],
) -> GameFieldsOut:
    fulfiller = _g2b_fulfiller_or_none()
    if fulfiller is None:
        return GameFieldsOut(fields=[])
    client = fulfiller._client()
    try:
        body = await client.games_fields(game_code)
    except Exception as exc:  # noqa: BLE001
        log.warning("integrations.g2b.fields_failed", game_code=game_code, error=str(exc))
        return GameFieldsOut(fields=[])
    info = body.get("info") or body
    fields_raw = info.get("fields") if isinstance(info, dict) else None
    fields = [str(f) for f in fields_raw] if isinstance(fields_raw, list) else []
    notes = info.get("notes") if isinstance(info, dict) else None
    return GameFieldsOut(fields=fields, notes=notes if notes else None)


@admin_router.post(
    "/g2b/games/{game_code}/check-player",
    response_model=CheckPlayerOut,
    summary="Verify a player_id against the G2B game's checker",
)
async def g2b_check_player(
    game_code: str,
    body: CheckPlayerIn,
    _admin: Annotated[User, Depends(require_admin)],
) -> CheckPlayerOut:
    """Admin-side diagnostic — proxies ``POST /v1/games/checkPlayerId``.

    Used by the mapping editor to confirm a test player id resolves before
    operators commit a new mapping. Never persists the ``player_id`` —
    it's a transient diagnostic call. Errors are folded into
    ``{valid: false, reason}`` so the UI stays out of error-boundary
    territory.
    """
    fulfiller = _g2b_fulfiller_or_none()
    if fulfiller is None:
        return CheckPlayerOut(valid=False, reason="G2B is not configured")
    client = fulfiller._client()
    try:
        resp = await client.games_check_player(
            game_code=game_code,
            player_id=body.player_id,
            server_id=body.server_id,
            charname=body.charname,
        )
    except Exception as exc:  # noqa: BLE001
        return CheckPlayerOut(valid=False, reason=str(exc)[:200])
    raw_valid = str(resp.get("valid") or "").lower()
    return CheckPlayerOut(
        valid=raw_valid == "valid",
        name=str(resp["name"]) if resp.get("name") else None,
        openid=str(resp["openid"]) if resp.get("openid") else None,
        reason=None if raw_valid == "valid" else str(resp.get("message") or "rejected"),
    )


@admin_router.get(
    "/sku-prices/{sku_id}/history",
    response_model=PriceHistoryOut,
    summary="Supplier cost history for a SKU (newest first)",
)
async def sku_price_history(
    sku_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> PriceHistoryOut:
    rows = await svc.list_price_history(db, sku_id=sku_id, limit=limit)
    return PriceHistoryOut(
        items=[
            PricePointOut(
                id=r.id,
                sku_id=r.sku_id,
                supplier_slug=r.supplier_slug,
                kind=r.kind,
                external_product_id=r.external_product_id,
                external_variant_id=r.external_variant_id,
                cost_usdt=str(r.cost_usdt),
                previous_cost_usdt=(
                    str(r.previous_cost_usdt) if r.previous_cost_usdt is not None else None
                ),
                source=r.source,
                captured_at=r.captured_at,
            )
            for r in rows
        ]
    )


@admin_router.post(
    "/refresh-all-prices",
    response_model=PriceRefreshOut,
    summary="Manually re-price every active mapping (the hourly job does this too)",
)
async def refresh_all_prices(
    _admin: Annotated[User, Depends(require_admin)],
) -> PriceRefreshOut:
    """On-demand admin trigger. Mirrors the scheduler job — the same
    ``integrations.price_refresh.refresh_all_mappings`` is invoked, so
    Telegram alerts on threshold crossings fire from here too."""
    from yupay.modules.integrations.price_refresh import refresh_all_mappings

    report = await refresh_all_mappings()
    return PriceRefreshOut(
        checked=report.checked,
        moved=report.moved,
        alerts_sent=report.alerts_sent,
        errors=report.errors,
    )


@admin_router.get(
    "/{supplier_slug}/health",
    response_model=SupplierHealthOut,
    summary="Connectivity probe for a supplier",
)
async def supplier_health(
    supplier_slug: str,
    _admin: Annotated[User, Depends(require_admin)],
) -> SupplierHealthOut:
    """Live probe against the supplier's status endpoint.

    For G2B we call ``GET /v1/getMe`` through the fulfiller and surface the
    balance + username back to the admin UI. The fulfiller's ``health()``
    method already swallows network errors and shapes them into
    ``{available: false, reason}`` — we just adapt to the DTO.
    """
    if supplier_slug not in _KNOWN_SUPPLIERS:
        return SupplierHealthOut(
            supplier=supplier_slug,
            available=False,
            reason="unknown supplier",
            last_checked_at=now(),
        )
    if supplier_slug == "g2b":
        from yupay.modules.fulfillment.suppliers import REGISTRY
        from yupay.modules.fulfillment.suppliers.g2b import G2bFulfiller

        fulfiller = REGISTRY.get("g2b")
        if not isinstance(fulfiller, G2bFulfiller):
            return SupplierHealthOut(
                supplier="g2b",
                available=False,
                reason="g2b adapter not registered",
                last_checked_at=now(),
            )
        result = await fulfiller.health()
        balance = result.get("balance")
        return SupplierHealthOut(
            supplier="g2b",
            available=bool(result.get("available")),
            reason=result.get("reason"),
            balance=str(balance) if balance is not None else None,
            currency=None,
            username=result.get("username"),
            last_checked_at=now(),
        )
    return SupplierHealthOut(
        supplier=supplier_slug,
        available=False,
        reason="no health probe defined",
        last_checked_at=now(),
    )
