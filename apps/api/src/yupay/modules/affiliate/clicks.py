"""Counting visits to partner links (``yupay.uz/?ref=CODE``).

The storefront calls :func:`record_click` from a browser beacon when a page opens with
``?ref=``. One row per ``(code, visitor, day)`` — a reload, a second tab or a replayed
request on the same day changes nothing (``UNIQUE`` in the database, ``ON CONFLICT DO
NOTHING`` here). So a "click" is a visitor-day, and "visitors" is the distinct visitor
over a window.

The visitor is a random id the storefront keeps in local storage, stored only as its
SHA-256: no IP, no user agent, nothing that names a person. Crawlers request the link but
run no JavaScript, so they never reach this — on MOKI's link Googlebot was 13 of 31 hits
in the proxy log (2026-10-09).

An unknown, inactive or suspended code records nothing and says nothing: the endpoint is
public, and answering "no such code" would make it a free code-guessing oracle.
"""

from __future__ import annotations

import hashlib
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.affiliate.discount import normalise
from yupay.modules.affiliate.models import AffiliateClick, AffiliateCode, AffiliatePartner

_MAX_PATH = 255


def visitor_hash(visitor_id: str) -> str:
    """SHA-256 hex of the storefront's random visitor id."""
    return hashlib.sha256(visitor_id.strip().encode()).hexdigest()


def clean_path(path: str | None) -> str:
    """The landing path without its query string or fragment, at most 255 chars."""
    raw = (path or "/").split("?", 1)[0].split("#", 1)[0].strip() or "/"
    if not raw.startswith("/"):
        raw = "/" + raw
    return raw[:_MAX_PATH]


async def record_click(
    db: AsyncSession, *, code: str, visitor_id: str, path: str | None = None
) -> bool:
    """Record one visitor-day on a partner link.

    Args:
        db: Session; the caller commits.
        code: The ``ref`` value as it arrived, any case.
        visitor_id: The storefront's random visitor id.
        path: The page the link opened.

    Returns:
        ``True`` if a new visitor-day was written, ``False`` for a repeat or for a code
        that does not count (unknown, inactive, partner not active).
    """
    row = (
        await db.execute(
            select(AffiliateCode.id, AffiliateCode.partner_id)
            .join(AffiliatePartner, AffiliatePartner.id == AffiliateCode.partner_id)
            .where(
                AffiliateCode.code == normalise(code),
                AffiliateCode.active.is_(True),
                AffiliatePartner.status == "active",
            )
        )
    ).first()
    if row is None:
        return False
    code_id, partner_id = row
    result = await db.execute(
        pg_insert(AffiliateClick)
        .values(
            id=new_id(),
            code_id=code_id,
            partner_id=partner_id,
            visitor_hash=visitor_hash(visitor_id),
            day=now().astimezone(UTC).date(),
            landing_path=clean_path(path),
        )
        .on_conflict_do_nothing(constraint="uq_affiliate_clicks_visit")
    )
    # ``rowcount`` lives on CursorResult; async ``execute`` is typed as Result.
    return bool(getattr(result, "rowcount", 0))


__all__ = ["clean_path", "record_click", "visitor_hash"]
