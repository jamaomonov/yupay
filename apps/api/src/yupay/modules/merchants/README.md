# `merchants`

B2B reseller accounts: a merchant, its cabinet operator(s), and the API keys
its server uses against `/merchant/v1`. This is the schema module that every
other part of the merchant B2B feature (the machine API, the cabinet BFF, the
deposit ledger, admin) builds on.

**Spec:** `docs/superpowers/specs/2026-09-06-merchant-b2b-design.md`
**Decisions:** ADR-0068 (the foundation), ADR-0069 (the machine API)
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

| Event                  | Body                                                           |
| ---------------------- | -------------------------------------------------------------- |
| `order.status_changed` | `merchant_order_id`, `order_id`, `status`, `at` (ISO 8601 UTC) |
| `balance.credited`     | `amount_usd`, `balance_usd` — two-decimal **strings**          |

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
  would have a reseller crediting their own customer twice.

The two typed producers are `enqueue_order_status_changed` and
`enqueue_balance_credited`, and the first is deliberately **not** called
`on_order_status_changed`: that is the name of the seam in `orders.service`, it
takes the same two arguments, and it also nudges retail. One name for both
would let an autocomplete in any module that imports `merchants` — most do —
swap the seam for this half of it, silently turning the storefront's live
updates off with no test to fail. The facade exports the generic `enqueue` as
`enqueue_webhook_event` for the same reason.

Drawn in `docs/architecture/sequence-diagrams/merchant-webhook-emit.mmd`.

## Outgoing webhooks — the delivery drain (`webhook_delivery.py`, `webhook_retry.py`)

M3a Task 4, run from `apps/worker` (`yupay_worker.consumer` LISTENs on
`merchant_webhook_queue` beside `fulfillment_queue`, sharing one wake event, and
calls `merchants.api.drain_pending_deliveries`). Same ADR-0064 shape as
fulfilment: claim `FOR UPDATE SKIP LOCKED`, one SAVEPOINT per row, never commit
— the worker owns the transaction. Drawn in
`sequence-diagrams/merchant-webhook-deliver.mmd`.

### What each attempt sends

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

### The retry table is derived from the client's taxonomy, not invented

`webhook_retry.py` is pure and reads `core/outbound_errors.py` rather than
matching on exception names. Two questions answer everything:

| Outcome                                             | What happens                       | Counts toward the streak |
| --------------------------------------------------- | ---------------------------------- | ------------------------ |
| `2xx`                                               | `delivered`                        | resets it to 0           |
| `408`, `429`, `5xx`                                 | `pending`, backoff                 | yes                      |
| any other `4xx`, and a redirect (never followed)    | `failed`                           | yes                      |
| `Delivery.RECEIVED` refusal (too large, compressed) | `failed` — a retry **re-delivers** | yes                      |
| `Delivery.NOT_SENT` / `UNKNOWN` transport failure   | `pending`, backoff                 | yes                      |
| `OutboundBrokenError` — **our** bug                 | `failed`                           | **no**                   |

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
`Retry-After` is honoured on the two statuses RFC 9110 defines it for (`429`,
`503`), both forms parsed, clamped into `[1 s, 1 h]` — the header is written by
a third party and `Retry-After: 0` on every answer would be a hot loop.

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

### Falsification

`uv run python apps/api/tests/tools/falsify_merchant_webhook_delivery.py` — 15
mutations, each asserting it changed the file before the suite runs. Read its
docstring before running it beside anything else.

## Deposit ledger

The merchant's prepaid balance is a **ledger balance**, never a column.
`merchant_deposit` is a debit-normal account kind (like `user_wallet`),
owned by `owner_type="merchant", owner_id=<merchant_id>, currency="USD"`
— USD-only in v1 (spec §7). Every movement posts through
`wallet.service.post`, so idempotency-by-key and all-or-nothing legs are
inherited from the ledger, not rebuilt here.

It lives in `deposit.py`; the posting table below is authoritative and no
caller may re-derive a direction from it:

| Event                       | Legs                                             | Kind                      |
| --------------------------- | ------------------------------------------------ | ------------------------- |
| Support credits top-up (M1) | `D merchant_deposit / C house_payments_received` | `merchant_deposit_credit` |
| Order charge (M2)           | `C merchant_deposit / D house_payments_received` | `merchant_order_charge`   |
| (M3) refund on failure      | `D merchant_deposit / C house_payments_received` | _not implemented_         |

The first two rows are live. `deposit.credit_deposit` posts the credit with
the caller's idempotency key, so a replay returns the original transaction;
`deposit.charge_deposit` posts the debit keyed `merchant-order:{order_id}`,
which makes a double debit impossible even if the order path were re-entered
for one order. `charge_deposit` is also **where the overdraw guard binds**: it
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
facade only. Two routers — `admin_router` in `admin_routes.py` and
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
  `amount` is the transaction's actual (original) amount — a mismatched
  replay is visible to the admin UI, and `balance` rides along. See
  `docs/architecture/sequence-diagrams/merchant-deposit-credit.mmd`.
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
response's `amount` with what the operator typed and warns loudly on a
mismatch, mints one idempotency key per logical credit attempt (stable
across retries), and blocks double-submit while a credit is in flight.

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
> two reads, order placement, the order read and the deposit ledger. The
> scheme is final. What does not exist yet is outbound webhooks, any refund
> path, and the self-service cabinet; see "Status" at the end of this file.

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

**A `5xx`.** No endpoint here raises one deliberately: nothing on this surface
calls a supplier while you wait (see "Fulfilment is asynchronous, always"), so
there is no upstream to be unavailable. A `500` means an unhandled bug on our
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

Two independent counters, both fixed 60-second windows:

| Axis                  | Limit          | Applies to                           |
| --------------------- | -------------- | ------------------------------------ |
| Per source IP address | **600 / 60 s** | Every request, before authentication |
| Per `key_id`          | **600 / 60 s** | Requests whose signature verified    |

Both return `429` with a `Retry-After` header in seconds; wait that long
rather than retrying immediately. The per-key counter is charged only after a
signature verifies, so someone who observes your `key_id` in a header cannot
spend your budget. Each live key has its own counter, so a rotation window
briefly has two.

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

Also part of the contract. Every response is JSON; every request is
signed as above. **Money is always a JSON string with exactly two decimal
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
| `expected_price`    | yes      | The `price_usd` you last read for that SKU. At most two decimals. See "Price drift" below.                                                                                                                                        |
| `fulfillment_data`  | no       | Whatever the SKU needs (a player id, a login) — the same fields the storefront collects, validated the same way. **Send those keys and nothing else**: an unrecognised key is a `422`, not a silently ignored one. See below.     |

One SKU per order. There is no `qty` and no line array: a reseller's basket
does not have to be ours, and one line per order means "the order failed"
never means "half the order failed". Send several orders.

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

"Same body" is decided on `sku_id`, `expected_price` and `fulfillment_data`.
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

_(Changed 2026-09-07, before any integrator existed: within the band the order
used to execute at the lower of the two prices. `POST /orders` is the only
endpoint affected, no request or response field changed shape, and the only
observable difference is `price_usd` on an order whose `expected_price` was
below ours.)_

#### Errors

| Status | `code`                 | Meaning                                                                                                                                                                                   |
| ------ | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 404    | `item_unavailable`     | This SKU cannot be ordered right now. The body carries a `reason` — see below.                                                                                                            |
| 422    | `price_changed`        | Drift beyond ±2%. Body carries `current_price` and the `expected_price` you sent.                                                                                                         |
| 422    | `margin_floor`         | Our own pricing for this SKU is misconfigured. Not your fault; tell support.                                                                                                              |
| 422    | —                      | A `fulfillment_data` field the product's schema rejects. The nested `extra` object names the `field` and the `reason` (`missing`, `type`, `pattern`, …) — see "Extra fields on the body". |
| 422    | `invalid_request`      | The request body itself did not parse — a missing field, an unknown one, more than two decimals on `expected_price`, a `sku_id` that is not a UUID. `errors` says which.                  |
| 409    | `insufficient_deposit` | Body carries `balance_usd` and `required_usd`. Top up and retry the **same** id.                                                                                                          |
| 409    | `order_conflict`       | A rare write conflict on our side. Retry the **same** id; it is safe.                                                                                                                     |
| 409    | `order_id_reused`      | This `merchant_order_id` already belongs to a different order.                                                                                                                            |

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
correctly accounted for the whole time and nothing is lost. Poll, and treat a
long `fulfilling` as "in progress", never as a reason to place a second order.

### `GET /merchant/v1/orders/{merchant_order_id}`

Where an order ends up, and **where you collect the code**. Poll it after a
`201`; there is no push in v1, and when the M3 webhook arrives it will tell you
that something changed without carrying the goods — a voucher code in a webhook
body is a bearer instrument written to your logs and ours.

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

| Field            | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `status`         | `paid`, `fulfilling`, `delivered`, `failed`. Those four are what a merchant order reaches today, in that order (`failed` from any of the first three). New values may be added — treat an unknown one as "still in flight".                                                                                                                                                                                                                                                                                        |
| `price_usd`      | What the order charged. Final.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `refunded_usd`   | **Money that came back to your deposit on this order.** Read off the ledger as a direction rather than as a transaction named "refund", so whatever M3 calls a refund will land here without a contract change. It is `"0.00"` on every order today, and not only because refunds are unbuilt: nothing we can do by hand books against an order either — a manual settlement is credited to your deposit as an ordinary top-up, so it shows on `GET /merchant/v1/transactions` and in `balance_usd`, and not here. |
| `failure_reason` | `null`, or one of the codes below.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `delivery`       | `null` until something has actually been delivered, and present as soon as it has — it is the delivery record that decides, not `status`. Normally the two move together. See below.                                                                                                                                                                                                                                                                                                                               |
| `timeline`       | The order's lifecycle events, oldest first, `{event, at}`. A merchant order produces `order.created`, `order.paid`, `order.fulfilling`, `order.delivered` and `order.failed`. `order.cancelled` is accepted by the same filter but cannot occur on this channel today — cancelling is legal only before payment, and a merchant order is born paid. More kinds may be added.                                                                                                                                       |

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

**Failure reasons** are a closed set. You will never get a supplier's own words
or an operator's note: neither is switchable, and both are internal.

| `failure_reason`     | What happened                                  | What to do                                           |
| -------------------- | ---------------------------------------------- | ---------------------------------------------------- |
| `fulfillment_failed` | The delivery failed and will not retry itself. | Contact support quoting `order_id`. Do not re-order. |
| `order_failed`       | Support closed the order as undeliverable.     | Contact support. Refunds are manual until M3.        |

Note that `failure_reason` can be set while `status` is still `fulfilling` —
nothing advances the order row when a delivery fails, so the status alone would
say "in progress" indefinitely. Treat a non-null `failure_reason` as terminal
for your own purposes even if the status has not moved.

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

`merchant_order_id` is on every row an order caused, so a statement line
reconciles against your books without a second call.

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
accident. Delivery to you is the order read and, from M3, the outbound webhook.

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
  jq -e '.status == "delivered" or .failure_reason != null' order.json >/dev/null && break
  sleep 3
done
jq -r '.delivery.artifact.code // .delivery.artifact.message // "no artifact"' order.json
```

Both stop conditions matter: a failed delivery leaves `status` at `fulfilling`
for good and only `failure_reason` moves, so a loop watching the status alone
never exits. Our ids here contain nothing that needs escaping; if yours do, the
path segment is percent-encoded and **the encoded form is what you sign**
(`encodeURIComponent`, `urllib.parse.quote(id, safe="")`).

### 8. Before you point production at this

- Reuse `merchant_order_id` across every retry of one intent. A fresh id per
  HTTP attempt places duplicate orders — this is the single most expensive
  mistake available on this API.
- There is **no push**. Poll the order read; there is no webhook in v1 and no
  price webhook ever.
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
| The deposit: credit, charge, balance, ledger listing        | `deposit.py` — every movement of a merchant's money                                                                                                                                                                                                                                                                                                                                                                                     |
| Admin HTTP surface                                          | `admin_routes.py` (`/admin/merchants`) and `catalog_b2b_routes.py` (`/admin/catalog`), over the shared replay helpers in `route_replay.py`                                                                                                                                                                                                                                                                                              |
| Machine API routes (`/merchant/v1`)                         | `machine_routes.py` — mounted by `bootstrap`, own prefix. **`GET /orders/{merchant_order_id:path}` is greedy** and matches everything under `/orders/`; register any future `/orders/{id}/…` route above it or Starlette will swallow it.                                                                                                                                                                                               |
| The priced catalog read model                               | `price_list.py`                                                                                                                                                                                                                                                                                                                                                                                                                         |
| What may be ordered and at what price                       | `quote.py` — orderability, margin floor, ±2 % drift                                                                                                                                                                                                                                                                                                                                                                                     |
| Reading one order back (status, code, refund mark)          | `order_status.py`                                                                                                                                                                                                                                                                                                                                                                                                                       |
| The deposit ledger page (`/transactions`)                   | `transactions.py` — cursor codec; the query is `deposit.py`'s                                                                                                                                                                                                                                                                                                                                                                           |
| Order placement + the deposit charge                        | `orders.py`; the debit itself is `deposit.charge_deposit`                                                                                                                                                                                                                                                                                                                                                                               |
| The wholesale price formula and the ±2% drift rule          | `pricing.py` — the one home for both                                                                                                                                                                                                                                                                                                                                                                                                    |
| Machine-API wire DTOs (the third-party contract)            | `machine_schemas.py` — additive changes only                                                                                                                                                                                                                                                                                                                                                                                            |
| A request the schema itself refused (`422 invalid_request`) | `core/errors.py::problem_json_validation_handler` — registered app-wide by `bootstrap`, **scoped to this prefix**, matched by path segment so a future `/merchant/v1beta` does not inherit it; every other path is delegated to FastAPI's own handler byte for byte, because the generated TS client types every operation in the repo from the `HTTPValidationError` schema. The OpenAPI half is `machine_routes._VALIDATION_PROBLEM`. |
| Admin-surface DTOs                                          | `schemas.py`                                                                                                                                                                                                                                                                                                                                                                                                                            |

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
`GET /merchant/v1/transactions` (M2 Task 5) — are in place. **Those five are
the whole machine API.** M3a Task 1 adds the webhook _storage_ and its
admin-only configuration surface (`merchant_webhooks`,
`merchant_webhook_deliveries`, migration 0071, and the four
`/admin/merchants/{id}/webhook` endpoints above), and Task 3 the producer
that fills the outbox (`webhooks.py`, below). Nothing is **delivered** yet —
the worker that drains the outbox is Task 4, and the wire contract a merchant
verifies against is written up in Task 6. Spec §9.1 also sketches a sixth row,
`POST /merchant/v1/validate/…`, which is deliberately not in v1: it would only
be honest for the SKUs a real player-check provider covers, and a validator
that approves whatever it is given is worse than no endpoint. Outbound
webhooks, refunds and the cabinet BFF are M3+.

Two things a reseller will ask about and we do not have yet. **Nothing refunds
a merchant order:** a failed delivery leaves the deposit debited, and support
settles it by crediting the deposit by hand — which moves `balance_usd` and
appears on `/transactions`, while the order's own `refunded_usd` stays
`"0.00"`, because no surface can book a transaction against an order. And there
is **no push of any kind** — poll the order read. (A configured webhook does
not change that until M3a Task 4 lands; setting a URL today fills an outbox
nobody drains yet.)

The refund gap is written up with what it costs in
`docs/runbooks/merchant-b2b.md`, under "Known gaps before a pilot integrates" —
read it before you put the first reseller on this. The absence of push is a
deliberate v1 scope decision rather than a gap, and is stated wherever polling
is described.
