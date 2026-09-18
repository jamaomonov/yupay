"""Admin-only HTTP routes for supplier integrations.

CRUD over ``sku_supplier_mapping``, real-time health probes against the
supplier API, and on-demand catalog sync that populates
``supplier_catalog_cache`` for autocomplete in the mapping editor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from yupay.modules.fulfillment.suppliers.g2b import G2bFulfiller
    from yupay.modules.fulfillment.suppliers.nova import NovaFulfiller
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
from yupay.modules.integrations.catalog_sync import run_catalog_sync, run_game_denomination_sync
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.integrations.player_check import check_player_for_brand
from yupay.modules.integrations.schemas import (
    CatalogEntryOut,
    CatalogKind,
    CatalogListOut,
    CatalogSyncOut,
    CheckPlayerIn,
    CheckPlayerOut,
    CostSyncResult,
    DenomSyncOut,
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
    "/brands/{slug}/check-player",
    response_model=PlayerCheckOut,
    summary="Verify a player id for a brand (advisory nickname lookup)",
)
async def check_player(
    slug: str,
    body: PlayerCheckIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> PlayerCheckOut:
    """Storefront-facing. Advisory — folds upstream errors into
    ``status="error"``; never blocks checkout. Rate-limited per IP. See
    ADR-0031 and ADR-0079 (why a brand: a brand is one game).
    """
    await guard_ip(request, bucket="check_player")
    return await check_player_for_brand(
        db, brand_slug=slug, player_id=body.player_id, server_id=body.server_id
    )


_KNOWN_SUPPLIERS = {"g2b", "waxpeer", "gengine", "nova"}


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
            # Tolerate replay bodies cached before ``mapping.sku_code`` was added
            # (the deploy window): fall back to the sku_id so a same-key retry
            # never 500s on the now-required nested field.
            data = {**(cached.body or {})}
            mapping = data.get("mapping")
            if isinstance(mapping, dict) and not mapping.get("sku_code"):
                data["mapping"] = {**mapping, "sku_code": mapping.get("sku_id", "")}
            return SupplierMappingUpsertOut.model_validate(data)
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

    ``allow_price_drop=True``, explicitly: an operator just chose this
    mapping in the admin UI, so a cost drop it uncovers may lower the
    shelf price, same as before ``allow_price_drop`` existed. The hourly/
    on-demand bulk refresh (``price_refresh.refresh_all_mappings``) is the
    one caller that passes ``False`` — see that function and
    ``set_sku_cost_usdt`` for the rule.
    """
    from yupay.modules.integrations.models import SkuSupplierMapping

    assert isinstance(mapping, SkuSupplierMapping)
    outcome = await svc.refresh_sku_cost_for_mapping(db, mapping=mapping, allow_price_drop=True)
    return CostSyncResult(
        updated=outcome.updated,
        old_cost=str(outcome.old_cost) if outcome.old_cost is not None else None,
        new_cost=str(outcome.new_cost) if outcome.new_cost is not None else None,
        source=outcome.source,
        reason=outcome.reason,
        old_price=str(outcome.old_price) if outcome.old_price is not None else None,
        new_price=str(outcome.new_price) if outcome.new_price is not None else None,
        price_drop_blocked=outcome.price_drop_blocked,
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
    parent_external_id: Annotated[str | None, Query(max_length=128)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> CatalogListOut:
    """Cache-only read — never calls a supplier (AGENTS.md §10). ``kind`` and
    ``parent_external_id`` together are how the admin picker narrows a
    ``game_denom`` listing down to one game's own denominations."""
    rows = await svc.list_catalog(
        db,
        supplier_slug=supplier_slug,
        kind=kind,
        search=search,
        parent_external_id=parent_external_id,
        limit=limit,
    )
    return CatalogListOut(items=[CatalogEntryOut.model_validate(r) for r in rows])


@admin_router.post(
    "/{supplier}/sync-catalog",
    response_model=CatalogSyncOut,
    summary="Refresh ``supplier_catalog_cache`` from one supplier's API",
)
async def sync_catalog(
    supplier: Literal["g2b", "nova", "gengine"],
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> CatalogSyncOut:
    """Pulls one supplier's game/voucher catalogue into our cache.

    Best-effort: partial failures are logged but the endpoint never raises
    so the admin UI gets a definitive answer instead of a 5xx. Live
    fulfilment does NOT depend on this cache — the source of truth is
    ``sku_supplier_mapping``.

    Generalised from the G2B-only ``POST /g2b/sync-catalog`` (kept working —
    ``supplier="g2b"`` is one of the three literal values this path accepts,
    so the old URL still resolves to this same handler) to also cover NOVA
    and G-Engine. The scheduler runs the same sync hourly, per supplier
    (``sync_supplier_catalog``); this button is for when someone does not
    want to wait.

    Accepts ``Idempotency-Key`` (AGENTS.md §9) the same way its sibling
    ``sync_game_denominations`` does, below: a replay returns the first
    report instead of re-running the sweep. The write itself (an upsert into
    ``supplier_catalog_cache``) is harmless to repeat — nothing here debits a
    wallet or double-books an order — but harmlessness is an argument for why
    a stray retry can't hurt, not for leaving the header off; a slow sweep
    behind a flaky admin connection can still be retried by a human, and a
    replayed key should get back the report that already ran rather than pay
    for a second one.
    """
    key = normalize_idempotency_key(idempotency_key)
    scope = "integrations.sync_catalog"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None:
            return CatalogSyncOut.model_validate(cached.body)
    report = await run_catalog_sync(db, supplier_slug=supplier)
    await db.commit()
    out = CatalogSyncOut(
        supplier=supplier,
        vouchers_synced=report.vouchers,
        games_synced=report.games,
        mapped_vouchers_refreshed=report.mapped_vouchers,
        missing_upstream=report.missing_upstream,
        error=report.error,
    )
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


@admin_router.post(
    "/{supplier}/games/{game_id}/sync-denominations",
    response_model=DenomSyncOut,
    summary="Pull one game's denominations into the catalog cache, on demand",
)
async def sync_game_denominations(
    supplier: Literal["nova", "gengine"],
    game_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> DenomSyncOut:
    """One live supplier call, made on purpose.

    AGENTS.md §10 forbids a synchronous supplier call inside a *request
    handler on the money path*; this route is the deviation-free shape
    instead of a violation of it — a ``POST``, explicitly triggered by an
    operator, off the order path, syncing exactly one game the mapping
    wizard's cache has never seen. Nothing here is on a customer's critical
    path, and ``GET .../catalog`` — the route the picker actually polls —
    never reaches a supplier itself; it only reads what this endpoint or the
    hourly job already wrote.

    G2B is not one of the two suppliers this path accepts: its own per-game
    denomination picker already exists as a live GET
    (``/g2b/games/{game_code}/catalogue``, pre-dating this endpoint) and was
    not moved into the cache.
    """
    key = normalize_idempotency_key(idempotency_key)
    scope = "integrations.sync_game_denominations"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None:
            return DenomSyncOut.model_validate(cached.body)
    count, error = await run_game_denomination_sync(db, supplier_slug=supplier, game_id=game_id)
    await db.commit()
    out = DenomSyncOut(supplier=supplier, game_id=game_id, denominations_synced=count, error=error)
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


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
    branch of ``player_check.check_player_for_brand``.
    """
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.waxpeer import WaxpeerFulfiller

    fulfiller = REGISTRY.get("waxpeer")
    if isinstance(fulfiller, WaxpeerFulfiller) and fulfiller.available:
        return fulfiller
    return None


def _nova_fulfiller_or_none() -> NovaFulfiller | None:
    """Return the registered NOVA adapter iff ``NOVA_API_KEY`` is set.

    Mirrors the two above — used by the player-check fallback in
    ``integrations.player_check_nova``.
    """
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.nova import NovaFulfiller

    fulfiller = REGISTRY.get("nova")
    if isinstance(fulfiller, NovaFulfiller) and fulfiller.available:
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
    supplier_slug: Annotated[str | None, Query(min_length=2, max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> PriceHistoryOut:
    """Newest-first cost history for a SKU, optionally scoped to one
    supplier. Unfiltered (``supplier_slug`` omitted) matches every caller
    from before this branch, when the table held only G2B rows; now that
    Task 1 writes a row for every active mapping, a caller that wants one
    supplier's own series — not an interleaved multi-supplier one — passes
    it.
    """
    rows = await svc.list_price_history(db, sku_id=sku_id, supplier_slug=supplier_slug, limit=limit)
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

    Resolved through the fulfiller registry rather than a per-supplier branch:
    a supplier that can describe its own health exposes ``health()``, and this
    route only adapts the result to the DTO. That is what lets Waxpeer appear
    here at all — it was integrated for Steam top-ups and had a balance probe
    the whole time, but no way to reach it from the admin.

    ``health()`` swallows its own network errors and shapes them into
    ``{available: false, reason}``, so an operator opening the page while a
    supplier is down sees "not available", not an error boundary.
    """
    if supplier_slug not in _KNOWN_SUPPLIERS:
        return SupplierHealthOut(
            supplier=supplier_slug,
            available=False,
            reason="unknown supplier",
            last_checked_at=now(),
        )

    from yupay.modules.fulfillment.suppliers import REGISTRY

    fulfiller = REGISTRY.get(supplier_slug)
    probe = getattr(fulfiller, "health", None)
    if fulfiller is None or probe is None:
        return SupplierHealthOut(
            supplier=supplier_slug,
            available=False,
            reason="no health probe defined",
            last_checked_at=now(),
        )

    result: dict[str, Any] = await probe()
    balance = result.get("balance")
    return SupplierHealthOut(
        supplier=supplier_slug,
        available=bool(result.get("available")),
        reason=result.get("reason"),
        balance=str(balance) if balance is not None else None,
        currency=result.get("currency"),
        username=result.get("username"),
        last_checked_at=now(),
    )
