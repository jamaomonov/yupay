"""Public anonymous GETs plus guest like/view writes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.config import get_settings
from yupay.core.errors import ValidationError
from yupay.core.idempotency import (
    IDEMPOTENCY_HEADER,
    MIN_IDEMPOTENCY_KEY_LENGTH,
    load_replay,
    save_replay,
)
from yupay.modules.auth.ip_guard import guard_ip
from yupay.modules.blog import engagement as eng
from yupay.modules.blog import service as svc
from yupay.modules.blog.deps import resolve_locale
from yupay.modules.blog.schemas import (
    BrandBlockOut,
    EngagementOut,
    Locale,
    PostDetailOut,
    PostKind,
    PostListOut,
)

router = APIRouter(prefix="/blog", tags=["blog"])


def _require_idempotency_key(idempotency_key: str | None) -> str:
    if not idempotency_key or len(idempotency_key) < MIN_IDEMPOTENCY_KEY_LENGTH:
        raise ValidationError(
            f"Idempotency-Key header is required (>={MIN_IDEMPOTENCY_KEY_LENGTH} chars)",
            extra={"header": IDEMPOTENCY_HEADER},
        )
    return idempotency_key


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


async def _guard(request: Request) -> None:
    """Per-IP ceiling on anonymous likes and views.

    A reader is whoever holds a cookie, and a request without one is minted a
    fresh reader, so the counts were as inflatable as a loop is fast — and
    each request also wrote an ``idempotent_responses`` row. The coarse
    600/min tier was the only bound. This one is per IP, generous enough for a
    carrier NAT full of real readers (``blog-engagement`` bucket).
    """
    await guard_ip(request, bucket="blog-engagement")


@router.post("/{slug}/view", response_model=EngagementOut, summary="Record a unique view")
async def record_view(
    slug: str,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
    locale: Annotated[Locale, Depends(resolve_locale)],
    reader: Annotated[str | None, Cookie(alias=eng.READER_COOKIE)] = None,
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> EngagementOut:
    """Anonymous. First view per reader cookie increments; repeats do not."""
    key = _require_idempotency_key(idempotency_key)
    await _guard(request)
    replay = await load_replay(db, scope="blog.view", idempotency_key=key)
    if replay is not None and replay.body is not None:
        return EngagementOut.model_validate(replay.body)
    raw, digest, minted = eng.resolve_reader(reader)
    if minted:
        eng.set_reader_cookie(response, value=raw, settings=get_settings())
    out = await eng.record_view(db, slug=slug, locale=locale, reader_hash=digest)
    await save_replay(db, scope="blog.view", idempotency_key=key, body=out.model_dump())
    return out


@router.post("/{slug}/like", response_model=EngagementOut, summary="Like a published post")
async def like_post(
    slug: str,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
    locale: Annotated[Locale, Depends(resolve_locale)],
    reader: Annotated[str | None, Cookie(alias=eng.READER_COOKIE)] = None,
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> EngagementOut:
    """Anonymous. Guests get a reader cookie. Repeat like is a no-op."""
    key = _require_idempotency_key(idempotency_key)
    await _guard(request)
    replay = await load_replay(db, scope="blog.like", idempotency_key=key)
    if replay is not None and replay.body is not None:
        return EngagementOut.model_validate(replay.body)
    raw, digest, minted = eng.resolve_reader(reader)
    if minted:
        eng.set_reader_cookie(response, value=raw, settings=get_settings())
    out = await eng.set_like(db, slug=slug, locale=locale, reader_hash=digest, liked=True)
    await save_replay(db, scope="blog.like", idempotency_key=key, body=out.model_dump())
    return out


@router.delete("/{slug}/like", response_model=EngagementOut, summary="Unlike a published post")
async def unlike_post(
    slug: str,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
    locale: Annotated[Locale, Depends(resolve_locale)],
    reader: Annotated[str | None, Cookie(alias=eng.READER_COOKIE)] = None,
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> EngagementOut:
    """Anonymous. Unlike without a prior like is a no-op."""
    key = _require_idempotency_key(idempotency_key)
    await _guard(request)
    replay = await load_replay(db, scope="blog.unlike", idempotency_key=key)
    if replay is not None and replay.body is not None:
        return EngagementOut.model_validate(replay.body)
    raw, digest, minted = eng.resolve_reader(reader)
    if minted:
        eng.set_reader_cookie(response, value=raw, settings=get_settings())
    out = await eng.set_like(db, slug=slug, locale=locale, reader_hash=digest, liked=False)
    await save_replay(db, scope="blog.unlike", idempotency_key=key, body=out.model_dump())
    return out


@router.get("/{slug}", response_model=PostDetailOut, summary="Get one published post")
async def get_post(
    slug: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    locale: Annotated[Locale, Depends(resolve_locale)],
) -> PostDetailOut:
    """404 when the post is unpublished or the locale row is missing."""
    return await svc.get_published_by_slug(db, slug=slug, locale=locale)
