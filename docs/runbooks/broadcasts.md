# Runbook — Telegram broadcasts

Admin-authored messages sent to every Telegram-linked user via the bot. See
[ADR-0033](../decisions/0033-telegram-broadcasts.md) for why delivery is a
**scheduler job**, not an outbox/worker, and
`apps/api/src/yupay/modules/broadcasts/README.md` for the module's tables,
FSM, and HTTP surface.

## Prerequisites

Both `apps/bot` and `apps/scheduler` need `DATABASE_URL` set (same as
`apps/api`) — the bot clears `bot_blocked_at` on `/start` and the scheduler's
`broadcast_dispatch` job reads/writes `broadcasts` and
`broadcast_recipients` directly; neither goes through the API process. If a
broadcast is stuck and either container is missing its DB config, that's the
first thing to check.

## Compose → test → send / schedule → cancel

1. **Compose** (`Admin → Рассылки → Новая рассылка`): title (internal only,
   never sent), body via the `TelegramEditor` toolbar (bold/italic/
   underline/strikethrough/spoiler/link/code), optional one attachment
   (photo/video/GIF/document, ≤ 20 MB), optional locale filter. Saves as
   `draft` via `POST`/`PATCH /admin/broadcasts`.
2. **Тест себе** — `POST /admin/broadcasts/{id}/test` sends the current
   draft content immediately to the admin's own linked Telegram chat,
   without touching the FSM state. Requires the calling admin to have a
   `TelegramLink` (422 "привяжите Telegram..." otherwise — the same
   `ValidationError` status the whitelist check uses). Always sends by
   URL, never by a captured `file_id` — a test send may be the very first
   send for this broadcast.
3. **Отправить (send now)** — `POST /admin/broadcasts/{id}/send` flips
   `status → sending`. This is a **status flip only** — no queue, no
   message sent from the request handler. The confirmation modal shows the
   live audience size from `GET /admin/broadcasts/audience-count?locale=`
   before the admin commits. The next dispatch tick (≤ ~5 s later) is what
   actually starts sending.
4. **Запланировать (schedule)** — `POST /admin/broadcasts/{id}/schedule`
   with an ISO-8601 UTC `scheduled_at` at least 5 seconds in the future.
   Flips `status → scheduled`; the same dispatch job promotes it to
   `sending` once due.
5. **Отменить (cancel)** — `POST /admin/broadcasts/{id}/cancel`, legal from
   `scheduled` or `sending`. Already-sent messages are not clawed back;
   the dispatch job re-checks status before claiming each new chunk, so a
   cancel mid-flight stops delivery within one chunk's worth of sends
   (paced at 25/s — see "Rate limits" below), not instantly.
6. **Editing**: only `draft` and `scheduled` broadcasts can be edited
   (`PATCH`). Editing a `scheduled` one resets it to `draft` and clears
   `scheduled_at` — re-schedule explicitly after changing content. Once a
   broadcast is `sending`/`sent`/`failed`/`canceled`, it's immutable.

## What `failed` / `blocked` mean

**On the broadcast (`status`):**

- `failed` — the _whole_ broadcast aborted. This only happens when, with
  **zero successes so far**, a send comes back Telegram HTTP 400 that
  signals a **broken message body** — "can't parse entities", "can't parse
  message text", or "message text is empty" — i.e. a failure that would
  repeat for every recipient. A per-recipient addressing 400 (e.g. "chat
  not found") does **not** abort; it fails just that one recipient and
  delivery continues. See "First-send abort" below. Check `last_error` on
  the broadcast row for Telegram's message.
- `blocked` is not a broadcast status — only a per-recipient one.

**On a recipient row (`broadcast_recipients.status`):**

- `sent` — delivered.
- `blocked` — Telegram returned 403 (user blocked the bot / deactivated
  their account / chat not found). Not retried. Also stamps that user's
  `telegram_links.bot_blocked_at`, excluding them from every future
  broadcast's audience until they `/start` the bot again (see below).
- `failed` — delivery failed after retries (5xx/network) or the
  first-send-400 abort case for recipients after the first (see below).
  `error` on the row carries Telegram's truncated description.

Check problem recipients with:

```
GET /api/v1/admin/broadcasts/{id}/recipients?status=failed
GET /api/v1/admin/broadcasts/{id}/recipients?status=blocked
```

## First-send abort behavior

If a send returns an HTTP 400 that identifies a **broken message body**
(the description contains "parse", "entit", or "message text is empty")
**and** the broadcast's `sent_count` is still `0`, the dispatch job aborts
the entire broadcast: status → `failed`, `last_error` set to Telegram's
description, `finished_at` set. The remaining `pending` recipients are left
untouched (not marked `failed` one by one) — the guard exists specifically
to avoid grinding through the whole audience with a message that's
malformed for everyone. A 400 that is **not** a body error — the classic
being "chat not found" for a stale/deleted account — is treated as a
per-recipient failure instead: that one row is marked `failed` and delivery
continues to the rest.

**Why this can still happen** despite the save-time whitelist
(`broadcasts/sanitize.py`): the whitelist is Telegram-shaped but not a
perfect model of Telegram's own HTML parser, so an edge case could in
theory still slip through as syntactically-allowed-but-semantically-broken
markup. If you see a broadcast in `failed` with a 400 `last_error`:

1. Read `last_error` for Telegram's exact complaint.
2. Move the broadcast back to `draft` (`PATCH` — editing an already-failed
   broadcast is not directly supported by the FSM today; recreate a new
   draft with the corrected body if the existing row won't accept an edit).
3. Fix the body in the composer (the preview + `TelegramEditor` should
   already prevent most of these; if not, the whitelist may need a fix —
   file that separately).
4. **Тест себе** again before re-sending to the full audience.

Note the guard only fires while `sent_count == 0` — a 400 after even one
successful send just fails that one recipient's row and the broadcast
keeps going, since a partial success means the body itself is fine and the
failure is recipient-specific (e.g. a stale `file_id` edge case).

## How a stuck `sending` broadcast resumes

There is no separate "resume" action. The dispatch job (`apps/scheduler`,
job id `broadcasts.dispatch`, every ~5s) simply keeps draining whatever
`broadcast_recipients` rows are still `pending` for every broadcast whose
`status = sending`, every tick, indefinitely, until none remain. If the
scheduler container restarts, redeploys, or crashes mid-chunk:

- Any recipient whose send committed before the crash stays `sent`/
  `failed`/`blocked` — it is never re-sent, **except** for at most one
  recipient whose send may have gone out to Telegram but whose row commit
  didn't land before the crash (a bounded ~1-recipient duplicate window —
  see ADR-0033). This is a deliberate at-least-once trade-off, not a bug.
- Every recipient still `pending` gets picked up by the next tick's chunk
  claim (`FOR UPDATE SKIP LOCKED`), with no manual action needed.
- If the broadcast looks "stuck" for longer than a few ticks, check that
  the scheduler container is actually running
  (`make logs service=scheduler`) and that `broadcasts.dispatch.registered`
  appears in its startup log. A `broadcasts.dispatch.broadcast_failed`
  warning log line means one broadcast's tick threw — it's isolated per
  broadcast and doesn't stall the others, but is worth investigating (the
  `error` field is logged, id only — no body/chat id, per the PII rule).

## Telegram rate limits

The dispatch job paces sends at `RATE = 25`/s (module constant in
`broadcast_dispatch.py`), comfortably under Telegram's own ~30/s broadcast
ceiling. Each tick claims and delivers at most `CHUNK = 250` recipients per
broadcast (~10s of paced sending), and at most `MAX_BROADCASTS_PER_TICK = 5`
broadcasts per tick, so one tick is bounded at roughly 50 seconds even if
several large broadcasts are `sending` concurrently — the next tick simply
continues. A `429` from Telegram is not treated as a failure: the job
sleeps the `retry_after` Telegram provides and retries that one recipient
once before giving up.

## Checking the audience query

The composer's recipient-count preview and the dispatch job's snapshot use
the same shape of query:

```sql
SELECT count(*) FROM telegram_links tl
JOIN users u ON u.id = tl.user_id
WHERE tl.bot_blocked_at IS NULL
  -- AND u.locale = :locale   -- only when a locale filter is set
```

To sanity-check a specific broadcast's actual snapshot after it starts
sending:

```
GET /api/v1/admin/broadcasts/{id}
```

`total_recipients` is the size frozen at snapshot time (not live — it does
not grow if new users link Telegram mid-send); `sent_count + failed_count +
blocked_count` should climb toward it as the dispatch job works through the
backlog, and equal it once `status` reaches `sent`.

## Related

- [ADR-0033](../decisions/0033-telegram-broadcasts.md) — scheduler-driven
  fan-out, at-least-once delivery, the editor choice, `file_id` reuse, the
  first-send abort.
- `apps/api/src/yupay/modules/broadcasts/README.md` — tables, FSM, HTTP
  surface, whitelist.
- `apps/scheduler/src/yupay_scheduler/jobs/broadcast_dispatch.py` — the
  dispatch job itself.
- `apps/api/src/yupay/modules/storage/README.md` — the `broadcast_media`
  upload kind (20 MB cap, video/GIF/PDF MIME types).
- `docs/architecture/sequence-diagrams/broadcast-send.mmd`.
- `docs/runbooks/waxpeer-troubleshooting.md` — the equivalent
  periodic-sweep pattern (`waxpeer_reconcile`) this job's shape is copied
  from, if you want a second example of the same operational model.
