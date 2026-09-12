"""Flip due ``scheduled`` blog posts to ``published``.

The column exists since migration 0075; the admin ``/schedule`` button only
stamps ``scheduled_for``. This job is the other half: it reuses
``admin_service.publish_post`` so pin-cap and sanitize stay one path.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from yupay.core.clock import now
from yupay.core.db import get_session_factory
from yupay.core.errors import ConflictError
from yupay.core.logging import get_logger
from yupay.modules.blog.admin_service import publish_post
from yupay.modules.blog.models import BlogPost

log = get_logger("yupay.scheduler.blog_publish_due")

_JOB_ID = "blog.publish_due"
_INTERVAL_SECONDS = 60


async def run_publish_due() -> None:
    """Publish every post whose ``scheduled_for`` has elapsed.

    Each post gets its own session so a sanitize/pin-cap refusal cannot
    roll back a neighbour that was ready.
    """
    factory = get_session_factory()
    async with factory() as session:
        ids = list(
            (
                await session.execute(
                    select(BlogPost.id).where(
                        BlogPost.status == "scheduled",
                        BlogPost.scheduled_for.is_not(None),
                        BlogPost.scheduled_for <= now(),
                    )
                )
            ).scalars()
        )
    for post_id in ids:
        async with factory() as session, session.begin():
            try:
                await publish_post(session, post_id)
            except ConflictError:
                log.info("blog.publish_due.skipped", post_id=post_id)
            except Exception:
                log.exception("blog.publish_due.failed", post_id=post_id)


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job. Safe to call once at startup."""
    scheduler.add_job(
        run_publish_due,
        trigger="interval",
        seconds=_INTERVAL_SECONDS,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    log.info("blog.publish_due.registered", interval_seconds=_INTERVAL_SECONDS)


__all__ = ["register", "run_publish_due"]
