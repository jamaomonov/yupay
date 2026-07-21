"""Integration tests for the ``broadcasts`` data model.

Covers: inserting a ``Broadcast`` with ``BroadcastRecipient`` rows against the
real (testcontainers) Postgres, the ``UNIQUE(broadcast_id, user_id)`` guard on
``broadcast_recipients``, and that ``telegram_links.bot_blocked_at`` defaults
to ``NULL`` on a fresh row.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.broadcasts.models import Broadcast, BroadcastRecipient
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio


async def _make_user(db: AsyncSession) -> str:
    user_id = str(uuid.uuid4())
    db.add(User(id=user_id, roles=[]))
    await db.flush()
    return user_id


async def test_broadcast_with_recipients_round_trips(db_session: AsyncSession) -> None:
    admin_id = await _make_user(db_session)
    recipient_a = await _make_user(db_session)
    recipient_b = await _make_user(db_session)

    broadcast = Broadcast(
        id=str(uuid.uuid4()),
        title="Promo blast",
        created_by=admin_id,
    )
    broadcast.recipients = [
        BroadcastRecipient(id=str(uuid.uuid4()), user_id=recipient_a, tg_chat_id=1001),
        BroadcastRecipient(id=str(uuid.uuid4()), user_id=recipient_b, tg_chat_id=1002),
    ]
    db_session.add(broadcast)
    await db_session.commit()

    fetched = (
        await db_session.execute(select(Broadcast).where(Broadcast.id == broadcast.id))
    ).scalar_one()
    assert fetched.status == "draft"
    assert fetched.body_html == ""
    assert fetched.media_type == "none"
    assert fetched.disable_web_page_preview is True
    assert fetched.total_recipients == 0
    assert fetched.sent_count == 0
    assert fetched.failed_count == 0
    assert fetched.blocked_count == 0
    assert len(fetched.recipients) == 2
    assert {r.status for r in fetched.recipients} == {"pending"}
    assert {r.tg_chat_id for r in fetched.recipients} == {1001, 1002}


async def test_broadcast_recipients_reject_duplicate_user(db_session: AsyncSession) -> None:
    admin_id = await _make_user(db_session)
    recipient = await _make_user(db_session)

    broadcast = Broadcast(id=str(uuid.uuid4()), title="Dup check", created_by=admin_id)
    db_session.add(broadcast)
    await db_session.flush()

    db_session.add(
        BroadcastRecipient(
            id=str(uuid.uuid4()),
            broadcast_id=broadcast.id,
            user_id=recipient,
            tg_chat_id=2001,
        )
    )
    await db_session.flush()

    db_session.add(
        BroadcastRecipient(
            id=str(uuid.uuid4()),
            broadcast_id=broadcast.id,
            user_id=recipient,
            tg_chat_id=2001,
        )
    )
    with pytest.raises(IntegrityError):
        # SAVEPOINT: the failed flush aborts only this nested transaction,
        # leaving db_session usable for the rest of the test.
        async with db_session.begin_nested():
            await db_session.flush()


async def test_telegram_link_bot_blocked_at_defaults_to_null(db_session: AsyncSession) -> None:
    user_id = await _make_user(db_session)
    link = TelegramLink(id=str(uuid.uuid4()), user_id=user_id, tg_user_id=999_000_111)
    db_session.add(link)
    await db_session.commit()

    fetched = (
        await db_session.execute(select(TelegramLink).where(TelegramLink.id == link.id))
    ).scalar_one()
    assert fetched.bot_blocked_at is None
