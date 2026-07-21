"""Integration test for the bot's ``/start`` → clear ``bot_blocked_at`` path.

``yupay_bot.main._clear_bot_blocked`` resolves its own session via
``get_session_factory()`` (the bot has no request-scoped session, same as the
scheduler jobs) — so, exactly like ``test_broadcast_dispatch.py`` does for
``yupay_scheduler.jobs.broadcast_dispatch``, ``_bot_session_factory`` below
redirects that call at the *bot module* to the truncated testcontainer
Postgres. ``apps/bot/tests`` has no testcontainers fixture of its own, so the
real-DB assertion lives here; the handler-wiring behaviour (that ``/start``
calls this function with the sender's id) is covered by
``apps/bot/tests/test_start_unblocks.py``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.users.models import TelegramLink, User
from yupay_bot import main as bot_main

pytestmark = pytest.mark.asyncio

# ``populate_existing`` forces the assertion session to re-read the row the
# function wrote from its own (separate) session rather than serving stale
# identity-map state.
_FRESH = {"populate_existing": True}


@pytest.fixture(autouse=True)
def _bot_session_factory(monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(bot_main, "get_session_factory", lambda: factory)


async def _seed_linked_user(db: AsyncSession, *, tg_id: int, blocked: bool) -> TelegramLink:
    user = User(id=new_id(), locale="ru", roles=[])
    db.add(user)
    await db.flush()
    link = TelegramLink(
        id=new_id(),
        user_id=user.id,
        tg_user_id=tg_id,
        bot_blocked_at=(now() if blocked else None),
    )
    db.add(link)
    await db.commit()
    return link


async def test_clear_bot_blocked_nulls_a_blocked_link(db_session: AsyncSession) -> None:
    link = await _seed_linked_user(db_session, tg_id=111222333, blocked=True)
    assert link.bot_blocked_at is not None

    await bot_main._clear_bot_blocked(111222333)

    refreshed = (
        await db_session.execute(
            select(TelegramLink).where(TelegramLink.id == link.id).execution_options(**_FRESH)
        )
    ).scalar_one()
    assert refreshed.bot_blocked_at is None


async def test_clear_bot_blocked_is_a_noop_when_already_unblocked(
    db_session: AsyncSession,
) -> None:
    link = await _seed_linked_user(db_session, tg_id=444555666, blocked=False)

    await bot_main._clear_bot_blocked(444555666)

    refreshed = (
        await db_session.execute(
            select(TelegramLink).where(TelegramLink.id == link.id).execution_options(**_FRESH)
        )
    ).scalar_one()
    assert refreshed.bot_blocked_at is None


async def test_clear_bot_blocked_is_a_noop_for_unknown_tg_id(db_session: AsyncSession) -> None:
    """No ``telegram_links`` row for this Telegram id — the ``UPDATE`` simply
    matches zero rows; must not raise."""
    await bot_main._clear_bot_blocked(999888777)
