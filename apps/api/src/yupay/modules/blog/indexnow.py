"""IndexNow outbox for published and archived blog URLs.

Enqueue rides the caller's transaction (same shape as merchant webhooks).
The worker POSTs to ``api.indexnow.org`` only in ``ENVIRONMENT=prod``;
everywhere else the row is marked ``skipped`` so the queue stays dry and
we never ping Bing/Yandex with localhost URLs. A failed ping does not
roll back publish or archive — IndexNow is a courtesy, ``make indexnow``
is the fallback.
"""

from __future__ import annotations

from typing import Final

import httpx
from sqlalchemy import select, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.blog.models import BlogIndexNowPing, BlogPost

log = get_logger("yupay.blog.indexnow")

INDEXNOW_QUEUE_CHANNEL: Final = "blog_indexnow_queue"
INDEXNOW_ORIGIN: Final = "https://yupay.uz"
INDEXNOW_HOST: Final = "yupay.uz"
INDEXNOW_KEY: Final = "f9c74a83b42e048f6273ce96100f14dd"
INDEXNOW_ENDPOINT: Final = "https://api.indexnow.org/indexnow"
_TIMEOUT: Final = 5.0
DEFAULT_LIMIT: Final = 20
_OK = frozenset({200, 202})


class IndexNowRejectedError(Exception):
    """IndexNow answered something other than 200/202. Status only, no body."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"http {status_code}")


def locale_prefix(locale: str) -> str:
    """Root-relative locale prefix. ``ru`` is the default and has none."""
    return "" if locale == "ru" else f"/{locale}"


def public_urls(post: BlogPost) -> list[str]:
    """Production article + index URLs for every translation on the post."""
    seen: set[str] = set()
    out: list[str] = []
    for row in post.translations:
        prefix = locale_prefix(row.locale)
        for path in (f"{prefix}/blog/{row.slug}", f"{prefix}/blog"):
            url = f"{INDEXNOW_ORIGIN}{path}"
            if url not in seen:
                seen.add(url)
                out.append(url)
    return out


async def enqueue(db: AsyncSession, post: BlogPost, *, reason: str) -> str | None:
    """Queue one ping in the caller's transaction. Never raises to the caller.

    Args:
        db: Session. The caller owns the transaction.
        post: Loaded post with translations.
        reason: ``published`` or ``archived``.

    Returns:
        The new row id, or ``None`` when there is nothing to submit or the
        insert was swallowed so publish/archive still commits.
    """
    urls = public_urls(post)
    if not urls:
        return None
    await db.flush()
    ping_id = new_id()
    try:
        async with db.begin_nested():
            db.add(
                BlogIndexNowPing(
                    id=ping_id,
                    post_id=post.id,
                    reason=reason,
                    urls=urls,
                )
            )
            await db.flush()
            await db.execute(
                text("SELECT pg_notify(:channel, :id)"),
                {"channel": INDEXNOW_QUEUE_CHANNEL, "id": ping_id},
            )
    except (IntegrityError, DataError):
        log.exception("blog.indexnow.enqueue_failed", post_id=post.id, reason=reason)
        return None
    return ping_id


async def drain_pending_pings(
    db: AsyncSession,
    *,
    limit: int = DEFAULT_LIMIT,
    live: bool | None = None,
) -> int:
    """Claim pending pings and POST them, or skip outside prod.

    Args:
        db: Session. The caller owns the transaction.
        limit: Rows to claim in this batch.
        live: When set, overrides ``ENVIRONMENT=prod``. Tests pass this;
            the worker leaves it unset.

    Returns:
        How many rows this batch claimed. ``0`` means the queue is dry.
    """
    if live is None:
        live = get_settings().environment == "prod"
    ids = await _claim(db, limit=limit)
    for ping_id in ids:
        try:
            async with db.begin_nested():
                await _attempt(db, ping_id=ping_id, live=live)
        except Exception:
            log.exception("blog.indexnow.attempt_failed", ping_id=ping_id)
            await _finish(db, ping_id, status="failed", error="crash")
    await db.flush()
    return len(ids)


async def _claim(db: AsyncSession, *, limit: int) -> list[str]:
    rows = (
        await db.execute(
            select(BlogIndexNowPing.id)
            .where(BlogIndexNowPing.status == "pending")
            .order_by(BlogIndexNowPing.created_at, BlogIndexNowPing.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).scalars()
    return list(rows)


async def _attempt(db: AsyncSession, *, ping_id: str, live: bool) -> None:
    ping = await db.get(BlogIndexNowPing, ping_id)
    if ping is None or ping.status != "pending":
        return
    if not live:
        await _finish(db, ping_id, status="skipped")
        return
    try:
        await post_indexnow(ping.urls)
    except IndexNowRejectedError as exc:
        await _finish(db, ping_id, status="failed", error=str(exc))
        return
    except httpx.HTTPError as exc:
        await _finish(db, ping_id, status="failed", error=type(exc).__name__)
        return
    await _finish(db, ping_id, status="done")


async def _finish(db: AsyncSession, ping_id: str, *, status: str, error: str | None = None) -> None:
    ping = await db.get(BlogIndexNowPing, ping_id)
    if ping is None:
        return
    ping.status = status
    ping.last_error = error
    ping.finished_at = now()
    log.info(
        "blog.indexnow.finished",
        ping_id=ping_id,
        status=status,
        reason=ping.reason,
        urls=len(ping.urls),
    )


async def post_indexnow(urls: list[str]) -> None:
    """POST ``urls`` to IndexNow. Raises :class:`IndexNowRejectedError` on 4xx/5xx."""
    payload = {
        "host": INDEXNOW_HOST,
        "key": INDEXNOW_KEY,
        "keyLocation": f"{INDEXNOW_ORIGIN}/{INDEXNOW_KEY}.txt",
        "urlList": urls,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
        res = await client.post(INDEXNOW_ENDPOINT, json=payload)
    if res.status_code not in _OK:
        raise IndexNowRejectedError(res.status_code)


__all__ = [
    "DEFAULT_LIMIT",
    "INDEXNOW_ENDPOINT",
    "INDEXNOW_QUEUE_CHANNEL",
    "IndexNowRejectedError",
    "drain_pending_pings",
    "enqueue",
    "locale_prefix",
    "post_indexnow",
    "public_urls",
]
