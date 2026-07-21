# Telegram Broadcasts (Рассылки) — Design Spec

- **Status:** Approved (brainstorm), ready for implementation plan
- **Date:** 2026-07-21
- **Author:** @jamaomonov
- **Surfaces:** Admin SPA (`apps/admin`), API (`apps/api`), Scheduler
  (`apps/scheduler`), Bot (`apps/bot`)
- **Mockup:** interactive composer + Telegram preview + list (shared separately)

---

## 1. Goal

Give admins a screen to compose and send a **broadcast message to users through the
Telegram bot** — formatted text plus one optional media attachment — targeting the
whole bot audience (optionally filtered by language), safely and at scale.

One sentence: *an admin writes one message, optionally attaches a photo/video/GIF/
document, previews it exactly as it will arrive, sends a test to themselves, then
fans it out to every user who has started the bot — in the background, throttled,
resumable, with live delivery counters.*

## 2. Decisions locked during brainstorming

| Question | Decision |
| --- | --- |
| **Channel** | Telegram bot DM **only** (users with a `TelegramLink`). No email/web in v1. |
| **Audience** | All Telegram-linked users; **optional locale filter** (all / ru / en / uz). Users who blocked the bot are excluded. |
| **Localization of the message** | **One message to everyone** (single body + single media). Not per-locale variants. |
| **Text formatting** | **WYSIWYG toolbar → Telegram HTML** (contenteditable editor); server validates against a whitelist. |
| **Media** | **One** attachment per broadcast: photo / video / GIF / document, **≤ 20 MB**. Or text-only. |
| **Scheduling** | Draft + **send now** + **scheduled** (send at a chosen time). |
| **Safety** | **Test-send to self** + **confirmation dialog** showing the recipient count. |
| **Delivery progress** | **Polling** in the admin (WS is a later option). |
| **Admin language** | Admin UI is **RU-only** (like every other admin page); no i18n keys. The broadcast *content* is authored by the admin, not translated. |

## 3. Architecture overview

A new backend module **`broadcasts`** owns the domain. **Delivery runs as a periodic
scheduler job** (`apps/scheduler`), mirroring the existing `waxpeer_reconcile` pattern —
the codebase's proven background mechanism. There is deliberately **no** outbox / broker
involvement: `core/outbox` is still a stub and the API holds no Dramatiq broker, so
introducing either just to start a broadcast would add unproven machinery. The job sends
through the **`notifications` Telegram channel** (extended for media). Media is stored in
**R2 via the `storage` presign flow** (extended for video/GIF/documents and a larger
cap). The admin gets a **`features/broadcasts`** area with a Telegram-style composer.

```
Admin SPA (composer)
   │  POST /admin/broadcasts (draft)  ── validate body_html (whitelist) ──► broadcasts row
   │  POST …/{id}/test                ── render + sendMessage/sendPhoto to admin's own chat
   │  POST …/{id}/send                ── FSM → sending  (status flip only; no queue)
   │  POST …/{id}/schedule            ── FSM → scheduled, scheduled_at set
   ▼
apps/scheduler  broadcast_dispatch job  (runs every ~5s, max_instances=1)
   │ 1. promote due `scheduled` (scheduled_at <= now) → `sending`
   │ 2. for each `sending` broadcast:
   │      snapshot recipients if missing (idempotent, ON CONFLICT DO NOTHING)
   │      claim a CHUNK of `pending` via SELECT … FOR UPDATE SKIP LOCKED
   │      send each, paced ~25/s → sent / blocked / failed
   │      first media send → capture file_id, reuse for the rest
   │      commit counters; finalize → sent when drained
   ▼
 status → sent | failed | canceled
Admin detail page polls GET /admin/broadcasts/{id} for live counters.
```

## 4. Data model

New tables (one Alembic migration), plus one column on `telegram_links`.

### `broadcasts`
| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | |
| `title` | text | Internal admin label only; never sent. |
| `status` | text | `draft` / `scheduled` / `sending` / `sent` / `failed` / `canceled`. CHECK-constrained. |
| `body_html` | text | Telegram-HTML caption/text (whitelist-validated). May be empty only if media present. |
| `media_type` | text | `none` / `photo` / `video` / `animation` / `document`. |
| `media_url` | text nullable | CDN URL of the uploaded file (from `storage` presign). |
| `media_file_id` | text nullable | Telegram `file_id` captured on the first successful media send; reused for the rest. |
| `locale_filter` | text nullable | `null` = all languages; else `ru`/`en`/`uz`. |
| `disable_web_page_preview` | bool | Default `true`. |
| `scheduled_at` | timestamptz nullable | Set when `status = scheduled`. Stored UTC. |
| `total_recipients` | int | Snapshot size (0 until send starts). |
| `sent_count` / `failed_count` / `blocked_count` | int | Live counters, updated per chunk. |
| `started_at` / `finished_at` | timestamptz nullable | |
| `last_error` | text nullable | Set on abort/catastrophic failure (e.g. first-send entity error). |
| `created_by` | uuid | Admin user id (FK users). |
| `created_at` / `updated_at` | timestamptz | |

### `broadcast_recipients`
The resumable work list — **snapshotted at send-start**.
| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | |
| `broadcast_id` | uuid FK → broadcasts (cascade) | |
| `user_id` | uuid FK → users | |
| `tg_chat_id` | bigint | Copied from the link at snapshot time. |
| `status` | text | `pending` / `sent` / `failed` / `blocked`. |
| `error` | text nullable | Telegram error description (truncated), for the "problem recipients" list. |
| `sent_at` | timestamptz nullable | |
| — | | `UNIQUE(broadcast_id, user_id)` → snapshot + re-delivery are idempotent. Index on `(broadcast_id, status)` for the chunk query. |

### `telegram_links.bot_blocked_at` (new column, nullable timestamptz)
Set when any send returns 403 "bot was blocked / user deactivated". **Cleared on `/start`**
(one-line addition to the bot's existing `/start` handler). Excluded from audience counts
and snapshots so repeat broadcasts don't keep hammering users who left.

## 5. Body formatting — Telegram HTML

### Allowed tags (whitelist)
The editor emits and the server accepts **only** the tags Telegram's HTML parse mode
understands:

`b`, `i`, `u`, `s`, `a` (with `href`, `http(s)`/`tg://` only), `code`, `pre`,
`tg-spoiler`, `blockquote`.

Line breaks are `\n` (Telegram HTML has no `<br>`). Everything else — other tags, other
attributes, `script`/`style`, unbalanced tags — is **rejected on save** (HTTP 422 with a
field error the composer surfaces), so a malformed body can never reach the fan-out and
fail on every recipient.

### Validator (`broadcasts/sanitize.py`)
A strict allowlist validator built on the **stdlib `html.parser.HTMLParser`** — no new
dependency. It:
- rejects any tag / attribute outside the whitelist,
- verifies tags are balanced and properly nested,
- validates `a[href]` scheme,
- escapes stray `<`, `>`, `&` in text,
- enforces the **length limit** measured Telegram-style (visible text, tags excluded):
  **≤ 1024** chars when media is attached (it becomes a caption), **≤ 4096** when
  text-only.

### Editor (`components/TelegramEditor.tsx`) — see ADR
A focused **contenteditable** WYSIWYG with a toolbar (B / I / U / S / spoiler / link /
code) and a DOM→Telegram-HTML serializer. No heavy rich-text dependency. This is a new
UI pattern → **ADR-0033** records the choice and the fallback (toolbar-wrapped textarea +
live preview) if the contenteditable route proves too fiddly.

## 6. Media

- **Upload:** reuse `storage.presign_upload` with a new kind **`broadcast_media`**.
  - Add video/GIF/document MIME to `_MIME_TO_EXT`; validate **per-kind** so image kinds
    keep their current image-only allowlist while `broadcast_media` also accepts
    `video/mp4`, `image/gif`, and a small document set (e.g. `application/pdf`).
  - Add setting **`broadcast_media_max_upload_bytes`** (default **20 MB**); presign uses
    it for broadcast kinds, images keep `media_max_upload_bytes` (5 MB).
- **MIME → Telegram method** (deterministic):
  - `image/jpeg|png|webp` → **sendPhoto**
  - `image/gif` → **sendAnimation**
  - `video/mp4` → **sendVideo**
  - documents → **sendDocument**
- **`file_id` reuse:** the first successful media send goes by CDN **URL**; capture the
  returned `file_id` (`result.photo[-1].file_id`, `result.video.file_id`, …), persist it,
  and send by `file_id` to every remaining recipient — one CDN fetch instead of thousands.

## 7. Delivery — scheduler dispatch job

`apps/scheduler/src/yupay_scheduler/jobs/broadcast_dispatch.py` — a periodic job
registered like `waxpeer_reconcile`, running every **~5 s** with `max_instances=1` +
`coalesce=True` (prod runs a single scheduler process, so no cross-process double-send;
the SKIP-LOCKED claim below guards the rest). Each tick:

1. **Promote** due scheduled broadcasts: `scheduled` with `scheduled_at <= now()` → `sending`.
2. For each `sending` broadcast (oldest `started_at` first), bounded to a per-tick global
   cap so one tick can't run away:
   - **Snapshot recipients** if not yet present: `INSERT … ON CONFLICT (broadcast_id,
     user_id) DO NOTHING` from `TelegramLink ⨝ User` where `bot_blocked_at IS NULL` and
     (locale filter). Set `total_recipients`, `started_at`.
   - If status is now `canceled` → skip. Otherwise **claim a CHUNK** (≈ 250, sized so a
     tick stays bounded at ~25 msg/s) of `pending` recipients with
     `SELECT … WHERE status='pending' … FOR UPDATE SKIP LOCKED LIMIT :chunk`.
   - Send each, paced at **~25 msg/s** (`asyncio.sleep(1/RATE)`), via the Telegram channel:
     - **200** → `sent` (+ capture `file_id` on the first media send, persisted on the broadcast).
     - **403** (blocked / deactivated / chat not found) → `blocked`, set
       `telegram_links.bot_blocked_at`, no retry.
     - **429** → sleep `retry_after`, retry the **same** recipient (not a failure).
     - **5xx / network** → a couple of retries, then `failed` with the error.
     - **400 "can't parse entities" on the very first send** → **abort**: status `failed`,
       `last_error` set, so the admin fixes formatting instead of blasting 5 000 failures.
   - Commit counters. When no `pending` remain → finalize: status `sent`, `finished_at`.

The FOR-UPDATE-SKIP-LOCKED claim + per-recipient status transition make the job
**resumable and idempotent**: a crash mid-tick leaves the uncommitted recipients
`pending`, and the next tick continues; two overlapping ticks never grab the same rows.

**Cancellation:** admin cancel sets `canceled`; the job checks status before claiming a
chunk and stops. Already-sent messages stay sent.

## 8. Scheduling

- **Send now:** request validates and sets `status = sending` (a status flip only — no
  queue, no outbox). The next dispatch tick (≤ ~5 s later) snapshots and starts sending.
- **Scheduled:** request sets `status = scheduled`, `scheduled_at`. The same dispatch job
  promotes it to `sending` once due. Times stored/compared **UTC**; the composer sends an
  ISO-8601 UTC instant.

## 9. Admin UI (`apps/admin/src/features/broadcasts`)

- **`BroadcastsListPage`** — DataTable: title, status badge (Отправлено / Отправляется +
  progress / Запланирована / Черновик / Ошибка / Отменена), audience, `sent / failed /
  blocked`, when, author. "Новая рассылка" button. New nav entry.
- **`BroadcastComposerPage`** — create / edit a **draft** (editing only allowed in
  `draft`; a `scheduled` one can be moved back to draft to edit). Left: title,
  `TelegramEditor` + toolbar, `BroadcastMediaUploader` (one file), locale chips, "Сейчас /
  Запланировать" (+ datetime), actions **Тест себе / Сохранить черновик / Отправить**.
  Right: **phone preview** rendering the exact message. Send opens a **confirmation modal**
  with the recipient count.
- **`BroadcastDetailPage`** — a sending/sent broadcast: live counters (TanStack
  `refetchInterval` while `sending`), **Отменить отправку** (when sending/scheduled), and
  a **problem-recipients** list (failed/blocked with reasons).
- New shared components: `TelegramEditor.tsx`, `BroadcastMediaUploader.tsx` (or an
  extended `ImageUploader` accepting the broadcast kind). `lib/queryKeys` + `lib/api`
  additions.

## 10. API surface (`/api/v1/admin/broadcasts`, `require_admin`)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/admin/broadcasts` | Paged list (+ status filter). |
| `POST` | `/admin/broadcasts` | Create draft. |
| `GET` | `/admin/broadcasts/{id}` | Detail + live counters. |
| `PATCH` | `/admin/broadcasts/{id}` | Edit draft (409 if not draft/scheduled). |
| `DELETE` | `/admin/broadcasts/{id}` | Delete draft. |
| `POST` | `/admin/broadcasts/{id}/test` | Send to the caller's own Telegram chat. |
| `POST` | `/admin/broadcasts/{id}/send` | Send now (FSM → sending; the dispatch job picks it up). |
| `POST` | `/admin/broadcasts/{id}/schedule` | Set `scheduled_at` (FSM → scheduled). |
| `POST` | `/admin/broadcasts/{id}/cancel` | Cancel scheduled/sending. |
| `GET` | `/admin/broadcasts/{id}/recipients?status=failed` | Problem-recipients list. |
| `GET` | `/admin/broadcasts/audience-count?locale=` | Live eligible-recipient estimate for the composer. |
| `POST` | `/admin/media/presign-upload` | Existing; extended for `broadcast_media`. |

All write endpoints accept **`Idempotency-Key`** (CLAUDE.md §9). `send` is additionally
guarded by the FSM: a broadcast already `sending`/`sent` cannot be re-sent (double-click
safe). Actions are written to the **`audit`** log. Bot token and `tg_chat_id` are never
logged (PII rule).

## 11. Error handling & edge cases

- Empty body **and** no media → 422 ("сообщение пустое").
- Body over the length limit → 422 with the limit.
- `test` when the admin has no `TelegramLink` → 400 ("привяжите Telegram, чтобы получить тест").
- First media send fails by URL (bad file) → retry once, then abort (`failed`) — nothing
  sent to the base at a bad file.
- Scheduled time in the past (or under a small skew margin) → **422** "время в прошлом".
- Overlapping / repeated dispatch ticks → idempotent via recipient `UNIQUE` + `FOR UPDATE
  SKIP LOCKED` claim + terminal-status guard; no double sends.
- Per-language preview: **not needed** — single message, so the one preview is exact.

## 12. Testing

`broadcasts` is not in the ≥95% tier (payments/wallet/fulfillment/suppliers); target the
standard **≥ 80%** Python / **≥ 70%** TS, but cover the delivery + validator logic hard.

- **Unit:** HTML validator (whitelist pass/reject, injection attempts, unbalanced tags,
  length limits, href scheme); FSM transitions (every legal + illegal edge); MIME→method
  inference; chunk/pacing math.
- **Contract (respx):** Telegram responses — 200 with `file_id`, 403 blocked, 429
  `retry_after`, 400 entities → abort; `file_id` reuse across recipients; each media
  method (photo/video/animation/document).
- **Integration:** audience snapshot with locale filter and `bot_blocked_at` exclusion;
  idempotent re-delivery (double outbox → single send); cancel between chunks; scheduled
  due firing; test-send path; `bot_blocked_at` set on 403.
- **TS:** `TelegramEditor` serialize round-trip (DOM → Telegram HTML) for each mark;
  composer validation states; preview render parity with the sent HTML.

## 13. Docs (delivered in the same PRs)

- **ADR-0033** — new `broadcasts` module + **scheduler-driven fan-out** (why not outbox/
  broker) + the WYSIWYG-editor decision (with fallback).
- `docs/architecture/module-map.md` + a Mermaid sequence diagram
  `docs/architecture/sequence-diagrams/broadcast-send.mmd`.
- `apps/api/src/yupay/modules/broadcasts/README.md`.
- Runbook `docs/runbooks/broadcasts.md` — how to send/schedule/cancel, what
  blocked/failed mean, how a stuck `sending` resumes, Telegram rate limits, the
  first-send-abort behaviour.
- `apps/api/src/yupay/modules/storage/README.md` — new kind + limits.
- Regenerate `docs/api/openapi.json` + `packages/api-client`; notes in `docs/api/README.md`.
- No i18n locale files (admin RU-only; content is admin-authored).

## 14. Out of scope (v1)

- Email / in-app-banner channels.
- Per-locale message variants.
- Segment builder (buyers vs non-buyers, spend, dates) — audience is "all linked users +
  optional language".
- Albums / multiple attachments (one attachment only).
- Inline buttons / reply markup.
- A/B tests, open/click analytics, per-user scheduling, recurring broadcasts.
- WebSocket live progress (polling is v1; WS is a later enhancement).
- "Clone to new draft" from a sent broadcast (nice-to-have, not required).

## 15. Build order (feeds the implementation plan)

1. Migration: `broadcasts`, `broadcast_recipients`, `telegram_links.bot_blocked_at`.
2. `broadcasts` models + HTML validator (`sanitize.py`) + service (create/edit/FSM/
   audience-count/snapshot) — TDD.
3. Extend `notifications` Telegram channel: sendPhoto/Video/Animation/Document returning
   `file_id`.
4. Extend `storage`: `broadcast_media` kind, MIME, 20 MB cap.
5. Scheduler dispatch job `broadcast_dispatch` (promote scheduled, snapshot, SKIP-LOCKED
   chunk claim, pacing, per-recipient outcomes, file_id reuse, abort, finalize) + register
   in `apps/scheduler/main.py`.
6. Admin routes + schemas + api mount + OpenAPI/client regen.
7. Bot `/start` clears `bot_blocked_at`.
8. Admin UI: `TelegramEditor`, `BroadcastMediaUploader`, List / Composer / Detail pages,
   nav entry, qk/api.
9. Docs (ADR, module-map, sequence diagram, README, runbook, storage README).
