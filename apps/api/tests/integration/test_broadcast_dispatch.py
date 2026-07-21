"""Integration tests for the broadcasts dispatch sweep (Task 7).

Exercises ``yupay_scheduler.jobs.broadcast_dispatch.run_broadcast_dispatch``
end to end against directly-seeded ``Broadcast`` + ``User``/``TelegramLink``
rows and a respx-stubbed Telegram Bot API.

Like ``test_waxpeer_reconcile.py``, the job resolves its own session via
``get_session_factory()`` (never the request-scoped ``db_session``), so
``_job_session_factory`` below redirects that call at the *job module* to the
truncated test container. ``RATE`` is monkeypatched sky-high so the paced
``asyncio.sleep(1 / RATE)`` between sends is effectively free -- no real
per-recipient waiting.
"""

from __future__ import annotations

import json
from datetime import timedelta

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from yupay.core import config as cfg
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.broadcasts.models import Broadcast, BroadcastRecipient
from yupay.modules.users.models import TelegramLink, User
from yupay_scheduler.jobs import broadcast_dispatch

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "test-bot-token"
_SEND_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

# ``populate_existing`` forces the assertion session to re-read rows the job
# wrote from its own (separate) session rather than serving stale cache.
_FRESH = {"populate_existing": True}


@pytest.fixture(autouse=True)
def _bot_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    cfg.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _job_session_factory(monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(broadcast_dispatch, "get_session_factory", lambda: factory)


@pytest.fixture(autouse=True)
def _fast_pacing(monkeypatch: pytest.MonkeyPatch) -> None:
    # 1 / 1_000_000 s per send -> effectively no wait, but still exercises the
    # real ``asyncio.sleep`` code path (never a monkeypatched no-op).
    monkeypatch.setattr(broadcast_dispatch, "RATE", 1_000_000)


# ---------- seeding helpers ----------


async def _seed_user_with_tg(
    db: AsyncSession, *, tg_id: int, locale: str = "ru", blocked: bool = False
) -> User:
    user = User(id=new_id(), locale=locale, roles=[])
    db.add(user)
    await db.flush()
    link = TelegramLink(
        id=new_id(),
        user_id=user.id,
        tg_user_id=tg_id,
        bot_blocked_at=(now() if blocked else None),
    )
    db.add(link)
    await db.flush()
    return user


async def _seed_broadcast(
    db: AsyncSession,
    *,
    creator_id: str,
    status: str = "sending",
    body_html: str = "<b>hi</b>",
    scheduled_at: object | None = None,
    total_recipients: int = 0,
) -> Broadcast:
    broadcast = Broadcast(
        id=new_id(),
        title="t",
        status=status,
        body_html=body_html,
        media_type="none",
        created_by=creator_id,
        scheduled_at=scheduled_at,
        total_recipients=total_recipients,
    )
    db.add(broadcast)
    await db.commit()
    return broadcast


def _ok_response() -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})


def _err_response(code: int) -> httpx.Response:
    return httpx.Response(
        code, json={"ok": False, "error_code": code, "description": f"err{code}"}
    )


def _responder(by_chat: dict[int, int]):
    """Return a respx side_effect that maps ``chat_id`` -> HTTP status (default 200)."""

    def _respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        code = by_chat.get(int(payload["chat_id"]), 200)
        return _ok_response() if code == 200 else _err_response(code)

    return _respond


async def _reload_broadcast(db: AsyncSession, broadcast_id: str) -> Broadcast:
    return (
        await db.execute(
            select(Broadcast).where(Broadcast.id == broadcast_id).execution_options(**_FRESH)
        )
    ).scalar_one()


async def _recipients(db: AsyncSession, broadcast_id: str) -> list[BroadcastRecipient]:
    return list(
        (
            await db.execute(
                select(BroadcastRecipient)
                .where(BroadcastRecipient.broadcast_id == broadcast_id)
                .execution_options(**_FRESH)
            )
        )
        .scalars()
        .all()
    )


async def _link_for(db: AsyncSession, tg_id: int) -> TelegramLink:
    return (
        await db.execute(
            select(TelegramLink)
            .where(TelegramLink.tg_user_id == tg_id)
            .execution_options(**_FRESH)
        )
    ).scalar_one()


# ---------- tests ----------


@respx.mock
async def test_one_tick_snapshots_and_sends_all(db_session: AsyncSession) -> None:
    """A sending broadcast + 3 linked users -> one tick snapshots recipients,
    sends to all three, sets counters, and finalizes status=sent."""
    admin = await _seed_user_with_tg(db_session, tg_id=1000)
    for tg_id in (101, 102, 103):
        await _seed_user_with_tg(db_session, tg_id=tg_id)
    await db_session.commit()
    broadcast = await _seed_broadcast(db_session, creator_id=admin.id)

    route = respx.post(_SEND_URL).mock(side_effect=_responder({}))

    await broadcast_dispatch.run_broadcast_dispatch()

    updated = await _reload_broadcast(db_session, broadcast.id)
    assert updated.status == "sent"
    assert updated.total_recipients == 4  # admin is Telegram-linked too
    assert updated.sent_count == 4
    assert updated.failed_count == 0
    assert updated.blocked_count == 0
    assert updated.finished_at is not None

    recips = await _recipients(db_session, broadcast.id)
    assert len(recips) == 4
    assert all(r.status == "sent" and r.sent_at is not None for r in recips)
    assert route.call_count == 4


@respx.mock
async def test_403_marks_blocked_and_sets_bot_blocked_at(db_session: AsyncSession) -> None:
    """A 403 for one recipient -> that row is 'blocked' and its telegram_link
    gets bot_blocked_at stamped so future broadcasts skip it."""
    admin = await _seed_user_with_tg(db_session, tg_id=1000)
    await _seed_user_with_tg(db_session, tg_id=201)
    await _seed_user_with_tg(db_session, tg_id=202)
    await db_session.commit()
    broadcast = await _seed_broadcast(db_session, creator_id=admin.id)

    respx.post(_SEND_URL).mock(side_effect=_responder({202: 403}))

    await broadcast_dispatch.run_broadcast_dispatch()

    updated = await _reload_broadcast(db_session, broadcast.id)
    assert updated.status == "sent"
    assert updated.sent_count == 2  # admin + 201
    assert updated.blocked_count == 1
    assert updated.failed_count == 0

    recips = {r.tg_chat_id: r for r in await _recipients(db_session, broadcast.id)}
    assert recips[202].status == "blocked"
    assert recips[201].status == "sent"

    link = await _link_for(db_session, 202)
    assert link.bot_blocked_at is not None


@respx.mock
async def test_scheduled_in_the_past_is_promoted_then_sent(db_session: AsyncSession) -> None:
    """A 'scheduled' broadcast whose scheduled_at is in the past is promoted to
    'sending' and delivered within the same tick."""
    admin = await _seed_user_with_tg(db_session, tg_id=1000)
    await db_session.commit()
    past = now() - timedelta(minutes=5)
    broadcast = await _seed_broadcast(
        db_session, creator_id=admin.id, status="scheduled", scheduled_at=past
    )

    respx.post(_SEND_URL).mock(side_effect=_responder({}))

    await broadcast_dispatch.run_broadcast_dispatch()

    updated = await _reload_broadcast(db_session, broadcast.id)
    assert updated.status == "sent"
    assert updated.started_at is not None
    assert updated.sent_count == 1


@respx.mock
async def test_second_tick_over_sent_broadcast_is_idempotent(db_session: AsyncSession) -> None:
    """Re-running the sweep over an already-finished broadcast makes no further
    Telegram calls -- it no longer shows up as 'sending'."""
    admin = await _seed_user_with_tg(db_session, tg_id=1000)
    await _seed_user_with_tg(db_session, tg_id=301)
    await db_session.commit()
    broadcast = await _seed_broadcast(db_session, creator_id=admin.id)

    route = respx.post(_SEND_URL).mock(side_effect=_responder({}))

    await broadcast_dispatch.run_broadcast_dispatch()
    first = await _reload_broadcast(db_session, broadcast.id)
    assert first.status == "sent"
    assert route.call_count == 2

    await broadcast_dispatch.run_broadcast_dispatch()
    assert route.call_count == 2  # no extra sends


@respx.mock
async def test_first_send_400_aborts_the_whole_broadcast(db_session: AsyncSession) -> None:
    """The very first send returning 400 (malformed body/media) fails the whole
    broadcast and stops -- no further recipients are attempted."""
    admin = await _seed_user_with_tg(db_session, tg_id=1000)
    await _seed_user_with_tg(db_session, tg_id=401)
    await db_session.commit()
    broadcast = await _seed_broadcast(db_session, creator_id=admin.id)

    route = respx.post(_SEND_URL).mock(side_effect=_responder({1000: 400, 401: 400}))

    await broadcast_dispatch.run_broadcast_dispatch()

    updated = await _reload_broadcast(db_session, broadcast.id)
    assert updated.status == "failed"
    assert updated.last_error is not None
    assert updated.sent_count == 0
    assert route.call_count == 1  # aborted after the first send, no retries

    recips = await _recipients(db_session, broadcast.id)
    assert all(r.status == "pending" for r in recips)


@respx.mock
async def test_cancel_between_snapshot_and_chunk_stops_the_job(
    db_session: AsyncSession, db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An admin cancel that lands after the recipient snapshot but before the
    chunk claim is honored: the re-check sees 'canceled' and sends nothing."""
    admin = await _seed_user_with_tg(db_session, tg_id=1000)
    await _seed_user_with_tg(db_session, tg_id=501)
    await db_session.commit()
    broadcast = await _seed_broadcast(db_session, creator_id=admin.id)

    route = respx.post(_SEND_URL).mock(side_effect=_responder({}))

    real_snapshot = broadcast_dispatch._snapshot_and_size
    cancel_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    async def _snapshot_then_cancel(broadcast_id: str) -> int:
        size = await real_snapshot(broadcast_id)
        # Simulate a concurrent admin cancel committing between the snapshot
        # and the chunk claim.
        async with cancel_factory() as s, s.begin():
            row = (
                await s.execute(select(Broadcast).where(Broadcast.id == broadcast_id))
            ).scalar_one()
            row.status = "canceled"
            row.finished_at = now()
        return size

    monkeypatch.setattr(broadcast_dispatch, "_snapshot_and_size", _snapshot_then_cancel)

    await broadcast_dispatch.run_broadcast_dispatch()

    updated = await _reload_broadcast(db_session, broadcast.id)
    assert updated.status == "canceled"
    assert route.call_count == 0
    recips = await _recipients(db_session, broadcast.id)
    assert all(r.status == "pending" for r in recips)
