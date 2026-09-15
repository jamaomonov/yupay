"""Admin writes for editorial posts: CRUD plus publish / archive / schedule."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.errors import ConflictError, NotFoundError, ValidationError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.blog.admin_schemas import (
    AdminPostOut,
    FaqIn,
    PostCreate,
    PostUpdate,
    TranslationIn,
    TranslationOut,
)
from yupay.modules.blog.indexnow import enqueue as enqueue_indexnow
from yupay.modules.blog.models import BlogPost, BlogPostBrand, BlogPostFaq, BlogPostTranslation
from yupay.modules.blog.sanitize import assert_hosted_media, sanitize_body
from yupay.modules.blog.schemas import FaqOut, PostStatus
from yupay.modules.catalog.models import Brand

log = get_logger("yupay.blog.admin")

_PIN_CAP = 2
_EDITABLE: frozenset[str] = frozenset({"draft", "scheduled"})
_PUBLISHABLE: frozenset[str] = frozenset({"draft", "scheduled", "archived"})


def _media_base() -> str:
    return get_settings().r2_public_base_url.rstrip("/")


def serialize_admin(post: BlogPost) -> AdminPostOut:
    """Shape a loaded post (with collections) as the admin response."""
    return AdminPostOut.model_validate(
        {
            "id": post.id,
            "kind": post.kind,
            "status": post.status,
            "primary_brand_id": post.primary_brand_id,
            "show_buy_card": post.show_buy_card,
            "pin_on_brand": post.pin_on_brand,
            "cover_image_url": post.cover_image_url,
            "event_starts_at": post.event_starts_at,
            "event_ends_at": post.event_ends_at,
            "published_at": post.published_at,
            "scheduled_for": post.scheduled_for,
            "created_at": post.created_at,
            "updated_at": post.updated_at,
            "translations": [TranslationOut.model_validate(row) for row in post.translations],
            "related_brand_ids": [link.brand_id for link in post.extra_brands],
            "faqs": [FaqOut.model_validate(row) for row in post.faqs],
        }
    )


_POST_LOAD = (
    selectinload(BlogPost.translations),
    selectinload(BlogPost.extra_brands),
    selectinload(BlogPost.faqs),
)


async def get_post(db: AsyncSession, post_id: str) -> BlogPost:
    """Load one post with translations, extra brands and FAQs."""
    row = (
        await db.execute(select(BlogPost).options(*_POST_LOAD).where(BlogPost.id == post_id))
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("post not found")
    return row


async def list_posts(
    db: AsyncSession,
    *,
    status_filter: PostStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[BlogPost], int]:
    """Offset page for the admin list. ``selectinload`` keeps this off the N+1 path."""
    filters = []
    if status_filter is not None:
        filters.append(BlogPost.status == status_filter)
    total = int(
        (await db.execute(select(func.count()).select_from(BlogPost).where(*filters))).scalar_one()
    )
    stmt = (
        select(BlogPost)
        .options(*_POST_LOAD)
        .where(*filters)
        .order_by(BlogPost.updated_at.desc(), BlogPost.id.desc())
        .limit(max(1, min(limit, 200)))
        .offset(max(0, offset))
    )
    rows = list((await db.execute(stmt)).scalars().unique().all())
    return rows, total


async def create_post(db: AsyncSession, body: PostCreate) -> BlogPost:
    """Insert a draft (or a scheduled-ready row still in ``draft``)."""
    if body.primary_brand_id is not None:
        await _require_brand(db, body.primary_brand_id)
    _require_event_window(body.kind, body.event_starts_at, body.event_ends_at)
    cover = _cover(body.cover_image_url)
    post = BlogPost(
        id=new_id(),
        kind=body.kind,
        status="draft",
        primary_brand_id=body.primary_brand_id,
        show_buy_card=body.show_buy_card,
        pin_on_brand=body.pin_on_brand,
        cover_image_url=cover,
        event_starts_at=body.event_starts_at,
        event_ends_at=body.event_ends_at,
        translations=_translations(body.translations, allow_empty=True),
        extra_brands=await _extra_brands(db, body.primary_brand_id, body.related_brand_ids),
        faqs=_faqs(body.faqs),
    )
    db.add(post)
    await _flush_slug(db)
    log.info("blog.post_created", post_id=post.id, kind=post.kind, status=post.status)
    return post


async def update_post(db: AsyncSession, post_id: str, body: PostUpdate) -> BlogPost:
    """Patch fields; a provided ``translations`` array replaces the set."""
    post = await get_post(db, post_id)
    _patch_scalars(post, body)
    # ``None`` in the body means "clear the brand", which is only reachable
    # while the post is a draft; omitting the key means "leave it alone".
    # Without the ``model_fields_set`` check the form could not take a brand
    # back off a draft at all — it would silently keep the old one.
    if "primary_brand_id" in body.model_fields_set:
        if body.primary_brand_id is not None:
            await _require_brand(db, body.primary_brand_id)
        post.primary_brand_id = body.primary_brand_id
    _require_event_window(post.kind, post.event_starts_at, post.event_ends_at)
    if post.status == "published" and post.pin_on_brand and post.primary_brand_id is not None:
        await _ensure_pin_cap(db, post.primary_brand_id, excluding_id=post.id)
    if body.translations is not None:
        post.translations.clear()
        await db.flush()
        post.translations = _translations(body.translations, allow_empty=True)
    if body.related_brand_ids is not None:
        post.extra_brands = await _extra_brands(db, post.primary_brand_id, body.related_brand_ids)
    if body.faqs is not None:
        await _replace_faqs(db, post, body.faqs)
    post.updated_at = now()
    await _flush_slug(db)
    log.info("blog.post_updated", post_id=post.id, kind=post.kind, status=post.status)
    return post


def _patch_scalars(post: BlogPost, body: PostUpdate) -> None:
    """Apply the plain "omitted means unchanged" fields, in place."""
    if body.kind is not None:
        post.kind = body.kind
        if body.kind != "event":
            post.event_starts_at = None
            post.event_ends_at = None
    if body.show_buy_card is not None:
        post.show_buy_card = body.show_buy_card
    if body.pin_on_brand is not None:
        post.pin_on_brand = body.pin_on_brand
    if body.cover_image_url is not None:
        post.cover_image_url = _cover(body.cover_image_url) if body.cover_image_url else None
    if body.event_starts_at is not None:
        post.event_starts_at = body.event_starts_at
    if body.event_ends_at is not None:
        post.event_ends_at = body.event_ends_at


async def publish_post(db: AsyncSession, post_id: str) -> BlogPost:
    """First publish stamps ``published_at``; later publishes keep it."""
    post = await get_post(db, post_id)
    if post.status == "published":
        raise ConflictError("post is already published")
    if post.status not in _PUBLISHABLE:
        raise ConflictError("only a draft, scheduled or archived post can be published")
    _require_event_window(post.kind, post.event_starts_at, post.event_ends_at)
    if not post.translations:
        raise ValidationError("publish requires at least one translation")
    if post.primary_brand_id is None:
        # The CHECK on ``blog_posts`` says the same thing; saying it here
        # turns a 500 from Postgres into the sentence the editor needs.
        raise ValidationError("publish requires a primary brand")
    for row in post.translations:
        row.body_html = sanitize_body(
            row.body_html, media_base_url=_media_base(), allow_empty=False
        )
    if post.pin_on_brand:
        await _ensure_pin_cap(db, post.primary_brand_id, excluding_id=post.id)
    if post.published_at is None:
        post.published_at = now()
    post.status = "published"
    post.updated_at = now()
    await db.flush()
    await enqueue_indexnow(db, post, reason="published")
    log.info("blog.post_published", post_id=post.id, kind=post.kind, status=post.status)
    return post


async def archive_post(db: AsyncSession, post_id: str) -> BlogPost:
    """Soft-archive. ``published_at`` stays so an indexed URL can still be explained."""
    post = await get_post(db, post_id)
    if post.status == "archived":
        raise ConflictError("post is already archived")
    post.status = "archived"
    post.updated_at = now()
    await db.flush()
    await enqueue_indexnow(db, post, reason="archived")
    log.info("blog.post_archived", post_id=post.id, kind=post.kind, status=post.status)
    return post


async def schedule_post(db: AsyncSession, post_id: str, scheduled_for: datetime) -> BlogPost:
    """Mark a draft for the M2 scheduler. The job itself is out of M1."""
    post = await get_post(db, post_id)
    if post.status not in _EDITABLE:
        raise ConflictError("only a draft or scheduled post can be scheduled")
    if post.primary_brand_id is None:
        raise ValidationError("scheduling requires a primary brand")
    when = scheduled_for if scheduled_for.tzinfo is not None else scheduled_for.replace(tzinfo=UTC)
    if when <= now():
        raise ValidationError("scheduled_for must be in the future")
    _require_event_window(post.kind, post.event_starts_at, post.event_ends_at)
    post.status = "scheduled"
    post.scheduled_for = when
    post.updated_at = now()
    await db.flush()
    log.info("blog.post_scheduled", post_id=post.id, kind=post.kind, status=post.status)
    return post


def _cover(url: str | None) -> str | None:
    if not url:
        return None
    return assert_hosted_media(url, media_base_url=_media_base(), subject="cover")


def _require_event_window(kind: str, starts: datetime | None, ends: datetime | None) -> None:
    if kind != "event":
        if starts is not None or ends is not None:
            raise ValidationError("event dates are only valid when kind=event")
        return
    if starts is None or ends is None:
        raise ValidationError("event posts require event_starts_at and event_ends_at")
    if ends <= starts:
        raise ValidationError("event_ends_at must be after event_starts_at")


def _translations(rows: list[TranslationIn], *, allow_empty: bool) -> list[BlogPostTranslation]:
    seen: set[str] = set()
    out: list[BlogPostTranslation] = []
    media = _media_base()
    for row in rows:
        if row.locale in seen:
            raise ValidationError(f"duplicate translation locale: {row.locale}")
        seen.add(row.locale)
        out.append(
            BlogPostTranslation(
                locale=row.locale,
                slug=row.slug,
                title=row.title,
                excerpt=row.excerpt,
                body_html=sanitize_body(
                    row.body_html, media_base_url=media, allow_empty=allow_empty
                ),
                seo_title=row.seo_title,
                seo_description=row.seo_description,
            )
        )
    return out


async def _replace_faqs(db: AsyncSession, post: BlogPost, rows: list[FaqIn]) -> None:
    """Swap FAQ rows. New ids + the same sort_order would 409 without a flush."""
    post.faqs.clear()
    await db.flush()
    post.faqs = _faqs(rows)


def _faqs(rows: list[FaqIn]) -> list[BlogPostFaq]:
    seen: set[tuple[str, int]] = set()
    out: list[BlogPostFaq] = []
    for row in rows:
        key = (row.locale, row.sort_order)
        if key in seen:
            raise ValidationError("duplicate FAQ sort_order for locale")
        seen.add(key)
        out.append(
            BlogPostFaq(
                id=new_id(),
                locale=row.locale,
                sort_order=row.sort_order,
                question=row.question,
                answer=row.answer,
            )
        )
    return out


async def _extra_brands(
    db: AsyncSession, primary_brand_id: str | None, brand_ids: list[str]
) -> list[BlogPostBrand]:
    out: list[BlogPostBrand] = []
    seen: set[str] = set()
    for brand_id in brand_ids:
        if brand_id == primary_brand_id:
            raise ValidationError("related_brand_ids must not repeat the primary brand")
        if brand_id in seen:
            continue
        seen.add(brand_id)
        await _require_brand(db, brand_id)
        out.append(BlogPostBrand(brand_id=brand_id))
    return out


async def _require_brand(db: AsyncSession, brand_id: str) -> None:
    if (await db.get(Brand, brand_id)) is None:
        raise NotFoundError("brand not found")


async def _ensure_pin_cap(db: AsyncSession, brand_id: str, *, excluding_id: str) -> None:
    count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(BlogPost)
                .where(
                    BlogPost.primary_brand_id == brand_id,
                    BlogPost.pin_on_brand.is_(True),
                    BlogPost.status == "published",
                    BlogPost.id != excluding_id,
                )
            )
        ).scalar_one()
    )
    if count >= _PIN_CAP:
        raise ValidationError("a brand may pin at most two published posts")


async def _flush_slug(db: AsyncSession) -> None:
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("slug already exists for locale") from exc


__all__ = [
    "archive_post",
    "create_post",
    "get_post",
    "list_posts",
    "publish_post",
    "schedule_post",
    "serialize_admin",
    "update_post",
]
