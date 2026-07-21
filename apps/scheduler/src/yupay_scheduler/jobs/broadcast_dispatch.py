"""Fan out queued Telegram broadcasts to their audience.

An admin composes a broadcast and marks it ``sending`` (immediately) or
``scheduled`` (for later). This job is the *only* thing that actually delivers
it: every 5 seconds it promotes any due scheduled broadcast, snapshots each
sending broadcast's audience into ``broadcast_recipients`` rows, then delivers
them in paced, resumable chunks.

**Resumable + idempotent.** One tick sends at most :data:`CHUNK` recipients per
broadcast; the next tick picks up whatever is still ``pending``. The per-row
status transition (``pending`` -> ``sent``/``failed``/``blocked``) is the
idempotency guard -- a re-run only ever touches rows that are still ``pending``,
and the chunk claim uses ``FOR UPDATE SKIP LOCKED`` so overlapping work can
never grab the same row twice. A terminal broadcast (``sent``/``failed``/
``canceled``) drops out of the ``sending`` listing and is a pure no-op.

**Abort semantics.** The status is re-checked from a fresh read immediately
before the chunk claim, so an admin ``cancel`` that lands mid-flight stops
delivery. And the *first* send of a broadcast returning HTTP 400 (a malformed
body/media that would fail for everyone) aborts the whole broadcast to
``failed`` rather than burning the entire audience on a broken message.

Each phase runs in its own committed transaction and failures are isolated per
broadcast (logged with the broadcast id only -- never body or chat id, which is
Telegram PII), so one bad broadcast can never abort the rest of the batch.
"""

from __future__ import annotations

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, select, text
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


async def _send_once(
    broadcast: Broadcast, chat_id: int, media_ref: str | None
) -> SendOutcome:
    return await send_broadcast_message(
        bot_token=get_settings().telegram_bot_token,
        chat_id=chat_id,
        body_html=broadcast.body_html,
        media_type=broadcast.media_type,
        media_url_or_file_id=media_ref,
        disable_web_page_preview=broadcast.disable_web_page_preview,
    )


def _classify(outcome: SendOutcome, *, is_first_send: bool) -> str | None:
    """Map an outcome to a terminal result, or ``None`` if it warrants a retry."""
    if outcome.ok:
        return "sent"
    if outcome.status == 403:
        return "blocked"
    if outcome.status == 400 and is_first_send:
        return "abort"
    return None


async def _deliver(
    broadcast: Broadcast, chat_id: int, media_ref: str | None, *, is_first_send: bool
) -> tuple[str, SendOutcome]:
    """Send to one recipient, applying the retry/abort policy.

    Returns ``(result, outcome)`` where ``result`` is one of ``sent``,
    ``blocked``, ``failed`` or ``abort`` (only when the first send of the whole
    broadcast is rejected 400).
    """
    outcome = await _send_once(broadcast, chat_id, media_ref)
    result = _classify(outcome, is_first_send=is_first_send)
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
        # A 400 mid-retry is no longer the broadcast's first send -> never aborts.
        result = _classify(outcome, is_first_send=False)
        if result is not None:
            return result, outcome
    return "failed", outcome


async def _process_chunk(broadcast_id: str) -> None:
    """Claim and deliver one chunk of pending recipients for a broadcast.

    Own transaction. Re-reads the broadcast first: an admin ``cancel`` (or any
    non-``sending`` state) landing since the snapshot stops delivery. Claims up
    to :data:`CHUNK` pending rows with ``FOR UPDATE SKIP LOCKED``, delivers each
    at :data:`RATE`/s, rolls the outcomes into the broadcast counters, and
    finalizes to ``sent`` once no ``pending`` rows remain.
    """
    factory = get_session_factory()
    async with factory() as session, session.begin():
        broadcast = (
            await session.execute(select(Broadcast).where(Broadcast.id == broadcast_id))
        ).scalar_one_or_none()
        if broadcast is None or broadcast.status != "sending":
            return

        claimed = list(
            (
                await session.execute(
                    select(BroadcastRecipient)
                    .where(
                        BroadcastRecipient.broadcast_id == broadcast_id,
                        BroadcastRecipient.status == "pending",
                    )
                    .order_by(BroadcastRecipient.id.asc())
                    .with_for_update(skip_locked=True)
                    .limit(CHUNK)
                )
            )
            .scalars()
            .all()
        )
        if not claimed:
            broadcast.status = "sent"
            broadcast.finished_at = now()
            return

        # "First send of the whole broadcast" == no recipient has settled yet.
        no_prior_progress = (
            broadcast.sent_count == 0
            and broadcast.failed_count == 0
            and broadcast.blocked_count == 0
        )
        media_ref = broadcast.media_file_id or broadcast.media_url

        sent = failed = blocked = 0
        aborted = False
        for index, recipient in enumerate(claimed):
            await asyncio.sleep(1 / RATE)
            is_first_send = no_prior_progress and index == 0
            result, outcome = await _deliver(
                broadcast, recipient.tg_chat_id, media_ref, is_first_send=is_first_send
            )

            if result == "abort":
                broadcast.status = "failed"
                broadcast.last_error = outcome.description
                broadcast.finished_at = now()
                aborted = True
                break

            if result == "sent":
                recipient.status = "sent"
                recipient.sent_at = now()
                sent += 1
                # Capture Telegram's file_id on the first successful media send
                # so the rest of the broadcast resends by file_id (no re-upload).
                if (
                    broadcast.media_type != "none"
                    and broadcast.media_file_id is None
                    and outcome.file_id
                ):
                    broadcast.media_file_id = outcome.file_id
                    media_ref = outcome.file_id
            elif result == "blocked":
                recipient.status = "blocked"
                blocked += 1
                await session.execute(
                    text(
                        "UPDATE telegram_links SET bot_blocked_at = now() "
                        "WHERE tg_user_id = :chat"
                    ),
                    {"chat": recipient.tg_chat_id},
                )
            else:  # failed
                recipient.status = "failed"
                recipient.error = outcome.description
                failed += 1

        broadcast.sent_count += sent
        broadcast.failed_count += failed
        broadcast.blocked_count += blocked

        if not aborted:
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

        log.info(
            "broadcasts.dispatch.chunk",
            broadcast_id=broadcast_id,
            sent=sent,
            failed=failed,
            blocked=blocked,
            aborted=aborted,
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
