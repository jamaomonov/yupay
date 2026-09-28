"""Admin HTTP routes for the ``skins`` module: the pricing document, a
price preview that explains itself, and per-item overrides."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.errors import NotFoundError, ValidationError
from yupay.core.idempotency import (
    IDEMPOTENCY_HEADER,
    load_replay,
    normalize_idempotency_key,
    save_replay,
)
from yupay.core.redis import get_redis
from yupay.modules.admin.deps import require_admin
from yupay.modules.skins.admin_trades import (
    AdminSkinTradeOut,
    AdminSkinTradesOut,
    TradesView,
    list_trades,
    resolve_trade,
)
from yupay.modules.skins.images import steam_image
from yupay.modules.skins.models import SkinItem
from yupay.modules.skins.prices import bump_catalog_version
from yupay.modules.skins.pricing import Channel, PricingRules, quote
from yupay.modules.skins.repricing import lock_pricing, reprice_rows
from yupay.modules.skins.schemas import (
    AdminSkinItemOut,
    AdminSkinItemsOut,
    ResolveTradeIn,
    SkinItemPricingIn,
    SkinQuoteOut,
    SkinsPricingOut,
)
from yupay.modules.skins.settings import (
    enabled_categories,
    load_rules,
    publish_rules,
    save_rules,
)
from yupay.modules.users.models import User

admin_router = APIRouter(
    prefix="/admin/skins", tags=["admin:skins"], dependencies=[Depends(require_admin)]
)


async def _out(db: AsyncSession, rules: PricingRules) -> SkinsPricingOut:
    settings = get_settings()
    active, synced = (
        await db.execute(
            select(func.count(), func.max(SkinItem.prices_updated_at)).where(
                SkinItem.active.is_(True)
            )
        )
    ).one()
    return SkinsPricingOut(
        rules=rules,
        enabled=settings.cs2_skins_enabled,
        sync_enabled=settings.cs2_skins_sync_enabled,
        categories=enabled_categories(settings),
        items_active=int(active),
        prices_updated_at=synced,
    )


@admin_router.get("/pricing", response_model=SkinsPricingOut, summary="The pricing rules")
async def admin_get_pricing(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> SkinsPricingOut:
    return await _out(db, await load_rules(db))


@admin_router.put("/pricing", response_model=SkinsPricingOut, summary="Replace the pricing rules")
async def admin_put_pricing(
    body: PricingRules,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> SkinsPricingOut:
    key = normalize_idempotency_key(idempotency_key)
    scope = "skins.put_pricing"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None and cached.body is not None:
            return SkinsPricingOut.model_validate(cached.body)
    await lock_pricing(db)
    await save_rules(db, rules=body, admin_id=admin.id)
    await reprice_rows(db, body)
    await db.commit()
    # Publish after the commit (the gifts/fx ordering), then expire every
    # cached catalogue page: the rules changed every price on the storefront.
    await publish_rules(body)
    await bump_catalog_version(get_redis())
    out = await _out(db, body)
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


@admin_router.get(
    "/pricing/preview",
    response_model=SkinQuoteOut,
    summary="What would this cost sell for, and why",
)
async def admin_preview_price(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    cost_usd: Annotated[Decimal | None, Query(ge=0)] = None,
    slug: str | None = None,
    category: str | None = None,
    channel: Channel = "retail",
    weapon: str | None = None,
    count: Annotated[int | None, Query(ge=0)] = None,
    item_pp: Decimal | None = None,
    fixed_price_usd: Decimal | None = None,
    steam_price_usd: Decimal | None = None,
) -> SkinQuoteOut:
    """A price and its reasoning — for typed numbers, or for a real skin by ``slug``.

    With ``slug`` the skin's own cost, category, weapon, listing count, overrides and
    Steam price are used; any parameter also given replaces the skin's (the override
    editor previews a new markup this way before saving it).
    """
    rules = await load_rules(db)
    steam_units = None if steam_price_usd is None else int(steam_price_usd * 1000)
    cost_units = None if cost_usd is None else int(cost_usd * 1000)
    if slug is not None:
        item = (
            await db.execute(select(SkinItem).where(SkinItem.slug == slug))
        ).scalar_one_or_none()
        if item is None:
            raise NotFoundError("skin not found")
        cost_units = cost_units if cost_units is not None else item.min_auto_units
        category = category or item.category
        weapon = weapon if weapon is not None else item.weapon
        count = count if count is not None else item.count_auto
        item_pp = item_pp if item_pp is not None else item.margin_override_pp
        fixed_price_usd = fixed_price_usd if fixed_price_usd is not None else item.fixed_price_usd
        steam_units = steam_units if steam_units is not None else item.steam_price_units
    if cost_units is None:
        raise ValidationError("cost_usd or a skin with a live price is required")
    q = quote(
        cost_units,
        rules=rules,
        category=category or "rifles",
        channel=channel,
        weapon=weapon,
        count_auto=count,
        item_pp=item_pp,
        fixed_price_usd=fixed_price_usd,
        steam_price_units=steam_units,
    )
    return SkinQuoteOut(
        price_usd=str(q.price_usd),
        cost_usd=str(q.cost_usd),
        expenses_usd=str(q.expenses_usd),
        bracket_margin_usd=str(q.bracket_margin_usd),
        category_pp=str(q.category_pp),
        weapon_pp=str(q.weapon_pp),
        liquidity_pp=str(q.liquidity_pp),
        item_pp=str(q.item_pp),
        effective_percent=str(q.effective_percent),
        applied=q.applied,
    )


@admin_router.patch(
    "/items/{slug}",
    response_model=SkinItemPricingIn,
    summary="Pin a margin or a price for one item",
)
async def admin_set_item_pricing(
    slug: str,
    body: SkinItemPricingIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> SkinItemPricingIn:
    key = normalize_idempotency_key(idempotency_key)
    scope = f"skins.set_item_pricing:{slug}"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None and cached.body is not None:
            return SkinItemPricingIn.model_validate(cached.body)
    await lock_pricing(db)
    item = (await db.execute(select(SkinItem).where(SkinItem.slug == slug))).scalar_one_or_none()
    if item is None:
        raise NotFoundError("skin not found")
    # A PATCH: only what was sent changes. ``null`` clears a field; an omitted
    # one keeps its value (a margin change must not unpin a price).
    if "margin_override_pp" in body.model_fields_set:
        item.margin_override_pp = body.margin_override_pp
    if "fixed_price_usd" in body.model_fields_set:
        item.fixed_price_usd = body.fixed_price_usd
    item.updated_at = now()
    await reprice_rows(db, await load_rules(db, fresh=True), ids=[item.id])
    await db.commit()
    await bump_catalog_version(get_redis())
    out = SkinItemPricingIn(
        margin_override_pp=item.margin_override_pp, fixed_price_usd=item.fixed_price_usd
    )
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


@admin_router.get(
    "/trades",
    response_model=AdminSkinTradesOut,
    summary="Skin trades, newest first — all, in flight, or needing a human",
)
async def admin_list_trades(
    db: Annotated[AsyncSession, Depends(db_session)],
    view: Annotated[TradesView, Query()] = "all",
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: int = 50,
    offset: int = 0,
) -> AdminSkinTradesOut:
    """The trades screen: Waxpeer status, our state, seller, and what needs settling."""
    return await list_trades(
        db, view=view, q=q, limit=max(1, min(limit, 500)), offset=max(0, offset)
    )


@admin_router.get(
    "/items",
    response_model=AdminSkinItemsOut,
    summary="Find items to override, or list the overridden ones",
)
async def admin_find_items(
    db: Annotated[AsyncSession, Depends(db_session)],
    q: Annotated[str | None, Query(max_length=100)] = None,
    overridden: bool = False,
    limit: int = 20,
) -> AdminSkinItemsOut:
    """Items by part of the name (most liquid first), or every item with an override."""
    stmt = select(SkinItem)
    if q and q.strip():
        stmt = stmt.where(SkinItem.search_text.ilike(f"%{q.strip().lower()}%"))
    if overridden:
        stmt = stmt.where(
            or_(SkinItem.margin_override_pp.is_not(None), SkinItem.fixed_price_usd.is_not(None))
        )
    rows = await db.execute(
        stmt.order_by(SkinItem.count_auto.desc(), SkinItem.slug).limit(max(1, min(limit, 100)))
    )
    host = get_settings().cs2_skins_image_host
    return AdminSkinItemsOut(
        items=[
            AdminSkinItemOut(
                slug=row.slug,
                name=f"{row.market_hash_name} {row.phase}".strip(),
                category=row.category,
                weapon=row.weapon,
                image_url=steam_image(row.image_url, host=host),
                count_auto=row.count_auto,
                cost_usd=(
                    str(Decimal(row.min_auto_units) / 1000)
                    if row.min_auto_units is not None
                    else None
                ),
                sell_price_usd=row.sell_price_usd,
                margin_override_pp=row.margin_override_pp,
                fixed_price_usd=row.fixed_price_usd,
            )
            for row in rows.scalars()
        ]
    )


@admin_router.post(
    "/trades/{trade_id}/resolve",
    response_model=AdminSkinTradeOut,
    summary="Mark a trade settled by a human — it leaves «needs attention»",
)
async def admin_resolve_trade(
    trade_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    body: ResolveTradeIn | None = None,
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> AdminSkinTradeOut:
    """Record that an operator settled this trade (refund, support answer, Waxpeer ticket)."""
    key = normalize_idempotency_key(idempotency_key)
    scope = f"skins.resolve_trade:{trade_id}"
    if key is not None:
        cached = await load_replay(db, scope=scope, idempotency_key=key)
        if cached is not None and cached.body is not None:
            return AdminSkinTradeOut.model_validate(cached.body)
    out = await resolve_trade(
        db, trade_id=trade_id, by=str(admin.id), note=body.note if body else None
    )
    if out is None:
        raise NotFoundError("skin trade not found")
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


__all__ = ["admin_router"]
