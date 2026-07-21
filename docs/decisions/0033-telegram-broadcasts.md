# 0033. Telegram broadcasts: scheduler-driven fan-out, not outbox/broker

- **Status**: Accepted
- **Date**: 2026-07-21
- **Deciders**: @jamaomonov
- **Tags**: backend | frontend | product

## Context and problem statement

Admins need a screen to compose a message (formatted text + one optional
photo/video/GIF/document) and fan it out to every Telegram-linked user, safely
and at scale: preview it exactly as it will render, test-send to themselves,
send now or schedule, then watch live delivery counters while thousands of
per-user sends happen in the background.

The interesting design question isn't the CRUD — it's **who actually presses
"send" on each of 5,000 Telegram API calls**, and how that fan-out survives a
crash without either losing recipients or double-messaging the whole
audience. This module also introduces the first admin-authored **rich-text**
input in the codebase: raw HTML would be an XSS/injection surface the moment
it's rendered anywhere (the composer's own preview, in-app if a "delivery
history" view is ever added), so the input's shape and its validation had to
be decided together.

## Decision drivers

- No new background-processing primitive to stand up correctly under time
  pressure — the codebase already has one proven periodic-job mechanism.
- A crash mid-fan-out must be recoverable without a human replaying the whole
  broadcast, and must not multiply into thousands of duplicate messages.
- One bad message body must not cost thousands of `failed` rows before anyone
  notices.
- The composer needs real bold/italic/spoiler/link formatting with a preview
  that matches what Telegram will actually render — a plain `<textarea>`
  isn't the product ask, but a heavy rich-text editor library is a lot of
  weight for seven marks.
- Media (photo/video/GIF/document) must not force re-uploading the same file
  to Telegram's CDN thousands of times.

## Considered options

1. **Scheduler periodic job** (chosen) — `apps/scheduler` runs a job every
   ~5 s that promotes due broadcasts and drains their recipient backlog in
   paced chunks, mirroring the existing `waxpeer_reconcile` sweep.
2. **Outbox + Dramatiq worker** — `core/outbox` emits one event per
   broadcast, a `broadcasts.dispatch` actor on the existing worker queue fans
   it out.
3. **Fire-and-forget inline task** — the `send` endpoint itself loops over
   recipients and calls Telegram synchronously before responding.

For the editor:

1. **Contenteditable WYSIWYG** (chosen) — a small toolbar over a
   `contentEditable` `<div>`, serializing the live DOM to Telegram-HTML.
2. **Toolbar-wrapped `<textarea>` + live preview** — marks are inserted as
   literal `<b>...</b>` text; a separate pane renders the preview.
3. **A full rich-text editor dependency** (Tiptap/Slate/Lexical) driving the
   same whitelist.

## Decision outcome

**Chosen option (delivery): the scheduler job.** `core/outbox` is still a
stub (no consumer, no worker actor exists that drains it) and the API
process holds no Dramatiq broker connection at all — introducing either
one just to kick off a broadcast would mean standing up and hardening two
pieces of unproven machinery (an outbox consumer, a broker connection in a
process that has never needed one) for a single feature, and betting the
first production use of both on a mass-messaging job with a real user-facing
blast radius. `apps/scheduler` already runs `waxpeer_reconcile` — a periodic
sweep that claims work, drives it to a terminal state, and tolerates
overlapping ticks — so `broadcast_dispatch.py` reuses that exact shape:
`POST /admin/broadcasts/{id}/send` is a **status flip only** (`sending`, no
queue, no message published anywhere); the next tick (≤ ~5 s later) is what
actually starts moving messages. `docs/architecture/module-map.md` gains an
edge from `broadcasts` to the scheduler process to make this explicit — the
module's own Python package never talks to Telegram; the job does.

Delivery is **at-least-once, not exactly-once**. Each tick claims a bounded
chunk (`CHUNK = 250`) of `pending` `broadcast_recipients` rows via
`SELECT … FOR UPDATE SKIP LOCKED`, and — critically — **delivers and commits
one recipient at a time**, in its own short transaction, before moving to
the next: the Telegram call happens _inside_ that recipient's transaction,
and the `pending → sent/failed/blocked` row update commits immediately after
it succeeds, before the paced `asyncio.sleep(1 / RATE)` between sends. A
crash or SIGTERM can therefore only ever catch **one** recipient between "we
sent it" and "we committed that we sent it" — a bounded ~1-recipient
duplicate window, never a whole in-flight chunk of 250. The `UNIQUE
(broadcast_id, user_id)` constraint plus the `FOR UPDATE SKIP LOCKED` claim
also make two overlapping ticks (or a slow tick and its successor) safe:
they can never grab the same row, and re-snapshotting is `ON CONFLICT DO
NOTHING`. This is a deliberate, bounded trade-off against a true
exactly-once design (which would need either a Telegram-side dedup key,
which the Bot API doesn't offer, or a two-phase claim/commit protocol) — for
a promotional broadcast, one recipient occasionally seeing a duplicate
message after an operator-triggered crash is an acceptable cost next to the
complexity a stronger guarantee would add.

**First-send abort.** A send returning Telegram HTTP 400 ("can't parse
entities" being the typical case a whitelist gap could still let through)
while the broadcast has **zero successful sends so far** aborts the _whole_
broadcast to `failed` immediately, instead of letting the dispatch job grind
through the same 400 for every remaining recipient one `failed` row at a
time. The guard keys on "no success yet" rather than "this is recipient #1"
specifically so a transient failure on the very first recipient doesn't
permanently disable the safety net for the rest of the send.

**`file_id` reuse.** The first successful media send for a broadcast goes
by the CDN URL (from the `storage` presign upload); Telegram's response
carries its own `file_id` for that upload, which the dispatch job persists
onto `broadcasts.media_file_id` and reuses for every subsequent recipient.
One R2 fetch by Telegram instead of thousands, and materially faster/more
reliable large sends.

**Telegram-HTML whitelist as a save-time chokepoint.**
`broadcasts/sanitize.py` validates every stored body against a fixed tag
whitelist (`b, i, u, s, a[href http/https/tg], code, pre, tg-spoiler,
blockquote`) using the stdlib `html.parser.HTMLParser` — no new dependency,
and no attacker-controlled markup can reach either the admin's own preview
or Telegram's parser. This runs at **save time** (create/update) and is
**re-run at send/schedule time** against the stored body (`service.py`'s
`_validate_sendable`) — a body is never assumed valid just because it was
accepted once, since neither `create_draft` nor `update_draft` itself
enforces the whitelist inline. Rejecting unbalanced tags, disallowed
attributes, disallowed `href` schemes, and comments/PIs/declarations at this
one chokepoint means a malformed body can never reach the fan-out job and
fail identically for every recipient — which is exactly the scenario the
first-send abort above exists to catch if this chokepoint is ever bypassed.

**Chosen option (editor): the contenteditable WYSIWYG**, `TelegramEditor.tsx`.
A toolbar (bold/italic/underline/strikethrough/spoiler/link/code) toggles
marks on the current selection — the four basic marks via
`document.execCommand` (deprecated API, but still the only reliable
cross-browser way to toggle marks on an arbitrary selection, and still
supported in every target browser), spoiler/link/code via manual
Selection/Range DOM manipulation since they have no native `execCommand`.
The editor re-serializes its own DOM into Telegram-HTML on every input event
through the same whitelist walker (`telegramHtml.ts`) that renders the
preview bubble, so the editable view and the preview can never drift from
two independently-hand-rolled copies of the same allowlist (an earlier draft
had exactly that problem — a preview renderer missing the `script`/`style`
drop that the editor's copy had). A full editor framework (Tiptap/Slate/
Lexical) was rejected as disproportionate weight for seven marks and a
single custom tag (`tg-spoiler`) with no image/table/list requirements.

**Documented fallback.** If contenteditable's caret/selection quirks (a
known cross-browser pain point for this API) prove too fiddly in practice,
the fallback — recorded here rather than built speculatively — is a
toolbar-wrapped `<textarea>` where toolbar buttons insert literal
`<b>...</b>`-style markers around the selection, paired with the exact same
`previewHtml`/`visibleLength` pair `TelegramEditor` already uses for its
preview and counter. Because `telegramHtml.ts`'s validation/rendering logic
is already decoupled from the DOM-based editor component, swapping the
input surface would not require touching the whitelist, the preview, or the
backend validator at all.

### Positive consequences

- Zero new background-processing surface to build and harden under time
  pressure; the delivery job is a straight structural copy of an
  already-proven pattern (`waxpeer_reconcile`).
- A crash during a send of thousands of messages loses at most the last
  ~5 s tick's unfinished chunk of work, resumes automatically on the next
  tick, and duplicates at most one message.
- One malformed body costs at most one failed send, not the whole audience.
- The composer's live preview is pixel-for-pixel derived from the same
  serializer that produces the stored body — what the admin sees is what
  gets sent.
- No new frontend dependency for rich text.

### Negative consequences

- Delivery is not exactly-once. A crash at the exact instant between "sent"
  and "committed" can duplicate one message to one recipient. Acceptable for
  a promotional broadcast; would need revisiting for anything
  transactional/financial.
- The scheduler process is now a hard dependency for broadcasts specifically
  (not just for the periodic jobs it already ran) — if the scheduler
  container is down, `sending`/`scheduled` broadcasts simply don't move
  until it's back up. No queue means no backlog metric beyond
  `total_recipients - sent_count - failed_count - blocked_count` on the row
  itself.
- `document.execCommand` is deprecated (no removal timeline from any
  browser vendor for the commands actually used here), and manual
  Selection/Range wrapping for spoiler/link/code is more code than a
  managed editor's mark API would have been — offset by having zero new
  runtime dependency and a serializer that's trivial to audit against the
  backend whitelist.

## Validation

- `apps/scheduler/src/yupay_scheduler/jobs/broadcast_dispatch.py` +
  `apps/api/tests/integration/test_broadcast_dispatch.py`: chunked/paced
  delivery, `FOR UPDATE SKIP LOCKED` claim safety under overlapping ticks,
  the first-send-400 abort, `file_id` capture and reuse, cancel-mid-flight.
- `apps/api/src/yupay/modules/broadcasts/sanitize.py` +
  `apps/api/tests/unit/test_broadcasts_sanitize.py` (whitelist
  pass/reject, injection attempts, unbalanced/unterminated markup, length
  ceilings).
- `apps/admin/src/features/broadcasts/telegramHtml.test.ts`: DOM → Telegram
  HTML round-trip per mark, preview/editor parity.
- Manual smoke (see `docs/runbooks/broadcasts.md`): draft with a photo,
  test-send to the admin's own Telegram, send to a small dev base, confirm
  counters reach `N/0/0`, block the bot on one account, re-broadcast and
  confirm it's excluded.
- Revisit if delivery volume ever needs true exactly-once semantics, or if
  a second rich-text surface elsewhere in the admin makes a shared editor
  library worth the dependency weight it was rejected for here.

## Alternatives considered (detail)

### Outbox + Dramatiq worker

Pros: fits the codebase's documented long-term shape for cross-module
fan-out (`core/outbox` exists precisely for this); a worker actor gets retry/
backoff semantics from Dramatiq for free.
Cons: the outbox has no consumer today and the API has no broker connection
— both would need to be built, wired, and trusted for the first time on a
feature whose failure mode is "spams or fails to reach real users." The
scheduler job needed writing either way (nothing else polls Telegram at a
paced rate); routing through an outbox+worker would have meant building the
scheduler's chunk/pace/abort logic _again_ inside a Dramatiq actor, or
having the actor itself call back into the scheduler's job — neither saves
work over the job owning delivery outright.

### Fire-and-forget inline task in the request handler

Pros: no new component at all.
Cons: violates AGENTS.md §10 (no synchronous external HTTP calls in request
handlers); a few thousand sequential Telegram calls would hold a connection
and a DB session open for minutes; a mid-request crash or deploy loses
arbitrary progress with no recipient-level durability at all.

### A full rich-text editor dependency (Tiptap/Slate/Lexical)

Pros: mature selection/caret handling, well past contenteditable's rough
edges, built-in extensibility if inline buttons or richer marks are ever
wanted.
Cons: a new frontend dependency (and its own serialization model to map
onto Telegram-HTML) for seven marks and one custom tag. Revisit if a second
rich-text surface appears elsewhere in the admin and shares the cost.

## References

- Design spec: `docs/superpowers/specs/2026-07-21-telegram-broadcasts-design.md`
- `apps/api/src/yupay/modules/broadcasts/README.md` — module responsibilities, FSM, HTTP surface.
- `docs/runbooks/broadcasts.md` — operator guide.
- `docs/architecture/sequence-diagrams/broadcast-send.mmd`.
- `apps/scheduler/src/yupay_scheduler/jobs/waxpeer_reconcile.py` — the
  periodic-sweep pattern this job's shape is copied from.
- `apps/api/src/yupay/modules/storage/README.md` — the `broadcast_media`
  upload kind this feature added.
- AGENTS.md §9 (Idempotency-Key on every write endpoint), §10 (no
  synchronous external HTTP calls in request handlers).
