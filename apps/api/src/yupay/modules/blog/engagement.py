"""Anonymous likes and unique views keyed by a first-party cookie, not an IP."""

from __future__ import annotations

import hashlib
import secrets

from fastapi import Response
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.config import Settings
from yupay.core.errors import NotFoundError
from yupay.modules.auth.cookies import cookie_domain
from yupay.modules.blog.models import BlogPost, BlogPostLike, BlogPostTranslation, BlogPostView
from yupay.modules.blog.schemas import EngagementOut, Locale

READER_COOKIE = "yp_blog_reader"
_READER_HEX_LEN = 64
_READER_MAX_AGE = 400 * 24 * 60 * 60


def hash_reader(raw: str) -> str:
    """SHA-256 hex of the cookie. The raw value is never stored."""
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def resolve_reader(raw: str | None) -> tuple[str, str, bool]:
    """Return ``(cookie, hash, minted)``. Garbage cookies are replaced."""
    if raw is not None and len(raw) == _READER_HEX_LEN and raw.isalnum():
        return raw, hash_reader(raw), False
    minted = secrets.token_hex(32)
    return minted, hash_reader(minted), True


def set_reader_cookie(response: Response, *, value: str, settings: Settings) -> None:
    """Attach the reader cookie. Same domain rules as the refresh cookie."""
    response.set_cookie(
        key=READER_COOKIE,
        value=value,
        max_age=_READER_MAX_AGE,
        path="/",
        httponly=True,
        secure=settings.is_prod,
        samesite="lax",
        domain=cookie_domain(settings),
    )


async def _published(db: AsyncSession, *, slug: str, locale: Locale) -> BlogPost:
    post = (
        await db.execute(
            select(BlogPost)
            .join(BlogPostTranslation, BlogPostTranslation.post_id == BlogPost.id)
            .where(
                BlogPost.status == "published",
                BlogPostTranslation.locale == locale,
                BlogPostTranslation.slug == slug,
            )
        )
    ).scalar_one_or_none()
    if post is None:
        raise NotFoundError("post not found")
    return post


async def _liked(db: AsyncSession, *, post_id: str, reader_hash: str) -> bool:
    hit = (
        await db.execute(
            select(BlogPostLike.post_id).where(
                BlogPostLike.post_id == post_id,
                BlogPostLike.reader_hash == reader_hash,
            )
        )
    ).scalar_one_or_none()
    return hit is not None


async def snapshot(db: AsyncSession, *, post: BlogPost, reader_hash: str) -> EngagementOut:
    """Current counters plus whether this reader already liked."""
    return EngagementOut(
        liked=await _liked(db, post_id=post.id, reader_hash=reader_hash),
        like_count=post.like_count,
        view_count=post.view_count,
    )


async def record_view(
    db: AsyncSession, *, slug: str, locale: Locale, reader_hash: str
) -> EngagementOut:
    """Count the first view from this reader. Repeats are a no-op."""
    post = await _published(db, slug=slug, locale=locale)
    result = await db.execute(
        insert(BlogPostView)
        .values(post_id=post.id, reader_hash=reader_hash)
        .on_conflict_do_nothing(index_elements=["post_id", "reader_hash"])
    )
    if result.rowcount:  # type: ignore[attr-defined]
        post.view_count = post.view_count + 1
        await db.flush()
    return await snapshot(db, post=post, reader_hash=reader_hash)


async def set_like(
    db: AsyncSession, *, slug: str, locale: Locale, reader_hash: str, liked: bool
) -> EngagementOut:
    """Like or unlike. Repeating the same state is a no-op."""
    post = await _published(db, slug=slug, locale=locale)
    if liked:
        result = await db.execute(
            insert(BlogPostLike)
            .values(post_id=post.id, reader_hash=reader_hash)
            .on_conflict_do_nothing(index_elements=["post_id", "reader_hash"])
        )
        if result.rowcount:  # type: ignore[attr-defined]
            post.like_count = post.like_count + 1
            await db.flush()
    else:
        result = await db.execute(
            delete(BlogPostLike).where(
                BlogPostLike.post_id == post.id,
                BlogPostLike.reader_hash == reader_hash,
            )
        )
        if result.rowcount:  # type: ignore[attr-defined]
            post.like_count = max(0, post.like_count - 1)
            await db.flush()
    return await snapshot(db, post=post, reader_hash=reader_hash)


__all__ = [
    "READER_COOKIE",
    "hash_reader",
    "record_view",
    "resolve_reader",
    "set_like",
    "set_reader_cookie",
    "snapshot",
]
