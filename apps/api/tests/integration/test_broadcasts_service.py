"""Integration tests for the ``broadcasts`` service against real Postgres.

Covers draft CRUD, the FSM guards on ``mark_send_now``/``schedule``/``cancel``
(including the mandatory re-validation of the stored body), and audience sizing
via ``TelegramLink ⨝ User``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.errors import ConflictError, NotFoundError, ValidationError
from yupay.modules.broadcasts import service as bc_svc
from yupay.modules.broadcasts.models import Broadcast, BroadcastRecipient
from yupay.modules.broadcasts.schemas import BroadcastCreateIn, BroadcastUpdateIn
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio


async def _make_user(db: AsyncSession, *, locale: str = "ru") -> str:
    user_id = str(uuid.uuid4())
    db.add(User(id=user_id, roles=[], locale=locale))
    await db.flush()
    return user_id


async def _link_telegram(
    db: AsyncSession, *, user_id: str, tg_user_id: int, blocked: bool = False
) -> None:
    db.add(
        TelegramLink(
            id=str(uuid.uuid4()),
            user_id=user_id,
            tg_user_id=tg_user_id,
            bot_blocked_at=datetime.now(UTC) if blocked else None,
        )
    )
    await db.flush()


def _minimal_body() -> BroadcastCreateIn:
    return BroadcastCreateIn(title="Promo blast", body_html="<b>Hello</b>")


async def _force_status(db: AsyncSession, *, broadcast_id: str, status: str) -> None:
    """Force a status the service's own FSM can't produce yet.

    Settling into ``sent``/``failed`` is the (later-task) dispatch job's job, not this
    service's — tests that need a terminal broadcast to probe the FSM guards reach past
    the service and set it directly.
    """
    await db.execute(update(Broadcast).where(Broadcast.id == broadcast_id).values(status=status))
    await db.flush()


async def test_create_draft_starts_in_draft_status(db_session: AsyncSession) -> None:
    admin_id = await _make_user(db_session)
    broadcast = await bc_svc.create_draft(db_session, actor_id=admin_id, data=_minimal_body())
    assert broadcast.status == "draft"
    assert broadcast.title == "Promo blast"
    assert broadcast.body_html == "<b>Hello</b>"
    assert broadcast.created_by == admin_id


async def test_get_missing_broadcast_raises_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await bc_svc.get(db_session, broadcast_id=str(uuid.uuid4()))


async def test_audience_count_excludes_blocked_and_filters_locale(
    db_session: AsyncSession,
) -> None:
    ru_user = await _make_user(db_session, locale="ru")
    en_user = await _make_user(db_session, locale="en")
    blocked_user = await _make_user(db_session, locale="ru")

    await _link_telegram(db_session, user_id=ru_user, tg_user_id=910_001)
    await _link_telegram(db_session, user_id=en_user, tg_user_id=910_002)
    await _link_telegram(db_session, user_id=blocked_user, tg_user_id=910_003, blocked=True)

    assert await bc_svc.audience_count(db_session, locale_filter=None) == 2
    assert await bc_svc.audience_count(db_session, locale_filter="ru") == 1
    assert await bc_svc.audience_count(db_session, locale_filter="en") == 1
    assert await bc_svc.audience_count(db_session, locale_filter="uz") == 0


async def test_mark_send_now_rejects_disallowed_tag(db_session: AsyncSession) -> None:
    admin_id = await _make_user(db_session)
    broadcast = await bc_svc.create_draft(
        db_session,
        actor_id=admin_id,
        data=BroadcastCreateIn(title="Bad", body_html="<script>alert(1)</script>"),
    )
    with pytest.raises(ValidationError):
        await bc_svc.mark_send_now(db_session, broadcast_id=broadcast.id)


async def test_mark_send_now_rejects_empty_body_without_media(db_session: AsyncSession) -> None:
    admin_id = await _make_user(db_session)
    broadcast = await bc_svc.create_draft(
        db_session,
        actor_id=admin_id,
        data=BroadcastCreateIn(title="Empty", body_html="   "),
    )
    with pytest.raises(ValidationError):
        await bc_svc.mark_send_now(db_session, broadcast_id=broadcast.id)


async def test_mark_send_now_allows_empty_body_with_media(db_session: AsyncSession) -> None:
    admin_id = await _make_user(db_session)
    broadcast = await bc_svc.create_draft(
        db_session,
        actor_id=admin_id,
        data=BroadcastCreateIn(
            title="Media only",
            body_html="",
            media_type="photo",
            media_url="https://cdn.example.com/y.jpg",
        ),
    )
    sent = await bc_svc.mark_send_now(db_session, broadcast_id=broadcast.id)
    assert sent.status == "sending"
    assert sent.scheduled_at is None


async def test_mark_send_now_conflicts_outside_draft_or_scheduled(
    db_session: AsyncSession,
) -> None:
    admin_id = await _make_user(db_session)
    broadcast = await bc_svc.create_draft(db_session, actor_id=admin_id, data=_minimal_body())
    await _force_status(db_session, broadcast_id=broadcast.id, status="sent")
    with pytest.raises(ConflictError):
        await bc_svc.mark_send_now(db_session, broadcast_id=broadcast.id)


async def test_schedule_rejects_past_time(db_session: AsyncSession) -> None:
    admin_id = await _make_user(db_session)
    broadcast = await bc_svc.create_draft(db_session, actor_id=admin_id, data=_minimal_body())
    past = datetime.now(UTC) - timedelta(minutes=1)
    with pytest.raises(ValidationError):
        await bc_svc.schedule(db_session, broadcast_id=broadcast.id, scheduled_at=past)


async def test_schedule_rejects_time_inside_the_lead_window(db_session: AsyncSession) -> None:
    admin_id = await _make_user(db_session)
    broadcast = await bc_svc.create_draft(db_session, actor_id=admin_id, data=_minimal_body())
    barely_soon = datetime.now(UTC) + timedelta(seconds=1)
    with pytest.raises(ValidationError):
        await bc_svc.schedule(db_session, broadcast_id=broadcast.id, scheduled_at=barely_soon)


async def test_schedule_rejects_bad_body_even_when_time_is_valid(
    db_session: AsyncSession,
) -> None:
    admin_id = await _make_user(db_session)
    broadcast = await bc_svc.create_draft(
        db_session,
        actor_id=admin_id,
        data=BroadcastCreateIn(title="Bad", body_html="<script>x</script>"),
    )
    future = datetime.now(UTC) + timedelta(hours=1)
    with pytest.raises(ValidationError):
        await bc_svc.schedule(db_session, broadcast_id=broadcast.id, scheduled_at=future)


async def test_schedule_success_sets_status_and_time(db_session: AsyncSession) -> None:
    admin_id = await _make_user(db_session)
    broadcast = await bc_svc.create_draft(db_session, actor_id=admin_id, data=_minimal_body())
    future = datetime.now(UTC) + timedelta(hours=1)
    scheduled = await bc_svc.schedule(db_session, broadcast_id=broadcast.id, scheduled_at=future)
    assert scheduled.status == "scheduled"
    assert scheduled.scheduled_at == future


async def test_schedule_conflicts_outside_draft_or_scheduled(db_session: AsyncSession) -> None:
    admin_id = await _make_user(db_session)
    broadcast = await bc_svc.create_draft(db_session, actor_id=admin_id, data=_minimal_body())
    await _force_status(db_session, broadcast_id=broadcast.id, status="sending")
    future = datetime.now(UTC) + timedelta(hours=1)
    with pytest.raises(ConflictError):
        await bc_svc.schedule(db_session, broadcast_id=broadcast.id, scheduled_at=future)


async def test_update_draft_on_sent_broadcast_conflicts(db_session: AsyncSession) -> None:
    admin_id = await _make_user(db_session)
    broadcast = await bc_svc.create_draft(db_session, actor_id=admin_id, data=_minimal_body())
    await _force_status(db_session, broadcast_id=broadcast.id, status="sent")
    with pytest.raises(ConflictError):
        await bc_svc.update_draft(
            db_session,
            broadcast_id=broadcast.id,
            data=BroadcastUpdateIn(title="New title", body_html="<i>hi</i>"),
        )


async def test_update_draft_on_scheduled_resets_to_draft(db_session: AsyncSession) -> None:
    admin_id = await _make_user(db_session)
    broadcast = await bc_svc.create_draft(db_session, actor_id=admin_id, data=_minimal_body())
    future = datetime.now(UTC) + timedelta(hours=1)
    await bc_svc.schedule(db_session, broadcast_id=broadcast.id, scheduled_at=future)

    updated = await bc_svc.update_draft(
        db_session,
        broadcast_id=broadcast.id,
        data=BroadcastUpdateIn(title="Edited", body_html="<i>hi</i>"),
    )
    assert updated.status == "draft"
    assert updated.scheduled_at is None
    assert updated.title == "Edited"


async def test_update_draft_on_draft_keeps_draft(db_session: AsyncSession) -> None:
    admin_id = await _make_user(db_session)
    broadcast = await bc_svc.create_draft(db_session, actor_id=admin_id, data=_minimal_body())
    updated = await bc_svc.update_draft(
        db_session,
        broadcast_id=broadcast.id,
        data=BroadcastUpdateIn(title="Edited", body_html="<i>hi</i>", locale_filter="uz"),
    )
    assert updated.status == "draft"
    assert updated.locale_filter == "uz"


async def test_delete_draft_removes_row(db_session: AsyncSession) -> None:
    admin_id = await _make_user(db_session)
    broadcast = await bc_svc.create_draft(db_session, actor_id=admin_id, data=_minimal_body())
    await bc_svc.delete_draft(db_session, broadcast_id=broadcast.id)
    with pytest.raises(NotFoundError):
        await bc_svc.get(db_session, broadcast_id=broadcast.id)


async def test_delete_draft_conflicts_outside_draft(db_session: AsyncSession) -> None:
    admin_id = await _make_user(db_session)
    broadcast = await bc_svc.create_draft(db_session, actor_id=admin_id, data=_minimal_body())
    await _force_status(db_session, broadcast_id=broadcast.id, status="scheduled")
    with pytest.raises(ConflictError):
        await bc_svc.delete_draft(db_session, broadcast_id=broadcast.id)


async def test_cancel_a_sent_broadcast_conflicts(db_session: AsyncSession) -> None:
    admin_id = await _make_user(db_session)
    broadcast = await bc_svc.create_draft(db_session, actor_id=admin_id, data=_minimal_body())
    await _force_status(db_session, broadcast_id=broadcast.id, status="sent")
    with pytest.raises(ConflictError):
        await bc_svc.cancel(db_session, broadcast_id=broadcast.id)


async def test_cancel_scheduled_broadcast_succeeds(db_session: AsyncSession) -> None:
    admin_id = await _make_user(db_session)
    broadcast = await bc_svc.create_draft(db_session, actor_id=admin_id, data=_minimal_body())
    future = datetime.now(UTC) + timedelta(hours=1)
    await bc_svc.schedule(db_session, broadcast_id=broadcast.id, scheduled_at=future)
    canceled = await bc_svc.cancel(db_session, broadcast_id=broadcast.id)
    assert canceled.status == "canceled"
    assert canceled.finished_at is not None


async def test_cancel_sending_broadcast_succeeds(db_session: AsyncSession) -> None:
    admin_id = await _make_user(db_session)
    broadcast = await bc_svc.create_draft(db_session, actor_id=admin_id, data=_minimal_body())
    await bc_svc.mark_send_now(db_session, broadcast_id=broadcast.id)
    canceled = await bc_svc.cancel(db_session, broadcast_id=broadcast.id)
    assert canceled.status == "canceled"


async def test_list_broadcasts_orders_newest_first_and_filters_status(
    db_session: AsyncSession,
) -> None:
    admin_id = await _make_user(db_session)
    first = await bc_svc.create_draft(db_session, actor_id=admin_id, data=_minimal_body())
    second = await bc_svc.create_draft(db_session, actor_id=admin_id, data=_minimal_body())
    # Both rows land in the same DB transaction, so CURRENT_TIMESTAMP would tie —
    # pin distinct created_at values so "newest first" has something to assert on.
    base = datetime.now(UTC)
    await db_session.execute(
        update(Broadcast).where(Broadcast.id == first.id).values(created_at=base)
    )
    await db_session.execute(
        update(Broadcast)
        .where(Broadcast.id == second.id)
        .values(created_at=base + timedelta(minutes=1))
    )
    await _force_status(db_session, broadcast_id=second.id, status="sent")

    rows, total = await bc_svc.list_broadcasts(db_session)
    assert total == 2
    assert [r.id for r in rows] == [second.id, first.id]

    rows_sent, total_sent = await bc_svc.list_broadcasts(db_session, status_filter="sent")
    assert total_sent == 1
    assert rows_sent[0].id == second.id


async def test_list_recipients_filters_by_status(db_session: AsyncSession) -> None:
    admin_id = await _make_user(db_session)
    recipient_a = await _make_user(db_session)
    recipient_b = await _make_user(db_session)
    broadcast = await bc_svc.create_draft(db_session, actor_id=admin_id, data=_minimal_body())
    db_session.add(
        BroadcastRecipient(
            id=str(uuid.uuid4()),
            broadcast_id=broadcast.id,
            user_id=recipient_a,
            tg_chat_id=5001,
            status="sent",
        )
    )
    db_session.add(
        BroadcastRecipient(
            id=str(uuid.uuid4()),
            broadcast_id=broadcast.id,
            user_id=recipient_b,
            tg_chat_id=5002,
        )
    )
    await db_session.flush()

    rows, total = await bc_svc.list_recipients(db_session, broadcast_id=broadcast.id)
    assert total == 2

    sent_rows, sent_total = await bc_svc.list_recipients(
        db_session, broadcast_id=broadcast.id, status_filter="sent"
    )
    assert sent_total == 1
    assert sent_rows[0].tg_chat_id == 5001
