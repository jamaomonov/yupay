# `merchants`

B2B reseller accounts: a merchant, its cabinet operator(s), and the API keys
its server uses against `/merchant/v1`. This is the schema module that every
other part of the merchant B2B feature (the machine API, the cabinet BFF, the
deposit ledger, admin) builds on.

**Spec:** `docs/superpowers/specs/2026-09-06-merchant-b2b-design.md`
**Decisions:** ADR-0068 (the foundation), ADR-0069 (the machine API),
ADR-0070 (the outgoing webhooks)
**Runbook:** `docs/runbooks/merchant-b2b.md` — onboarding, key rotation, and
the known gaps a pilot integrator will meet

## Terminology note

Acquirers call **us** the merchant (Click/Payme `merchant_id` credentials);
in this module the merchant is the reseller.

## Tables

- `merchants` — the reseller account: `title`, `status` (`active`/`frozen`),
  and a dormant `markup_adjustment_pp` reserved for a future per-merchant
  pricing override (spec §8.3).
- `merchant_users` — cabinet operators. One user per merchant in v1; the FK
  already permits more.
- `merchant_api_keys` — machine credentials for `/merchant/v1`: a public
  `key_id` (`ypm_`-prefixed) and the secret held **encrypted at rest**
  (`secret_enc` / `secret_nonce`, migration 0070 — see "Storage" below), with
  an optional IP allowlist, a `last_used_at` stamp and a `revoked_at`
  tombstone. See "Machine-API authentication" below.
- `merchant_webhooks` — the **one** endpoint (unique on `merchant_id`) we
  POST a merchant's events to, its `ypmw_`-prefixed signing secret held
  encrypted at rest under its own HKDF purpose label
  (`yupay:merchants:webhook:v1`), a `disabled_at` switch, and the delivery
  worker's running health: `failure_streak`, `last_success_at`,
  `last_failure_at`. Migration 0071.
- `merchant_webhook_deliveries` — the outbox, in ADR-0064's shape: `payload`
  JSONB, a claimable `status` (`pending` → `in_progress` → `delivered` |
  `failed`), `attempts_count` / `next_attempt_at` for backoff, and — because
  this table is also the cabinet's delivery log from M4 — the `url` we
  addressed, the merchant's `response_code`, the first 2048 characters of
  their `response_body`, and our own `last_error` (capped at 512). Both text
  caps are **column bounds**, because both interpolate material a third party
  chose and our own cabinet renders it, so "the writer truncates" is not a
  promise worth resting on.

  Three shapes here are load-bearing rather than incidental. `url` is a
  **snapshot taken at enqueue**, not a join onto `merchant_webhooks` — setting
  a URL edits that row in place, so a join would re-attribute every historical
  response to whatever address is configured now, and "we recorded a 200, but
  was that their old staging host?" is exactly what this log exists to answer.
  `next_attempt_at` is **NOT NULL, defaulting to now**: nullable-meaning-now
  makes the claim predicate `next_attempt_at <= now()` NULL-_false_ for a
  never-attempted row, so it is never claimed and, never being claimed, never
  gets a value — a queue that silently delivers nothing; and the `IS NULL`
  workaround trades that for starvation, since btree ASC sorts NULLs last and
  every fresh event would queue behind one dead endpoint's retries. `payload`
  has **no** server default, so an enqueue that forgets the body fails instead
  of logging a delivery whose content is unrecoverable.

  **Known limitation for M4:** there is no index that reaches a delivery by
  order id — the order lives inside `payload` JSONB, and "did merchant X hear
  about order Y" is the commonest support question. `(merchant_id,
created_at DESC)` narrows it to one merchant's log, which is enough at our
  volume; a real answer needs either an expression index on the payload key or
  a promoted column, and that is a decision for whoever builds the screen.

## Outgoing webhooks — the producer (`webhooks.py`)

M3a Task 3. `enqueue(db, *, merchant_id, event_type, payload)` writes one
`pending` row **into the caller's transaction** and issues
`pg_notify('merchant_webhook_queue', <delivery_id>)` inside it. Postgres
delivers a NOTIFY on COMMIT and drops it on ROLLBACK, so an order that rolls
back tells nobody and no nudge can outrun the fact behind it. The channel name
is one constant, `WEBHOOK_QUEUE_CHANNEL` — Task 4's listener imports it rather
than respelling the string, because a channel spelled twice is a queue nobody
drains and no test fails.

**A merchant with no webhook row and one whose row is disabled are the same
outcome: nothing is written.** The outbox holds only deliverable work; a row
the worker must skip makes the backlog meaningless and the cabinet's delivery
log a lie.

**A courtesy may never fail money.** The insert runs inside a SAVEPOINT, and
an `IntegrityError`/`DataError` from it is swallowed — the order commits, the
merchant misses one event, ops gets an `error` line. Three details make that
safe rather than sloppy:

- the swallow is _narrow_ (those two types only), so a broken session or a
  programming error still propagates instead of hiding behind a plausible
  commit;
- it is a SAVEPOINT, not a bare `try` — a failed flush poisons a session until
  something rolls back, and rolling back the _caller's_ transaction is the
  exact harm the rule exists to prevent. The caller's own pending writes are
  flushed **before** the savepoint opens so they can never sit inside it;
- the log line carries the exception type and the SQLSTATE and **not** the
  driver's message. A `NotNullViolation` renders `DETAIL: Failing row contains
(…)` — the whole row, including the `url` snapshot, which is sized to hold a
  path with a token in it. Reaching here is our bug (every column is NOT NULL
  or length-bounded on purpose), so the type is enough to find it.

### The payloads are a contract

| Event                  | Body                                                        |
| ---------------------- | ----------------------------------------------------------- |
| `order.status_changed` | `merchant_order_id`, `order_id`, `status`, `at` (see below) |
| `balance.credited`     | `amount_usd`, `balance_usd` — two-decimal **strings**       |

`at` is `order.updated_at.isoformat()` — a real timestamp taken per transition
(`core.clock.now`, so `paid` and `fulfilling` from one placement differ by
microseconds rather than sharing a transaction clock) rendered with an explicit
`+00:00` offset. That is **not** the `Z` the machine API's Pydantic DTOs emit
for the same instant: this string is built by hand into JSONB and never passes
through a response model. Both are ISO 8601, the contract section says which one
this is, and neither may change shape inside v1.

Those key sets are exact, and the tests assert them as key sets rather than as
"no key named `code`". A voucher code is a bearer instrument and a webhook body
is written to the receiver's logs wholesale (spec §10), so the code is fetched
over `GET /merchant/v1/orders/{merchant_order_id}` and never pushed — and an
exact-shape assertion is what stops a future field addition from smuggling a
value into a body somebody else logs. Money goes through the same
`machine_schemas` annotations `/merchant/v1` uses, so a webhook body and the
read endpoint cannot disagree about the shape of a balance.

### Where events come from

- **`order.status_changed`** — `orders.service.on_order_status_changed`, the
  one seam every status transition in the system passes through (`orders`,
  `payments` and `fulfillment` all call it; the three used to keep a verbatim
  copy of the realtime nudge each). The webhook could not ride that existing
  nudge: `publish_order_event` is a no-op for a NULL `user_id`, which every
  merchant order has. A merchant order therefore emits `paid` and `fulfilling`
  from the placement transaction and `delivered` from the worker's settle.
- **`balance.credited`** — `deposit.credit_deposit`, in the same transaction as
  the ledger posting. A **replay** of the admin's idempotency key books nothing
  and so announces nothing: a `balance.credited` for money that did not move
  would have a reseller crediting their own customer twice. Its payload stays
  exactly `{amount_usd, balance_usd}` when the credit settles an order (M3b
  Task 2): the key set is published, a receiver is entitled to it, and a
  settlement is already legible on `/transactions` and on the order's
  `refunded_usd`. Naming the order in the event would be a `/merchant/v2`.

**No event exists for a fulfilment that fails, or stalls, on its own — unless
the failure refunds.** The seam fires where `orders.status` moves. A stall does
not move it, and neither does a terminal failure whose money did not come back:
both are recorded against the _task_, so the order sits at `fulfilling` with a
non-null `failure_reason` and a reseller sees `paid → fulfilling → silence`.
A **fully refunded** order does move it (M3c Task 6): every way to deliver it is
already refused by `deposit_already_returned`, so it is closed as `failed` and
that goes through the seam like any other transition. A `failed` event therefore
arrives from three places — `orders.service.mark_order_failed_admin` when
support closes the order by hand, `fulfillment.service.end_a_refunded_merchant_order`
from the refund seam when the automatic refund settles it in full, and the same
function from `deposit.credit_deposit` when a settlement a person books brings
the order to a full one (M3c Task 4). From outside they are one fact — the
order ended without a delivery — and `failure_reason` is what distinguishes
them.

Adding a task-level event is not a small change — it is a third event type and
a payload shape — so M3b Task 4 answered it on the **read** instead:
`failure_reason` now goes non-null for a stall too (`fulfillment_delayed`), so
a poller has a state to act on rather than a timeout it had to invent. A stall
is not a state change and pushes nothing; if it ever should, that is a new
event type and a `/merchant/v2` conversation. The integrator contract says all
of this outright rather than letting every integrator discover it.

**An automatic refund pushes twice, and neither event names the other.** M3b
Task 3 emitted only `balance.credited` — a deposit credit like any other, and
the hand settlement it replaces already emitted one, so an automatic path that
stayed silent would have _removed_ a notification integrators get today. M3c
Task 6 closes the order as well, so `order.status_changed` with
`status: "failed"` now follows it in the same transaction; the money is
enqueued first and the order state second, and both rows tie on `created_at`
(the transaction clock) with the uuid7 id keeping that order. So a receiver is
told about a refund by **push** — which is not what M3b's own text said, and it
said so for a version of the code where the order row genuinely never moved.

What still needs a read is the _link_ between the two. `balance.credited`
carries exactly `{amount_usd, balance_usd}` and naming the order in it would be
a `/merchant/v2`; `order.status_changed` carries `status` and not
`failure_reason`. So a receiver learns "money came back" and "this order
ended", and gets `fulfillment_failed_refunded` and `refunded_usd` by reading
`GET /merchant/v1/orders/{merchant_order_id}` or `/transactions`, where the
refund carries `order_id` and `merchant_order_id`. A **partial** settlement and
a failure that refunded nothing still move no order row and still push nothing
but the credit: for those, poll.

The two typed producers are `enqueue_order_status_changed` and
`enqueue_balance_credited`, and the first is deliberately **not** called
`on_order_status_changed`: that is the name of the seam in `orders.service`, it
takes the same two arguments, and it also nudges retail. One name for both
would let an autocomplete in any module that imports `merchants` — most do —
swap the seam for this half of it, silently turning the storefront's live
updates off with no test to fail. The facade exports the generic `enqueue` as
`enqueue_webhook_event` for the same reason.

Drawn in `docs/architecture/sequence-diagrams/merchant-webhook-emit.mmd`.

## Outgoing webhooks — the delivery drain (`webhook_delivery.py`, `webhook_outcome.py`, `webhook_retry.py`)

Three files, split at their concerns once they passed AGENTS §6's 500-line
limit together: `webhook_delivery.py` claims a row, signs it and sends it;
`webhook_outcome.py` is everything that happens after the answer comes back —
the row's log, the hook's health, the auto-disable and its one email;
`webhook_retry.py` is the pure decision table both consult.

M3a Task 4, run from `apps/worker` (`yupay_worker.consumer` LISTENs on
`merchant_webhook_queue` beside `fulfillment_queue`, in this queue's **own
asyncio task** so a slow endpoint cannot become the fulfilment queue's polling
period, and
calls `merchants.api.drain_pending_deliveries`). Same ADR-0064 shape as
fulfilment: claim `FOR UPDATE SKIP LOCKED`, one SAVEPOINT per row, never commit
— the worker owns the transaction. Drawn in
`sequence-diagrams/merchant-webhook-delivery.mmd`.

### What each attempt sends

The receiver's half of this is written for an integrator under
["Outgoing webhooks"](#outgoing-webhooks) below, with an executed worked example
and a runnable verifier. This is the sender's half; the two must not drift.

`POST` of the stored payload, serialised with sorted keys and compact
separators so two attempts at one row put identical bytes on the wire, to the
row's **`url` snapshot** — never to whatever the hook says now. Four headers,
all named in `signing.py` because they are wire format:

| Header              | Value                                           |
| ------------------- | ----------------------------------------------- |
| `X-Yupay-Delivery`  | the delivery row id — stable across every retry |
| `X-Yupay-Event`     | `order.status_changed` / `balance.credited`     |
| `X-Yupay-Timestamp` | Unix seconds, ASCII digits                      |
| `X-Yupay-Signature` | hex HMAC-SHA256 under the `ypmw_` secret        |

The canonical string is
`{timestamp}\n{delivery_id}\n{event_type}\n{hex(sha256(body))}` — four fields,
each either fixed-width or unable to contain the LF separator, exactly the
discipline §9.2's inbound scheme follows. The `ypmw_` secret is decrypted at
send time under its own `crypto` purpose label and never logged, never stored
on the delivery row, never in a body.

**The delivery id is inside the signed material, not only in a header**, and
that is the one decision here that could not be taken later: a webhook is
at-least-once, so a retry after a lost `200` is indistinguishable from a
genuine second transition unless something stable identifies the attempt — and
an unsigned header is worthless against a replay. `order.status_changed` has no
event id in its payload (that would have broken the exact-key-set rule above),
so this is the receiver's only dedupe handle. Adding it after the first
integrator would be a `/merchant/v2`.

### Verifying a delivery

Spec §10 asks for this, and until now the docs described the canonical string
without handing you code for it — while the _inbound_ direction, where you sign
your own calls, had two snippets. That was backwards: a wrong signature on your
own request answers `401`, so you debug it in a minute; an unverified webhook
answers nothing at all, and an accepted forgery is silent.

Three things the code below is doing on purpose:

- **Hash the raw bytes you received**, never a re-serialised object. Parsing
  and re-dumping JSON changes whitespace and key order, and the digest with it.
- **Compare in constant time.** A `==` on a hex signature leaks it a byte at a
  time to anyone who can measure your response.
- **Dedupe on `X-Yupay-Delivery`.** Delivery is at-least-once: a retry after a
  lost `200` is indistinguishable from a genuine second transition, and that
  header is the only stable handle — which is why it is inside the signed
  material rather than only on the wire.

Python (Flask; `request.get_data()` is the raw body, `request.json` is not):

```python
import hashlib, hmac, time

SECRET = "ypmw_…"  # the webhook secret — a different credential from ypms_
TOLERANCE_SECONDS = 300


def verify(headers: dict[str, str], body: bytes) -> bool:
    ts = headers.get("X-Yupay-Timestamp", "")
    canonical = "\n".join(
        (
            ts,
            headers.get("X-Yupay-Delivery", ""),
            headers.get("X-Yupay-Event", ""),
            hashlib.sha256(body).hexdigest(),
        )
    ).encode()
    expected = hmac.new(SECRET.encode(), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, headers.get("X-Yupay-Signature", "")):
        return False
    # Your own replay window; we do not impose one on you.
    return ts.isdigit() and abs(time.time() - int(ts)) <= TOLERANCE_SECONDS
```

Node 18+ (no dependencies; keep the raw `Buffer` — `express.json()` discards
it unless you pass `verify`):

```js
import { createHash, createHmac, timingSafeEqual } from "node:crypto";

const SECRET = "ypmw_…";
const TOLERANCE_SECONDS = 300;

function verify(headers, body /* Buffer */) {
  const ts = headers["x-yupay-timestamp"] ?? "";
  const canonical = [
    ts,
    headers["x-yupay-delivery"] ?? "",
    headers["x-yupay-event"] ?? "",
    createHash("sha256").update(body).digest("hex"),
  ].join("\n");
  const expected = createHmac("sha256", SECRET).update(canonical).digest("hex");
  const got = headers["x-yupay-signature"] ?? "";
  if (expected.length !== got.length) return false;
  if (!timingSafeEqual(Buffer.from(expected), Buffer.from(got))) return false;
  return /^\d+$/.test(ts) && Math.abs(Date.now() / 1000 - Number(ts)) <= TOLERANCE_SECONDS;
}
```

Answer `2xx` once you have stored the event — anything else is a retry, and a
`4xx` other than `408`/`429` counts toward the streak that auto-disables your
endpoint.

### The retry table is derived from the client's taxonomy, not invented

`webhook_retry.py` is pure and reads `core/outbound_errors.py` rather than
matching on exception names. Two questions answer everything:

| Outcome                                                                 | What happens                       | Counts toward the streak |
| ----------------------------------------------------------------------- | ---------------------------------- | ------------------------ |
| `2xx`                                                                   | `delivered`                        | resets it to 0           |
| `408`, `429`, `5xx`                                                     | `pending`, backoff                 | yes                      |
| any other `4xx`, and a redirect (never followed)                        | `failed`                           | yes                      |
| `Delivery.RECEIVED` refusal (too large, compressed)                     | `failed` — a retry **re-delivers** | yes                      |
| any other `OutboundRefusedError` (`UrlNotAllowed`, `AddressNotAllowed`) | `failed`                           | yes                      |
| `OutboundUnreachableError` — they did not answer                        | `pending`, backoff                 | yes                      |
| `OutboundBrokenError` — **our** bug                                     | `failed`                           | **no**                   |

Read the rows as the code does: **the delivery fact outranks the family, and
the family answers the rest.** `RECEIVED` is terminal wherever it appears, and
below it the split is refusal-versus-unreachable, not `NOT_SENT`-versus-the-rest
— a refusal we made (their host resolved to a private address, their URL will
not encode) is terminal even though nothing was sent, because the delivery row
carries a `url` **snapshot** and no change on their side fixes _that_ row.

`UNKNOWN` (a timeout, an exchange broken mid-flight) may already have been
processed by the merchant, and we retry it anyway: that is what at-least-once
means, and the delivery id is what makes it actionable rather than a warning.
`OutboundBrokenError` is the one class special-cased against its own family —
counting it would auto-disable a working endpoint and tell the merchant, in the
log they read, that we refused their URL.

Backoff is 30 s doubling to a 1 h cap, no jitter (the herd is one merchant's own
backlog, and a deterministic schedule is one support can predict from
`attempts_count`), and a row is given up on after `MAX_ATTEMPTS` = 10 — a
backstop for the intermittent case, since a dead endpoint auto-disables first.
`Retry-After` is honoured on the two statuses that define it for a retry —
`503` (RFC 9110 §10.2.3) and `429` (RFC 6585 §4) — both forms parsed, clamped
into `[1 s, 1 h]`; the header is written by a third party and `Retry-After: 0`
on every answer would be a hot loop. A `3xx` also defines it (RFC 9110 §10.2.3)
and never reaches this table: we do not follow redirects, so a `30x` is
terminal.

### Ordering

The claim orders by `next_attempt_at, created_at, id`. The third term is
load-bearing: both timestamps default to `CURRENT_TIMESTAMP`, which in Postgres
is the **transaction start**, so the `paid` and `fulfilling` rows one placement
enqueues are byte-identical in both columns and an ORDER BY over them alone
leaves the order unspecified. A reseller receiving `fulfilling` before `paid`
reads the later `paid` as a status regression and re-opens an order their back
office closed. `id` is a uuid7, so it encodes enqueue order.

That fixes the tie, not global ordering: a **retried** event lands after events
enqueued behind it, which is inherent to per-row backoff. Integrator docs must
say so — order by the payload's `at`, dedupe on the delivery id.

Rows are processed merchant-major (merchants in id order) so two concurrent
drainers take hook-row locks in one global order and cannot deadlock.

### Auto-disable, and the one recovery path

A failure that is the merchant's increments `failure_streak`; any success
resets it. At `MERCHANT_WEBHOOK_DISABLE_AFTER_FAILURES` (default 20 — attempts,
not events, so retries reach it) the hook's `disabled_at` is set and every
`merchant_users` operator is emailed **once per disable**, naming the endpoint's
**host** and not its URL (a webhook path can carry a token, and an email goes
through a third-party provider). A merchant with no operator row is still
disabled, silently.

Nothing is deleted and no queued event is thrown away: rows stay `pending` and
are simply not claimed while the hook is off — including rows already claimed
in the batch that tripped the disable, which are skipped rather than sent to an
endpoint we have just switched off. `PUT /admin/merchants/{id}/webhook` clears
`disabled_at` and the streak, and that resumes the backlog. It is the only
recovery path and there is deliberately no second one.

Two things "resumes the backlog" does **not** mean, both of which support has to
be able to say out loud:

- **Events that happen while the hook is off are not queued at all.** The
  producer treats "no hook" and "disabled hook" as one outcome (above), so the
  backlog is what was waiting when it went off, and nothing else. A merchant
  coming back from a disable has a gap, and the order read is the only thing
  that closes it.
- **A queued row keeps the URL it was enqueued with.** `url` is a snapshot, so
  correcting a wrong address re-enables the hook without re-aiming the rows
  already in the queue: they will be attempted against the old host and fail
  out. That is the price of a delivery log that can answer "which host answered
  us at 14:02", and it is the right trade — but a merchant who moved hosts
  should be told to expect it rather than discover it.

### Falsification

`uv run python apps/api/tests/tools/falsify_merchant_webhook_delivery.py` — 20
mutations, each asserting it changed the file before the suite runs. Read its
docstring before running it beside anything else.

## Deposit ledger

The merchant's prepaid balance is a **ledger balance**, never a column.
`merchant_deposit` is a debit-normal account kind (like `user_wallet`),
owned by `owner_type="merchant", owner_id=<merchant_id>, currency="USD"`
— USD-only in v1 (spec §7). Every movement posts through
`wallet.service.post`, so idempotency-by-key and all-or-nothing legs are
inherited from the ledger, not rebuilt here.

It lives in `deposit.py` — the accounts, the reads and the two movements an
operator or an order causes — and, since M3b Task 3, in `refund.py`, which
owns the third. The posting table below is authoritative for all three and no
caller may re-derive a direction from it:

| Event                       | Legs                                             | Kind                      |
| --------------------------- | ------------------------------------------------ | ------------------------- |
| Support credits top-up (M1) | `D merchant_deposit / C house_payments_received` | `merchant_deposit_credit` |
| Order charge (M2)           | `C merchant_deposit / D house_payments_received` | `merchant_order_charge`   |
| Refund on failure (M3b)     | `D merchant_deposit / C house_payments_received` | `merchant_order_refund`   |

The first two rows are live. `deposit.credit_deposit` posts the credit with
the caller's idempotency key, so a replay returns the original transaction;
`deposit.charge_deposit` posts the debit keyed `merchant-order:{order_id}`
(`deposit.charge_key`), which makes a double debit impossible even if the
order path were re-entered for one order — and, because a _second_ charge for
one order therefore debits nothing, is also why a refunded order may not be
re-driven; see "Automatic refunds" below. `refund.refund_order` posts the
third row keyed `merchant-order-refund:{order_id}`, a namespace that
**cannot** collide with the charge's: neither prefix is a prefix of the other,
so no order id on either side can make the two keys equal. That is not
tidiness — `wallet.service.post` replays by key without comparing parameters,
so a collision would silently hand the caller the charge and call it a refund. `charge_deposit` is also **where the overdraw guard binds**: it
locks the `merchant_deposit` row with `SELECT … FOR UPDATE` before reading the
balance, the same shape `wallet.service.reverse_topup` uses, so two concurrent
orders serialise instead of both spending the same dollars. The order path's
earlier balance read exists only to answer a clean `409` before any row is
written.

`deposit.deposit_balance` reads the balance (`Decimal("0")` when no account
exists yet — the read creates nothing). Freezing a merchant
(`service.set_status`) blocks orders — `merchant_auth` refuses a frozen
merchant with `403 merchant_frozen` — never money in: support can always
credit a frozen merchant.

### What a movement is _about_ — the reference (M3b Task 2)

A leg says how much moved and in which direction. The transaction's
**reference** says what it was about, and it is a separate axis: two credits
with identical legs can be an ordinary prepayment and the settlement of one
failed order.

| Movement                 | `reference_type` | `reference_id` |
| ------------------------ | ---------------- | -------------- |
| Prepayment (no order)    | `merchant`       | `merchant_id`  |
| Order charge             | `order`          | our `order_id` |
| Credit settling an order | `order`          | our `order_id` |
| Automatic refund (M3b)   | `order`          | our `order_id` |

Both words are spelled once, in `deposit.ORDER_REFERENCE_TYPE` /
`MERCHANT_REFERENCE_TYPE`, and read back through one function,
`deposit.order_reference_of`. That is not tidiness. Until M3b Task 2 the
writer and the reader each carried their own literal: `credit_deposit` wrote
`merchant` while `refunded_for_order` filtered `order`, so `refunded_usd`
could only ever answer `"0.00"` — the hand settlement support performs after a
failed delivery moved the balance and appeared **nowhere on the order it paid
for**. A mismatch is now a `NameError`, not a silent zero.

Two surfaces read the reference, and neither needed a contract change to start
telling the truth:

- `refunded_usd` on `GET /merchant/v1/orders/{merchant_order_id}` sums the
  **debit** legs on the merchant's `merchant_deposit` account across every
  transaction referencing that order (`deposit.refunded_for_order`). It reads
  a direction, not a transaction kind, so whatever M3b's automatic refund
  calls its posting lands there too.
- `order_id` / `merchant_order_id` on `GET /merchant/v1/transactions` are set
  on any row that names an order — a charge, a settlement credit, and an
  automatic refund.

`reference_type` is a free-form `String(32)` and **nothing validates it**, so
a posting spelled `merchant_refund` — naming the reference after its purpose,
which is the natural thing to write — would move the money and read `"0.00"`
on the order, silently. Every writer goes through the constants above; that is
the whole reason they exist.

Attributing a credit is **additive and optional**. Omit `order_id` and the
posting is byte-for-byte what it was: same legs, same kind, same
`merchant` reference, same null columns on the statement. The
`balance.credited` webhook payload is untouched either way — its key set is
published as exactly `{amount_usd, balance_usd}`, and a receiver is entitled
to that.

**The order must be the credited merchant's.** One that is not — including an
order that does not exist, and a string that is not a UUID — answers a single
`404 order_not_found`. The rule is `/merchant/v1`'s: a distinguishable "not
yours" is an oracle. Support has an order lookup of its own and loses nothing
by the discipline; what it buys is that the guard is already right when M4's
cabinet reaches `credit_deposit` from a surface where a merchant, not an
operator, picked the id. The id is canonicalised (`str(UUID(...))`) before it
is compared **and** before it is stored, because `orders.id` is a Postgres
`uuid` — a `{braced}` .NET spelling reaching it raw is a 500 — while
`reference_id` is a `VARCHAR` that would happily store a spelling matching
nothing, which is this same defect one layer down.

### Automatic refunds (M3b Task 3)

> Drawn in `docs/architecture/sequence-diagrams/merchant-refund.mmd`; the
> decisions behind it — and the gaps it leaves open on purpose — are
> [ADR-0071](../../../../../../docs/decisions/0071-merchant-refunds.md).

`refund.refund_order` posts the third row of the table above:
`D merchant_deposit / C house_payments_received`, keyed
`merchant-order-refund:{order_id}`, referencing the order, `kind`
`merchant_order_refund`.

**One thing fires it**, from `fulfillment.service._settle_merchant_deposit`:
a terminal fulfilment failure on an order with a `merchant_id` whose
`MoneyOutcome` is `RETURNED`. `SPENT` and `UNKNOWN` post nothing and raise
`_alert_merchant_needs_a_human` instead — refunding money we did not get back
is not a safe failure mode, and it is the owner's decision, not a default
waiting to be optimised. Almost every `g2b` failure **from a call that went
out** is `UNKNOWN` (see `fulfillment/README.md`), so that lane is real; how big
it is nobody has counted, and an earlier version of this sentence claimed
"most" without a measurement behind it. The one exception, added in M3c, is a
game create G2B refuses with its own `HTTP 400 {"message":"Invalid player
ID…","success":false}` — the owner ruled on 2026-09-09 that they do not debit
us for it, so that one refunds itself. It is matched on their exact envelope
and on the **whole** message (case-folded, whitespace-collapsed) and on
nothing looser — a reworded variant is a rejection we have not been told
about, and it keeps answering `UNKNOWN` and keeps fetching a human.

**What that changes for the reseller, which is not obvious from the field:**
before M3c the order parked, so a corrected player id could be delivered on
the _same_ order by an operator Retry. Now the deposit is back within seconds
and the order is closed to re-driving — Retry and Force-complete both answer
`409 deposit_already_returned` (see "A refunded order may not be
re-driven" below). The reseller places a **new** order with a new
`merchant_order_id`; `refunded_usd` and `fulfillment_failed_refunded` are what
tell them so.

**The amount is the charge's, read off the charge's own ledger transaction**
(`deposit.charged_for_order`), never off `order_items.unit_price_usd` and
never off the order total. Those two carry **one number** today —
`merchants.orders.place` binds `quote.price_for`'s result once and hands the
same value to `unit_price_usd_override` and to `charge_deposit` — but by
construction, not by any constraint, and a line a migration or a repair script
edited must not decide what we pay back. An order that was never charged must
also refund nothing, and a price on a line is present whether or not any money
followed it. An order with **no** charge posting is not swallowed: it cannot
happen — the debit and the order row are written in one transaction — so it is
a bug or a hand-edited row, and it raises, alerts and leaves the failure
refundable by hand.

**Where it runs, and why not where the failure is recorded.** Under
`drain_pending_tasks` a task runs inside a SAVEPOINT whose crash arm answers
an unexpected exception with `UNKNOWN` — the one value `record_money_outcome`
never lets anything move back down, with no operator re-grade path anywhere in
the system. A refund raising inside that savepoint would roll back the
`RETURNED` it was acting on and replace it with a permanent "we cannot tell":
_the attempt to refund would make the order unrefundable._ So the seam runs
after the savepoint is released, at the **four** sites that can terminally
fail a merchant task — the drain, `retry_task`, `process_webhook_update` and
`fail_manual_task`. Merchant orders are enqueue-only by construction
(`orders._enqueue_only`), so no merchant task is ever run by the synchronous
`start_for_order` path, and those four are the rest. The fourth is reachable
because a B2B-visible `top_up` SKU with **no active `SkuSupplierMapping`** —
and no sourcing rule — falls through `sourcing._resolve_auto` to
`supplier:manual`.

**The seam's whole body is inside one savepoint and one `except Exception`** —
the lazy import, the three reads, the posting and the alert. Propagating is
what that avoids, and the cost of propagating is not the money but the queue:
a deterministic fault escapes `drain_pending_tasks`, rolls the batch back,
returns every row to `pending` and re-crashes next tick, taking the
**storefront's** fulfilment down with the reseller's. Catching is safe because
of where it sits: outside the per-task savepoint, so it can never reach the
crash arm and never write `UNKNOWN`.

Nothing is swallowed, which is the half of the 64decbd rule that actually
matters. Every exception is logged at `error` with the order id and raises the
`merchant_refund_failed` alert, and the log line carries
`modelled=true|false` — `RefundError`/`AppError`/`SQLAlchemyError` against
anything else — so an ordinary "support already settled this" and an
`ImportError` from the lazy import are one query apart rather than
indistinguishable.

**Two** regions are outside both, and both are deliberate.

The first is the flush of the **caller's** pending writes. A savepoint cannot
contain it without a rollback discarding the very failure record the refund
exists to act on. It introduces no failure that was not already there — delete
the call and `_load_task`'s autoflush fires the identical flush one statement
later — so what the placement buys is not avoiding a failure but making it
_visible_: outside, it reaches the caller; inside, it would be swallowed. That
statement is all the seam's _placement_ still protects, and it has its own
test.

The second is the `except` arm itself, which is outside its own `try` by
construction. That is not a footnote: the arm used to hold a lazy
`from ...refund import RefundError`, so on the one input the catch exists for —
`merchants.refund` unimportable — the body's import raised, control reached the
handler, and the handler's import raised too, and `ImportError` escaped with no
line and no alert. The classification now reads `sys.modules` and imports
nothing (`_is_modelled`), and the handler body has a `try` of its own whose
fallback formats nothing, because a reporter that needs the failing exception
to be printable fails on exactly the exception worth reporting.

Retail pays neither. The `merchant_id` gate (`_merchant_of_task`) is one
indexed read **inside the try and ahead of the savepoint**, so a storefront
task that runs the warehouse dry with no fallback to switch to — a `RETURNED`
failure, and one of the commoner ones — costs one query and no
`SAVEPOINT`/`RELEASE` pair.

Those two placements are different things, and confusing them is how the gate
briefly sat outside every catch one commit after the catch was widened for
exactly that class. Inside the try, a fault there is reported like any other.
Outside the savepoint, a **transaction-poisoning** fault there is reported and
_not repaired_ — there is nothing to roll back to, the rest of the batch fails
behind it, and the worker's rollback-and-retick is what recovers. That is the
trade the retail fast path buys, and it is cheap because the deterministic half
is unreachable: `one_or_none()` over a primary-key join, after the flush has
already run.

**A refunded order may not be re-driven.** `charge_deposit` is idempotent on
`merchant-order:{order_id}`, so a _second_ charge for one order replays the
first transaction and **debits nothing**. Refund the deposit, click Retry —
one button in the admin SPA, and the failure it exists for looks identical to
this one — and a success hands the reseller the goods _and_ their money back,
with no code path noticing. `_refuse_a_settled_merchant_order` closes it in
`retry_task` (and so in `bulk_retry_tasks`) and in `complete_manual_task`'s
`force=True` arm, with `409 deposit_already_returned`. It reads the same sum
`refunded_usd` publishes, so it catches a **hand** settlement too — an
operator crediting the order and another retrying it is the same loophole
through a different door, and it predates the automatic refund. Refusing beats
re-charging under a fresh key: a reseller told the money is back has probably
already settled with their own customer, and silently debiting them again for
an order they closed is a surprise money movement that can also fail on a
balance no longer covering it, mid-retry. The recovery is the one the contract
already describes — place a new order.

**A fully settled order is closed, and its status says so (M3c Tasks 6 and 4).**
`end_a_refunded_merchant_order`, in the same savepoint as the posting, sets
`order.status = "failed"`, writes an `order.failed` event and routes the move
through `orders.service.on_order_status_changed`. The reason is the paragraph
above: retail's rule that a terminal fulfilment failure leaves the order row
alone exists because an operator may still top up, retry or deliver by hand,
and for a refunded order **every one of those is already refused**. The status
said "in progress" about an order with no way out, which is what an owner found
at 05:30 on the stuck-order alert.

**Task 4 gives it the second caller, and the placement is the decision.** A
settlement a person books through `deposit.credit_deposit` closes the order
identically, because what ends an order is that the money is back and not who
decided it. It lives at the **posting** rather than in the admin SPA's new
settle button: put it in the button and the runbook's `curl` procedure and M4's
cabinet keep leaving orders open — the same inconsistency, only harder to find,
and dependent on which surface the operator used. The counter-proposal (compose
at the admin service layer, keep the money primitive money-only) is answered in
`_close_a_settled_order`'s own docstring rather than only here: the primitive
already reasons about the order — `_refuse_over_settlement` caps a credit
against **that order's** charge — so this is the same invariant's other half,
refuse above the total and close at it.

Five things about it are worth knowing before anyone widens it:

- **`failed`, not a new `refunded` value.** The integrator contract tells
  clients to treat an unknown `status` as _still in flight_, so a value minted
  today would be polled for ever by everyone already integrated — strictly
  worse than doing nothing. `failed` is already published as terminal and
  already documented as reachable "from any of the first three".
- **The precedence in `order_status._failure_reason` had to move with it.**
  That function tested `order.status == "failed"` first and answered
  `order_failed`; leaving it would have collapsed every automatic refund to
  "support closed this by hand" in the same commit that added the status. The
  refunded branch now runs first, and `order_failed` keeps winning wherever
  money is still owed — nothing back, or only part of it.
- **Only on a full settlement, measured off the ledger** through
  `refund.settled_in_full` — the same predicate `failure_reason` and the
  cancellation alert ask. The reason is that **money is still owed**, so the
  order is not over: a partial is a person mid-decision and the remainder is
  theirs to finish. It is _not_ that closing would take away their retry —
  `_refuse_a_settled_merchant_order` already refuses both `retry_task` and
  `complete_manual_task` on any returned amount, so a partially settled order
  lost its retry the moment the first cent landed.
- **`list_stuck_paid_orders` stops matching it for free.** Its `STUCK_STATUSES`
  is `paid`/`fulfilling`/`fulfilled`, so the five-minute watchdog goes quiet
  about an order we no longer hold money for without learning anything about
  merchants. That is why there is no merchant gate on that query: the state was
  wrong, not the alert.
- **The `failure_reason` a hand settlement leaves is not always
  `fulfillment_failed_refunded`.** That value needs a **failed item**, which is
  the case the settlement exists for. Settle an order whose delivery was
  _cancelled_ instead — nothing coming, but no item `failed` — and the reseller
  reads `order_failed`: a person ended it, the delivery did not. Both are
  terminal and both are true; it is the one place the two paths give different
  words for the same money returned.
- **A settlement is refused while a fulfilment task is open**
  (`409 order_still_fulfilling`, naming the tasks). The terminal status this
  writes is only true if the delivery is over, and the queue does not honour
  `deposit_already_returned` — `drain_pending_tasks` claims on
  `status = 'pending'` alone, so an order closed with a live task would have
  been bought from the supplier afterwards and the reseller would hold the
  goods and the money. `credit_deposit` takes `FOR UPDATE` on the order's task
  rows before it decides, so the drain's `SKIP LOCKED` claim skips the order
  instead of racing it.

The reseller-visible consequences — `order.status_changed` by push, and the
`order.failed` timeline line — are under
`GET /merchant/v1/orders/{merchant_order_id}` and "Outgoing webhooks".

**The automatic path and the hand path cannot stack.** They live in different
ledger-key namespaces (the operator's key is
`merchant-credit:{merchant}:{whatever they typed}`), so `post()` cannot dedupe
them: without a check, support settling at 10:00 and the drain running at
10:05 would credit one order's deposit twice and publish `refunded_usd:
"2.14"` on a `"1.07"` order. Both directions are closed —
`refund_order` refuses an order anything has already returned money on
(`AlreadySettledError`, after its own key check so a replay still replays),
and `credit_deposit` refuses a credit that would take an order past what it
charged (`409 order_already_settled`). Goodwill beyond the order's price is
still an **unattributed** credit, exactly as before.

**A frozen merchant is refunded like any other.** Freezing blocks new orders
and has never blocked money in; an account under review is still owed for
goods we failed to deliver.

**Cancellation is a money state this does not resolve, and says so.**
`_apply_cancel` (an admin cancelling a task, or the order/refund cascade)
records **no** money outcome, so no refund fires — while the deposit stays
debited and the order becomes unmovable, since `retry_task` and
`complete_manual_task` both refuse a `cancelled` task. It is also the shape
most likely to have left our money with us, because a cancel usually precedes
any supplier verdict. Inferring a refund from it would be exactly the guess
`MoneyOutcome` exists to forbid — cancelling is a human action taken for a
reason this code cannot see — so the deposit is left to a human and the state
is made **loud** instead: `log.warning("merchant_task_cancelled")` plus the
`_alert_merchant_order_cancelled` ops alert, deduped per order for an hour.
The runbook says what to do with one.

It fires **unless the order is square against what it charged** —
`refund.settled_in_full`, the same predicate `failure_reason` splits on, and
deliberately not "has anything come back". `cancel_open_tasks_for_order`
cancels `failed` tasks too, so any tidy-up of an already-refunded order runs
straight through that line: an operator cancelling the dead task from the
Fulfilment Inbox, and, before M3c Task 6 closed these orders itself, the
support step of closing the order by hand. An alert saying "the deposit is
still debited" about an order reading `refunded_usd: "1.07"` would be wrong on
the feature's commonest path, and an alert that is wrong on the common path is
one nobody reads by the time it is right. A **partial** settlement is not
square, so it still alerts — which is the point: that is the state with money
genuinely parked.

`fail_manual_task`'s `UNKNOWN` refunds nothing, so calling the seam there
moves no money today; it is there so the safety does not rest on which
constant that function happens to record.

## Pricing

The wholesale price formula — the **one home**, per
`docs/superpowers/plans/2026-09-06-merchant-b2b-m1.md` Task 5 — lives in
`pricing.py` and nowhere else:

```
price = ceil_to_cent(
    effective_cost(sku) * (1 + (sku.b2b_markup_pct + (merchant.markup_adjustment_pp ?? 0)) / 100)
)
```

Five pure functions, all `Decimal`, no DB access:

- `effective_cost(sku) -> Decimal | None` reads `sku.cost_usdt`. `None`
  means the SKU is **not sellable B2B** — excluded from the merchant
  catalog, orders for it rejected. It never falls back to `price_usd` or
  any other retail figure (spec §8.2).
- `merchant_markup_pct(sku, merchant)` adds the dormant per-merchant
  `markup_adjustment_pp` (spec §8.3, `None` for every merchant in v1) to
  the SKU's uniform `b2b_markup_pct`.
- `merchant_price(cost, markup_pct)` rounds up to the cent
  (`ROUND_CEILING`) — rounding down would erase margin on cheap SKUs
  invisibly, a cent at a time.
- `violates_margin_floor(cost, price, floor_pct)` is the only global
  pricing control (spec §8.3): it catches a fat-fingered per-SKU markup
  (including one that goes negative — Task 4 deliberately added no DB
  `CHECK` on `b2b_markup_pct`) and cost spikes a stale markup no longer
  covers. Callers read `settings.merchant_margin_floor_pct` (default `2`)
  and pass it in; the pure functions never read settings themselves.
- `price_to_charge(current, expected)` is the single home of the ±2% drift
  rule (spec §8.4, amended by the owner 2026-09-07): inside the band it
  returns `current` — **our** price, never the merchant's and never the lower
  of the two — and outside it returns `None`, which the order path turns into
  `422 price_changed`. Its docstring carries why, in full. The order path
  decides nothing about drift on its own, so the policy changes here or
  nowhere.

**Nothing else in the codebase may reimplement this formula.** The one
sanctioned exception is the admin SPA's client-side price _preview_ next to
the markup field (Task 8, labelled «предварительно») — display-only, never
authoritative; the server always recomputes and is the source of truth for
what a merchant is actually charged.

Import these from `api`, not from `pricing` directly — the same rule as
every other symbol in this module.

## Admin surface

Everything support needs to run a pilot merchant by hand (Task 6), all
admin-gated (`require_admin`), business logic imported through the `api`
facade only.

**The operator reads the reseller's own words (M3c Task 3).** The admin order
list and detail carry `failure_reason` with exactly the values published under
`GET /merchant/v1/orders/{merchant_order_id}` below, computed by
`order_status.order_stop_states` — the batch form of the same `_failure_reason`
this module already had, over the same `refund.settled_in_full` and the same
`fulfillment.stall` predicate. It is one function and not two on purpose: the
operator answering "why has my order stopped" is reading it off the screen
while the reseller reads it off the API, and two spellings would let them
disagree about one order in front of a customer. It is batched because a list
endpoint may not ask per row (AGENTS.md §10) — three reads for a page of up to
500, none of them per order. Retail orders are included and get a real answer;
only the refunded value is merchant-shaped, because it is measured off the
deposit ledger, which a retail order has no rows in.
Two routers — `admin_router` in `admin_routes.py` and
`catalog_b2b_router` in `catalog_b2b_routes.py`, split apart in M3a Task 2
when the one file passed §6's split-before-500 line, sharing the replay
helpers in `route_replay.py` (both mounted by `api/v1` directly from their
own module — the facade never exports a router, or it would close a cycle
back through the route stack, same rule as `affiliate.routes`):

- `POST`/`GET /admin/merchants` — create a reseller; list every merchant
  with its USD deposit balance joined in **one grouped query**
  (`admin.list_merchants_with_balances`, the batch variant of
  `deposit_balance` — no per-merchant balance read).
- `POST /admin/merchants/{id}/freeze|unfreeze` — persists `status`. M1 only
  recorded it; since M2 it is enforced, by `merchant_auth` refusing every
  `/merchant/v1` request from a frozen merchant with `403 merchant_frozen`.
- `POST /admin/merchants/{id}/deposit-credits` — posts via
  `deposit.credit_deposit`. **Requires** `Idempotency-Key`; the ledger key
  is namespaced `merchant-credit:{merchant_id}:{client_key}` so one
  client's key can never replay another merchant's transaction. The ledger
  replays by key **without comparing parameters**, so the response's
  `amount` and `order_id` are the transaction's actual (original) ones — a
  mismatched replay is visible to the admin UI, and `balance` rides along.
  The optional body field **`order_id`** (M3b Task 2) names the order this
  credit settles: our order id, not the reseller's `merchant_order_id`, and it
  must be an order of this merchant's — one that is not answers
  `404 order_not_found`, byte-identically to an id that never existed. Given,
  the amount shows on that order's `refunded_usd` and carries the order onto
  the merchant's own statement; omitted, the credit is the ordinary
  prepayment, unchanged. The ledger key is deliberately **not** derived from
  it: the client key is the replay handle, and the runbook's
  `refund-<order-id>` already namespaces a settlement by order. See "What a
  movement is _about_" above and
  `docs/architecture/sequence-diagrams/merchant-deposit-credit.mmd`.
  The admin SPA's deposit-credit form carries the field, validates the id
  the way this endpoint does (so a pasted `merchant_order_id` is caught
  before it becomes a `404` reading "no such order"), and echoes the booked
  attribution back — see `docs/runbooks/merchant-b2b.md`.
  **Since M3c Task 4 the order's own page has a second, narrower door**: a
  «Депозит мерчанта» card showing what the order charged and what has come
  back, with one button that returns the charge — no typing, a fresh
  `Idempotency-Key` per attempt, and a confirmation naming the merchant, the
  amount and the order first. It is hidden on an order that is square (nothing
  to do), on a partly settled one (it posts the whole charge, which
  `order_already_settled` would refuse every time), and on one whose delivery
  has **not** terminally failed — settling a live order returns the money
  without stopping the supplier call, so the drain could still deliver goods
  the reseller has been paid back for. That last gap is the API's and predates
  the button (the merchant page's form has always allowed it); the button
  declines to be a one-click way into it. A refusal that does reach it is
  rendered as a sentence rather than as a raw `409`. And **an attributed
  credit that brings the order to a full settlement closes it** — the same
  closer, the same predicate, at the posting rather than in the button, so
  the runbook's `curl` and M4's cabinet close it too.
- `GET /admin/merchants/{id}/transactions` — the merchant's deposit ledger,
  newest first (`deposit.list_deposit_transactions`, one grouped query —
  shared with `/merchant/v1/transactions` rather than copied). Each row
  carries the **signed** deposit delta (positive = balance up; order charges
  surface as negative rows, unchanged), the credit's `note`, and
  the `admin:<id>` actor. Read-only; a typo'd merchant id is a 404, never a
  plausible-looking `[]`.
- `PATCH /admin/catalog/skus/{id}/b2b` (`markup_pct?`, `visible_b2b?`),
  `POST /admin/catalog/b2b/bulk-markup` (`brand_slug | category`,
  `markup_pct` — one UPDATE, returns the affected count) and
  `PATCH /admin/catalog/brands/{id}/b2b` (`visible_b2b`) — the catalog B2B
  knobs. No pricing math in routes; the markup is stored verbatim and the
  order-time margin floor is the guard (spec §8.3).

- `POST /admin/merchants/{id}/api-keys` — mint a machine credential
  (`label?`, `ip_allowlist?`). **The secret is in this response and nowhere
  else, ever.** `GET .../api-keys` lists every key ever issued, newest
  first, revoked ones included, and its response model has no `secret`
  field at all. `DELETE .../api-keys/{key_id}` revokes: it sets
  `revoked_at`, is naturally idempotent (a second call returns the FIRST
  timestamp rather than moving it), and matches on `(merchant_id, key_id)`
  so one merchant's id in the path can never revoke another's credential.

- `PUT /admin/merchants/{id}/webhook` — point the merchant's outgoing
  webhook at a URL. **The signing secret is in this response and nowhere
  else, ever.** One endpoint per merchant in v1, so this is an upsert: the
  first call mints the secret and returns it once; a later call edits the URL
  of the same row and answers `secret: null`, because changing where
  deliveries go must not silently break a working verifier — rotation is its
  own endpoint. Setting a URL also clears `disabled_at` and resets
  `failure_streak`, which is the recovery path after the delivery worker
  auto-disables a hook. Two operators saving at once both miss the pre-check
  and both insert; the loser resolves the uniqueness violation by returning
  the **winner's** row with `secret: null` rather than a 500 — the winner
  minted the key, so a second secret would sign nothing, and the advice on a
  lost response is the same as for a lost mint: rotate. The URL is refused at save time unless it is `https`
  with a public host, through the same
  `catalog.image_url_safety.validate_public_https_url` the catalog's image
  URLs go through — one blocked-range table in the repo, not two that drift.
  That check reads notation, not resolved addresses; DNS rebinding is the
  outbound client's problem, not this validator's.
  `POST .../webhook/rotate-secret` mints a replacement and returns it once,
  with no overlap window (unlike an API key, where the _merchant_ redeploys
  between issue and revoke — here we are the sender and the switch is ours).
  `DELETE .../webhook` disables by setting `disabled_at`, is naturally
  idempotent, and is a disable rather than a delete so the delivery log and
  the URL stay readable. `GET .../webhook` returns the configuration and its
  delivery health, and its response model has no `secret` field at all.

  **Configuration is admin-only in M3a by owner decision.** The merchant gets
  this control from the cabinet in M4; there is deliberately no
  `/merchant/v1` write for it, because its only purpose would be to let a
  stranger aim our own worker at an address of their choosing. The
  consequence, stated rather than discovered: a pilot cannot receive webhooks
  before M4 unless support sets the URL.

The non-ledger writes accept an optional `Idempotency-Key` and replay
through the generic `(scope, key)` store (`core.idempotency`), like the
other admin write endpoints. Each scope is **per resource** —
`merchants.sku_b2b:{sku_id}`, `merchants.brand_b2b:{brand_id}`,
`merchants.bulk_markup:{target}`, `merchants.set_status.{to}:{merchant_id}`,
`merchants.api_key_create:{merchant_id}`,
`merchants.api_key_revoke:{merchant_id}:{key_id}`,
`merchants.webhook_set:{merchant_id}`,
`merchants.webhook_rotate:{merchant_id}`,
`merchants.webhook_disable:{merchant_id}` — because an admin client
that mints one key per session and reuses it across two SKUs would
otherwise get the first SKU's response replayed for the second, and the
second SKU would silently never be patched.

Key creation and the two webhook writes that can mint a secret are the
endpoints where the replay snapshot is deliberately **not** the response: the
stored body carries `secret: null`, so a retry returns the original row with
no secret. `idempotent_responses` has no reaper, and a usable credential
sitting there in the clear forever is worse than telling an operator whose
first response was lost to revoke or rotate and take the new one.

The admin SPA screens for this surface live in
`apps/admin/src/features/merchants/` (`/merchants` list + create,
`/merchants/:id` freeze / deposit credit / ledger). The deposit-credit form
is the UI half of the replay-visibility mechanism above: it compares the
response's `amount` **and its `order_id`** with what the operator entered and
warns loudly on either mismatch (`1db6ccf` — a replay can silently ignore the
order just as it can the amount, and unlike the amount the attribution cannot
be repaired afterwards), mints one idempotency key per logical credit attempt
(stable across retries), and blocks double-submit while a credit is in flight.

The catalog B2B knobs (Task 8) live on the catalog edit screens instead —
`apps/admin/src/features/catalog/b2b.ts` plus a `SkuB2bCard` /
`BrandB2bCard` on the SKU and brand editors: the `visible_b2b` switches,
the per-SKU markup with the sanctioned «предварительно» price preview
(see "Pricing" above — `previewB2bPrice` mirrors `pricing.merchant_price`
in BigInt math and names this module as the authority), and the bulk
"наценка всем SKU бренда" action, confirm-gated because it rewrites the
whole brand's markups, reporting `affected` from the response. The read
side those controls render from is `AdminBrandOut.visible_b2b` /
`AdminSkuOut.{visible_b2b,b2b_markup_pct}` in the catalog module's admin
list DTOs — admin-only, never on the public catalog DTOs.

## Machine-API authentication (`/merchant/v1`)

**This section is the contract.** Third parties implement against the text
below without reading our source, so it must stay complete and it must not
change without a new API version — `/merchant/v1` is consumed by code nobody
but its owner can redeploy.

> **Status:** every endpoint documented below is live — authentication, the
> two reads, order placement, the order read, the deposit ledger and the player
> check. The scheme is final. **Outgoing webhooks are live too** (see "Outgoing
> webhooks" below), configured by support rather than by you. What does not
> exist yet is any refund path and the self-service cabinet; see "Status" at
> the end of this file.

Base URL: **`https://api.yupay.uz`**. All requests are HTTPS. All strings are
UTF-8. Every `\n` below is a single LF byte (`0x0A`) — never CRLF.

**In a hurry?** ["Your first order in ten minutes"](#your-first-order-in-ten-minutes)
is this same contract as a runnable script, with signatures you can check
offline before you have an account.

### Credentials

Support issues a key from the admin surface and hands over two values:

| Value    | Example                                     | Notes                                              |
| -------- | ------------------------------------------- | -------------------------------------------------- |
| `key_id` | `ypm_9j2v…` (36 chars)                      | Public. Sent on every request.                     |
| `secret` | `ypms_Rk8…` (48 chars, 256 bits of entropy) | **Shown once.** Store it; we cannot show it again. |

Several keys can be live at the same time, which is what makes rotation
zero-downtime: issue the new one, deploy it, then revoke the old one.

We hold the secret **encrypted at rest** (XSalsa20-Poly1305 under an
application key that is not in the database), which is what lets us verify
your signature without keeping key material in the clear. Honest boundary: a
stolen database dump on its own yields nothing usable; an attacker holding
both the dump and the application key is another matter, and the controls that
bound that are revocation and the per-key IP allowlist.

### The signature

Three headers on every request:

```
X-Merchant-Key:       <key_id>
X-Merchant-Timestamp: <unix seconds, digits only>
X-Merchant-Signature: <lowercase hex HMAC-SHA256>
```

The signature is `HMAC_SHA256(secret, canonical)` — the secret's UTF-8 bytes
are the key, with **no derivation step** — where the canonical string is five
fields joined by LF:

```
canonical = timestamp + "\n" + METHOD + "\n" + raw_path + "\n" + raw_query + "\n" + sha256_hex(body)
```

| Field              | What exactly                                                                                                                                                    |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `timestamp`        | The **same characters** you put in the header. Do not re-format it.                                                                                             |
| `METHOD`           | Upper-case: `GET`, `POST`.                                                                                                                                      |
| `raw_path`         | The path **exactly as it appears on the request line**, percent-encoded, no scheme, no host, no query: `/merchant/v1/orders/my%2Forder`.                        |
| `raw_query`        | The query string **as sent**, without the leading `?`. Empty string when there is no query — the field is still there, so the string still has four separators. |
| `sha256_hex(body)` | Lowercase hex SHA-256 of the raw request body. A GET signs `sha256("")` = `e3b0c442…b855`, not an empty field.                                                  |

Three consequences worth stating outright:

- **Sign the bytes you send.** Re-serialising your JSON between signing and
  sending changes the signature. Sign the exact byte string, then send it.
- **Do not decode the path or the query before signing.** They are signed in
  their encoded form, which is what removes every ambiguity about how a
  character in your own `merchant_order_id` should be spelled.
- **The query string is covered.** `?limit=10` and `?limit=100000` are
  different requests and need different signatures.

### Worked example

`GET /merchant/v1/me` at `1757000000`, no query, no body:

```
canonical = "1757000000\nGET\n/merchant/v1/me\n\ne3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
```

Python:

```python
import hashlib, hmac, time, httpx

KEY_ID = "ypm_…"
SECRET = "ypms_…"
BASE = "https://api.yupay.uz"


def call(method: str, path: str, query: str = "", body: bytes = b"") -> httpx.Response:
    ts = str(int(time.time()))
    canonical = "\n".join(
        (ts, method.upper(), path, query, hashlib.sha256(body).hexdigest())
    ).encode()
    signature = hmac.new(SECRET.encode(), canonical, hashlib.sha256).hexdigest()
    url = f"{BASE}{path}?{query}" if query else f"{BASE}{path}"
    return httpx.request(
        method,
        url,
        content=body,
        headers={
            "X-Merchant-Key": KEY_ID,
            "X-Merchant-Timestamp": ts,
            "X-Merchant-Signature": signature,
            "Content-Type": "application/json",
        },
    )
```

Node 18+ (no dependencies):

```js
import crypto from "node:crypto";

const KEY_ID = "ypm_…";
const SECRET = "ypms_…";
const BASE = "https://api.yupay.uz";

export async function call(method, path, query = "", body = "") {
  const bodyBytes = Buffer.from(body, "utf8");
  const ts = Math.floor(Date.now() / 1000).toString();
  const bodyHash = crypto.createHash("sha256").update(bodyBytes).digest("hex");
  const canonical = [ts, method.toUpperCase(), path, query, bodyHash].join("\n");
  const signature = crypto
    .createHmac("sha256", SECRET) // the secret itself is the key — no pre-hashing
    .update(canonical, "utf8")
    .digest("hex");

  const url = query ? `${BASE}${path}?${query}` : `${BASE}${path}`;
  return fetch(url, {
    method,
    body: bodyBytes.length ? bodyBytes : undefined,
    headers: {
      "X-Merchant-Key": KEY_ID,
      "X-Merchant-Timestamp": ts,
      "X-Merchant-Signature": signature,
      "Content-Type": "application/json",
    },
  });
}
```

### Rules the server applies, in order

The whole path is drawn in
`docs/architecture/sequence-diagrams/merchant-api-auth.mmd`.

| #   | Failure                                                      | Status | `code`                |
| --- | ------------------------------------------------------------ | ------ | --------------------- |
| 1   | Too many requests **from this address**                      | 429    | —                     |
| 2   | A credential header missing                                  | 401    | `missing_credentials` |
| 3   | Timestamp not digits-only, or more than **±300 s** from ours | 401    | `stale_timestamp`     |
| 4   | Unknown `key_id`, revoked key, or wrong signature            | 401    | `invalid_credentials` |
| 5   | Too many requests **for this key**                           | 429    | —                     |
| 6   | Merchant frozen                                              | 403    | `merchant_frozen`     |
| 7   | Caller's address not in the key's IP allowlist               | 403    | `ip_not_allowed`      |

The two rate-limit axes really do sit at 1 and 5, not together: the per-address
counter is charged before anything is parsed, so an unauthenticated flood costs
us one Redis increment, and the per-key counter is charged only once your
signature has verified, so nobody who reads your `key_id` off a header can
spend your budget.

The three credential failures return **one identical body** on purpose: the
payload does not reveal whether a `key_id` exists, and the HMAC is computed
either way so the crypto cost does not either.

### Replay and retries

**Retries are safe. Resend the identical request, headers and all.** A
signature is valid for the whole ±300 s window and may be presented more than
once — there is no single-use marker, no "re-sign the retry" rule, and no
minimum interval between identical requests. That is deliberate: an attacker
replaying a request and your client retrying one are byte-identical, so a
server-side marker cannot separate them and would only turn a network fault
into an auth error. Neither AWS SigV4 nor Stripe single-uses a signature
either.

What bounds replay instead:

- **The ±300 s window.** A captured request stops working five minutes after
  it was signed. Keep your server's clock in sync.
- **Your credentials stay out of our logs.** Our edge deletes
  `X-Merchant-Signature` and `X-Merchant-Key` from the access log, so a signed
  request is not sitting in a log store waiting to be replayed. Keep your side
  of that bargain too: these two headers do not belong in your own request
  logs, and neither does the secret.
- **Idempotency, for anything that changes state.** Order creation is
  idempotent on your `merchant_order_id` (spec §9.3): the same id twice returns
  the existing order rather than placing a second one, whether the repeat came
  from your retry or from somebody replaying you. That is what makes a replayed
  mutation harmless, so **always send a `merchant_order_id` you control and
  reuse it across retries of the same intent.**

Stated plainly, because you should design against it rather than assume
otherwise: a replay inside the window by somebody who can observe your traffic
is **accepted**. The mitigation for mutations is the idempotency above, not the
auth layer.

### Errors

RFC 7807 `application/problem+json`. `type` is the stable identifier; `code`
is a short discriminator on the auth and business failures. A sample body:

```json
{
  "type": "https://app.yupay.uz/errors/unauthorized",
  "title": "Unauthorized",
  "status": 401,
  "detail": "invalid merchant credentials",
  "code": "invalid_credentials"
}
```

The complete set of `type` URIs this API can return:

| `type`                                     | Status | When                                              |
| ------------------------------------------ | ------ | ------------------------------------------------- |
| `https://app.yupay.uz/errors/unauthorized` | 401    | Any authentication failure                        |
| `https://app.yupay.uz/errors/forbidden`    | 403    | Frozen merchant, IP not allowed                   |
| `https://app.yupay.uz/errors/not-found`    | 404    | No such order / SKU / resource                    |
| `https://app.yupay.uz/errors/conflict`     | 409    | Deposit too small, or an id reused for a new body |
| `https://app.yupay.uz/errors/validation`   | 422    | A value we rejected, or a body that did not parse |
| `https://app.yupay.uz/errors/rate-limited` | 429    | Either rate-limit axis                            |

The `type` host is an identifier namespace, not a URL to fetch.

#### Extra fields on the body

`type`, `title`, `status` and `detail` are always present, and `detail` is
always a **string**. Beyond those, an error carries whatever names the failure:

- `code` on every auth and business failure — the short discriminator the
  per-endpoint tables below list. Switch on this, not on `detail`.
- the failure's own facts, at the top level: `current_price` and
  `expected_price` on `price_changed`, `balance_usd` and `required_usd` on
  `insufficient_deposit`, `reason` on `item_unavailable`.
- an `extra` **object** on a `fulfillment_data` refusal, naming the field and
  why. That one is nested; the others are not. Verbatim, so there is nothing
  to guess at:

```json
{
  "type": "https://app.yupay.uz/errors/validation",
  "title": "Validation failed",
  "status": 422,
  "detail": "unexpected fields: ['note']",
  "extra": { "reason": "extra", "keys": ["note"] }
}
```

#### A body that does not parse: `422 invalid_request`

Anything the schema itself refuses — a missing `sku_id`, a misspelled
`fulfilment_data`, an `expected_price` with three decimals, `?limit=0` —
answers problem+json too, with `code: "invalid_request"` and one extra field:
an `errors` array carrying a machine-readable entry per failure.

```json
{
  "type": "https://app.yupay.uz/errors/validation",
  "title": "Validation failed",
  "status": 422,
  "detail": "body.sku_id: Value error, sku_id must be a UUID",
  "code": "invalid_request",
  "errors": [
    {
      "type": "value_error",
      "loc": ["body", "sku_id"],
      "msg": "Value error, sku_id must be a UUID",
      "input": "not-a-uuid",
      "ctx": { "error": {} }
    }
  ]
}
```

Read `errors` for diagnostics — `loc` tells you which field, and `loc[0]` is
`"body"`, `"query"` or `"path"` — but **do not switch on it.** (`ctx.error` is
sometimes an empty object; that is our framework declining to serialise an
internal exception, not a field you are missing.) It is our web framework's shape, passed through unchanged, and
it is the one part of this contract that may be reshaped inside v1. `detail`
summarises the first few in one sentence; `code` is what your code should
branch on.

#### The answers that are **not** problem+json

**A `5xx`.** No endpoint here raises one deliberately. Nothing on this surface
calls a supplier while you wait for _money_ to move (see "Fulfilment is
asynchronous, always"), and the one endpoint that does call a supplier inline —
`POST /merchant/v1/validate/player` — is built to answer `200` with
`status: "error"` when that call fails, precisely so an upstream's bad day is
never your `5xx`. A `500` means an unhandled bug on our
side and arrives as a bare `Internal Server Error`; a `502` or `504` is our
edge rather than our application — most likely a deploy, which holds and
retries for 15 s before giving up. Both are safe to retry: resend the identical
signed request if it is still inside the ±300 s window, re-sign if it is not,
and keep the same `merchant_order_id`.

**A wrong URL or a wrong method**, which our web framework answers before any
of this API's own code runs:

| You sent                                                     | You get                                  |
| ------------------------------------------------------------ | ---------------------------------------- |
| A path this API does not serve (`GET /merchant/v1/nope`)     | `404` `{"detail": "Not Found"}`          |
| A method it does not serve on a path it does (`GET /orders`) | `405` `{"detail": "Method Not Allowed"}` |

Both are `application/json` with no `type` and no `code`. Routing happens
before authentication, so these are also the only two answers you can get
**without** valid credentials — a `405` is not a hint that your signature was
accepted. Note the second row in particular: `POST /merchant/v1/orders` places
an order and `GET /merchant/v1/orders/{merchant_order_id}` reads one, but a
bare `GET /merchant/v1/orders` is not an endpoint. If you meet either of
these, check the URL and the method against the endpoint list below before you
touch your signing code.

### Rate limits

Four independent counters — two on every request, two more on
`validate/player` — all fixed 60-second windows:

| Axis                               | Limit          | Applies to                                        |
| ---------------------------------- | -------------- | ------------------------------------------------- |
| Per source IP address              | **600 / 60 s** | Every request, before authentication              |
| Per `key_id`                       | **600 / 60 s** | Requests whose signature verified                 |
| Per source IP, `validate/*` only   | **120 / 60 s** | `POST /merchant/v1/validate/player`, as well      |
| Per merchant account, `validate/*` | **120 / 60 s** | the same endpoint, whatever address you call from |

All four return `429` with a `Retry-After` header in seconds; wait that long
rather than retrying immediately. The per-key counter is charged only after a
signature verifies, so someone who observes your `key_id` in a header cannot
spend your budget. Each live key has its own counter, so a rotation window
briefly has two — but the `validate/*` pair is keyed on your address and on
your **merchant account**, so neither a key rotation nor a spread of egress
nodes doubles your claim on a supplier's quota. The last two are _additional_,
not instead of: a validate call advances the general counters too, and the
tighter ones simply bind first.

### IP allowlist

A key with an allowlist only authenticates from those addresses; entries are
single addresses (`198.51.100.7`) or CIDR blocks (`203.0.113.0/24`), IPv4 or
IPv6, and host bits inside a block are ignored when matching. No allowlist
means no filter.

**Ask support to set one when the key is issued.** The allowlist is fixed at
issue time — there is no endpoint that edits it, and no self-service cabinet in
v1 — so changing it means issuing a new key and revoking the old one. That is
the same zero-downtime rotation described above, so it costs a deploy, not an
outage.

## Endpoints (`/merchant/v1`)

Also part of the contract. Every response is JSON, and so is every request
body: no endpoint on this surface takes a form-encoded or `multipart` body, and
none will be added inside `v1` — the signature covers the raw body bytes, and
the dependency that verifies it reads them before your handler does, so a form
endpoint would be a different auth scheme wearing this one's name. Every request
is signed as above. **Money is always a JSON string with exactly two decimal
places** (`"1.06"`), never a JSON number — a float round-trips through
IEEE-754 and turns `1.06` into `1.0599999999999999`. Parse it with your
language's decimal type, not its float.

Fields may be **added** to any response without notice; nothing is ever
renamed, retyped or removed inside `v1`. Ignore fields you do not know.

### `GET /merchant/v1/me`

Who you are and what you can spend. Cheap — call it as a health check.

```json
{
  "merchant_id": "0198c3c9-2a44-7c1a-9f3e-4b6f2e0d9a11",
  "title": "Acme Resale",
  "status": "active",
  "balance_usd": "42.50"
}
```

`balance_usd` is your prepaid USD deposit, computed live from the ledger on
every call — there is no cached figure that can disagree with what an order
is charged against. `status` is `active` or `frozen`. A frozen account gets
`403 merchant_frozen` on **every** endpoint, this one included, so in practice
a successful read here always says `active`; the field is there so the value
is explicit rather than inferred, and for the day a third state exists.

### `GET /merchant/v1/catalog`

The whole wholesale price list, priced **for you**. No parameters, no paging:
the B2B catalog is a few hundred lines, and one consistent snapshot beats a
cursor you have to reconcile.

```json
{
  "brands": [
    {
      "brand_id": "0198c3c9-…",
      "slug": "pubg-mobile",
      "name": "PUBG Mobile",
      "products": [
        {
          "product_id": "0198c3ca-…",
          "slug": "pubg-mobile-uc",
          "name": "UC",
          "skus": [
            {
              "sku_id": "0198c3cb-…",
              "sku_code": "PUBGM_UC_60",
              "name": "60 UC",
              "price_usd": "1.06",
              "updated_at": "2026-09-07T08:14:22.918431Z"
            }
          ]
        }
      ]
    }
  ]
}
```

- **`sku_id` is what you order with** (`POST /merchant/v1/orders`), and it is
  the only identifier here we promise never changes: it is a database key, so
  it is never re-pointed and never reused. `sku_code` is our human-readable
  code — it is stable in practice and it is what support will ask you for, but
  an operator editing a SKU **can** rewrite it (as they can a brand or product
  `slug`). Key your mapping table on `sku_id` and carry `sku_code` beside it
  for humans, not the other way round.
- **`price_usd` is your price**, cost plus this SKU's wholesale markup plus
  any adjustment negotiated for your account, rounded up to the cent. It is
  not the retail price and not another merchant's.
- **`name`** is a display label: the SKU's denomination where it has one
  (`"60 UC"`), else its `sku_code`. Brand and product `name`s are Russian —
  the catalog's default language. Use `slug` and `sku_code` as identifiers;
  the names are for showing to people and may be edited.
- **`updated_at`** is that SKU's own last-modified stamp. **There are no price
  webhooks:** poll this endpoint (once a minute is plenty — see the rate
  limits) and act on the SKUs whose `updated_at` moved. One caveat, so you can
  design around it: `updated_at` tracks the **SKU row**, so it does not move
  when a discount negotiated for your account changes — that adjustment
  reprices your whole catalog without touching any SKU. It is unused today
  (every account prices off the flat per-SKU markup) and support tells you
  before it is switched on for you; if you cache prices, re-read the full list
  on that notice as well as on `updated_at`.
- **A SKU appears only if it is currently sellable to you.** It must be
  B2B-visible, have a wholesale cost on file, price above our minimum margin,
  and carry a fixed denomination rather than a customer-chosen amount (a Steam
  wallet top-up prices off a live FX rate, so there is no wholesale number to
  quote — `item_unavailable` / `variable_amount` if you order one anyway). A
  SKU failing any of those is **absent rather than cheap** — never listed at
  zero, and never listed at a price an order would then be rejected for.
  Likewise a brand or product with nothing purchasable under it is absent
  entirely, so you never have to iterate past empty shells.
- **Read an absence as "not currently sellable", not as "deleted".** A SKU can
  leave the list and come back — because it went out of B2B distribution, or
  because its pricing was misconfigured on our side and then fixed. Key your
  own catalog on `sku_id`, and treat a missing id as unavailable rather than
  removing your mapping for it.
- Ordering is ours (curated), stable, and safe to present as-is.
- An empty catalog is `{"brands": []}`, never a `404`.

> **Steam gifts are not in v1.** They are excluded here and cannot be
> ordered through the machine API. Ask support if you need them.

### `POST /merchant/v1/orders`

Buy one SKU. The order is created, charged to your deposit and handed to
fulfilment in a single step — there is no separate "pay" call, and no payment
page: your deposit **is** the payment.

```json
{
  "merchant_order_id": "acme-2026-000417",
  "sku_id": "0198c3cb-…",
  "expected_price": "1.06",
  "fulfillment_data": { "player_id": "5123456789" }
}
```

| Field               | Required | Notes                                                                                                                                                                                                                             |
| ------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `merchant_order_id` | yes      | **Your** id for this order, and the idempotency key. 1–128 printable ASCII characters, no spaces. Unique within your account, and compared **byte for byte** — `MY-ORDER` and `my-order` are two different orders and two debits. |
| `sku_id`            | yes      | From `/catalog`. Must be a UUID.                                                                                                                                                                                                  |
| `quantity`          | see note | **Required** when the SKU's `kind` is `"unit"`, **refused** otherwise — a `422` either way, never a silent default. Must sit inside the SKU's `min_qty`/`max_qty`.                                                                |
| `amount_usd`        | see note | **Required** when the SKU's `kind` is `"amount"`, **refused** otherwise. The **face value you are loading**, not what you pay: $100 of Steam wallet costs $104 at a 4% markup. Inside `min_amount_usd`/`max_amount_usd`.          |
| `expected_price`    | yes      | The **order total** you last computed. For a `fixed` SKU that is its `price_usd`; for a `unit` SKU it is `ceil_to_cent(unit_price_usd × quantity)`. At most two decimals. See "Price drift" below.                                |
| `fulfillment_data`  | no       | Whatever the SKU needs (a player id, a login) — the same fields the storefront collects, validated the same way. **Send those keys and nothing else**: an unrecognised key is a `422`, not a silently ignored one. See below.     |

One SKU per order, and no line array: a reseller's basket does not have to be
ours, and one line per order means "the order failed" never means "half the
order failed". Send several orders.

**Three kinds of SKU, and `/catalog` tells you which.** G-Engine's FIXED /
UNFIXED split, with UNFIXED separated the two ways it actually occurs:

- **`kind: "fixed"`** — a denomination. The row carries `price_usd`, you send
  nothing extra, and `expected_price` is that price.
- **`kind: "unit"`** — a currency sold by the unit (Telegram Stars). The row
  carries `unit_price_usd` at **six** decimals plus `unit`, `min_qty` and
  `max_qty`; you send `quantity`, and
  `expected_price = ceil_to_cent(unit_price_usd × quantity)`.
- **`kind: "amount"`** — a balance loaded in dollars (the Steam wallet). The
  row carries `unit_price_usd` — the price of **one dollar of balance** — plus
  `min_amount_usd` and `max_amount_usd`; you send `amount_usd`, and
  `expected_price = ceil_to_cent(unit_price_usd × amount_usd)`. A dollar of
  balance costs us a dollar, so `unit_price_usd` is simply `1 + markup`:
  `"1.040000"` at 4%, and $100 of balance is $104.

The six decimals are not decoration. One Star costs us about a cent and a
half, so a price rounded to the cent is a rounding _larger than the margin_ —
1000 Stars would be $20.00 instead of $16.54. The rounding to whole cents
happens **once, on your order total**, which is why you can reproduce your
charge exactly from the number we publish.

`expected_price` may be sent as a JSON string (`"1.07"`, what we send you and
what we recommend) **or** as a JSON number (`1.07`). Refusing a well-formed
number would be a worse failure mode than accepting it. More than two decimals
is refused in either spelling — a price does not have them, and silently
rounding your number would be us deciding what you meant.

Unknown fields are **rejected**, not ignored — at both levels, and for the
same reason: a typo'd `fulfilment_data` would otherwise become an order with no
player id, delivered to nobody.

- **At the top level of the body.** Anything beside the four fields above is a
  `422`.
- **Inside `fulfillment_data`.** Only the keys that SKU's product declares are
  accepted; any other key refuses the whole order with
  `detail: "unexpected fields: [...]"` and an `extra.keys` listing them. So do
  not pass your own correlation ids or spare diagnostics through here — put
  them in your `merchant_order_id`, which is yours to shape.
- **For a SKU that asks for nothing** (most vouchers), the only accepted values
  are `{}` and leaving the field out. `{"note": "…"}` is a `422`.

Unknown fields in our _responses_ are still yours to ignore; that rule is
one-way on purpose.

Success is `201`:

```json
{
  "merchant_order_id": "acme-2026-000417",
  "order_id": "0198c3d1-…",
  "status": "fulfilling",
  "sku_id": "0198c3cb-…",
  "price_usd": "1.06",
  "balance_usd": "41.44",
  "created_at": "2026-09-07T08:20:11.402913Z"
}
```

- **`price_usd` is what you were actually charged**, and it is final. Whatever
  the order ends up costing us is our problem, not yours.
- **`balance_usd` is your deposit as of this response.** On the call that
  placed the order that is the balance after it; on a _replayed_ call it is
  your balance now, which will have moved if you have ordered since. Watch it
  — there is no low-balance webhook — but reconcile against
  `GET /merchant/v1/me`, not against a stored copy of an old order response.
- **`status` is live, not always `"paid"`.** A merchant order is born paid and
  goes straight into fulfilment, so the usual value here is `"fulfilling"`.
  Poll `GET /merchant/v1/orders/{merchant_order_id}` for the rest.
- Key your own records on `merchant_order_id`. `order_id` is ours; quote it to
  support.

#### Idempotency — read this before you write the retry loop

**`merchant_order_id` is the idempotency key.** There is no
`Idempotency-Key` header on this API and sending one does nothing.

- Same id, **same body** → the order you already placed, returned again, and
  as `201` — the status code does not distinguish a first placement from a
  replay, `created_at` does. No second order, no second debit, whatever the
  repeat was: your retry, a proxy's retry, or somebody replaying your traffic
  inside the ±300 s window.
- Same id, **different body** → `409 order_id_reused`. Same id means same
  order; if you meant a new one, use a new id.
- Two merchants may use the same id. Scope is per account.

"Same body" is decided on `sku_id`, `quantity`, `amount_usd`,
`expected_price` and `fulfillment_data`. The sizing is part of it because it
is part of the _intent_: retrying `acme-417` with a corrected count is a new order, not a
retry, and answering it with the first one would deliver 100 Stars against a
request for 1000 and report success.
The safest retry is the one the auth section already asks for: **resend the
identical bytes.**

Pick the id from something your own system already has — your order number —
and reuse it across every retry of that intent. A fresh UUID per HTTP attempt
defeats the whole mechanism and will place duplicate orders.

#### Price drift

`expected_price` is a safety interlock, not a bid. It decides **whether** the
order proceeds; it never decides what it costs.

- Within **±2%** of our current price, the order proceeds and is charged at
  **our** price — not yours, and not the lower of the two.
- Outside it, `422 price_changed`, with our `current_price` in the body. Re-read
  `/catalog` and decide.

So what you are protected from is a price that moved out from under you: you
will never be charged much more than the number you sent — the exact bound is
just over 2%, because the band is 2% of **our** price rather than yours, so a
quote 2% under ours is charged 2/98 ≈ 2.04% above what you sent. A bigger move
is refused outright with our exact current price in the body, before anything is
debited. What you are **not** promised is that a stale-low `expected_price` caps
what you pay — quoting 2% under our price buys at our price, not at yours.

**We keep the number you sent.** Since M3b the `expected_price` on an accepted
order is stored on it (`order_items.merchant_expected_price_usd`, migration
0072), beside the price we charged. It is not published on this API and it
changes nothing about what you pay — it exists so that a disagreement about a
charge is settled from a record rather than from two memories, and so that how
far quotes drift from our prices is a number somebody can look up. Before it,
`expected_price` survived only inside a one-way hash of your request.

_(Changed 2026-09-07, before any integrator existed: within the band the order
used to execute at the lower of the two prices. `POST /orders` is the only
endpoint affected, no request or response field changed shape, and the only
observable difference is `price_usd` on an order whose `expected_price` was
below ours.)_

#### Errors

| Status | `code`                  | Meaning                                                                                                                                                                                   |
| ------ | ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 404    | `item_unavailable`      | This SKU cannot be ordered right now. The body carries a `reason` — see below.                                                                                                            |
| 422    | `price_changed`         | Drift beyond ±2%. Body carries `current_price` and the `expected_price` you sent.                                                                                                         |
| 422    | `margin_floor`          | Our own pricing for this SKU is misconfigured. Not your fault; tell support.                                                                                                              |
| 422    | `quantity_required`     | The SKU's `kind` is `"unit"` and you sent no `quantity`. Body carries `min_qty` and `max_qty`.                                                                                            |
| 422    | `quantity_not_accepted` | The SKU's `kind` is `"fixed"`. It is bought one at a time; send several orders.                                                                                                           |
| 422    | `quantity_out_of_range` | Outside the SKU's `min_qty`/`max_qty`, which the body repeats.                                                                                                                            |
| 422    | `amount_required`       | The SKU's `kind` is `"amount"` and you sent no `amount_usd`. Body carries the bounds.                                                                                                     |
| 422    | `amount_not_accepted`   | The SKU is not loaded in dollars. Send `quantity`, or nothing at all.                                                                                                                     |
| 422    | `amount_out_of_range`   | Outside `min_amount_usd`/`max_amount_usd`, which the body repeats.                                                                                                                        |
| 422    | —                       | A `fulfillment_data` field the product's schema rejects. The nested `extra` object names the `field` and the `reason` (`missing`, `type`, `pattern`, …) — see "Extra fields on the body". |
| 422    | `invalid_request`       | The request body itself did not parse — a missing field, an unknown one, more than two decimals on `expected_price`, a `sku_id` that is not a UUID. `errors` says which.                  |
| 409    | `insufficient_deposit`  | Body carries `balance_usd` and `required_usd`. Top up and retry the **same** id.                                                                                                          |
| 409    | `order_conflict`        | A rare write conflict on our side. Retry the **same** id; it is safe.                                                                                                                     |
| 409    | `order_id_reused`       | This `merchant_order_id` already belongs to a different order.                                                                                                                            |

`item_unavailable` reasons, because a 404 you cannot act on is a support
ticket:

| `reason`          | What it means                                                   | What to do                               |
| ----------------- | --------------------------------------------------------------- | ---------------------------------------- |
| `unknown_sku`     | No such `sku_id`.                                               | Re-read `/catalog`; check your mapping.  |
| `not_b2b_visible` | Withdrawn from B2B distribution (the SKU or its whole brand).   | Treat as unavailable; it may come back.  |
| `out_of_stock`    | The supplier has no codes left.                                 | Retry later. Stock moves without notice. |
| `not_for_sale`    | Switched off, or the brand is in maintenance.                   | Retry later.                             |
| `no_cost`         | No wholesale cost on file — we cannot price it.                 | Tell support; this one is ours to fix.   |
| `variable_amount` | A customer-chooses-the-amount SKU (e.g. a Steam wallet top-up). | Not orderable in v1. Ask support.        |

> **A SKU in `/catalog` is not a promise that we can fill it.** The price list
> says "sellable to you at this price"; it does not consult supplier stock, and
> stock moves as other resellers draw on the same pool. `item_unavailable` is
> where you find out, so handle it as an ordinary outcome rather than an
> exception.

#### Fulfilment is asynchronous, always

We never call a supplier while we are taking your money. The order and the
deposit charge commit first; the actual purchase is queued and runs
immediately afterwards. That is why the response says `"fulfilling"` and why
`GET /merchant/v1/orders/{merchant_order_id}` is where delivery shows up.

The practical consequence: a `201` means **the order exists and your deposit
was charged**, not that the goods are delivered. If our fulfilment workers ever
fall behind, orders sit in `fulfilling` a little longer — the money is
correctly accounted for the whole time and nothing is lost.

**Poll, and read `failure_reason` rather than the clock.** `status` alone stays
`fulfilling` on an order that has failed or stalled — nothing advances the order
row below it — so "how long has this been `fulfilling`?" is not a question with
an answer. (A **fully refunded** order is the one exception: since M3c Task 6
that one is closed as `failed`, because every way to deliver it is already
refused. It is the exception, not the rule, and it does not make `status` a stop
condition for anything else.) A timeout of your own is fine as an **SLA** —
raise it with a human — but it is a guess about our side, not a stop
condition. `failure_reason` is: `null` means in progress, `fulfillment_delayed`
means stopped on our side and still coming, and the three terminal values mean
act now. The table under `GET /orders/{merchant_order_id}` is the whole rule.
Whatever it says, never place a second order for the same purchase — re-sending
the same `merchant_order_id` replays the first one, and a fresh id buys the
goods twice.

### `GET /merchant/v1/orders/{merchant_order_id}`

Where an order ends up, and **where you collect the code**. Poll it after a
`201`. If you have a webhook configured it tells you that something changed
without carrying the goods — a voucher code in a webhook body is a bearer
instrument written to your logs and ours — so this read is the delivery channel
either way.

The path segment is **your** id, percent-encoded:

```
GET /merchant/v1/orders/acme-2026-000417
GET /merchant/v1/orders/acme%2F2026%2F000417     <- the id "acme/2026/000417"
```

`merchant_order_id` may contain `/`, `%`, `?`, `#` — anything printable and
non-blank. Encode the segment (`urllib.parse.quote(id, safe="")`,
`encodeURIComponent(id)`) and **sign the encoded form**, which is what the
signature section already tells you: the canonical string carries the request
line as sent. Signing the decoded path is a `401`, not a `404`.

```json
{
  "merchant_order_id": "acme-2026-000417",
  "order_id": "0198c3d1-…",
  "status": "delivered",
  "sku_id": "0198c3cb-…",
  "price_usd": "1.06",
  "refunded_usd": "0.00",
  "created_at": "2026-09-07T08:20:11.402913Z",
  "paid_at": "2026-09-07T08:20:11.402913Z",
  "delivered_at": "2026-09-07T08:20:19.881204Z",
  "failure_reason": null,
  "delivery": {
    "artifact_kind": "voucher_code",
    "artifact": { "code": "WXYZ-1234-ABCD" },
    "delivered_at": "2026-09-07T08:20:19.881204Z"
  },
  "timeline": [
    { "event": "order.created", "at": "2026-09-07T08:20:11.402913Z" },
    { "event": "order.paid", "at": "2026-09-07T08:20:11.402913Z" },
    { "event": "order.fulfilling", "at": "2026-09-07T08:20:11.402913Z" },
    { "event": "order.delivered", "at": "2026-09-07T08:20:19.881204Z" }
  ]
}
```

| Field            | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `status`         | `paid`, `fulfilling`, `delivered`, `failed`. Those four are what a merchant order reaches today, in that order (`failed` from any of the first three). `failed` arrives two ways: support closing an undeliverable order by hand, and — since M3c Task 6 — a delivery failure whose **whole** charge we have already put back on your deposit, which closes itself within seconds. New values may be added — treat an unknown one as "still in flight".                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `price_usd`      | What the order charged. Final.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `refunded_usd`   | **Money that came back to your deposit on this order — a running total, not a flag.** It counts exactly two things, because it is read off the ledger as a _direction_ rather than as a transaction named "refund": the automatic refund of a supplier failure that gave our money back (M3b, within seconds of the failure), and a settlement support books by hand against this order. Both appear on `/transactions` against the same `order_id` — `merchant_order_refund` and `merchant_deposit_credit` — so the field and the statement reconcile line for line. Expect `"0.00"` on an order nothing has come back on, and expect a **partial** to be possible: a value strictly between `"0.00"` and `price_usd` means a settlement in progress, not a completed one, and `failure_reason` stays `fulfillment_failed` until the whole of it is back. **It can never exceed what the order charged** — the cap is enforced against the deposit charge on the ledger, which is the authority, not against `price_usd` on this response: the automatic path refuses an order support already settled, and a hand credit that would take the total past the charge is refused with `order_already_settled`. The two numbers are the same today, because one value becomes both when the order is placed; the guard does not rely on that and neither should you. It only ever grows. |
| `failure_reason` | `null`, or one of the codes below. **One of them, `fulfillment_delayed`, is not terminal** — do not treat "non-null" as "stop".                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `delivery`       | `null` until something has actually been delivered, and present as soon as it has — it is the delivery record that decides, not `status`. Normally the two move together. See below.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `timeline`       | The order's lifecycle events, oldest first, `{event, at}`. A merchant order produces `order.created`, `order.paid`, `order.fulfilling`, `order.delivered` and `order.failed`. `order.failed` is written both when support closes the order and when an automatic refund settles it in full (M3c Task 6) — one kind, because from outside they are one fact: the order ended without a delivery. Which of the two it was is `failure_reason`'s job, and no event payload is ever published. `order.cancelled` is accepted by the same filter but cannot occur on this channel today — cancelling is legal only before payment, and a merchant order is born paid. More kinds may be added.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |

**The goods are in `delivery.artifact`.** Two `artifact_kind` values exist
today: `voucher_code`, which carries `code` (or `codes` for a line delivered as
several), and `topup_receipt`, which confirms a credit applied directly to the
account in your `fulfillment_data` and carries a `message` and/or that
`fulfillment_data` echoed back. More kinds may be added.

`artifact` is filtered through an allow-list, so the keys you may ever see are
exactly: `code`, `codes`, `key`, `pin`, `serial`, `login`, `steam_login`,
`message`, `note`, `fulfillment_data`, `kind`, `app_name`, `package_name`,
`status`. Anything else we recorded — which supplier filled the line, their
order id, our warehouse row — is ours and never leaves. Read the keys you know
and ignore the rest; the safe rule is "`code`/`codes`/`key`/`pin`/`serial` are
the redeemable ones, the rest is context".

**Failure reasons** are a **controlled** vocabulary: you will never get a
supplier's own words or an operator's note, because neither is switchable and
both are internal. Controlled is not frozen — values get **added** (M3b added
two), never renamed or removed, which is why the last rule under this table is
the one to build against.

**One of the four means "keep waiting", and the other three mean "stop".** That
is the first thing to get right about this field, because it is not how it
behaved before M3b: read the `Terminal?` column before the text.

| `failure_reason`              | Terminal? | What happened                                                                                       | What **we** do next                                                                                                                                                                                                                                                                                                                                                     | What **you** do — and what you must never do                                                                                                                                                           |
| ----------------------------- | --------- | --------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `fulfillment_delayed`         | **no**    | The delivery has stopped on **our** side and somebody here is fixing it. The order is still coming. | An operator clears the blockage — usually by topping a supplier up — and the delivery finishes. It can also end terminally instead, in which case this value is replaced by one of the three below. Nothing is asked of you, and no webhook announces either outcome.                                                                                                   | **Keep polling.** Escalate on your own SLA, never on this value. **Never** place a replacement order, **never** refund your end customer, **never** treat it as an ending because it is non-null.      |
| `fulfillment_failed_refunded` | yes       | The delivery failed **and the whole of what you paid is back on your deposit.**                     | Nothing further on the money: it is already back, and this order will not move again **by itself**. When we refunded it automatically the order is closed as `status: "failed"` in the same breath; when a person settled it by hand the money is just as complete and `status` may still read `fulfilling` until somebody closes it — read this field, not the status. | Refund your own customer. **Never** re-send this `merchant_order_id` — it replays this same order. If they still want the goods, place a **new** order.                                                |
| `fulfillment_failed`          | yes       | The delivery failed and will not retry itself. Your money has **not** come back — or not all of it. | A person decides what happens to the money. Where we can, we settle it by hand onto your deposit, which then shows on `refunded_usd`.                                                                                                                                                                                                                                   | Contact support quoting `order_id`, and check `refunded_usd` for what has arrived so far. **Never** re-order, and **never** assume a non-zero `refunded_usd` means you have been made whole — read it. |
| `order_failed`                | yes       | Support closed the order as undeliverable.                                                          | A person is already in the loop and closed it deliberately. Any money owed is settled by hand, before or after the closure, onto your deposit.                                                                                                                                                                                                                          | Contact support if you have not already; read `refunded_usd` for what has come back. **Never** re-order under the same id, and **never** read this value as "no money is coming".                      |

A value you do not recognise is **not** a stop condition: treat it as
`fulfillment_delayed` — keep polling and raise it with a human. Guessing the
other way costs you a customer refund on an order that then arrives.

**That rule is why the schema does not carry this vocabulary.** In
`docs/api/openapi.json` the field is a plain nullable string, with no `enum`
and no description, and that is deliberate rather than an omission. An `enum`
would give you a generated type and would make an added value a visible schema
diff — and it would also close the set in a machine-checkable way, at exactly
the moment we are still adding to it: M3b alone added **two** values, so a
client generated before it would carry a type that excludes something we now
send, and a strict generated validator would reject a perfectly good response.
Since nobody but you can redeploy your receiver, that trade is the wrong way
round. **This table is the contract; the generated type is not.** Read the
value as an open string and switch on the ones you know. (Recorded in
ADR-0071, with the condition that would change the answer: once the vocabulary
stops growing, an `enum` becomes safe.)

**"Terminal" is about the delivery attempt, not about the order for ever.** A
`fulfillment_failed` order whose money has not come back can be retried by an
operator, and if that retry stalls the value moves `fulfillment_failed` →
`fulfillment_delayed`. So the three terminal values mean "nothing will move
this on its own, act now" — not "this can never change again". They are safe
to act on, which is what you need; they are not safe to cache as final. If you
stop polling on one, poll it once more before you write off the order, or read
`refunded_usd`, which only ever grows.

`fulfillment_delayed` is M3b's second and last addition, and it exists because
its absence was worse than a wrong value. A delivery can stop for a reason that
is ours to fix in minutes; until M3b that order published `failure_reason:
null` and `status: "fulfilling"`, which is byte-for-byte what an order placed
thirty seconds ago publishes. So a polling loop had no terminal condition at
all, and the only workable strategy was a timeout you had to invent. What the
value never tells you is **why** — that is a fact about our own supply, not
about your order — and it carries no timing promise: it says the order has
stopped, not when it will move.

`fulfillment_failed_refunded` is the other one, and the distinction it draws is
"we are refunding you" versus "a human is deciding": `fulfillment_failed` has
always meant the second, so nothing you switch on from before M3b changes
meaning. Whether a supplier kept our money or we cannot tell is **not** in this
field and will not be — that is a fact about our supplier relationships, not
about your order, and `fulfillment_failed` covers both.

The refunded value is derived from the ledger, not from a flag: it says
`fulfillment_failed_refunded` only when the money is genuinely back on your
deposit, whichever route put it there, and only when **all** of it is —
compared against what the order charged. A **partial** settlement reads
`fulfillment_failed`, because a partial settlement is a human mid-decision and
telling you "nothing to chase" against part of your money would have you
refund your customer in full. Read the amount on `refunded_usd`; it is the
number, and this field is only ever the summary of it.

**So a partial looks like this, and it is worth knowing what to do with it:**
`failure_reason: "fulfillment_failed"` with a `refunded_usd` that is neither
`"0.00"` nor the whole of `price_usd`. It means a person here has begun
settling your order and has not finished — an operator has credited part of
the amount and is still working on the rest. **Do not net it off
against your customer's refund and close the case**: quote the `order_id` to
support and let them finish, because the remainder is still owed and the value
will move to `fulfillment_failed_refunded` the moment it lands. On our side a
partial is a state that needs a person more than a zero does — it blocks the
automatic refund and the operator retry alike — so raising it is not a
formality.

Note that `failure_reason` can be set while `status` is still `fulfilling` —
nothing advances the order row when a delivery fails or stalls, so the status
alone would say "in progress" indefinitely. **The stop condition is therefore
the field, not the status — but it is the field's _value_, not merely its
non-nullness.** A loop written as `break if failure_reason != null` breaks out
on `fulfillment_delayed` and stops polling an order we are about to deliver;
see the worked loop under "Your first order in ten minutes".

The one case where the status _does_ move is a **fully refunded** order (M3c
Task 6): `status` goes `failed` beside
`failure_reason: "fulfillment_failed_refunded"`. Do not read that as a reason to
watch the status instead — it happens on one of the four values and not on the
other three, so a loop built on it still never exits for the rest.

**A full automatic refund is the only one of these that pushes anything about
the order.** The webhook seam is where `orders.status` moves. A stall does not
move it and neither does a failure whose money stayed out, so for those the
failure is recorded below the order row and nothing is announced at all — poll.
A refund that settles the order in full moves it (M3c Task 6), so you get
`balance.credited` for the money **and** `order.status_changed` with
`status: "failed"`, in that order. Neither body carries `failure_reason` or
`refunded_usd`: read those back off this endpoint once either event arrives.

Errors:

| Status | `code`            | Meaning                                                                                                                                             |
| ------ | ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| 404    | `order_not_found` | No order of **yours** under that id. An order belonging to another merchant answers identically — we do not confirm that somebody else's id exists. |

### `GET /merchant/v1/transactions`

Your deposit ledger: what we credited, what each order spent, and what came
back. Newest first. `amount_usd` is **signed** — positive credited the deposit,
negative spent it — and the column adds up to the `balance_usd` on
`GET /merchant/v1/me`.

```
GET /merchant/v1/transactions?limit=50
GET /merchant/v1/transactions?limit=50&cursor=MjAyNi0wOS0wN…
```

| Parameter | Default | Notes                                                                        |
| --------- | ------- | ---------------------------------------------------------------------------- |
| `limit`   | 50      | 1–200. Out of range is a `422`, not a silent clamp.                          |
| `cursor`  | —       | A `next_cursor` from a previous page. Opaque; do not construct or parse one. |

Both are part of the signed canonical string — they are the query, the
**fourth** of the five fields: a signature made for `limit=50` will not spend
on `limit=200`.

```json
{
  "items": [
    {
      "transaction_id": "0198c3e0-…",
      "kind": "merchant_order_charge",
      "amount_usd": "-1.06",
      "order_id": "0198c3d1-…",
      "merchant_order_id": "acme-2026-000417",
      "created_at": "2026-09-07T08:20:11.402913Z"
    },
    {
      "transaction_id": "0198c3cf-…",
      "kind": "merchant_deposit_credit",
      "amount_usd": "1.06",
      "order_id": "0198c3d1-…",
      "merchant_order_id": "acme-2026-000417",
      "created_at": "2026-09-07T09:41:02.771004Z"
    },
    {
      "transaction_id": "0198c3c0-…",
      "kind": "merchant_deposit_credit",
      "amount_usd": "500.00",
      "order_id": null,
      "merchant_order_id": null,
      "created_at": "2026-09-05T11:02:44.101002Z"
    }
  ],
  "next_cursor": "MjAyNi0wOS0wNVQxMTowMjo0NC4xMDEwMDIrMDA6MDB8MDE5OGMzYzA"
}
```

Three `kind`s exist today. `merchant_deposit_credit` is money we put on your
deposit — an ordinary top-up, or a settlement support booked against one of
your orders. `merchant_order_charge` is an order spending it.
`merchant_order_refund` is M3b's automatic return of a charge whose supplier
failed the order and gave our money back; it carries the order it belongs to
and the same amount that order's `refunded_usd` reports. More kinds may be
added — treat an unknown one as "some movement" and trust `amount_usd`.

`merchant_order_id` is on every row that names an order, so a statement line
reconciles against your books without a second call. That is every order
charge, every automatic refund, and a settlement credit we booked against one
of your failed orders. A `merchant_deposit_credit` with a **null** `order_id`
is an ordinary top-up of your balance and belongs to no order.

**Paging.** Follow `next_cursor` until it is `null`; a `null` means this page
was the last one, so never call again on one. Do not page with an offset of
your own devising and do not hold a cursor for long — it is a position in a
list you are also writing to.

The cursor is deliberately not a page number, and the difference matters if you
pull statements while you trade. New rows land at the **top** of a newest-first
list, so with `?page=2` one order placed mid-walk shifts every row down and
page 2 re-serves a charge you already recorded — silently, with nothing in the
response to notice. A cursor says "older than this exact row", which no
insertion can move: rows created after you started are simply newer than your
first page, and your next poll picks them up.

What that guarantees, precisely: **a walk sees every row exactly once, and no
row twice, against writes that land at the head** — which is every ordinary
movement on your deposit. It is not a guarantee against every possible
interleaving: a row's timestamp is taken when its transaction _starts_, so a
long-running one can commit a row that sorts inside a range you have already
walked past, and you would see it on your next poll rather than this one.
Reconcile by `transaction_id` and treat a poll as a poll, not as a one-shot
export.

Errors:

| Status | `code`            | Meaning                                                         |
| ------ | ----------------- | --------------------------------------------------------------- |
| 422    | `invalid_cursor`  | Not a cursor we issued. Drop it and start from the newest page. |
| 422    | `invalid_request` | `limit` outside 1–200. `errors[0].loc` is `["query", "limit"]`. |

#### No emails, ever

We never mail your customer. We do not hold their address, we do not accept
one, and the delivery path skips merchant orders explicitly rather than by
accident. Delivery to you is the order read, with the outbound webhook as the
notification beside it. The one address we do mail is your **operator's**, and
only to say we have stopped delivering webhooks (see "Auto-disable").

### `POST /merchant/v1/validate/player`

Check the identifier your customer gave you **before** you spend a deposit on
it — a game player id, or a Steam login for a Steam top-up. Optional: no order
consults it, and skipping it costs you nothing but the chance to catch a typo
before the code is gone.

```json
POST /merchant/v1/validate/player
{
  "sku_id": "0198c3d0-11a2-7b31-9ac4-5f2b7d0e8c41",
  "player_id": "51234567",
  "server_id": null
}
```

| Field       | Required | Notes                                                                              |
| ----------- | -------- | ---------------------------------------------------------------------------------- |
| `sku_id`    | yes      | The SKU you are about to order, from `/catalog`. A UUID; anything else is a `422`. |
| `player_id` | yes      | Your **customer's** identifier. 1–64 characters.                                   |
| `server_id` | no       | The game server / zone, for the games whose form asks for one. `null` or omitted.  |

A SKU, not a product, so the id you check is the id you buy. Unknown fields are
rejected (`422`) rather than ignored — a typo'd `player_id` that we silently
dropped would come back as "no check needed", which is the one answer you must
not get by accident.

```json
{ "status": "valid", "name": "NeoUZ" }
```

| `status`      | What it means                                                                   | What to do                                           |
| ------------- | ------------------------------------------------------------------------------- | ---------------------------------------------------- |
| `valid`       | The provider resolved the id. `name` is the account nickname when there is one. | Show the name back to your customer; order.          |
| `invalid`     | The provider gave us a verdict we understand, and it is "no such player".       | The answer to show your customer as "check that id". |
| `error`       | **We could not check.** Says nothing at all about the id.                       | Retry later, or order without a check. Never refuse. |
| `unsupported` | This SKU has no player check configured, and will not grow one on its own.      | Order without a check. Do not retry.                 |

> **`error` is not a verdict.** An upstream fault, a timeout, a credential of
> ours that got rejected, or a circuit we opened after a run of failures all
> arrive as `error`, and every one of them means "we learned nothing". If you
> branch on `status != "invalid"` you will treat those as approval; if you
> branch on `status != "valid"` you will refuse perfectly good ids whenever a
> supplier has a bad ten minutes. Branch on all four.
>
> **And `invalid` is a verdict.** You get it only when the provider sent a
> token we recognise and that token said "no such player". A response we cannot
> read — a field renamed, a shape we have not seen before — is `error`, not
> `invalid`, deliberately: the alternative is that one supplier-side rename
> makes us tell every one of your customers they mistyped, on a stream of HTTP
> 200s, with nothing anywhere reading as a fault. You may act on `invalid`;
> that is what it is for.

`name` is `null` whenever the provider gives us no name — Steam has no display
name to return, so a `valid` Steam login always reads `{"status": "valid",
"name": null}`. It is an absence, not a failure.

We do not tell you how the answer was reached. A verdict may be served from a
short cache and it is still our best answer; there is no "this was cached"
field to make you doubt a good one.

**No `Idempotency-Key`, and no `GET`.** This endpoint writes nothing, so the
header does not apply. It is a `POST` anyway because `player_id` identifies
_your customer_ and must not travel in a URL: our edge writes an access log
that records query strings verbatim, and a player id in it is a leak in the
one place that otherwise logs only a hash. Send it in the body, and note that
the body is part of the signed canonical string (its SHA-256 is the fifth
field), so a signature is good for exactly one payload.

**Its own rate limits — two of them.** This is the only endpoint here that
spends a _supplier's_ quota rather than ours, so on top of the 600 / 60 s the
whole prefix shares it carries **120 / 60 s per source address** and **120 /
60 s per merchant account**. All of them are charged; the tight pair binds
first. The account counter is not redundant with the address one — a supplier's
quota is spent by _you_, not by your egress node, so calling us from a six-node
NAT pool must not buy six budgets, and neither should rotating a key. A `429`
here is problem+json with a `Retry-After`, like every other. One check per
order is well inside it; a validation loop is not, by design.

What these counters are and are not: fixed 60-second windows in Redis that
**fail open**, so if our Redis is unwell they stop counting rather than
refusing everything — and that is the same outage that empties this endpoint's
result cache and its supplier circuit breaker. All three protections go
together, and the supplier's own limiter is what remains. We would rather say
so than let the numbers above read as a guarantee they are not.

Errors:

| Status | `code`              | Meaning                                                                                                                                        |
| ------ | ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| 404    | `item_unavailable`  | `reason: unknown_sku` — no such SKU; `reason: not_b2b_visible` — withheld from B2B, so there is nothing to check.                              |
| 404    | `product_not_found` | The SKU's product vanished between our two lookups. A race, and vanishingly rare; retry once.                                                  |
| 422    | `invalid_request`   | The body did not parse — a `sku_id` that is not a UUID in any spelling, an empty `server_id`, a missing or unknown field. `errors` says which. |
| 429    | —                   | Over any of the counters that apply here. Wait `Retry-After` seconds.                                                                          |

Any spelling of a UUID your language emits is accepted and normalised — plain,
uppercase, undashed, braced (`{0198…}`, which is .NET's `Guid.ToString("B")`),
or `urn:uuid:…`. You never have to reformat an id you got from us.

Note what is **not** here. The order path's other refusals — `out_of_stock`,
`not_for_sale`, `no_cost` — do not apply: stock and pricing move between a
check and an order, and refusing to verify an id because a SKU is momentarily
unbuyable would answer a question you did not ask. Visibility is the one
condition that governs both, so a SKU you cannot see in `/catalog` is a SKU you
cannot check.

## Outgoing webhooks

**Also part of the contract**, and the second half of it: everything above is
your server calling ours, this is ours calling yours. You register one `https`
endpoint and we `POST` a signed JSON body to it when one of your orders changes
status or support credits your deposit.

Registration is done **by support** — ask them for it, with the URL. There is no
`/merchant/v1` write for the webhook configuration and there will not be one in
v1; the merchant cabinet gets the control in M4. Setting it returns a signing
secret (`ypmw_…`, 48 characters) that is **shown once**, exactly like your API
secret and stored the same way.

The webhook is a **notification, not a delivery channel**. It tells you
something moved; `GET /merchant/v1/orders/{merchant_order_id}` is where you read
what it moved to and where you collect the code. Every guarantee below is about
telling you promptly, and none of them replaces the read.

### What arrives

A `POST` to your URL, `Content-Type: application/json` and
`Accept-Encoding: identity`, with a compact JSON body and four headers of ours
(anything else on the request is our HTTP client's ordinary business and is not
part of this contract):

| Header              | Value                                                               |
| ------------------- | ------------------------------------------------------------------- |
| `X-Yupay-Delivery`  | The delivery id (UUID). **Stable across every retry of one event.** |
| `X-Yupay-Event`     | `order.status_changed` or `balance.credited`                        |
| `X-Yupay-Timestamp` | Unix seconds, ASCII digits. **Per attempt**, not per event.         |
| `X-Yupay-Signature` | Lowercase hex HMAC-SHA256. See below.                               |

They are `X-Yupay-*` and not `X-Merchant-*` on purpose: you hold two credentials
at once and they key opposite directions of one integration, so the two header
families cannot be confused.

Two event types, and they are the complete v1 list:

| Event                  | Body — these keys, exactly                      |
| ---------------------- | ----------------------------------------------- |
| `order.status_changed` | `merchant_order_id`, `order_id`, `status`, `at` |
| `balance.credited`     | `amount_usd`, `balance_usd`                     |

```json
{
  "at": "2026-09-07T08:20:19.881204+00:00",
  "merchant_order_id": "acme-2026-000417",
  "order_id": "0198c3d1-7f22-7a90-b118-9d3c5e604a7f",
  "status": "delivered"
}
```

```json
{ "amount_usd": "500.00", "balance_usd": "541.44" }
```

- **The keys are sorted and there is no whitespace.** We serialise with sorted
  keys and compact separators so two attempts at one event put identical bytes
  on the wire. Do not infer meaning from the order, and do not re-serialise
  before you verify — see below.
- **`at` is the instant the status was written**, ISO 8601 with an explicit
  `+00:00` offset and microseconds. Note the difference from the REST responses
  above, which render UTC as `Z`: parse it with a real ISO 8601 parser rather
  than by matching a suffix.
- **`status`** is the same vocabulary the order read publishes: `paid`,
  `fulfilling`, `delivered`, `failed`. New values may be added; treat one you do
  not know as "still in flight". `failed` reaches you here for two reasons —
  support closed the order, or we refunded the whole charge automatically — and
  the body does not say which. Read `failure_reason` off the order to tell them
  apart before you decide what to do about your own customer.
- **Money is a two-decimal string** here as everywhere else on this API.
  `amount_usd` is what was credited; `balance_usd` is your deposit after it.
- Fields may be **added** to these bodies without notice, and nothing is ever
  renamed, retyped or removed inside v1. Ignore keys you do not know — but see
  "What never rides in a body" for the one addition we will not make.

### The signature

Four fields joined by single LF bytes (`0x0A`), HMAC-SHA256 under your `ypmw_`
secret — the secret's UTF-8 bytes are the key, with **no derivation step**:

```
canonical = timestamp + "\n" + delivery_id + "\n" + event_type + "\n" + sha256_hex(body)
```

`timestamp`, `delivery_id` and `event_type` are the header values exactly as
sent, and `body` is the **raw bytes you received**. There is no method field and
no URL field: a webhook is always a `POST` to the one endpoint you configured,
and you already know which endpoint received the request.

Three things worth knowing before you write the verifier:

- **Hash the bytes, not your parse of them.** `JSON.parse` then `JSON.stringify`
  gives you a different byte string and therefore a different digest. Capture
  the raw body first (`express.raw({ type: "application/json" })`,
  `await request.body()`, `req.rawBody`), verify, then parse.
- **Compare in constant time**, and treat a bad signature as a `401` rather than
  as a `500` — a `401` is terminal for us, so a delivery you reject stays
  rejected instead of coming back. (`408` and `429` are the two `4xx`es we do
  retry; see the table below.)
- **A retry re-signs.** The delivery id is the same, the timestamp and therefore
  the signature are not. Deduplicate on `X-Yupay-Delivery`, never on the
  signature.

### Worked example

Generated by the server's own signing code, not composed by hand. Secret:

```
ypmw_EXAMPLE9wQ2vR7kB4mN8sT3jH6dF1gL5xZ0cY4uA2eK
```

Headers, and the body exactly as it goes on the wire. `X-Yupay-Timestamp`
decodes to one second after the `at` inside the body, because an attempt
follows the transition it reports.

```
X-Yupay-Delivery: 0198c3d2-4e11-7c05-8a6d-1b2f9e7a0c34
X-Yupay-Event: order.status_changed
X-Yupay-Timestamp: 1788769220
X-Yupay-Signature: 256046194be552f3c3a99d322334320f3b1b1898c66ca7af711d6968873e4277
```

```
{"at":"2026-09-07T08:20:19.881204+00:00","merchant_order_id":"acme-2026-000417","order_id":"0198c3d1-7f22-7a90-b118-9d3c5e604a7f","status":"delivered"}
```

so that

```
sha256_hex(body) = 31b8745c082c9c37390c5d19fe80b4831721815e1094ea20a1af52577d06102c

canonical = "1788769220\n0198c3d2-4e11-7c05-8a6d-1b2f9e7a0c34\norder.status_changed\n31b8745c082c9c37390c5d19fe80b4831721815e1094ea20a1af52577d06102c"
```

That example secret authenticates nothing — it exists so you can check your
verifier's arithmetic before you have an account. Node 18+, no dependencies:

```js
import crypto from "node:crypto";

const SECRET = process.env.YUPAY_WEBHOOK_SECRET; // "ypmw_…"
const TOLERANCE_SECONDS = 300;

// rawBody MUST be the bytes as received. Do not JSON.parse and re-stringify:
// the signature covers the exact bytes, and our key order is not yours.
export function verify(rawBody, headers, { now = Date.now() / 1000 } = {}) {
  const timestamp = headers["x-yupay-timestamp"];
  const deliveryId = headers["x-yupay-delivery"];
  const eventType = headers["x-yupay-event"];
  const provided = headers["x-yupay-signature"];
  if (!timestamp || !deliveryId || !eventType || !provided) return false;
  if (!/^[0-9]+$/.test(timestamp)) return false;
  if (Math.abs(now - Number(timestamp)) > TOLERANCE_SECONDS) return false;

  const bodyHash = crypto.createHash("sha256").update(rawBody).digest("hex");
  const canonical = [timestamp, deliveryId, eventType, bodyHash].join("\n");
  const expected = crypto
    .createHmac("sha256", SECRET) // the secret itself is the key — no pre-hashing
    .update(canonical, "utf8")
    .digest("hex");

  const a = Buffer.from(expected, "utf8");
  const b = Buffer.from(String(provided).trim().toLowerCase(), "utf8");
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}
```

Run it against the example above — the body as a `Buffer`, the four headers
lower-cased, `now: 1788769220` — and it prints:

```
signature valid: true
tampered body: false
stale timestamp: false
```

The timestamp tolerance is **yours**, not ours: we sign the instant of each
attempt and never re-send an old signature, so a window is worth having, and 300
seconds is the same figure this API uses in the other direction. Nothing breaks
if you widen it; a backlog released after a long outage can carry timestamps
minutes old.

### At-least-once, and the ordering you get

**Delivery is at-least-once. Build for a duplicate.** A timeout, or an exchange
that breaks after we have written the request, leaves us unable to tell an
answer that never arrived from one that was never sent, so we retry — which
means an event you have already processed can arrive again. `X-Yupay-Delivery`
is the handle that makes that safe: it is stable across every retry of one
event, it is inside the signed material rather than only in a header, and
recording it is the whole of deduplication.

Ordering, precisely:

- Two events written by one transaction (`paid` and `fulfilling`, which a
  placement emits together) are **tie-broken** into enqueue order, so you do not
  see `fulfilling` before `paid` on a first attempt.
- Nothing beyond that is globally ordered. A retried event lands **after**
  events queued behind it, which is inherent to per-event backoff, so you can
  see `paid` after `delivered`.
- **Order by the payload's `at`**, and never treat a status you have already
  passed as a regression. Applying only forward transitions is the rule; there
  is no sequence number and `at` plus your own state is enough.

### Retries, and what is terminal

| Your answer                                            | What we do                                            |
| ------------------------------------------------------ | ----------------------------------------------------- |
| Any `2xx`                                              | Done. Your failure streak resets.                     |
| `408`, `429`, any `5xx`                                | Retry with backoff.                                   |
| Any other `4xx`, or a redirect                         | **Given up on immediately.** We never follow a `30x`. |
| More than **64 KiB** of body, or a compressed body     | **Given up on immediately** — you received it.        |
| No answer at all (DNS, TCP, TLS, timeout, reset)       | Retry with backoff.                                   |
| We would not connect (not `https`, non-public address) | **Given up on immediately.**                          |

The backoff doubles from 30 seconds to a one-hour ceiling, with no jitter, and
one event gets **ten attempts** before it is abandoned:

```
30s → 1m → 2m → 4m → 8m → 16m → 32m → 1h → 1h   (10 attempts over 3h 03m 30s)
```

`Retry-After` is honoured on the two statuses that define it for a retry —
`503` (RFC 9110 §10.2.3) and `429` (RFC 6585 §4) — in both its forms, clamped
into `[1 s, 1 h]`. On any other status we use our own schedule, including a
`3xx`, which defines the header too and which we never follow anyway.

What your endpoint has to live inside: **10 seconds** of total wall clock per
attempt, DNS and TLS included, and **64 KiB** of response body. Answer `2xx` as
soon as you have durably recorded the delivery id and do the work afterwards —
an endpoint that provisions synchronously is an endpoint we time out on and
retry, which is the double-delivery you were trying to avoid. We send
`Accept-Encoding: identity` and refuse a compressed answer, so a server that
gzips unconditionally fails **every** delivery.

### Auto-disable, and getting turned back on

After **20 consecutive failed attempts** (not events — retries count, and the
streak is per account across all your events) we stop delivering: the hook is
disabled and your operator addresses get one email, once per disable.

Turning it back on is a support action — the same `PUT` that set the URL, which
clears the disable and the streak. Three consequences to plan around:

- **Events that occur while the hook is off are never queued.** Only what was
  already waiting resumes. There is no backfill, so after an outage on your side
  reconcile by polling the order read for anything you have open.
- **Queued events keep the URL they were queued with.** If the fix was a new
  address, expect the waiting rows to fail out against the old one rather than
  arrive.
- **The signing secret does not change.** Neither a URL change nor a re-enable
  rotates it; rotation is its own action, has no overlap window (there is one
  live secret at a time), and takes effect on the next attempt of every event —
  so deploy the new value promptly once you ask for it.

### What never rides in a body

**A voucher code, ever.** The webhook says `delivered`; you fetch the artifact
over `GET /merchant/v1/orders/{merchant_order_id}`. A webhook receiver logs the
bodies it is sent, wholesale, and a code is a bearer instrument — whoever reads
it can redeem it. A code in your nginx log is our leak as much as yours, so the
payload shapes above are asserted as exact key sets in our own tests
specifically to stop a later field addition from smuggling one in.

### What has no webhook at all

- **A fulfilment that fails, or stalls, on its own — with one exception.** Our
  order row does not move for a stall, or for a failure whose money did not
  come back, because both are recorded against the fulfilment task; you see
  `paid → fulfilling → silence`. Poll the order read: `failure_reason` goes
  non-null while the status is still `fulfilling`, for a terminal failure
  (three values) and for a delivery delayed on our side
  (`fulfillment_delayed`, which is **not** terminal — keep polling). You no
  longer need a timeout of your own to tell "progressing" from "stuck"; you
  still want one as a ceiling, because we promise no bound on a delay. **The
  exception is a failure we refund in full** (M3c Task 6): that closes the
  order, so you get `order.status_changed` with `status: "failed"` right after
  the `balance.credited`.
- **Prices.** There are no price webhooks and never will be; poll `/catalog` and
  watch `updated_at`.
- **A low balance.** There is no `balance.low`. `balance_usd` rides
  `balance.credited`, every order response and `GET /merchant/v1/me`; the
  threshold is yours to pick.

## Your first order in ten minutes

`bash`, `curl` and `openssl`, nothing else — deliberately not Python, because
the point of this scheme is that it needs no SDK and no library. Ten minutes
assumes support has already credited your deposit; without one you can do
everything here except step 6.

### 1. What support hands you

A `key_id` and a `secret` (see "Credentials"). Ask for two more things in the
same conversation, because both are cheaper to arrange now than later:

- **an IP allowlist**, if your calls leave from fixed addresses. It is fixed
  when the key is issued, so adding one later means a new key.
- **a cheap SKU to test on.** A live order spends real money from your
  deposit; there is no sandbox and no test mode, and an order that reaches
  fulfilment cannot be undone by either side.

### 2. The client, in twenty lines

```bash
#!/usr/bin/env bash
# Minimal /merchant/v1 client: bash, curl, openssl. Nothing else.
set -euo pipefail

BASE="${YUPAY_BASE:-https://api.yupay.uz}"
KEY_ID="${YUPAY_KEY_ID:?export YUPAY_KEY_ID first}"
SECRET="${YUPAY_SECRET:?export YUPAY_SECRET first}"

# canonical = ts \n METHOD \n raw_path \n raw_query \n sha256_hex(body)
yupay_sign() { # ts method path query body -> hex signature
  local ts=$1 method=$2 path=$3 query=$4 body=$5 body_hash
  body_hash=$(printf '%s' "$body" | openssl dgst -sha256 | awk '{print $NF}')
  printf '%s\n%s\n%s\n%s\n%s' "$ts" "$method" "$path" "$query" "$body_hash" |
    openssl dgst -sha256 -hmac "$SECRET" | awk '{print $NF}'
}

yupay() { # method path [query] [body]
  local method=$1 path=$2 query=${3:-} body=${4:-} ts sig url
  ts=$(date +%s)
  sig=$(yupay_sign "$ts" "$method" "$path" "$query" "$body")
  url="$BASE$path"
  if [ -n "$query" ]; then url="$url?$query"; fi
  if [ -n "$body" ]; then
    curl -sS -X "$method" "$url" \
      -H "X-Merchant-Key: $KEY_ID" -H "X-Merchant-Timestamp: $ts" \
      -H "X-Merchant-Signature: $sig" -H 'Content-Type: application/json' \
      --data-raw "$body"
  else
    curl -sS -X "$method" "$url" \
      -H "X-Merchant-Key: $KEY_ID" -H "X-Merchant-Timestamp: $ts" \
      -H "X-Merchant-Signature: $sig"
  fi
}
```

Save it as `yupay.sh`. Two things about it that are fine in a terminal and do
not belong in a service: the secret sits in `openssl`'s argv, where anyone
running `ps` sees it for the length of the call, and `date +%s` trusts the
machine's clock — which the ±300 s window does not.

### 3. Prove the signer before you blame the network

A signature that is wrong is wrong invisibly: you get the same `401
invalid_credentials` as someone with no key at all, on purpose. So check the
arithmetic offline first, against numbers generated with the server's own
signing code:

```bash
export YUPAY_KEY_ID="ypm_EXAMPLEqQ0Zr7t3vXbN9mK2sJ8dF4hL6"
export YUPAY_SECRET="ypms_EXAMPLEt5Rk8pW2vZ9xB4nM7jH3gD6sQ1cL0aY7uE2i"
source ./yupay.sh

yupay_sign 1757000000 GET  /merchant/v1/me           ""         ""
yupay_sign 1757000000 GET  /merchant/v1/catalog      ""         ""
yupay_sign 1757000000 GET  /merchant/v1/transactions "limit=50" ""
yupay_sign 1757000000 GET  /merchant/v1/orders/acme%2F2026%2F000417 "" ""
yupay_sign 1757000000 POST /merchant/v1/orders       ""         '{"merchant_order_id":"acme-2026-000417","sku_id":"0198c3cb-6a0f-7b31-9c22-2f7a1e5d4b08","expected_price":"1.06","fulfillment_data":{"player_id":"5123456789"}}'
```

prints exactly, in order:

```
249f19db4ffa0bac0ee3fd8971ed05faecbdd38a4672f711ff0ba4532797d36c
73d503d7dcec7365addd66c8547cfad75a0227e37d8e34249b5e05d85efb4cb7
b879b159e5aa3c5aa0984b7e198b8fff28446d2747a6f942e43ef429dccae6fb
b351c764049f32804fd34a1063f97acdeee3ae82a7b0027ac41602cf590b5b01
e5940d771c60bc074cbb00d0b93265a3990fef35aa769d94cb9588468d04e1f5
```

Those two credentials are examples. They authenticate against nothing — they
exist so the arithmetic is checkable with no account. If your implementation
disagrees on any line, the fault is in the canonical string, and in practice
it is one of five things: a trailing newline (`echo` where `printf` belongs),
CRLF instead of LF, the query carrying its leading `?`, the path
percent-**de**coded before signing, or a body re-serialised between signing
and sending.

Then export your real `YUPAY_KEY_ID` and `YUPAY_SECRET` and carry on.

### 4. `GET /me` — are the credentials live?

```bash
yupay GET /merchant/v1/me
```

```json
{
  "merchant_id": "0198c3c9-2a44-7c1a-9f3e-4b6f2e0d9a11",
  "title": "Acme Resale",
  "status": "active",
  "balance_usd": "42.50"
}
```

If this fails, the `code` in the body says where to look: `stale_timestamp` is
your clock, `missing_credentials` is a header you did not send,
`invalid_credentials` is the key or the signature (step 3), `ip_not_allowed` is
the address you called from, `merchant_frozen` is a conversation with support.

### 5. `GET /catalog` — pick something to buy

```bash
yupay GET /merchant/v1/catalog > catalog.json
jq -r '.brands[] as $b | $b.products[] as $p | $p.skus[]
       | [.sku_id, .sku_code, ($b.slug + "/" + $p.slug), .price_usd] | @tsv' catalog.json
```

```
0198c3cb-6a0f-7b31-9c22-2f7a1e5d4b08	PUBGM_UC_60	pubg-mobile/pubg-mobile-uc	1.06
```

Take one `sku_id` and the `price_usd` beside it: that price is what goes into
the order as `expected_price`, which is how you find out if it moved.

### 6. `POST /orders` — spend a dollar

```bash
SKU="0198c3cb-6a0f-7b31-9c22-2f7a1e5d4b08"
PRICE="1.06"
ORDER="first-$(date +%Y%m%d-%H%M%S)"          # yours, and the idempotency key
BODY=$(printf '{"merchant_order_id":"%s","sku_id":"%s","expected_price":"%s","fulfillment_data":{}}' \
  "$ORDER" "$SKU" "$PRICE")

echo "$ORDER"                                  # write it down BEFORE you send
yupay POST /merchant/v1/orders "" "$BODY"
```

`fulfillment_data` is `{}` for a voucher SKU. For a top-up, put in exactly the
keys that product asks for and nothing else — an unrecognised key refuses the
whole order.

```json
{
  "merchant_order_id": "first-20260907-081953",
  "order_id": "0198c3d1-7f22-7a90-b118-9d3c5e604a7f",
  "status": "fulfilling",
  "sku_id": "0198c3cb-6a0f-7b31-9c22-2f7a1e5d4b08",
  "price_usd": "1.06",
  "balance_usd": "41.44",
  "created_at": "2026-09-07T08:19:53.402913Z"
}
```

`201` and `"fulfilling"` mean the order exists and your deposit is charged —
not that anything is delivered. If the call times out, **resend the identical
request**: same id, same body, no second order.

### 7. Poll until the code lands

```bash
while :; do
  yupay GET "/merchant/v1/orders/$ORDER" > order.json
  jq -r '"\(.status)\t\(.failure_reason // "-")"' order.json
  jq -e '.status == "delivered"
         or (.failure_reason as $r
             | ["fulfillment_failed", "fulfillment_failed_refunded", "order_failed"]
             | index($r))' \
     order.json >/dev/null && break
  sleep 3
done
jq -r '.delivery.artifact.code // .delivery.artifact.message // "no artifact"' order.json
```

Both stop conditions matter, and so does the shape of the second: it breaks on
a **list of values you know**, not on "`failure_reason` is not null". A failed
delivery whose money is still out leaves `status` at `fulfilling` for good and
only `failure_reason` moves, so a loop watching the status alone never exits for
it — one whose money we put back does close as `failed`, which is exactly why
"watch the status instead" is not the fix. And `fulfillment_delayed` is **not**
a failure, nor is any value we add after you write this. A loop that breaks on
any non-null value stops polling an order that is still coming and leaves your
customer unserved with their money taken; an allow-list keeps waiting through
both, which is the safe direction to be wrong in. See "Failure reasons" for the
table, and put a ceiling of your own on the wait, because we make no promise
about how long a delay lasts.

Our ids here contain nothing that needs escaping; if yours do, the path segment
is percent-encoded and **the encoded form is what you sign**
(`encodeURIComponent`, `urllib.parse.quote(id, safe="")`).

### 8. Before you point production at this

- Reuse `merchant_order_id` across every retry of one intent. A fresh id per
  HTTP attempt places duplicate orders — this is the single most expensive
  mistake available on this API.
- **Poll the order read anyway.** A webhook is a notification and it is
  at-least-once, not exactly-once and not guaranteed-once-only-in-order: it
  never carries the code, it is silent on a fulfilment that fails on its own,
  and it stops entirely if we auto-disable your endpoint. There is no price
  webhook, ever. See "Outgoing webhooks".
- Honour `Retry-After` on a `429` instead of retrying immediately.
- Watch `balance_usd` yourself. Nothing warns you before it runs out; an order
  that cannot be covered is a `409 insufficient_deposit`, which is recoverable
  but only after somebody tops you up.
- Parse money with a decimal type. `"1.06"` through a float is `1.0599…`.
- Bill off `price_usd` in the **response**, not off the `expected_price` you
  sent. Inside the drift band we charge our price, so the two legitimately
  differ — see "Price drift". Reconciling against your own request is the
  quiet way to end up disagreeing with your invoice.
- Branch on `code`, not on `detail`. Every error here is problem+json except a
  `5xx` and a wrong URL or method (see "Errors"), and a request we could not
  even parse is `422 invalid_request`.

## Implementation map

| Concern                                                     | Where                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ----------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The merchant account (create / load / freeze)               | `service.py`                                                                                                                                                                                                                                                                                                                                                                                                                            |
| Wire format: key/secret minting, canonical string, digests  | `signing.py` — the one home; nothing else may re-derive these                                                                                                                                                                                                                                                                                                                                                                           |
| Secret encryption at rest                                   | `core/crypto.py` (purpose `yupay:merchants:apikey:v1`)                                                                                                                                                                                                                                                                                                                                                                                  |
| Credential lifecycle (create / list / revoke)               | `credentials.py`, via the `api` facade                                                                                                                                                                                                                                                                                                                                                                                                  |
| Request verification + the FastAPI dependency               | `auth.py`                                                                                                                                                                                                                                                                                                                                                                                                                               |
| The deposit: credit, charge, balance, ledger listing        | `deposit.py` — the accounts, the reads, and every movement **except** the automatic refund                                                                                                                                                                                                                                                                                                                                              |
| The automatic refund of a failed order                      | `refund.py` — the posting, its three refusals and the key; fired by `fulfillment.service._settle_merchant_deposit`, never by this module                                                                                                                                                                                                                                                                                                |
| Admin HTTP surface                                          | `admin_routes.py` (`/admin/merchants`) and `catalog_b2b_routes.py` (`/admin/catalog`), over the shared replay helpers in `route_replay.py`                                                                                                                                                                                                                                                                                              |
| Machine API routes (`/merchant/v1`)                         | `machine_routes.py` — mounted by `bootstrap`, own prefix. **`GET /orders/{merchant_order_id:path}` is greedy** and matches everything under `/orders/`; register any future `/orders/{id}/…` route above it or Starlette will swallow it.                                                                                                                                                                                               |
| The published contract (`GET /merchant/openapi.json`)       | `machine_openapi.py` — the app's schema narrowed to these six paths and the models they reach. **Unauthenticated, not limiter-exempt, and deliberately outside `/merchant/v1`** — that prefix means "signed", and four sweeps enumerate it to assert exactly that of everything in it                                                                                                                                                   |
| The priced catalog read model                               | `price_list.py`                                                                                                                                                                                                                                                                                                                                                                                                                         |
| What may be ordered and at what price                       | `quote.py` — orderability, margin floor, ±2 % drift. Its `unavailable()` is the one `item_unavailable` refusal on this API; `validate.py` raises the same one.                                                                                                                                                                                                                                                                          |
| The advisory player check (`/validate/player`)              | `validate.py` — resolves the SKU, decides `unsupported`, and hands the rest to `integrations.player_check`. It performs no check of its own and must never turn that module's `error` into anything friendlier.                                                                                                                                                                                                                         |
| Reading one order back (status, code, refund mark)          | `order_status.py`                                                                                                                                                                                                                                                                                                                                                                                                                       |
| The deposit ledger page (`/transactions`)                   | `transactions.py` — cursor codec; the query is `deposit.py`'s                                                                                                                                                                                                                                                                                                                                                                           |
| Order placement + the deposit charge                        | `orders.py`; the debit itself is `deposit.charge_deposit`, and the merchant's quote is recorded on the line by the same call (`orders.create_order`'s merchant-only `merchant_expected_price_usd=`, migration 0072)                                                                                                                                                                                                                     |
| The wholesale price formula and the ±2% drift rule          | `pricing.py` — the one home for both                                                                                                                                                                                                                                                                                                                                                                                                    |
| Machine-API wire DTOs (the third-party contract)            | `machine_schemas.py` — additive changes only                                                                                                                                                                                                                                                                                                                                                                                            |
| A request the schema itself refused (`422 invalid_request`) | `core/errors.py::problem_json_validation_handler` — registered app-wide by `bootstrap`, **scoped to this prefix**, matched by path segment so a future `/merchant/v1beta` does not inherit it; every other path is delegated to FastAPI's own handler byte for byte, because the generated TS client types every operation in the repo from the `HTTPValidationError` schema. The OpenAPI half is `machine_routes._VALIDATION_PROBLEM`. |
| Admin-surface DTOs                                          | `schemas.py`                                                                                                                                                                                                                                                                                                                                                                                                                            |
| Cabinet HTTP surface (`/merchant/cabinet`)                  | `cabinet_routes.py` (the signed-in reads and writes) and `cabinet_auth_routes.py` (everything that runs **before** there is a session) — the browser's BFF, **not** part of the contract above. Mounted by `bootstrap` beside `/merchant/v1` and deliberately _not_ on its rate-limit exemption list.                                                                                                                                   |
| Cabinet sessions (register / confirm / login / refresh)     | `cabinet_auth.py` over `merchant_sessions`; `cabinet_deps.current_merchant_user` is the dependency every cabinet read sits behind                                                                                                                                                                                                                                                                                                       |
| Cabinet DTOs                                                | `cabinet_schemas.py` — free to change with the app that reads it, which is why they are not `machine_schemas.py`                                                                                                                                                                                                                                                                                                                        |
| The cabinet's Orders list (no machine-API twin)             | `cabinet_orders.py` — keyset paging, a closed filter set, money from the ledger                                                                                                                                                                                                                                                                                                                                                         |
| The cabinet's webhook screen                                | `cabinet_webhook_routes.py` — a second router over the same prefix, carved off when the first passed AGENTS §6's soft limit                                                                                                                                                                                                                                                                                                             |
| The cabinet's delivery log (no machine-API twin)            | `cabinet_webhooks.py` — keyset paging over the index `merchant_webhook_deliveries` was built with                                                                                                                                                                                                                                                                                                                                       |
| Shared cabinet dependencies                                 | `cabinet_deps.py` — `current_merchant_user`, the `Db`/`CurrentUser` annotations, and `merchant_of`, which reloads the company on **every** request so a freeze lands on the next call                                                                                                                                                                                                                                                   |
| An API key's IP allowlist, parsed                           | `allowlist.py` — **one** validator, shared by the admin DTO and the cabinet's; a second table of what an address is drifts, and the drift is a 403 nobody can explain                                                                                                                                                                                                                                                                   |
| The dashboard's three numbers                               | `cabinet_summary.py` — counts exact, money from the ledger, and the window's start comes from the **browser**, never from the stored timezone                                                                                                                                                                                                                                                                                           |
| The cabinet's CSV exports                                   | `cabinet_export.py` — built from `transactions.build` and `price_list.build`, so a file can never disagree with the screen it came from                                                                                                                                                                                                                                                                                                 |
| Security notices to a merchant's operators                  | `cabinet_notify.py` — five events, one closed vocabulary, mailed to **every** confirmed operator and never only to whoever clicked                                                                                                                                                                                                                                                                                                      |
| The cabinet's «Отправить тестовое событие»                  | `cabinet_webhook_routes.send_test_event` — queues a `webhook.test` down the **real** path, so a verifier that is broken fails the test                                                                                                                                                                                                                                                                                                  |

Three of those files were carved out of two in M2 Task 5, when `service.py`
(487 lines) and `orders.py` (468) had both drifted past the 400-line soft
limit in AGENTS.md §6. `service.py` was one name over three responsibilities —
the account, its credentials, its money — and `orders.py` was answering "may
this be bought, and for how much" in the same breath as "place it and charge
for it". Nothing moved but the code.

`auth.merchant_auth` is the dependency every `/merchant/v1` endpoint sits
behind. **Import it from `merchants.auth` directly, never from
`merchants.api`**: it takes its session from `api.v1.deps.db_session` so the
endpoint behind it shares one transaction, which means the facade cannot
re-export it without closing an import cycle back through the v1 route stack —
the same rule the two admin routers follow. It supports **byte-body
endpoints only**: it reads `await request.body()`, and an endpoint declaring
`Form(...)`/`UploadFile` would send FastAPI down the `request.form()` branch,
consuming the stream without populating the cache the dependency relies on.

### Storage

The secret is encrypted, not hashed, and the reason is structural: an HMAC
cannot be verified without the key material, so a one-way digest either
forbids HMAC or forces the digest itself to be the signing key — which is
storing key material in the clear under a reassuring name. `core/crypto.py`
gives each purpose an HKDF-derived key from the one `INVENTORY_ENC_KEY` input,
so merchant secrets and voucher codes never share a key. The same protection
`inventory_codes` has had all along, applied to the instrument that is worth
more.

The **outgoing-webhook** secret (`merchant_webhooks`) is stored the same way
for the same reason — we compute the HMAC on every delivery — under its own
label, `yupay:merchants:webhook:v1`. A third label rather than a shared one:
the two secrets key opposite directions of the same integration, and
compromising the derived key behind one should not read the other's rows.

### Rate limiting internals

Two axes, one counter implementation (`auth.ip_guard.hit_counter`):

- **per IP** — `guard_ip(request, bucket="merchant-api")`, ceiling
  `auth_ip_guard_bucket_max["merchant-api"]`. No `subject` is passed:
  `guard_ip`'s subject axis is capped by the single global
  `auth_ip_guard_subject_max` (10), which would throttle every merchant to ten
  requests a minute.
- **per key** — `settings.merchant_api_key_rate_max`, charged after the
  signature verifies.
- **per IP, on `/validate/player` only** — `guard_ip(request,
bucket="merchant-validate")` in the handler, ceiling
  `auth_ip_guard_bucket_max["merchant-validate"]` (120). Charged _after_
  authentication, since the prefix-wide counter has already turned away
  anyone unauthenticated, and stricter than that counter because the quota it
  protects is a supplier's rather than ours (spec §12).

Brute force is not the threat model — the secret is 256 bits and compared with
`compare_digest` — throughput is, which is what both numbers are sized for.

### Inherited assumption: the caller's address

The allowlist is enforced against `core.client_ip`, which takes the first
`X-Forwarded-For` entry with **no trusted-proxy check**; its safety rests
entirely on the shared edge overwriting that header rather than appending to
it. That assumption previously only decided which rate-limit counter got
charged. Hardening `client_ip` itself is filed for M3 (it is repo-wide), and
the mitigating fact is that the allowlist is **defence-in-depth on top of the
HMAC**, never the primary control: an attacker who can spoof the header still
has no secret.

## Status

Schema (M1 Task 1), the deposit service (M1 Task 3), wholesale pricing
(M1 Task 5), the admin endpoints (M1 Task 6), the admin SPA screens
(M1 Tasks 7–8), API-key issuance plus the signed-request dependency
(M2 Task 2, wire format and storage revised after review), `GET /merchant/v1/me`
and `GET /merchant/v1/catalog` (M2 Task 3), `POST /merchant/v1/orders`
(M2 Task 4) and the two reads a reseller's back office lives on —
`GET /merchant/v1/orders/{merchant_order_id}` and
`GET /merchant/v1/transactions` (M2 Task 5) — are in place. M3a lands outgoing
webhooks end to end (ADR-0070): Task 1 the _storage_ and its admin-only
configuration surface (`merchant_webhooks`, `merchant_webhook_deliveries`,
migration 0071, and the four `/admin/merchants/{id}/webhook` endpoints above),
Task 2 the SSRF-checked outbound client (`core/outbound.py`), Task 3 the
producer that fills the outbox (`webhooks.py`, above) and Task 4 the worker
that drains it, signs it and gives up on it. M3a Task 5 adds spec §9.1's sixth
row,
`POST /merchant/v1/validate/player` — which M2 had deliberately left out
because it is honest only for the SKUs a real player-check provider covers,
and a validator that approves whatever it is given is worse than no endpoint.
That constraint is now the endpoint's contract rather than a reason to omit
it: a SKU with no provider answers `unsupported`, and a check we could not
make answers `error`, neither of which a client can mistake for approval.
**Those six are the whole machine API.** Refunds and the cabinet BFF are M3+.

**A merchant order now refunds itself when it can.** M3b Task 3 closes the gap
M2 left: a terminal fulfilment failure whose money outcome is `RETURNED` posts
the charge straight back to the deposit, in the same transaction the drain
records the failure in, referencing the order. `SPENT` and `UNKNOWN` refund
nothing and raise an ops alert instead — see "Automatic refunds" below for
what that costs and who carries it. Task 2 had already closed the half of the
gap that was a defect rather than an omission: an operator's settlement can
name the order it settles, which is both the manual fallback and the reason
`refunded_usd` was capable of reading anything but `"0.00"`.

What is left is written up with what it costs in
`docs/runbooks/merchant-b2b.md`, under "Known gaps before a pilot integrates" —
read it, and the settlement procedure beside it, before you put the first
reseller on this.

Push exists now and is deliberately narrow: a webhook notifies, it never
carries the artifact, it is silent on a fulfilment that fails on its own, and it
is configured by support until M4's cabinet. Polling the order read remains the
contract's delivery channel, which is why it is described that way wherever it
appears.

**M4 adds the cabinet** — the browser half, `apps/merchant` at
`reseller.yupay.uz` over `/merchant/cabinet` (ADR-0076). Nothing in it changes
this contract: it is a BFF our own app talks to, with its own DTOs, its own
credential and its own token kind, and a reseller integrating `/merchant/v1`
can ignore every word of it. What it changes is who has to be awake — sign-up,
the wholesale price list, a first order without writing code, the order and
statement reads, and **issuing and revoking API keys** are self-serve now,
where each one used to be a message to support. **Webhook configuration moved
with them.** Through M3a it was admin-only, and the reason was SSRF — letting
a stranger aim our outbound worker at an address of their choosing. What makes
handing it over safe is that both defences sit below the caller:
`admin.validate_webhook_url` refuses a non-https or non-public host at save
time, and `core/outbound.py` pins one resolved address per attempt at send
time. Neither asks who called. The screen also carries the **delivery log**
`merchant_webhook_deliveries` was built for — what we sent, where it went,
what came back — which is the question support answered by hand until now.
