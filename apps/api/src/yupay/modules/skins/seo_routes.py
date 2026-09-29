"""``/skins/seo/*`` — what the storefront's sitemap needs: every item page on sale.

A plain slug list in stable (alphabetical) pages, so the web can split ~24 000 pages across
several sitemap files. Postgres only; no Waxpeer call. 404 while the feature flag is off.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.config import get_settings
from yupay.modules.skins.models import SkinItem
from yupay.modules.skins.routes import _ensure_enabled
from yupay.modules.skins.settings import enabled_categories

router = APIRouter(prefix="/skins/seo", tags=["skins"], dependencies=[Depends(_ensure_enabled)])


class SkinSlugsOut(BaseModel):
    """A page of item slugs on sale, and how many there are."""

    items: list[str]
    total: int


@router.get("/slugs", response_model=SkinSlugsOut, summary="Item pages for the sitemap")
async def get_slugs(
    db: Annotated[AsyncSession, Depends(db_session)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=5000)] = 5000,
) -> SkinSlugsOut:
    """Slugs of active items in enabled categories, alphabetical — the same set the
    catalogue shows, so a sitemap never lists a page the market hides."""
    live = (
        SkinItem.active.is_(True),
        SkinItem.category.in_(enabled_categories(get_settings())),
    )
    total = (await db.execute(select(func.count()).where(*live))).scalar_one()
    slugs = (
        await db.execute(
            select(SkinItem.slug).where(*live).order_by(SkinItem.slug).offset(offset).limit(limit)
        )
    ).scalars()
    return SkinSlugsOut(items=list(slugs), total=int(total))


__all__ = ["SkinSlugsOut", "router"]
