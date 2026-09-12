"""Public reads for published blog translations. Writes live in ``admin_service``."""

from __future__ import annotations

import base64
from datetime import datetime

from sqlalchemy import and_, case, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from yupay.core.clock import now
from yupay.core.errors import NotFoundError, ValidationError
from yupay.modules.blog.models import BlogPost, BlogPostTranslation
from yupay.modules.blog.schemas import (
    BrandBlockOut,
    BrandRefOut,
    FaqOut,
    Locale,
    PostDetailOut,
    PostKind,
    PostListItemOut,
    PostListOut,
)
from yupay.modules.catalog.models import Brand, BrandTranslation

_MAX_LIST = 50
_BRAND_BLOCK = 6


def _encode_cursor(live_rank: int, published_at: datetime, post_id: str) -> str:
    raw = f"{live_rank}|{published_at.isoformat()}|{post_id}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(cursor: str) -> tuple[int, datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        rank_s, iso, post_id = raw.split("|", 2)
        return int(rank_s), datetime.fromisoformat(iso), post_id
    except (ValueError, TypeError) as exc:
        raise ValidationError("invalid cursor") from exc


_KINDS: dict[str, PostKind] = {
    "guide": "guide",
    "news": "news",
    "update": "update",
    "event": "event",
}


def _as_kind(value: str) -> PostKind:
    kind = _KINDS.get(value)
    if kind is None:
        raise ValidationError(f"unknown kind: {value}")
    return kind


def _live_predicate(now_ts: datetime) -> ColumnElement[bool]:
    return and_(
        BlogPost.kind == "event",
        BlogPost.event_starts_at <= now_ts,
        BlogPost.event_ends_at >= now_ts,
    )


def _to_item(
    post: BlogPost,
    translation: BlogPostTranslation,
    brand_slug: str,
    brand_name: str,
) -> PostListItemOut:
    return PostListItemOut(
        id=post.id,
        slug=translation.slug,
        kind=_as_kind(post.kind),
        title=translation.title,
        excerpt=translation.excerpt,
        cover_image_url=post.cover_image_url,
        published_at=post.published_at,
        updated_at=post.updated_at,
        primary_brand=BrandRefOut(slug=brand_slug, name=brand_name),
        event_starts_at=post.event_starts_at,
        event_ends_at=post.event_ends_at,
        pin_on_brand=post.pin_on_brand,
        like_count=post.like_count,
        view_count=post.view_count,
    )


async def list_published(
    db: AsyncSession,
    *,
    locale: Locale,
    brand: str | None = None,
    kind: PostKind | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> PostListOut:
    """Published translations for ``locale``, live events first, then newest."""
    limit = max(1, min(limit, _MAX_LIST))
    now_ts = now()
    live_rank = case((_live_predicate(now_ts), 0), else_=1)
    stmt = (
        select(BlogPost, BlogPostTranslation, Brand, BrandTranslation)
        .join(BlogPostTranslation, BlogPostTranslation.post_id == BlogPost.id)
        .join(Brand, Brand.id == BlogPost.primary_brand_id)
        .outerjoin(
            BrandTranslation,
            and_(BrandTranslation.brand_id == Brand.id, BrandTranslation.locale == locale),
        )
        .where(BlogPost.status == "published", BlogPostTranslation.locale == locale)
        .order_by(live_rank.asc(), BlogPost.published_at.desc(), BlogPost.id.desc())
        .limit(limit + 1)
    )
    if brand is not None:
        stmt = stmt.where(Brand.slug == brand)
    if kind is not None:
        stmt = stmt.where(BlogPost.kind == kind)
    if cursor is not None:
        c_rank, c_published, c_id = _decode_cursor(cursor)
        stmt = stmt.where(
            (live_rank > c_rank)
            | ((live_rank == c_rank) & (BlogPost.published_at < c_published))
            | (
                (live_rank == c_rank)
                & (BlogPost.published_at == c_published)
                & (BlogPost.id < c_id)
            )
        )
    rows = (await db.execute(stmt)).all()
    has_more = len(rows) > limit
    page = rows[:limit]
    items = [
        _to_item(
            post, tr, brand_row.slug, brand_tr.name if brand_tr is not None else brand_row.slug
        )
        for post, tr, brand_row, brand_tr in page
    ]
    next_cursor: str | None = None
    if has_more and page:
        last_post = page[-1][0]
        last_rank = 0 if _is_live(last_post, now_ts) else 1
        if last_post.published_at is not None:
            next_cursor = _encode_cursor(last_rank, last_post.published_at, last_post.id)
    return PostListOut(items=items, next_cursor=next_cursor)


def _is_live(post: BlogPost, now_ts: datetime) -> bool:
    return (
        post.kind == "event"
        and post.event_starts_at is not None
        and post.event_ends_at is not None
        and post.event_starts_at <= now_ts <= post.event_ends_at
    )


async def get_published_by_slug(db: AsyncSession, *, slug: str, locale: Locale) -> PostDetailOut:
    """Return one published translation or raise :class:`NotFoundError`."""
    row = (
        await db.execute(
            select(BlogPost, BlogPostTranslation, Brand, BrandTranslation)
            .join(BlogPostTranslation, BlogPostTranslation.post_id == BlogPost.id)
            .join(Brand, Brand.id == BlogPost.primary_brand_id)
            .outerjoin(
                BrandTranslation,
                and_(BrandTranslation.brand_id == Brand.id, BrandTranslation.locale == locale),
            )
            .where(
                BlogPost.status == "published",
                BlogPostTranslation.locale == locale,
                BlogPostTranslation.slug == slug,
            )
            .options(selectinload(BlogPost.faqs), selectinload(BlogPost.extra_brands))
        )
    ).first()
    if row is None:
        raise NotFoundError("post not found")
    post, tr, brand_row, brand_tr = row
    related_ids = [link.brand_id for link in post.extra_brands]
    related_slugs = await _brand_slugs(db, related_ids)
    faqs = [FaqOut.model_validate(faq) for faq in post.faqs if faq.locale == locale]
    item = _to_item(
        post, tr, brand_row.slug, brand_tr.name if brand_tr is not None else brand_row.slug
    )
    locale_slugs = {row.locale: row.slug for row in post.translations}
    return PostDetailOut(
        **item.model_dump(),
        body_html=tr.body_html,
        seo_title=tr.seo_title,
        seo_description=tr.seo_description,
        show_buy_card=post.show_buy_card,
        related_brand_slugs=related_slugs,
        faqs=faqs,
        locale_slugs=locale_slugs,
    )


async def list_by_brand(
    db: AsyncSession, *, brand_slug: str, locale: Locale, limit: int = _BRAND_BLOCK
) -> BrandBlockOut:
    """Pins first, then latest published for the brand page block."""
    brand = (await db.execute(select(Brand).where(Brand.slug == brand_slug))).scalar_one_or_none()
    if brand is None:
        raise NotFoundError("brand not found")
    limit = max(1, min(limit, _MAX_LIST))
    pins = await _brand_page(db, brand=brand, locale=locale, pinned_only=True, limit=2)
    latest = await _brand_page(db, brand=brand, locale=locale, pinned_only=False, limit=limit)
    seen = {item.slug for item in pins}
    items = pins + [item for item in latest if item.slug not in seen][:limit]
    return BrandBlockOut(items=items)


async def _brand_page(
    db: AsyncSession,
    *,
    brand: Brand,
    locale: Locale,
    pinned_only: bool,
    limit: int,
) -> list[PostListItemOut]:
    stmt = (
        select(BlogPost, BlogPostTranslation, BrandTranslation)
        .join(BlogPostTranslation, BlogPostTranslation.post_id == BlogPost.id)
        .outerjoin(
            BrandTranslation,
            and_(BrandTranslation.brand_id == brand.id, BrandTranslation.locale == locale),
        )
        .where(
            BlogPost.primary_brand_id == brand.id,
            BlogPost.status == "published",
            BlogPostTranslation.locale == locale,
        )
        .order_by(BlogPost.published_at.desc(), BlogPost.id.desc())
        .limit(limit)
    )
    if pinned_only:
        stmt = stmt.where(BlogPost.pin_on_brand.is_(True))
    rows = (await db.execute(stmt)).all()
    return [
        _to_item(post, tr, brand.slug, brand_tr.name if brand_tr is not None else brand.slug)
        for post, tr, brand_tr in rows
    ]


async def _brand_slugs(db: AsyncSession, brand_ids: list[str]) -> list[str]:
    if not brand_ids:
        return []
    rows = (await db.execute(select(Brand.slug).where(Brand.id.in_(brand_ids)))).scalars().all()
    return list(rows)


__all__ = ["get_published_by_slug", "list_by_brand", "list_published"]
