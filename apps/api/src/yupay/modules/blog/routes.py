"""Public anonymous GETs for published blog translations."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.modules.blog import service as svc
from yupay.modules.blog.deps import resolve_locale
from yupay.modules.blog.schemas import BrandBlockOut, Locale, PostDetailOut, PostKind, PostListOut

router = APIRouter(prefix="/blog", tags=["blog"])


@router.get("", response_model=PostListOut, summary="List published posts")
async def list_posts(
    db: Annotated[AsyncSession, Depends(db_session)],
    locale: Annotated[Locale, Depends(resolve_locale)],
    brand: str | None = None,
    kind: PostKind | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
) -> PostListOut:
    """Published translations only. Live events sort above ordinary news."""
    return await svc.list_published(
        db, locale=locale, brand=brand, kind=kind, cursor=cursor, limit=limit
    )


@router.get(
    "/by-brand/{brand_slug}",
    response_model=BrandBlockOut,
    summary="Pins and latest posts for a brand page",
)
async def list_by_brand(
    brand_slug: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    locale: Annotated[Locale, Depends(resolve_locale)],
    limit: int = Query(default=6, ge=1, le=20),
) -> BrandBlockOut:
    return await svc.list_by_brand(db, brand_slug=brand_slug, locale=locale, limit=limit)


@router.get("/{slug}", response_model=PostDetailOut, summary="Get one published post")
async def get_post(
    slug: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    locale: Annotated[Locale, Depends(resolve_locale)],
) -> PostDetailOut:
    """404 when the post is unpublished or the locale row is missing."""
    return await svc.get_published_by_slug(db, slug=slug, locale=locale)
