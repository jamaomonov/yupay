# Telegram Broadcasts (Рассылки) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let admins compose a formatted Telegram message with one optional media attachment, test it to themselves, and broadcast it to the whole bot audience (optionally filtered by language) — delivered in the background, throttled, resumable, with live counters.

**Architecture:** New backend module `broadcasts` (models + HTML validator + service + admin routes). Delivery is a periodic **scheduler job** (`apps/scheduler`, mirroring `waxpeer_reconcile`) that promotes due scheduled broadcasts, snapshots recipients, claims a chunk of `pending` via `FOR UPDATE SKIP LOCKED`, and sends paced ~25/s through the extended `notifications` Telegram channel. Media rides the existing `storage` R2 presign flow (extended for video/GIF/doc). Admin gets a `features/broadcasts` area with a Telegram-style composer.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2 async / Alembic / Pydantic v2 / APScheduler / httpx; React 19 + Vite + TanStack Query + React Router 7 (admin SPA); stdlib `html.parser` for validation (no new dependency).

**Spec:** `docs/superpowers/specs/2026-07-21-telegram-broadcasts-design.md` (read it — it holds the rationale).

## Global Constraints

- **Telegram HTML whitelist** — the ONLY allowed tags: `b`, `i`, `u`, `s`, `a` (href, scheme `http`/`https`/`tg` only), `code`, `pre`, `tg-spoiler`, `blockquote`. Line breaks are `\n` (no `<br>`). Anything else → reject on save (HTTP 422).
- **Length limits** (measured on *visible text*, tags stripped): **≤ 1024** chars with media (caption), **≤ 4096** text-only.
- **Media:** exactly one attachment or none. `media_type ∈ {none, photo, video, animation, document}`. Cap **20 MB**. MIME→method: `image/jpeg|png|webp`→sendPhoto, `image/gif`→sendAnimation, `video/mp4`→sendVideo, documents→sendDocument.
- **Statuses (FSM):** `draft`, `scheduled`, `sending`, `sent`, `failed`, `canceled`. Editable only in `draft`. `scheduled`→back to `draft` allowed. `scheduled`/`sending`→`canceled` allowed. `sent`/`failed`/`canceled` terminal.
- **Delivery:** pacing **~25 msg/s** (`asyncio.sleep(1/25)`), chunk **250**, dispatch interval **~5 s**, `max_instances=1`, `coalesce=True`. Claim pending with `FOR UPDATE SKIP LOCKED`.
- **Per-recipient outcomes:** 200→`sent` (capture `file_id` on first media send); 403→`blocked` + set `telegram_links.bot_blocked_at`; 429→sleep `retry_after`, retry same; 5xx/network→retry twice then `failed`; **first-send 400 "can't parse entities"→abort broadcast to `failed`**.
- **Audience:** `TelegramLink ⨝ User` where `telegram_links.bot_blocked_at IS NULL`, optional `users.locale` filter (`ru`/`en`/`uz`; `null`=all).
- **Auth/idempotency:** all write endpoints under `require_admin` and accept `Idempotency-Key` (`>= MIN_IDEMPOTENCY_KEY_LENGTH`). `send` also FSM-guarded (a non-draft can't be sent again).
- **Admin UI is RU-only** — hardcoded Russian strings, **no** i18n locale files. Broadcast *content* is admin-authored (not translated).
- **PII:** never log bot token, `tg_chat_id`, `tg_user_id`, or the message body. Broadcast id / counts are OK.
- **Times:** stored/compared **UTC**; API sends/receives ISO-8601 UTC instants.
- **No new backend dependency** for HTML validation (stdlib `html.parser.HTMLParser`).
- **Money rules N/A** (no money in this feature).

---

## File Structure

**Backend (`apps/api/src/yupay/modules/broadcasts/`)**
- `models.py` — `Broadcast`, `BroadcastRecipient` ORM.
- `sanitize.py` — Telegram-HTML whitelist validator + visible-length counter. Pure, no I/O.
- `schemas.py` — Pydantic DTOs.
- `service.py` — create/edit/FSM/audience-count/snapshot/render helpers.
- `routes.py` — admin router.
- `api.py` — public module surface (`admin_router`, service fns, models).
- `README.md`.
- `tests/` under `apps/api/tests/{unit,integration}/`.

**Backend edits**
- `apps/api/src/yupay/modules/notifications/channels/telegram.py` — add media senders returning `file_id`.
- `apps/api/src/yupay/modules/storage/service.py` — `broadcast_media` kind, MIME map, per-kind cap.
- `apps/api/src/yupay/core/config.py` — `broadcast_media_max_upload_bytes`, extend allowlists.
- `apps/api/src/yupay/api/v1/__init__.py` — mount `broadcasts` admin router.
- `apps/api/migrations/versions/NNNN_broadcasts.py` — tables + `telegram_links.bot_blocked_at`.

**Scheduler**
- `apps/scheduler/src/yupay_scheduler/jobs/broadcast_dispatch.py` — the dispatch job.
- `apps/scheduler/src/yupay_scheduler/main.py` — register it + import broadcasts models.

**Bot**
- `apps/bot/src/yupay_bot/main.py` — `/start` clears `bot_blocked_at`.

**Admin SPA (`apps/admin/src/`)**
- `components/TelegramEditor.tsx` — contenteditable WYSIWYG → Telegram HTML.
- `features/broadcasts/BroadcastMediaUploader.tsx` — one-file uploader (photo/video/gif/doc).
- `features/broadcasts/BroadcastsListPage.tsx`, `BroadcastComposerPage.tsx`, `BroadcastDetailPage.tsx`, `types.ts`, `telegramHtml.ts` (shared serialize/validate/preview helpers).
- `lib/queryKeys.ts`, `lib/api.ts` (additions), router + nav registration.

**Docs**
- `docs/decisions/0033-telegram-broadcasts.md`, `docs/architecture/module-map.md`, `docs/architecture/sequence-diagrams/broadcast-send.mmd`, `docs/runbooks/broadcasts.md`, `apps/api/src/yupay/modules/storage/README.md`.

---

## Task 1: Data model + migration

**Files:**
- Create: `apps/api/src/yupay/modules/broadcasts/__init__.py` (empty), `apps/api/src/yupay/modules/broadcasts/models.py`
- Create: `apps/api/migrations/versions/NNNN_broadcasts.py` (via `make migration name=broadcasts`)
- Modify: `apps/api/src/yupay/modules/users/models.py` (add `bot_blocked_at` to `TelegramLink`)
- Test: `apps/api/tests/integration/test_broadcasts_models.py`

**Interfaces:**
- Produces: `Broadcast`, `BroadcastRecipient` ORM (see columns below); `TelegramLink.bot_blocked_at: Mapped[datetime | None]`.

**Column reference (mirror `fulfillment/models.py` style — `UUID(as_uuid=False)`, `server_default=text(...)`):**

`broadcasts`: `id` (uuid PK), `title` (Text, not null), `status` (String(16), not null, server_default `'draft'`), `body_html` (Text, not null, server_default `''`), `media_type` (String(16), not null, server_default `'none'`), `media_url` (Text, nullable), `media_file_id` (Text, nullable), `locale_filter` (String(8), nullable), `disable_web_page_preview` (Boolean, not null, server_default `'true'`), `scheduled_at` (timestamptz, nullable), `total_recipients` (Integer, not null, server_default `'0'`), `sent_count`/`failed_count`/`blocked_count` (Integer, not null, server_default `'0'`), `started_at`/`finished_at` (timestamptz, nullable), `last_error` (Text, nullable), `created_by` (uuid FK `users.id`, not null), `created_at`/`updated_at` (timestamptz, server_default CURRENT_TIMESTAMP). CHECK `status IN ('draft','scheduled','sending','sent','failed','canceled')`; CHECK `media_type IN ('none','photo','video','animation','document')`.

`broadcast_recipients`: `id` (uuid PK), `broadcast_id` (uuid FK `broadcasts.id` ON DELETE CASCADE, not null), `user_id` (uuid FK `users.id`, not null), `tg_chat_id` (BigInteger, not null), `status` (String(12), not null, server_default `'pending'`), `error` (Text, nullable), `sent_at` (timestamptz, nullable), `created_at` (timestamptz, server_default CURRENT_TIMESTAMP). `UNIQUE(broadcast_id, user_id)` = `uq_broadcast_recipients_broadcast_user`. Index `ix_broadcast_recipients_broadcast_status` on `(broadcast_id, status)`. CHECK `status IN ('pending','sent','failed','blocked')`.

`telegram_links`: add `bot_blocked_at` timestamptz nullable.

- [ ] **Step 1: Write the model file** `models.py` with both classes (mirror `FulfillmentTask` column idioms), plus a `relationship` from `Broadcast.recipients` (`cascade="all, delete-orphan"`, `lazy="selectin"`). Add `bot_blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)` to `TelegramLink`.

- [ ] **Step 2: Generate + fill the migration**
Run: `make migration name=broadcasts`
Then hand-write `upgrade()` / `downgrade()` with `op.create_table` for both tables (columns + CHECKs + unique + index above) and `op.add_column("telegram_links", sa.Column("bot_blocked_at", sa.DateTime(timezone=True), nullable=True))`. `downgrade()` drops the column then both tables.

- [ ] **Step 3: Register models in the metadata-touch lists**
Modify `apps/scheduler/src/yupay_scheduler/main.py` — add `from yupay.modules.broadcasts import models as _broadcasts_models  # noqa: F401`. (The API loads models via its own module import graph once the router is mounted in Task 6; the scheduler needs the explicit touch because it imports the dispatch job, which imports these models — add it now so Task 7's migration/tests resolve FKs.)

- [ ] **Step 4: Write the failing integration test** `test_broadcasts_models.py`: insert a `Broadcast` + two `BroadcastRecipient` rows against the testcontainers Postgres, assert the `UNIQUE(broadcast_id, user_id)` raises on a dup, and that `bot_blocked_at` defaults to `NULL` on a fresh `TelegramLink`.

- [ ] **Step 5: Run migration + test**
Run: `make migrate` then `cd apps/api && uv run pytest tests/integration/test_broadcasts_models.py -v`
Expected: PASS. Then `uv run mypy src/yupay/modules/broadcasts/models.py` → clean.

- [ ] **Step 6: Commit**
```bash
git add apps/api/src/yupay/modules/broadcasts apps/api/migrations/versions apps/api/src/yupay/modules/users/models.py apps/scheduler/src/yupay_scheduler/main.py apps/api/tests/integration/test_broadcasts_models.py
git commit -m "feat(broadcasts): data model + migration (broadcasts, recipients, bot_blocked_at)"
```

---

## Task 2: Telegram-HTML validator (`sanitize.py`)

**Files:**
- Create: `apps/api/src/yupay/modules/broadcasts/sanitize.py`
- Test: `apps/api/tests/unit/test_broadcasts_sanitize.py`

**Interfaces:**
- Produces:
  - `ALLOWED_TAGS: frozenset[str]` = `{"b","i","u","s","a","code","pre","tg-spoiler","blockquote"}`
  - `visible_length(html: str) -> int` — length of the text with tags removed and HTML entities decoded.
  - `validate_body(html: str, *, has_media: bool) -> None` — raises `yupay.core.errors.ValidationError` on any violation (disallowed tag/attr, bad `a` scheme, unbalanced/mis-nested tags, over-length). Empty `html` is allowed only when `has_media` is True (caller enforces the "empty + no media" case; this fn only checks the length ceiling: 1024 if `has_media` else 4096).

**Implementation notes:** Build a small subclass of `html.parser.HTMLParser`. Track an open-tag stack. On `handle_starttag`: reject if tag ∉ ALLOWED_TAGS; for `a` require exactly an `href` attr with scheme in `{http,https,tg}` and no other attrs; for every other allowed tag reject if any attrs present; push onto stack. On `handle_endtag`: reject if it doesn't match the top of the stack (mis-nesting / unbalanced). On `handle_data`: accumulate text for the visible-length count. At end, stack must be empty. `visible_length` uses a second parser pass (or the same one) accumulating only `handle_data`, then `html.unescape`.

- [ ] **Step 1: Write failing tests** covering: plain text passes; each allowed tag passes (`<b>x</b>`, `<tg-spoiler>x</tg-spoiler>`, `<a href="https://a.b">x</a>`); `<script>` rejected; `<div>` rejected; `<b class="x">` rejected (stray attr); `<a href="javascript:…">` rejected (scheme); `<b><i>x</b></i>` rejected (mis-nested); `<b>x` rejected (unbalanced); over-length caption (1025 visible chars with `has_media=True`) rejected; 2000 visible chars with `has_media=False` passes; 4097 with `has_media=False` rejected; `visible_length("<b>ab</b>&amp;c") == 4`.

- [ ] **Step 2: Run** `cd apps/api && uv run pytest tests/unit/test_broadcasts_sanitize.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement `sanitize.py`.**

- [ ] **Step 4: Run tests** → PASS; `uv run mypy src/yupay/modules/broadcasts/sanitize.py` → clean; `uv run ruff check src/yupay/modules/broadcasts/sanitize.py`.

- [ ] **Step 5: Commit** `feat(broadcasts): Telegram-HTML whitelist validator`.

---

## Task 3: Storage — broadcast media kind, MIME, 20 MB cap

**Files:**
- Modify: `apps/api/src/yupay/core/config.py` (add setting + MIME)
- Modify: `apps/api/src/yupay/modules/storage/service.py` (kind, MIME map, per-kind cap)
- Modify: `apps/api/src/yupay/modules/storage/README.md`
- Test: `apps/api/tests/unit/test_storage_broadcast_media.py`

**Interfaces:**
- `MediaKind` gains `"broadcast_media"`.
- `presign_upload(*, kind, content_type, size_bytes)` now caps broadcast kinds at `settings.broadcast_media_max_upload_bytes` (20 MB) and validates `content_type` **per kind**: image kinds keep the image-only set; `broadcast_media` also allows `video/mp4`, `image/gif`, `application/pdf`.

- [ ] **Step 1: Config** — add to `config.py`: `broadcast_media_max_upload_bytes: int = Field(default=20 * 1024 * 1024)`. Extend `media_allowed_mime` default list with `"image/gif"`, `"video/mp4"`, `"application/pdf"`.

- [ ] **Step 2: Storage service** — add to `MediaKind` literal `"broadcast_media"`. Extend `_MIME_TO_EXT` with `"image/gif":"gif"`, `"video/mp4":"mp4"`, `"application/pdf":"pdf"`. Add a per-kind allowlist map `_KIND_ALLOWED_MIME: dict[str, set[str]]` — image kinds → the 4 image types; `"broadcast_media"` → images + gif + mp4 + pdf. In `presign_upload`, validate `content_type in _KIND_ALLOWED_MIME[kind]` (raise `ValidationError` otherwise) and pick the cap: `cap = settings.broadcast_media_max_upload_bytes if kind == "broadcast_media" else settings.media_max_upload_bytes`; use `cap` in the size check and in `PresignResult.max_bytes`.

- [ ] **Step 3: Failing tests** — `broadcast_media` presign accepts `video/mp4` (returns `.mp4` key, `max_bytes == 20MB`); rejects `application/zip`; a `brand_logo` presign still rejects `video/mp4` (image kinds unchanged); oversize (21 MB) `broadcast_media` rejected. Mock the S3 client the same way the existing storage tests do.

- [ ] **Step 4: Run** → PASS; mypy + ruff clean.

- [ ] **Step 5: Update `storage/README.md`** — document the new kind, allowed types, and 20 MB cap for broadcasts.

- [ ] **Step 6: Commit** `feat(storage): broadcast_media kind (video/gif/pdf, 20 MB)`.

---

## Task 4: Telegram channel — media senders returning `file_id`

**Files:**
- Modify: `apps/api/src/yupay/modules/notifications/channels/telegram.py`
- Test: `apps/api/tests/contract/test_telegram_channel_media.py` (respx)

**Interfaces:**
- Produces a single entry point used by both the dispatch job and test-send:
```python
@dataclass(frozen=True, slots=True)
class SendOutcome:
    ok: bool
    file_id: str | None = None      # captured on a successful media send
    status: int = 0                  # HTTP status (0 = network error)
    retry_after: int | None = None   # from 429
    description: str = ""            # Telegram error description, truncated

async def send_broadcast_message(
    *, bot_token: str, chat_id: int,
    body_html: str, media_type: str,          # "none"|"photo"|"video"|"animation"|"document"
    media_url_or_file_id: str | None,          # URL on first send, file_id afterwards
    disable_web_page_preview: bool = True,
) -> SendOutcome: ...
```
Method + payload field by `media_type`: `none`→`sendMessage` (`text`, `parse_mode=HTML`); `photo`→`sendPhoto` (`photo`, `caption`); `video`→`sendVideo` (`video`, `caption`); `animation`→`sendAnimation` (`animation`, `caption`); `document`→`sendDocument` (`document`, `caption`). Capture `file_id` from the 200 response: photo→`result.photo[-1].file_id`, video→`result.video.file_id`, animation→`result.animation.file_id`, document→`result.document.file_id`. On 429 read `parameters.retry_after`. Reuse the existing `_get_client()` (proxy-aware). Never raise — return `SendOutcome(ok=False, …)`; never log the body/chat_id (mirror the existing redaction).

- [ ] **Step 1: Failing contract tests** with respx stubbing `api.telegram.org`: `sendMessage` 200→`ok, file_id None`; `sendPhoto` 200 with `result.photo:[{file_id:"F"}]`→`ok, file_id="F"`; 403 `{"description":"Forbidden: bot was blocked by the user"}`→`ok=False, status=403`; 429 `{"parameters":{"retry_after":7}}`→`retry_after==7`; 400 `{"description":"can't parse entities…"}`→`ok=False, status=400`. Assert the correct method URL + payload field per media type.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** `SendOutcome` + `send_broadcast_message` (keep `send_message` as-is for existing callers).

- [ ] **Step 4: Run** → PASS; mypy + ruff clean.

- [ ] **Step 5: Commit** `feat(notifications): Telegram media senders returning file_id`.

---

## Task 5: Broadcasts service + schemas (create / edit / FSM / audience / snapshot)

**Files:**
- Create: `apps/api/src/yupay/modules/broadcasts/schemas.py`, `apps/api/src/yupay/modules/broadcasts/service.py`
- Test: `apps/api/tests/integration/test_broadcasts_service.py`

**Interfaces (service — all `async def`, `db: AsyncSession` first):**
- `create_draft(db, *, actor_id, data: BroadcastCreateIn) -> Broadcast`
- `update_draft(db, *, broadcast_id, data: BroadcastUpdateIn) -> Broadcast` — 409 (`ConflictError`) if status ∉ {draft, scheduled}; a `scheduled` edit resets to `draft` and clears `scheduled_at`.
- `delete_draft(db, *, broadcast_id) -> None` — 409 unless draft.
- `get(db, *, broadcast_id) -> Broadcast` — 404 (`NotFoundError`) if missing.
- `list_broadcasts(db, *, status_filter=None, limit=50, offset=0) -> tuple[list[Broadcast], int]` — newest `created_at` first.
- `audience_count(db, *, locale_filter: str | None) -> int` — COUNT of `TelegramLink ⨝ User` with `bot_blocked_at IS NULL` (+ `users.locale == locale_filter` when set).
- `mark_send_now(db, *, broadcast_id) -> Broadcast` — validate body (via `sanitize.validate_body`, `has_media = media_type != 'none'`) and the "empty body + no media" rule; 409 unless draft/scheduled; set `status='sending'`, `scheduled_at=None`.
- `schedule(db, *, broadcast_id, scheduled_at: datetime) -> Broadcast` — same validation; 422 (`ValidationError`) if `scheduled_at <= now() + 5s`; 409 unless draft/scheduled; set `status='scheduled'`.
- `cancel(db, *, broadcast_id) -> Broadcast` — 409 unless status ∈ {scheduled, sending}; set `status='canceled'`, `finished_at=now()`.
- `list_recipients(db, *, broadcast_id, status_filter=None, limit=100, offset=0) -> tuple[list[BroadcastRecipient], int]`.

**Validation rules inside `mark_send_now`/`schedule`:** if `media_type == 'none'` and `body_html.strip() == ''` → `ValidationError("сообщение пустое")`. Always call `sanitize.validate_body`.

**Schemas:** `BroadcastCreateIn`/`BroadcastUpdateIn` (`title`, `body_html`, `media_type`, `media_url`, `locale_filter`, `disable_web_page_preview`); `BroadcastOut` (all row fields + counters + `status`); `BroadcastListOut` (`items`, `total`); `RecipientOut` (`user_id`, `tg_chat_id` as string, `status`, `error`, `sent_at`); `ScheduleIn` (`scheduled_at: datetime`); `AudienceCountOut` (`count: int`). Use `model_config = ConfigDict(from_attributes=True)`. `media_type`/`locale_filter`/`status` typed as `Literal[...]`.

- [ ] **Step 1: Write schemas** with the Literals and validators (`locale_filter ∈ {ru,en,uz}` or None; `media_type` ∈ the 5).

- [ ] **Step 2: Failing integration tests** (`test_broadcasts_service.py`): create draft → status draft; `audience_count` respects `bot_blocked_at` + locale (seed 3 linked users, one blocked, one `en`); `mark_send_now` on a body with `<script>` → `ValidationError`; empty body + no media → `ValidationError`; `schedule` with past time → `ValidationError`; `cancel` a `sent` broadcast → `ConflictError`; `update_draft` on a `sent` → `ConflictError`.

- [ ] **Step 3: Run** → FAIL.

- [ ] **Step 4: Implement `service.py`** (use `yupay.core.clock.now`, `yupay.core.errors.{ValidationError,ConflictError,NotFoundError}`, `yupay.core.ids.new_id`).

- [ ] **Step 5: Run** → PASS; mypy + ruff clean; confirm ≥80% coverage on `service.py` (`uv run pytest tests/integration/test_broadcasts_service.py --cov=yupay.modules.broadcasts.service`).

- [ ] **Step 6: Commit** `feat(broadcasts): service + schemas (FSM, audience, validation)`.

---

## Task 6: Admin routes + api surface + mount + OpenAPI/client regen

**Files:**
- Create: `apps/api/src/yupay/modules/broadcasts/routes.py`, `apps/api/src/yupay/modules/broadcasts/api.py`
- Modify: `apps/api/src/yupay/api/v1/__init__.py` (import + `include_router`)
- Test: `apps/api/tests/integration/test_broadcasts_routes.py`

**Interfaces (all under `admin_router = APIRouter(prefix="/admin/broadcasts", tags=["admin:broadcasts"], dependencies=[Depends(require_admin)])`):** the endpoints from spec §10. Mirror `promo/routes.py` for the `require_admin` + `Idempotency-Key` pattern (`IDEMPOTENCY_HEADER`, `_require_idempotency_key` helper). `test`, `send`, `schedule`, `cancel`, `POST`, `PATCH`, `DELETE` require the key.

**Test-send handler:** `POST /admin/broadcasts/{id}/test` — look up the calling admin's `TelegramLink`; 400 (`ValidationError "привяжите Telegram…"`) if none; render via `broadcasts.service` + `notifications.channels.telegram.send_broadcast_message` with the media **URL** (not file_id); return `{"ok": bool}`. Does not change broadcast status.

**Audience count:** `GET /admin/broadcasts/audience-count?locale=` → `AudienceCountOut`.

- [ ] **Step 1: Write `routes.py`** (each handler thin — parse + call service; routers hold no business logic). `api.py` re-exports `admin_router`, `Broadcast`, `BroadcastRecipient`, and the service functions the dispatch job needs (`get`, `list_broadcasts` not needed by job; the job imports `service` directly — see Task 7 note on avoiding the `api`→`routes`→`api/v1` cycle).

- [ ] **Step 2: Mount** in `apps/api/src/yupay/api/v1/__init__.py`: `from yupay.modules.broadcasts.api import admin_router as broadcasts_admin_router` and `router.include_router(broadcasts_admin_router)` next to the other admin routers.

- [ ] **Step 3: Failing integration tests** (mirror `test_admin_fulfillment_bulk_routes.py` auth helpers): 401 without token; create→200; `send` without `Idempotency-Key`→422; `send` a draft with valid body→200 and status `sending`; `send` again→409; `test` when admin has no TelegramLink→400; `audience-count` returns the seeded count.

- [ ] **Step 4: Run** → PASS.

- [ ] **Step 5: Regenerate API artifacts**
Run: `cd apps/api && uv run python -m yupay.scripts.export_openapi ../../docs/api/openapi.json && cd ../.. && pnpm --filter @yupay/api-client gen:api`
Expected: `docs/api/openapi.json` gains the `/admin/broadcasts*` paths; `git status` shows the openapi change (client may or may not change).

- [ ] **Step 6: Commit** `feat(broadcasts): admin routes + mount + OpenAPI` (include regenerated files).

---

## Task 7: Scheduler dispatch job

**Files:**
- Create: `apps/scheduler/src/yupay_scheduler/jobs/broadcast_dispatch.py`
- Modify: `apps/scheduler/src/yupay_scheduler/main.py` (register)
- Test: `apps/api/tests/integration/test_broadcast_dispatch.py`

**Interfaces:**
- `register(scheduler: AsyncIOScheduler) -> None` — `add_job(run_broadcast_dispatch, trigger="interval", seconds=5, id="broadcasts.dispatch", replace_existing=True, max_instances=1, coalesce=True)`.
- `run_broadcast_dispatch() -> None` — one tick.
- Import `service` **directly** (`from yupay.modules.broadcasts.service import …`) not `.api`, to avoid the `api`→`routes`→`api/v1` circular import (see the identical note in `waxpeer_reconcile.py`).

**Tick algorithm (each phase in its own committed transaction; failures isolated per broadcast, logged with id only — never body/chat_id):**
1. `promote_due(db)` — `UPDATE broadcasts SET status='sending', started_at=COALESCE(started_at, now()) WHERE status='scheduled' AND scheduled_at <= now()`.
2. Load ids of `status='sending'` broadcasts (oldest `started_at` first).
3. For each id, in its own session: reload; if `canceled`/terminal → skip. Snapshot recipients if `total_recipients == 0` and none exist: `INSERT INTO broadcast_recipients (…) SELECT … FROM telegram_links JOIN users … WHERE bot_blocked_at IS NULL [AND users.locale = :loc] ON CONFLICT DO NOTHING`; set `total_recipients`. If the snapshot is empty → finalize `sent`, `finished_at=now()`, continue.
4. Claim a chunk: `SELECT * FROM broadcast_recipients WHERE broadcast_id=:id AND status='pending' ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 250`. If empty → finalize `sent`, `finished_at`, continue.
5. For each claimed recipient, paced `await asyncio.sleep(1/25)`: call `send_broadcast_message` with `media_url_or_file_id = broadcast.media_file_id or broadcast.media_url`. Apply the per-recipient outcome rules (Global Constraints). Capture `file_id` into `broadcast.media_file_id` on the first successful media send. **First send of the whole broadcast returning 400 → set broadcast `failed` + `last_error`, break.** On 429 → `asyncio.sleep(retry_after)` then retry the same recipient once. Update counters (`sent_count`/`failed_count`/`blocked_count`) and each recipient row; on 403 also `UPDATE telegram_links SET bot_blocked_at=now() WHERE tg_user_id=:chat`.
6. Commit. (Next tick continues remaining `pending`.)

Per-tick global cap: process at most **one chunk per broadcast per tick** (already bounded by LIMIT 250) and at most the 5 oldest sending broadcasts, so a tick stays ~10 s.

- [ ] **Step 1: Failing integration tests** (`test_broadcast_dispatch.py`, respx for Telegram): seed a `sending` broadcast + 3 linked users → one tick snapshots + sends → all `sent`, counters right, status `sent`. 403 for one user → that recipient `blocked` + `telegram_links.bot_blocked_at` set. A `scheduled` broadcast due in the past → promoted to `sending` then sent. A second tick over an already-`sent` broadcast → no extra Telegram calls (idempotent). First-send 400 → broadcast `failed`, nothing else sent. `canceled` mid-flight (set status between snapshot and chunk) → job stops. Pin `RATE` fast in tests (e.g. monkeypatch the sleep) so tests don't wait.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** the job; make `RATE`/`CHUNK` module constants so tests can monkeypatch pacing.

- [ ] **Step 4: Register** in `main.py` (`broadcast_dispatch.register(scheduler)`), keep the models-touch import from Task 1.

- [ ] **Step 5: Run** → PASS; mypy + ruff clean.

- [ ] **Step 6: Commit** `feat(scheduler): broadcast dispatch job (snapshot, chunked, paced)`.

---

## Task 8: Bot `/start` clears `bot_blocked_at`

**Files:**
- Modify: `apps/bot/src/yupay_bot/main.py` (in the `/start` handler, after resolving/creating the user)
- Test: `apps/bot/tests/test_start_unblocks.py` (or extend existing bot tests)

**Interfaces:** on `/start`, if the sender has a `TelegramLink`, `UPDATE telegram_links SET bot_blocked_at = NULL WHERE tg_user_id = :id`. Re-engaging the bot means they can receive broadcasts again.

- [ ] **Step 1: Failing test** — simulate `/start` from a user whose link has `bot_blocked_at` set; assert it becomes `NULL`. Mirror the existing bot test harness (`apps/bot/tests/`).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — add the update in the `/start` handler path that already touches the DB (mirror how the handler currently upserts the link / logs `bot.start`).
- [ ] **Step 4: Run** → PASS; mypy + ruff clean.
- [ ] **Step 5: Commit** `feat(bot): clear bot_blocked_at on /start`.

---

## Task 9: `TelegramEditor` component (contenteditable → Telegram HTML)

**Files:**
- Create: `apps/admin/src/features/broadcasts/telegramHtml.ts` (pure serialize/validate/preview)
- Create: `apps/admin/src/components/TelegramEditor.tsx`
- Test: `apps/admin/src/features/broadcasts/telegramHtml.test.ts`

**Interfaces (`telegramHtml.ts`):**
- `serialize(root: HTMLElement): string` — walk the contenteditable DOM → Telegram HTML string (marks → `b/i/u/s/code/tg-spoiler/a`; block boundaries → `\n`; escape `<`,`>`,`&` in text).
- `previewHtml(telegramHtml: string): string` — Telegram HTML → safe HTML for the preview bubble (`\n`→`<br>`, `tg-spoiler`→`<span class="spoiler">`), whitelist-guarded.
- `visibleLength(telegramHtml: string): number` — mirrors the server counter.
- `MAX_WITH_MEDIA = 1024`, `MAX_TEXT = 4096`, `ALLOWED_TAGS` (same set as backend).

**`TelegramEditor.tsx` props:** `{ value: string; onChange: (telegramHtml: string) => void; maxLength: number }`. A toolbar (B/I/U/S/spoiler/link/code) toggling marks on the current selection via the `Selection`/`Range` API (use `document.execCommand` for bold/italic/underline/strikethrough — still supported in all target browsers; wrap selection manually for spoiler/link/code), then `onChange(serialize(editorEl))`. Deep-link/spoiler insert via a tiny inline prompt. See the ADR (Task 14) — if contenteditable proves too fiddly, the documented fallback is a toolbar-wrapped `<textarea>` + the same `previewHtml`.

- [ ] **Step 1: Failing unit tests** for `telegramHtml.ts` (jsdom): `serialize` of a DOM with `<b>` → `"<b>..</b>"`; two paragraphs → `"a\nb"`; a text node with `<` → escaped `&lt;`; `visibleLength("<b>ab</b>") === 2`; `previewHtml("<tg-spoiler>x</tg-spoiler>")` contains `class="spoiler"` and no raw `tg-spoiler`. Build DOM via `document.createElement`.

- [ ] **Step 2: Run** `pnpm --filter @yupay/admin exec vitest run src/features/broadcasts/telegramHtml.test.ts` → FAIL.

- [ ] **Step 3: Implement** `telegramHtml.ts` then `TelegramEditor.tsx`.

- [ ] **Step 4: Run** tests → PASS; `pnpm --filter @yupay/admin exec tsc --noEmit` clean.

- [ ] **Step 5: Commit** `feat(admin): TelegramEditor + Telegram-HTML serializer`.

---

## Task 10: Admin API/query keys/types + `BroadcastMediaUploader`

**Files:**
- Modify: `apps/admin/src/lib/queryKeys.ts` (add `broadcasts`, `broadcast`, `broadcastRecipients`, `broadcastAudience`)
- Create: `apps/admin/src/features/broadcasts/types.ts`
- Create: `apps/admin/src/features/broadcasts/BroadcastMediaUploader.tsx`

**Interfaces:**
- `qk.broadcasts(filters?: { status?: string | null })`, `qk.broadcast(id)`, `qk.broadcastRecipients(id, status)`, `qk.broadcastAudience(locale)`.
- `types.ts` — mirror the OpenAPI DTOs: `BroadcastOut`, `BroadcastListOut`, `RecipientOut`, `MediaType`, `BroadcastStatus`, `LocaleFilter`.
- `BroadcastMediaUploader` — mirror `components/ImageUploader.tsx` but `kind="broadcast_media"`, `ACCEPT_LIST = ["image/png","image/jpeg","image/webp","image/gif","video/mp4","application/pdf"]`, `MAX_BYTES = 20*1024*1024`, and `onChange(url, mediaType)` where `mediaType` is derived from the file MIME (gif→animation, mp4→video, pdf→document, else photo). Shows a filename/size/type chip; supports "Заменить"/"Убрать".

- [ ] **Step 1: Add query keys** + `types.ts` (hand-typed from the regenerated OpenAPI in Task 6).
- [ ] **Step 2: Implement `BroadcastMediaUploader.tsx`** (copy ImageUploader's presign→PUT handshake; swap accept list, cap, and the derived media type).
- [ ] **Step 3: Typecheck** `pnpm --filter @yupay/admin exec tsc --noEmit` clean; `pnpm --filter @yupay/admin exec eslint src/features/broadcasts` clean.
- [ ] **Step 4: Commit** `feat(admin): broadcasts api keys, types, media uploader`.

---

## Task 11: Broadcasts list page + nav + route

**Files:**
- Create: `apps/admin/src/features/broadcasts/BroadcastsListPage.tsx`
- Modify: the admin router + sidebar nav (mirror where `promo` / `users` register their route + nav entry — grep `features/promo` in the router and nav files).
- Test: `apps/admin/src/features/broadcasts/BroadcastsListPage.test.tsx` (Testing Library — render with a mocked query client, assert rows + status badges).

**Interface:** `GET /api/v1/admin/broadcasts?status_filter=` → DataTable (title, status badge, audience, `sent/failed/blocked`, when, author). "Новая рассылка" button → `/broadcasts/new`. Status badge component with the six states (Черновик / Запланирована / Отправляется + progress / Отправлено / Ошибка / Отменена) — mirror `promo` `StatusBadge`.

- [ ] **Step 1: Failing test** rendering the page with a stubbed list response (2 rows) → asserts the titles + a status badge text.
- [ ] **Step 2: Implement** the page (mirror `UsersListPage`/`PromoPage` DataTable usage + `PageHeader`).
- [ ] **Step 3: Register** route + nav entry.
- [ ] **Step 4: Run** vitest → PASS; tsc + eslint clean.
- [ ] **Step 5: Commit** `feat(admin): broadcasts list page + nav`.

---

## Task 12: Composer page (compose / edit / preview / test / send / schedule)

**Files:**
- Create: `apps/admin/src/features/broadcasts/BroadcastComposerPage.tsx`
- Create: `apps/admin/src/features/broadcasts/BroadcastPreview.tsx` (the phone bubble)
- Modify: admin router (routes `/broadcasts/new` and `/broadcasts/:id/edit`)
- Test: `apps/admin/src/features/broadcasts/BroadcastComposerPage.test.tsx`

**Interface / behavior:** left column — title input, `TelegramEditor` (maxLength derived from whether media is attached: 1024 with media, 4096 without), `BroadcastMediaUploader`, locale chips (Все/RU/EN/UZ → `locale_filter`), send-mode radios (Сейчас / Запланировать + datetime-local converted to UTC ISO), actions **Тест себе / Сохранить черновик / Отправить**. Right column — `BroadcastPreview` rendering `previewHtml(body)` + the media thumb, live audience count via `GET /admin/broadcasts/audience-count?locale=`. "Отправить" opens a confirm modal (recipient count) → `POST …/{id}/send` (save draft first if new). "Тест себе" → `POST …/{id}/test` → toast. Client-side length guard mirrors the server; block send when over-length or empty. Send/schedule/test/create/update all send a fresh `Idempotency-Key` header (use `crypto.randomUUID()`; mirror any existing admin idempotency usage).

- [ ] **Step 1: Failing test** — render composer, type a title + body, assert the preview shows the text and the "Отправить" button opens a confirm dialog with the audience number (stub the audience-count query).
- [ ] **Step 2: Implement** `BroadcastPreview.tsx` then `BroadcastComposerPage.tsx`.
- [ ] **Step 3: Register** routes.
- [ ] **Step 4: Run** vitest → PASS; tsc + eslint clean; `pnpm --filter @yupay/admin exec prettier --check src/features/broadcasts`.
- [ ] **Step 5: Commit** `feat(admin): broadcast composer + preview`.

---

## Task 13: Detail page (live counters / cancel / problem recipients)

**Files:**
- Create: `apps/admin/src/features/broadcasts/BroadcastDetailPage.tsx`
- Modify: admin router (route `/broadcasts/:id`)
- Test: `apps/admin/src/features/broadcasts/BroadcastDetailPage.test.tsx`

**Interface:** `GET /admin/broadcasts/{id}` with `refetchInterval: 3000` while `status === "sending"` (else no interval). Header with status badge + progress (`sent+failed+blocked` / `total`). "Отменить отправку" button (visible when `sending`/`scheduled`) → `POST …/{id}/cancel` (with Idempotency-Key). Problem-recipients table from `GET …/{id}/recipients?status=failed` and `?status=blocked`.

- [ ] **Step 1: Failing test** — render a `sending` broadcast (stubbed) → shows counters + a "Отменить отправку" button; clicking it fires the cancel mutation (assert the POST).
- [ ] **Step 2: Implement** the page.
- [ ] **Step 3: Register** route.
- [ ] **Step 4: Run** vitest → PASS; tsc + eslint clean.
- [ ] **Step 5: Commit** `feat(admin): broadcast detail with live counters + cancel`.

---

## Task 14: Documentation

**Files:**
- Create: `docs/decisions/0033-telegram-broadcasts.md` (MADR template)
- Create: `apps/api/src/yupay/modules/broadcasts/README.md`
- Create: `docs/runbooks/broadcasts.md`
- Create: `docs/architecture/sequence-diagrams/broadcast-send.mmd`
- Modify: `docs/architecture/module-map.md`

**Content requirements:**
- **ADR-0033** — records: the new `broadcasts` module; **scheduler-driven fan-out** and *why not* the outbox/broker (outbox is a stub, API has no broker — see spec §3); the **contenteditable WYSIWYG** editor choice + the textarea+preview fallback; the `file_id`-reuse optimization; the first-send-abort safety.
- **module README** — responsibilities, tables, FSM diagram, HTTP surface, the Telegram-HTML whitelist, the dispatch job, `bot_blocked_at` lifecycle.
- **runbook** — how to compose/test/send/schedule/cancel; what `failed`/`blocked` mean; how a stuck `sending` resumes (the dispatch job just keeps draining `pending`); Telegram rate limits; the first-send-abort behavior; how to check the audience query.
- **sequence diagram** — admin → API (send) → status flip → scheduler tick → Telegram → counters, Mermaid.
- **module-map** — add `broadcasts` with its edges (users, storage, notifications, scheduler).

- [ ] **Step 1: Write ADR-0033** from `docs/decisions/0000-template.md`.
- [ ] **Step 2: Write the module README + runbook + sequence diagram; update module-map.**
- [ ] **Step 3: Sanity-check** `pnpm exec prettier --check .` passes on the new markdown; Mermaid block parses (fenced ```mermaid or `.mmd`).
- [ ] **Step 4: Commit** `docs(broadcasts): ADR-0033, README, runbook, sequence diagram, module-map`.

---

## Final verification (after all tasks)

- [ ] `make lint typecheck test` green (Python + TS).
- [ ] `make gen-api` produces no drift (openapi + client already committed in Task 6).
- [ ] Manual smoke on dev: create a draft with a photo, "Тест себе" arrives in the admin's Telegram, "Отправить" to a 2-user dev base delivers both, counters reach `2/0/0`, blocking the bot on one account then re-broadcasting excludes them.
