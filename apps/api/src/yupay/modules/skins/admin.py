"""Admin HTTP routes for the ``skins`` module: the pricing document, a
price preview that explains itself, and per-item overrides."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.errors import NotFoundError
from yupay.core.idempotency import (
    IDEMPOTENCY_HEADER,
    load_replay,
    normalize_idempotency_key,
    save_replay,
)
from yupay.core.redis import get_redis
from yupay.modules.admin.deps import require_admin
from yupay.modules.skins.models import SkinItem
from yupay.modules.skins.prices import bump_catalog_version
from yupay.modules.skins.pricing import Channel, PricingRules, quote
from yupay.modules.skins.repricing import reprice_rows
from yupay.modules.skins.schemas import (
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


def _out(rules: PricingRules) -> SkinsPricingOut:
    settings = get_settings()
    return SkinsPricingOut(
        rules=rules,
        enabled=settings.cs2_skins_enabled,
        sync_enabled=settings.cs2_skins_sync_enabled,
        categories=enabled_categories(settings),
    )


@admin_router.get("/pricing", response_model=SkinsPricingOut, summary="The pricing rules")
async def admin_get_pricing(
    db: Annotated[AsyncSession, Depends(db_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> SkinsPricingOut:
    return _out(await load_rules(db))


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
    await save_rules(db, rules=body, admin_id=admin.id)
    await reprice_rows(db, body)
    await db.commit()
    # Publish after the commit (the gifts/fx ordering), then expire every
    # cached catalogue page: the rules changed every price on the storefront.
    await publish_rules(body)
    await bump_catalog_version(get_redis())
    out = _out(body)
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
    cost_usd: Annotated[Decimal, Query(ge=0)],
    category: str = "rifles",
    channel: Channel = "retail",
    weapon: str | None = None,
    count: Annotated[int | None, Query(ge=0)] = None,
    item_pp: Decimal | None = None,
    fixed_price_usd: Decimal | None = None,
    steam_price_usd: Decimal | None = None,
) -> SkinQuoteOut:
    rules = await load_rules(db)
    q = quote(
        int(cost_usd * 1000),
        rules=rules,
        category=category,
        channel=channel,
        weapon=weapon,
        count_auto=count,
        item_pp=item_pp,
        fixed_price_usd=fixed_price_usd,
        steam_price_units=None if steam_price_usd is None else int(steam_price_usd * 1000),
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
    await reprice_rows(db, await load_rules(db), ids=[item.id])
    await db.commit()
    await bump_catalog_version(get_redis())
    out = SkinItemPricingIn(
        margin_override_pp=item.margin_override_pp, fixed_price_usd=item.fixed_price_usd
    )
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


__all__ = ["admin_router"]
