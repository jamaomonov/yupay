"""Fan out queued Telegram broadcasts to their audience.

An admin composes a broadcast and marks it ``sending`` (immediately) or
``scheduled`` (for later). This job is the *only* thing that actually delivers
it: every 5 seconds it promotes any due scheduled broadcast, snapshots each
sending broadcast's audience into ``broadcast_recipients`` rows, then delivers
them in paced, resumable chunks.

**Resumable, at-least-once.** One tick sends at most :data:`CHUNK` recipients
per broadcast; the next tick picks up whatever is still ``pending``. Each
recipient is claimed and delivered in its **own** short transaction that commits
the ``pending`` -> ``sent``/``failed``/``blocked`` transition *before* the next
send, so a crash/deploy (SIGTERM) mid-chunk re-sends at most ~1 message rather
than the whole in-flight chunk. Delivery is therefore genuine at-least-once with
a one-recipient duplicate window on an ill-timed crash -- not exactly-once. Each
per-row claim uses ``FOR UPDATE SKIP LOCKED`` so overlapping work never grabs
the same row twice. A terminal broadcast (``sent``/``failed``/``canceled``)
drops out of the ``sending`` listing and is a pure no-op.

**Abort semantics.** The broadcast status is re-read before each recipient's
send, so an admin ``cancel`` that lands mid-flight stops delivery promptly. The
whole broadcast aborts to ``failed`` only on a **body/parse 400** (``can't parse
entities`` / ``can't parse message`` / ``message text is empty``) while it has
**zero successful sends so far** (``sent_count == 0``) -- that kind of 400
repeats for every recipient, so it must not be burned across the whole audience
one ``failed`` row at a time. A per-recipient addressing 400 (``chat not
found``, ``PEER_ID_INVALID``, ``chat_id is empty``) fails only *that* recipient
and delivery continues to the rest -- one dead chat_id never dooms the broadcast.
Keying the abort on "no success yet" rather than "first recipient" means a prior
transient failure on recipient #1 does not disable the guard.

Each phase runs in its own committed transaction and failures are isolated per
broadcast (logged with the broadcast id only -- never body or chat id, which is
Telegram PII), so one bad broadcast can never abort the rest of the batch.
"""

from __future__ import annotations

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.broadcasts.models import Broadcast, BroadcastRecipient

# Import the Telegram channel directly -- there is no ``broadcasts.api`` import
# here on purpose: pulling a module's ``api`` surface into the scheduler drags
# in its route registrations and the whole ``api/v1`` stack, a circular import
# outside the FastAPI process (see the identical note in ``waxpeer_reconcile``
# / ``expire_orders``). The channel only depends on config + logging.
from yupay.modules.notifications.channels.telegram import SendOutcome, send_broadcast_message

log = get_logger("yupay.scheduler.broadcast_dispatch")

_JOB_ID = "broadcasts.dispatch"
_INTERVAL_SECONDS = 5

# Recipients delivered per broadcast per tick. One chunk ~= CHUNK / RATE seconds
# of paced sending; the next tick continues the remaining ``pending`` rows.
CHUNK = 250
# Sends per second (Telegram's global broadcast ceiling is ~30/s). Module-level
# so tests can raise it and make the paced ``asyncio.sleep(1 / RATE)`` free.
RATE = 25
# At most this many oldest-started sending broadcasts per tick, to bound a tick
# at roughly ``MAX_BROADCASTS_PER_TICK * CHUNK / RATE`` seconds.
MAX_BROADCASTS_PER_TICK = 5


async def _promote_due() -> None:
    """Flip every scheduled broadcast whose time has come to ``sending``."""
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await session.execute(
            text(
                "UPDATE broadcasts "
                "SET status = 'sending', started_at = COALESCE(started_at, now()) "
                "WHERE status = 'scheduled' AND scheduled_at <= now()"
            )
        )


async def _list_sending_ids() -> list[str]:
    """Ids of currently-``sending`` broadcasts, oldest ``started_at`` first."""
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(Broadcast.id)
                .where(Broadcast.status == "sending")
                .order_by(Broadcast.started_at.asc(), Broadcast.id.asc())
                .limit(MAX_BROADCASTS_PER_TICK)
            )
        ).scalars()
        return list(rows)


async def _snapshot_and_size(broadcast_id: str) -> int:
    """Materialize the audience for a broadcast and return its recipient count.

    Own committed transaction. Skips (returns 0) if the broadcast vanished or is
    no longer ``sending``. On the first pass it inserts one ``pending`` recipient
    per eligible Telegram-linked user (excluding known-blocked chats, optionally
    narrowed by locale) and records ``total_recipients``; an empty audience is
    finalized to ``sent`` right here. Subsequent passes just return the stored
    ``total_recipients`` so delivery can resume.
    """
    factory = get_session_factory()
    async with factory() as session, session.begin():
        broadcast = (
            await session.execute(select(Broadcast).where(Broadcast.id == broadcast_id))
        ).scalar_one_or_none()
        if broadcast is None or broadcast.status != "sending":
            return 0

        if broadcast.started_at is None:
            broadcast.started_at = now()

        if broadcast.total_recipients != 0:
            return broadcast.total_recipients

        existing = (
            await session.execute(
                select(func.count())
                .select_from(BroadcastRecipient)
                .where(BroadcastRecipient.broadcast_id == broadcast_id)
            )
        ).scalar_one()
        if existing == 0:
            params: dict[str, str] = {"bid": broadcast_id}
            locale_clause = ""
            if broadcast.locale_filter is not None:
                locale_clause = " AND u.locale = :loc"
                params["loc"] = broadcast.locale_filter
            await session.execute(
                text(
                    "INSERT INTO broadcast_recipients "
                    "(id, broadcast_id, user_id, tg_chat_id, status) "
                    "SELECT gen_random_uuid(), :bid, u.id, tl.tg_user_id, 'pending' "
                    "FROM telegram_links tl JOIN users u ON u.id = tl.user_id "
                    "WHERE tl.bot_blocked_at IS NULL" + locale_clause + " "
                    "ON CONFLICT (broadcast_id, user_id) DO NOTHING"
                ),
                params,
            )

        count = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(BroadcastRecipient)
                    .where(BroadcastRecipient.broadcast_id == broadcast_id)
                )
            ).scalar_one()
        )
        broadcast.total_recipients = count
        if count == 0:
            broadcast.status = "sent"
            broadcast.finished_at = now()
        return count


async def _send_once(broadcast: Broadcast, chat_id: int, media_ref: str | None) -> SendOutcome:
    return await send_broadcast_message(
        bot_token=get_settings().telegram_bot_token,
        chat_id=chat_id,
        body_html=broadcast.body_html,
        media_type=broadcast.media_type,
        media_url_or_file_id=media_ref,
        disable_web_page_preview=broadcast.disable_web_page_preview,
    )


def _classify(outcome: SendOutcome) -> str | None:
    """Map an outcome to a terminal result, or ``None`` if it warrants a retry.

    A 400 is terminal (``bad_request``) -- never retried -- because it means the
    request itself is malformed; the caller decides whether it aborts the whole
    broadcast (no success yet) or is just this recipient's failure.
    """
    if outcome.ok:
        return "sent"
    if outcome.status == 403:
        return "blocked"
    if outcome.status == 400:
        return "bad_request"
    return None


async def _deliver(
    broadcast: Broadcast, chat_id: int, media_ref: str | None
) -> tuple[str, SendOutcome]:
    """Send to one recipient, applying the retry policy.

    Returns ``(result, outcome)`` where ``result`` is one of ``sent``,
    ``blocked``, ``bad_request`` or ``failed``.
    """
    outcome = await _send_once(broadcast, chat_id, media_ref)
    result = _classify(outcome)
    if result is not None:
        return result, outcome

    if outcome.status == 429:
        # Rate limited: honor Telegram's back-off, then retry this recipient once.
        await asyncio.sleep(outcome.retry_after or 1)
        retries = 1
    else:
        # 5xx / network (status 0) / other 4xx: retry up to twice, then give up.
        retries = 2

    for _ in range(retries):
        outcome = await _send_once(broadcast, chat_id, media_ref)
        result = _classify(outcome)
        if result is not None:
            return result, outcome
    return "failed", outcome


_COUNTER_COLUMN = {"sent": "sent_count", "failed": "failed_count", "blocked": "blocked_count"}

# Substrings that identify a Telegram 400 as a BODY/PARSE error -- a malformed
# message that will fail identically for every recipient (e.g. "can't parse
# entities", "can't parse message text", "message text is empty"). These are the
# only 400s that justify aborting the whole broadcast. A 400 that lacks all of
# these is a per-recipient addressing problem ("chat not found", "PEER_ID_INVALID",
# "chat_id is empty") and must fail only that one recipient.
_BODY_ERROR_MARKERS = ("parse", "entit", "message text is empty")


def _is_body_error(description: str) -> bool:
    """Return True if a 400 description signals a broken body (repeats for all)."""
    lowered = description.lower()
    return any(marker in lowered for marker in _BODY_ERROR_MARKERS)


async def _deliver_one(
    broadcast_id: str, recipient_id: str, media_ref: str | None
) -> tuple[str | None, str]:
    """Deliver to a single recipient in its **own** committed transaction.

    Returns ``(media_ref, control)`` where ``media_ref`` is the (possibly newly
    captured) media reference to carry forward and ``control`` is:
      * ``"done"`` -- the row settled (sent/failed/blocked) and committed; pace,
        then continue.
      * ``"skip"`` -- the row was already handled or is locked by an overlapping
        worker; continue without pacing (no send happened).
      * ``"stop"`` -- a mid-flight cancel (broadcast no longer ``sending``) or a
        400 abort; break out of the chunk.

    The send happens *inside* the row transaction, but the caller's pacing sleep
    is not -- a delivered row is committed ``sent`` before the next send, so a
    crash re-sends at most this one recipient (at-least-once).
    """
    factory = get_session_factory()
    async with factory() as session, session.begin():
        broadcast = (
            await session.execute(select(Broadcast).where(Broadcast.id == broadcast_id))
        ).scalar_one_or_none()
        if broadcast is None or broadcast.status != "sending":
            return media_ref, "stop"  # canceled / terminal since the chunk was read

        recipient = (
            await session.execute(
                select(BroadcastRecipient)
                .where(
                    BroadcastRecipient.id == recipient_id,
                    BroadcastRecipient.status == "pending",
                )
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if recipient is None:
            return media_ref, "skip"  # already delivered, or claimed by an overlap

        result, outcome = await _deliver(broadcast, recipient.tg_chat_id, media_ref)

        if result == "bad_request":
            recipient.status = "failed"
            recipient.error = outcome.description
            await _bump_counter(session, broadcast_id, "failed")
            # Abort the whole broadcast ONLY on a body/parse 400 with no success
            # yet -- a malformed message repeats for everyone, so it must not burn
            # the audience one row at a time. A per-recipient addressing 400
            # ("chat not found", "PEER_ID_INVALID", ...) fails just this recipient
            # and delivery continues to the rest.
            if broadcast.sent_count == 0 and _is_body_error(outcome.description):
                broadcast.status = "failed"
                broadcast.last_error = outcome.description
                broadcast.finished_at = now()
                return media_ref, "stop"
            return media_ref, "done"

        if result == "sent":
            recipient.status = "sent"
            recipient.sent_at = now()
            await _bump_counter(session, broadcast_id, "sent")
            # Capture Telegram's file_id on the first successful media send so the
            # rest of the broadcast resends by file_id (no re-upload).
            if (
                broadcast.media_type != "none"
                and broadcast.media_file_id is None
                and outcome.file_id
            ):
                broadcast.media_file_id = outcome.file_id
                media_ref = outcome.file_id
        elif result == "blocked":
            recipient.status = "blocked"
            await _bump_counter(session, broadcast_id, "blocked")
            await session.execute(
                text("UPDATE telegram_links SET bot_blocked_at = now() WHERE tg_user_id = :chat"),
                {"chat": recipient.tg_chat_id},
            )
        else:  # failed
            recipient.status = "failed"
            recipient.error = outcome.description
            await _bump_counter(session, broadcast_id, "failed")

    return media_ref, "done"


async def _bump_counter(session: AsyncSession, broadcast_id: str, kind: str) -> None:
    """Atomically increment one broadcast counter (avoids read-modify-write races)."""
    column = _COUNTER_COLUMN[kind]  # fixed lookup -> no SQL injection surface
    await session.execute(
        text(f"UPDATE broadcasts SET {column} = {column} + 1 WHERE id = :id"),
        {"id": broadcast_id},
    )


async def _finalize_if_done(broadcast_id: str) -> None:
    """Finalize a still-``sending`` broadcast to ``sent`` once nothing is pending."""
    factory = get_session_factory()
    async with factory() as session, session.begin():
        broadcast = (
            await session.execute(select(Broadcast).where(Broadcast.id == broadcast_id))
        ).scalar_one_or_none()
        if broadcast is None or broadcast.status != "sending":
            return
        remaining = (
            await session.execute(
                select(func.count())
                .select_from(BroadcastRecipient)
                .where(
                    BroadcastRecipient.broadcast_id == broadcast_id,
                    BroadcastRecipient.status == "pending",
                )
            )
        ).scalar_one()
        if remaining == 0:
            broadcast.status = "sent"
            broadcast.finished_at = now()


async def _process_chunk(broadcast_id: str) -> None:
    """Deliver one chunk of pending recipients, each in its own committed txn.

    Reads the chunk's recipient ids with a plain (unlocked) query so no lock is
    held across the paced loop, then delivers each id via :func:`_deliver_one`
    (which re-claims the row ``FOR UPDATE SKIP LOCKED``, sends, and commits). The
    pacing sleep sits between committed rows. Finalizes to ``sent`` once nothing
    remains pending.
    """
    factory = get_session_factory()
    async with factory() as session:
        broadcast = (
            await session.execute(select(Broadcast).where(Broadcast.id == broadcast_id))
        ).scalar_one_or_none()
        if broadcast is None or broadcast.status != "sending":
            return
        media_ref = broadcast.media_file_id or broadcast.media_url
        chunk_ids = list(
            (
                await session.execute(
                    select(BroadcastRecipient.id)
                    .where(
                        BroadcastRecipient.broadcast_id == broadcast_id,
                        BroadcastRecipient.status == "pending",
                    )
                    .order_by(BroadcastRecipient.id.asc())
                    .limit(CHUNK)
                )
            )
            .scalars()
            .all()
        )

    if not chunk_ids:
        await _finalize_if_done(broadcast_id)
        return

    stopped = False
    delivered = 0
    for recipient_id in chunk_ids:
        media_ref, control = await _deliver_one(broadcast_id, recipient_id, media_ref)
        if control == "stop":
            stopped = True
            break
        if control == "skip":
            continue
        delivered += 1
        await asyncio.sleep(1 / RATE)  # pace OUTSIDE any transaction

    if not stopped:
        await _finalize_if_done(broadcast_id)

    log.info(
        "broadcasts.dispatch.chunk",
        broadcast_id=broadcast_id,
        delivered=delivered,
        stopped=stopped,
    )


async def run_broadcast_dispatch() -> None:
    """One scheduler tick: promote due broadcasts, then deliver a chunk each.

    Failures are isolated per broadcast -- logged (id + error only, never body
    or chat id) and skipped -- so one bad broadcast can't stall the rest.
    """
    await _promote_due()
    broadcast_ids = await _list_sending_ids()
    for broadcast_id in broadcast_ids:
        try:
            size = await _snapshot_and_size(broadcast_id)
            if size > 0:
                await _process_chunk(broadcast_id)
        except Exception as exc:  # noqa: BLE001 -- one bad broadcast must not abort the batch
            log.warning(
                "broadcasts.dispatch.broadcast_failed",
                broadcast_id=broadcast_id,
                error=str(exc),
            )


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to a running scheduler. Safe to call once at startup."""
    scheduler.add_job(
        run_broadcast_dispatch,
        trigger="interval",
        seconds=_INTERVAL_SECONDS,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,  # never let two ticks race the same backlog.
        coalesce=True,  # if a tick is missed, run once -- don't burst-replay.
    )
    log.info("broadcasts.dispatch.registered", interval_seconds=_INTERVAL_SECONDS)


__all__ = ["register", "run_broadcast_dispatch"]
