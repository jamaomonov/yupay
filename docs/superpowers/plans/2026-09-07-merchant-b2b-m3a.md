# Merchant B2B — M3a: the webhook outbox, SSRF hardening, and validate endpoints

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** a merchant's server learns about order and balance changes without
polling, over signed HTTP deliveries our worker makes — and our worker cannot
be turned into a probe of our own private network while doing it.

**Architecture:** the existing Postgres-queue pattern (ADR-0064): a table with
a claimable status, enqueued in the same transaction as the fact that causes
it, drained by `apps/worker` on its own LISTEN channel. Delivery goes through a
purpose-built outbound client that re-resolves and re-checks the destination IP
**at connect time**, which is the one thing the repo's existing image-URL
validator documents itself as unable to do.

**Tech stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, httpx,
asyncpg LISTEN/NOTIFY, pytest + testcontainers.

**Spec:** `docs/superpowers/specs/2026-09-06-merchant-b2b-design.md` §10 (and
§9.1 for the validate row); owner additions in
`docs/superpowers/specs/2026-09-07-merchant-m3-requirements.md`.

## Global Constraints

- **Contract stability.** `/merchant/v1` and the webhook payloads are consumed
  by third-party code nobody but its owner can redeploy. Breaking changes need
  a new version, not an edit. Error bodies are RFC 7807 with documented codes.
- **Voucher codes never ride in a webhook body** (spec §10). The event says
  `delivered`; the merchant fetches the code over the authenticated GET.
  Webhook receivers get logged wholesale on the merchant's side — a code in
  their access log is our leak. A test must assert no artifact field can reach
  a payload.
- **Event types in v1 are exactly two:** `order.status_changed`,
  `balance.credited`. `balance.low` was deliberately dropped _(owner)_.
- **The merchant configures the webhook from the cabinet (M4)** _(owner)_. M3a
  ships the storage and an **admin** write only — support sets a pilot's URL on
  request, the same shape as crediting a deposit today. Do **not** add a
  `/merchant/v1` write for it: its only purpose would be to point our worker at
  an arbitrary address, which is precisely the surface this milestone hardens,
  and M4's cabinet is where the owner wants that control to live.
- **PII:** merchant-supplied end-customer identifiers are transit-only. Never
  in URLs, never in logs beyond existing redaction; `hash_short` for anything
  that must be logged. The webhook secret and any signature never appear in a
  log line or an error body — `core/logging.py`'s blocklist already carries the
  merchant API headers; extend it in the same spirit.
- **Money** as `Decimal`, serialised as strings, in every payload.
- mypy --strict, ruff, Google docstrings on every public function; migrations
  pair schema with their indices; `make gen-api` committed when a route or
  response shape moves; `pnpm exec prettier --check .` before finishing any task
  touching TS/JSON/MD.
- Never `git stash` or `git checkout <path>` — several agents share this
  worktree and it has destroyed work before. Use `git show HEAD:<path>`.

## Carry-overs this plan must honour

1. **The connect-time check is the deliverable, not the save-time one.**
   `modules/catalog/image_url_safety.py` already validates a URL at save time
   and its docstring states plainly that it cannot catch DNS rebinding, because
   Next owns that fetcher. Here we own the fetcher. Reuse the existing helper
   for the admin write, and build the connect-time check as the real control.
2. **`Retry-After` and RFC 7807** are already the house style for merchant
   errors; the validate endpoints inherit them.
3. **`docs/architecture/cache-keys.md`** documents every Redis key (AGENTS §10).
   Any new key lands there in the task that adds it.

---

### Task 1: Schema and the admin configuration surface

**Files:**

- Create: `apps/api/migrations/versions/0071_merchant_webhooks.py`
- Modify: `modules/merchants/models.py`, `admin.py`, `admin_routes.py`,
  `schemas.py`, `api.py`
- Test: `apps/api/tests/integration/test_merchant_webhook_admin.py`

**Interfaces:**

- Produces `MerchantWebhook`: `merchant_id` (unique — one endpoint per merchant
  in v1), `url`, `secret_hash`-style storage decided below, `disabled_at`,
  `failure_streak`, `last_success_at`, `last_failure_at`, timestamps.
- Produces `MerchantWebhookDelivery`: the outbox row — `merchant_id`,
  `event_type`, `payload` JSONB, `status` (`pending`/`in_progress`/`delivered`/
  `failed`), `attempts_count`, `next_attempt_at`, `response_code`,
  `response_body` (truncated), `last_error`, timestamps. This table is also the
  cabinet's delivery log in M4, so it is written for reading by a human.
- Produces admin endpoints: `PUT /admin/merchants/{id}/webhook` (set URL,
  returns the secret **once**), `POST .../webhook/rotate-secret`,
  `DELETE .../webhook` (disable), `GET .../webhook` (never returns the secret).

**The secret is a signing key, so store it the way M2 stores API secrets.**
M2 established that a hash cannot be used to sign — see ADR-0069 and
`core/crypto.py`. Encrypt it at rest with the same primitive and its own HKDF
purpose label. Do not invent a second scheme, and do not store it in plaintext.

- [ ] **Step 1: failing tests** — the admin write validates the URL through the
      existing `validate_public_image_url`-style save-time check (https only,
      no private/loopback literals); a set returns the secret once and never
      again; rotate replaces it and invalidates the old; disable sets
      `disabled_at`; the delivery table round-trips a JSONB payload; per-resource
      replay scopes on every write, matching M2's admin endpoints.
- [ ] **Step 2-4:** run to see them fail → implement → pass.
- [ ] **Step 5: commit** `feat(api/merchants): webhook configuration and the delivery outbox`

---

### Task 2: The SSRF-safe outbound client

**Files:**

- Create: `apps/api/src/yupay/core/outbound.py`
- Test: `apps/api/tests/unit/test_outbound_ssrf.py`,
  `apps/api/tests/integration/test_outbound_ssrf_live.py`

**This task is the security core of the milestone and gets its own review.**

**Interfaces:**

- Produces an async `post_json(url, *, body, headers, timeout, max_bytes)`
  returning a small result (status, truncated body, timing) and raising a typed
  error for every refusal, distinguishing _blocked by policy_ from _network
  failure_ — the caller records different things for each.

**Required properties, each with its own test:**

1. **https only.** A `http://` URL is refused without a connection attempt.
2. **The IP is validated at connect time, on the address actually connected
   to.** Resolve the host, reject the request unless **every** returned address
   is public, and connect to the address that was checked — a resolve-then-
   connect-by-name implementation is the bug this task exists to prevent, since
   the second resolution can differ from the first.
3. **Blocked ranges:** loopback, private, link-local (including
   `169.254.169.254`), unique-local, multicast, reserved, and IPv4-mapped IPv6
   forms of all of them. Test each family by name, not as one lump.
4. **Redirects are never followed.** A 30x is a delivery outcome, not a hop.
5. **Response size and time are capped**, and exceeding either is a typed
   refusal rather than a hang or an unbounded read.
6. **No credentials leak:** the client never forwards our own headers to a
   redirect target (it has none, by 4) and never logs the body it sends.

**Note for the implementer:** `modules/catalog/image_url_safety.py` already
covers the save-time half and documents why it cannot cover this half. Read its
docstring first — it names the obfuscated-notation limits you should not
re-introduce here (bare-integer IPv4, octal/hex octets), and this client sees
resolved addresses rather than notation, which is what makes it stronger.

- [ ] **Step 1: failing tests** for all six properties. Property 2 needs a real
      server: bind one on a loopback port and prove the client refuses it even
      when the hostname is public-looking.
- [ ] **Step 2-4:** fail → implement → pass.
- [ ] **Step 5: commit** `feat(api/core): an outbound client that re-checks the address it connects to`

---

### Task 3: Emitting events into the outbox

**Files:**

- Modify: `modules/merchants/webhooks.py` (new), `modules/orders/service.py` or
  its status-transition site, `modules/merchants/deposit.py`
- Test: `apps/api/tests/integration/test_merchant_webhook_events.py`

**Interfaces:**

- Produces `enqueue(db, *, merchant_id, event_type, payload)` — inserts a
  `pending` row **in the caller's transaction** and issues `pg_notify` on the
  webhook channel inside the same transaction, so a rollback drops both.
  Mirror `fulfillment.service`'s enqueue exactly; do not invent a second shape.
- Consumes: the order status transition and `credit_deposit`.

**Rules:**

- A merchant with no webhook row, or a disabled one, enqueues **nothing** — not
  a row that will never be delivered.
- `order.status_changed` carries the order's public identity and its new
  status, and **nothing from the delivery artifact**. Assert that.
- `balance.credited` carries the amount and the new balance as strings.
- Enqueue must not be able to fail the business transaction it rides in: a
  webhook is a courtesy, an order is money. Decide and document what happens if
  the insert raises.

- [ ] **Step 1: failing tests** — a status change enqueues exactly one row with
      the right payload; no webhook configured enqueues none; a disabled hook
      enqueues none; a rolled-back order leaves no row and fires no NOTIFY; a
      voucher code never appears in a payload.
- [ ] **Step 2-4:** fail → implement → pass.
- [ ] **Step 5: commit** `feat(api/merchants): enqueue webhook events with the fact that causes them`

---

### Task 4: Delivering from the worker

**Files:**

- Modify: `apps/worker/src/yupay_worker/consumer.py`,
  `modules/merchants/webhooks.py`
- Test: `apps/api/tests/integration/test_merchant_webhook_delivery.py`

**Interfaces:**

- Produces `drain_pending_deliveries(db) -> int`, shaped like
  `drain_pending_tasks`: claims with `FOR UPDATE SKIP LOCKED`, one savepoint per
  row so a poisoned delivery cannot livelock the batch.
- The consumer gains a **second LISTEN channel**. `ListenerManager` is currently
  hardcoded to `fulfillment_queue`; parameterise the channel rather than
  duplicating the class, and let both managers share one wake event — a wake
  drains both queues, and an empty queue returns immediately.

**Rules:**

- Signed with the webhook secret and a timestamp; the exact canonical string is
  documented in Task 6 and must be decided here, not left implicit. M2's
  scheme is the precedent worth copying, including _why_ its fields cannot
  contain the separator.
- Retries with backoff on a network failure or a 5xx; a 4xx other than 408/429
  is terminal (their endpoint rejected it — retrying will not change that).
- `Retry-After` on a 429 from the merchant's own server is honoured.
- Auto-disable after a sustained failure streak, with an email to the merchant
  (`merchant_users.email`, via the existing notifications channel), and a
  clear `disabled_at`. The streak threshold is a setting.
- Every attempt appends to the delivery row: response code, truncated body,
  attempt count. This is the cabinet's log in M4 — write it to be read.

- [ ] **Step 1: failing tests** — a 200 marks delivered; a 500 retries with a
      later `next_attempt_at`; a 404 is terminal; a streak disables the hook and
      sends exactly one email; a blocked address (Task 2) is recorded as a
      policy refusal, not a network error; a poisoned row does not stall the
      batch.
- [ ] **Step 2-4:** fail → implement → pass. Run the FULL worker and fulfilment
      suites — this task edits the consumer every retail order flows through.
- [ ] **Step 5: commit** `feat(worker): deliver merchant webhooks with backoff and auto-disable`

---

### Task 5: `POST /merchant/v1/validate/…`

**Files:**

- Modify: `modules/merchants/machine_routes.py`, `machine_schemas.py`
- Test: `apps/api/tests/integration/test_merchant_validate.py`

`modules/integrations/player_check.py` already implements the two real checks
(G2B nickname lookup, Waxpeer Steam login) behind one advisory three-way
`valid`/`invalid`/`error` result with a circuit breaker and a 300 s cache.

**Rules (spec §9.1):** expose only where the answer is **truthful**. Never a
fake approver: `error` must never render as `valid`, and a SKU with no
configured checker must say so rather than returning a cheerful default. It
spends supplier quota, so it carries its own rate-limit bucket (spec §11's
sliding cap).

- [ ] **Step 1: failing tests** — a checkable SKU returns the upstream verdict;
      an unconfigured SKU is an explicit "cannot check", not `valid`; an
      upstream fault is `error`; the bucket throttles; the auth tests (401/403)
      that every merchant route gets.
- [ ] **Step 2-4:** fail → implement → pass → `make gen-api`.
- [ ] **Step 5: commit** `feat(api/merchants): expose the truthful player checks`

---

### Task 6: The webhook contract, ADR-0070, runbook

**Files:** `modules/merchants/README.md`, `docs/api/README.md`,
`docs/decisions/0070-merchant-webhooks.md`,
`docs/architecture/sequence-diagrams/merchant-webhook-delivery.mmd`,
`docs/runbooks/merchant-b2b.md`, `docs/security/threat-model.md`

The audience is a third-party integrator who will implement signature
verification from our text alone. M2 established the standard: **the worked
example is executed and its output pasted, never composed by hand.**

Must carry: the event list and payload shapes; the canonical signed string with
a runnable non-Python verification snippet; the retry and backoff schedule; what
auto-disable means and how to recover from it; that codes never ride in a body
and why; and the ordering guarantee (or the explicit absence of one).

ADR-0070 records: the outbox-on-Postgres choice over a message broker; the
connect-time IP check and why the save-time one is not enough (quote the image
validator's own docstring); the two event types and why `balance.low` was
dropped; and admin-only configuration until M4's cabinet.

Runbook: how to set a pilot's webhook, how to read the delivery log, what to do
when a hook auto-disables, and how to replay a failed delivery.

- [ ] **Steps:** write → verify every falsifiable claim against the code →
      `pnpm exec prettier --check .` → commit `docs(merchants): the webhook contract`

---

## Self-review notes

- Ordering: 1 (storage) → 2 (the client, independently testable) → 3 (enqueue)
  → 4 (deliver, needs 1-3) → 5 (unrelated, parked last on purpose) → 6.
- Task 2 is deliberately standalone: it is the security control, it has no
  merchant dependencies, and it deserves a review that is not distracted by
  queue mechanics.
- Task 4 touches `apps/worker`'s only loop. The blast radius is every retail
  order, which is why its step 4 runs the full worker and fulfilment suites.
- Names used consistently: `MerchantWebhook`, `MerchantWebhookDelivery`,
  `drain_pending_deliveries`, `core/outbound.py`, event types exactly as
  spec §10 lists them.
- Out of scope: the cabinet (M4), and everything in M3b — auto-refund, stall
  visibility, and order-attributed ledger references.
