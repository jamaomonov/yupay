# Runbook — Merchant B2B

Two halves. The **catalog** sections cover M1's B2B visibility flags and the
one-time launch flip. The **machine API** sections, from "The machine API"
onward, cover the `/merchant/v1` surface a reseller's server calls **and the
outgoing webhooks we send back**: onboarding, credentials, the failure modes
that need a human, and the gaps a pilot integrator will meet.

## Catalog: verify the launch-flip after deploy (migration 0068)

`apps/api/migrations/versions/0068_catalog_b2b_flags.py` adds `visible_b2b`
to `brands`/`skus` and backfills it on deploy: every active brand of an
active, `top_up`/`voucher` SKU flips `visible_b2b = true`, except the
`steam-gifts` brand (a spec non-goal, excluded by slug).

**Do not trust the migration docstring's dev-snapshot list of brands as the
expected result on prod.** The flip runs against whatever the catalog holds
on deploy day — brands added, removed, or deactivated since this migration
was written change the outcome, and the docstring is a point-in-time example,
not a spec. Always verify against the live result:

```bash
docker compose -f docker-compose.prod.yml exec postgres psql -U yupay_app -d yupay -c \
  "SELECT slug, visible_b2b FROM brands ORDER BY visible_b2b DESC, slug;"
```

Read the output against the actual rule, not a memorized list: every row
with `visible_b2b = t` should be an active brand carrying at least one
active `top_up`/`voucher` SKU, and `steam-gifts` should be the one
otherwise-eligible brand sitting at `f`. If a brand you expected to see
flipped isn't there, check whether it (or all of its SKUs) was inactive at
deploy time — the migration only flips what was active then; it does not
re-run when a brand is reactivated later (see "Reflipping a brand" below).

## Catalog: reflipping a brand after the fact

The 0068 backfill is a one-time migration, not a standing rule — a brand
activated (or given its first active SKU) after deploy does **not**
automatically gain `visible_b2b`. The admin UI covers per-brand/per-SKU
toggles and bulk **markup** (spec §8.3); what it does not yet offer is a bulk
**visibility** action — for that, flip by hand:

```bash
docker compose -f docker-compose.prod.yml exec postgres psql -U yupay_app -d yupay -c \
  "UPDATE brands SET visible_b2b = true WHERE slug = '<brand-slug>';
   UPDATE skus SET visible_b2b = true
     FROM products
    WHERE skus.product_id = products.id
      AND products.brand_id = (SELECT id FROM brands WHERE slug = '<brand-slug>')
      AND skus.active AND products.active
      AND products.kind IN ('top_up', 'voucher');"
```

---

## The machine API (`/merchant/v1`)

Everything from here on concerns the reseller-facing API that M2 shipped. The
contract a merchant implements against is
`apps/api/src/yupay/modules/merchants/README.md`; the decisions behind it are
ADR-0068, ADR-0069 and ADR-0070 (the outgoing webhooks). **Read "Known gaps
before a pilot integrates" at the bottom before you put the first reseller on
this.**

Admin calls below use `-H "Authorization: Bearer <admin JWT>"` — the same
admin session the SPA uses.

## Telling a merchant order apart in admin

Since M3c Task 7 the Заказы list and the order page label the surface as
**«Merchant API»**. Before that every `/merchant/v1` order read «—»: the
`orders.source` CHECK had no value for the channel, so a machine order — which
sends no `X-Yupay-Surface` header, having no browser — fell through to
`unknown`, the same bucket as every order older than the column. The one class
of order whose origin is not in doubt was the one the list refused to name.

`merchants.orders.place` sets `source = 'merchant_api'` server-side, after the
signature has said which merchant is calling. That is worth knowing when you
read the column: for a retail row `source` is a client's own claim about
itself, and **on these rows it is not**. It still authorises nothing.

To find them by hand:

```sql
SELECT id, created_at, status FROM orders WHERE source = 'merchant_api';
```

Two things worth knowing:

- **Older orders were relabelled by 0073, and that is not a guess.**
  `merchant_id IS NOT NULL` has exactly one writer — `POST /merchant/v1/orders`
  — so the migration set `source = 'merchant_api'` on every merchant order that
  was still sitting in `unknown`, and left every other `unknown` row alone
  (0046's own rule: backfill what the data proves, never what it merely
  suggests). The practical consequence is that the two queries agree today:
  `source = 'merchant_api'` and `merchant_id IS NOT NULL` select the same
  orders. They stop agreeing the day M4's cabinet ships, and `merchant_id` is
  the one that keeps meaning "a reseller's order" — `source` means "which
  surface", which is a different question.
- **`merchant_panel` is allowed by the CHECK and written by nothing.** It is
  reserved for M4's cabinet and rides 0073 so that milestone needs no migration
  for one string. A row carrying it before the cabinet ships means something
  wrote it that should not have — that is a bug to chase, not a surface to
  interpret.

## Onboarding a merchant, end to end

Five steps, in this order. Steps 1–2 have SPA screens; steps 3 and 5 do not
yet, and step 5 is optional.

### 1. Create the account

Admin SPA → **Мерчанты** → «Создать». Or:

```bash
curl -X POST "https://api.yupay.uz/api/v1/admin/merchants" \
  -H "Authorization: Bearer <admin JWT>" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Acme Resale"}'
```

Keep the returned `id`. It is the `merchant_id` every step below needs, and it
is what the merchant quotes to support.

### 2. Credit the deposit

Admin SPA → the merchant's detail page → the deposit-credit form. It mints one
`Idempotency-Key` per logical attempt and warns loudly if the response's
`amount` differs from what was typed — which is how a mistakenly reused key
becomes visible, since the ledger replays **by key without comparing
parameters**. Prefer the SPA for this. The API, if you must:

```bash
curl -X POST "https://api.yupay.uz/api/v1/admin/merchants/<merchant-id>/deposit-credits" \
  -H "Authorization: Bearer <admin JWT>" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H 'Content-Type: application/json' \
  -d '{"amount":"500.00","note":"bank transfer 2026-09-07, ref 44812"}'
```

`Idempotency-Key` is **required** here (16–100 characters; `uuidgen`, or any
unique string that long). A fresh one per logical credit; the same one for
every retry of that credit.

This is the **prepayment** shape: money in, belonging to no particular order.
Leave the SPA form's **ID заказа** field (`order_id` on the API) empty. A
credit that settles one failed order fills it in and has its own procedure —
see "Settling a failed order by hand" below.

**Ordering is not blocked on the deposit** — a merchant with a zero balance
authenticates, reads `/me` and `/catalog` fine, and only `POST /orders` refuses
with `409 insufficient_deposit`. So a merchant can be handed a key and start
integrating before any money moves.

### 3. Issue the API key

There is **no SPA screen for this yet** — it is a curl call.

```bash
curl -X POST "https://api.yupay.uz/api/v1/admin/merchants/<merchant-id>/api-keys" \
  -H "Authorization: Bearer <admin JWT>" \
  -H 'Content-Type: application/json' \
  -d '{"label":"acme prod","ip_allowlist":["203.0.113.0/24"]}'
```

Both fields are optional; omit `ip_allowlist` (or send `null`) for no filter.
Entries are addresses or CIDR blocks, IPv4 or IPv6, at most 32, and a typo is
rejected at the parse boundary rather than stored to fail silently later.

The response carries `key_id` **and** `secret`. **That is the only time the
secret exists anywhere.** It is encrypted at rest under a key the database does
not hold, so nobody — including us — can read it back.

Do not pass `Idempotency-Key` on this call unless you have a reason: a replay
returns the original `key_id` with `secret: null` on purpose (the replay store
has no reaper and a usable credential must not sit in it in the clear). If you
did, and the first response was lost, revoke that key and issue another.

### 4. Hand it over, once

Send `key_id` and `secret` over a channel the merchant controls, and say in the
same message that we cannot resend it. Send with it:

- the base URL, `https://api.yupay.uz`;
- the contract: `apps/api/src/yupay/modules/merchants/README.md`, whose
  "Your first order in ten minutes" is a runnable script;
- a cheap SKU to test on — **there is no sandbox.** The first order they place
  is a real order against their real deposit.

Then confirm they are live:

```bash
curl "https://api.yupay.uz/api/v1/admin/merchants/<merchant-id>/api-keys" \
  -H "Authorization: Bearer <admin JWT>"
```

`last_used_at` moving from `null` is the signal that their signing works. It is
throttled to one write a minute per key, so it lags a burst; it never lags by
more than that.

### 5. Set the webhook, if they want one

Optional, and there is **no SPA screen and no merchant-facing endpoint** for it:
configuration is admin-only until M4's cabinet (ADR-0070 decision 7), so a pilot
who wants push depends on this call.

```bash
curl -X PUT "https://api.yupay.uz/api/v1/admin/merchants/<merchant-id>/webhook" \
  -H "Authorization: Bearer <admin JWT>" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://hooks.acme.example/yupay"}'
```

The response carries the row **and `secret`** — a `ypmw_…` value that, like the
API secret, exists nowhere else, ever. Hand it over in the same message as the
`key_id`/`secret` pair and point them at "Outgoing webhooks" in the module
README, which carries the canonical string, a worked example and a runnable
verifier.

Four things to say in that message, because each of them is a support ticket
otherwise:

- the webhook **never carries a voucher code** — they still poll
  `GET /merchant/v1/orders/{merchant_order_id}` to collect it;
- delivery is **at-least-once**: dedupe on `X-Yupay-Delivery`, order by the
  payload's `at`;
- their endpoint has **10 seconds** and must answer `2xx` with **at most 64 KiB**,
  uncompressed — a server that gzips unconditionally fails every delivery;
- nothing tells them when a fulfilment fails **or stalls** on its own
  (`paid → fulfilling →` silence); `failure_reason` on the order read is where
  both live — and one of its values, `fulfillment_delayed`, is **not**
  terminal, so a loop that breaks on "non-null" stops polling an order we are
  about to deliver. Send them the "Failure reasons" table, not a summary.

Read it back, and note what is missing on purpose:

```bash
curl "https://api.yupay.uz/api/v1/admin/merchants/<merchant-id>/webhook" \
  -H "Authorization: Bearer <admin JWT>"
```

`GET` returns the URL, `disabled_at`, `failure_streak`, `last_success_at` and
`last_failure_at` — the delivery worker's running health — and **no secret
field at all**. A `PUT` to a merchant that already has a hook edits the URL and
answers `secret: null`: changing where deliveries go must not silently break a
working verifier. Rotation is its own call
(`POST .../webhook/rotate-secret`), has no overlap window — one live secret at
a time — and takes effect on the very next attempt, so tell them before you run
it. `DELETE .../webhook` stops delivery by setting `disabled_at`; it is not a
delete, so the log and the URL stay readable and turning it back on does not
mean re-onboarding.

There is **no "send test event"** in M3a (it is a cabinet feature, spec §11).
The cheapest live test is the pilot's first real order, which emits `paid` and
`fulfilling` from one transaction and `delivered` from the worker.

## Rotating and revoking a key

Several keys can be live at once, which is what makes rotation zero-downtime:

1. issue the new key (step 3 above);
2. the merchant deploys it and confirms traffic on the new `key_id`
   (`last_used_at`);
3. revoke the old one:

```bash
curl -X DELETE "https://api.yupay.uz/api/v1/admin/merchants/<merchant-id>/api-keys/<key-id>" \
  -H "Authorization: Bearer <admin JWT>"
```

Revocation sets `revoked_at` and takes effect on the next request — there is no
cache and no grace period. It is naturally idempotent (a second call returns
the **first** timestamp, not a new one), and the key is matched on
`(merchant_id, key_id)`, so one merchant's id in the path can never revoke
another's credential — that is a 404.

**Changing an IP allowlist means rotating.** There is no endpoint that edits an
existing key's allowlist; issue a new key with the right list and revoke the
old one.

**On a suspected leak, revoke first and talk after.** A leaked secret is worth
the merchant's whole deposit balance, a signature is valid for the ±300 s
window it was made in, and there is no per-order approval step to catch a
fraudulent order after the fact.

## `INVENTORY_ENC_KEY` is now load-bearing for three subsystems

It was the voucher-code warehouse's key. It is now also the input from which
**merchant API-key secrets** (M2) and **merchant webhook signing secrets**
(M3a) are encrypted. `core/crypto.py` derives a separate key per purpose by
HKDF — `yupay:merchants:apikey:v1` and `yupay:merchants:webhook:v1` — so the
three never share key material, but they share the one input.

Losing it therefore breaks two merchant-facing things at once, with two
different symptoms. **Every merchant API key stops verifying**, and **no webhook
can be signed**: the secret is decrypted per attempt, `crypto.decrypt` raises a
`CryptoError`, the drain's poison belt catches it, and the delivery row is
written `failed` with

```
merchant_webhook.attempt_crashed   delivery_id=… error=CryptoError: …
```

The merchant's failure streak is deliberately **not** touched by that — the
fault is ours, so it must not auto-disable a working endpoint — which means a
lost key produces a queue that fails silently rather than a hook that switches
itself off. Grep for that log line, not for a disable.

The API-key symptom is precise and worth memorising, because it does not look
like an encryption failure from the outside:

- every `/merchant/v1` request answers an ordinary `401 invalid_credentials` —
  the same body an unknown key gets, because the auth path treats an
  unopenable secret as a bad credential rather than a 500;
- the api container logs `merchant_api_key_undecryptable` with the `key_id`,
  once per request. That log line is the only way to tell this apart from a
  merchant who broke their own signing.

```bash
docker compose -f docker-compose.prod.yml logs --since 30m api \
  | grep merchant_api_key_undecryptable
```

**Recovery is revoke-and-reissue.** There is no re-encryption path: the
plaintext secrets are gone with the old key. Restore the old value of
`INVENTORY_ENC_KEY` if you still have it (the voucher warehouse needs that
anyway — the same rotation breaks every stored code); otherwise every merchant
needs a new key issued and deployed on their side, which is a conversation, not
a command. The webhook half of that conversation is
`POST /api/v1/admin/merchants/{id}/webhook/rotate-secret` per merchant, and the
deliveries that crashed while the key was wrong are `failed` **terminally** —
nothing retries them, so replay the ones that matter by hand (below) once the
merchant is verifying again.

If the variable is **empty** in prod rather than wrong, the failure is louder
and earlier: `core.crypto` raises at first use, so key issuance and
verification both 500, and `bootstrap` already logs `prod_config_incomplete` at
startup naming `INVENTORY_ENC_KEY`. Apply the secret with
`docker compose up -d`, never `restart` — `restart` reuses the container and
keeps the old `env_file` values.

See also `docs/runbooks/rotate-secrets.md`.

## The Caddy access-log redaction must be deployed

`infra/caddy/Caddyfile.prod` deletes `X-Merchant-Signature` and
`X-Merchant-Key` from the access log in **both** site blocks that keep one —
`yupay.uz` and `api.yupay.uz`. Only the second can ever see a merchant
request; the first carries the same filter so a copied log block cannot
reintroduce the leak. Caddy
redacts `Authorization` and nothing else, so without that filter every signed
request writes its credentials verbatim to stdout, promtail ships them to Loki,
and anyone with Loki read access can replay a captured request for the
remainder of its ±300 s window.

**Confirm it is live before the first merchant sends a real signature:**

```bash
docker compose -f docker-compose.prod.yml exec caddy \
  grep -c 'X-Merchant-Signature delete' /etc/caddy/Caddyfile
# 2 — one per site block that keeps an access log (yupay.uz and api.yupay.uz).
# 0 means the container is running an older file: force-recreate, below.

# Then make one signed request and confirm nothing leaked:
docker compose -f docker-compose.prod.yml logs --since 5m caddy \
  | grep -c 'X-Merchant-Signature'   # must be 0
```

**Editing `Caddyfile.prod` on the host needs `up -d --force-recreate caddy`.**
It is a single-file bind mount and `git checkout` swaps the inode out from
under the running process, so `caddy reload` re-reads the stale one and you
will believe you have deployed a change you have not:

```bash
docker compose -f docker-compose.prod.yml up -d --force-recreate caddy
```

## The merchant channel is always asynchronous

`POST /merchant/v1/orders` forces the fulfilment queue on at the call site,
whatever `FULFILMENT_ASYNC` is set to (ADR-0069 §6, and
`docs/runbooks/fulfillment-queue.md` for the queue itself).

Two consequences for whoever is on call:

- **It depends on the worker being up, always** — not only after the flag is
  flipped. A stalled worker shows as merchant orders sitting in `fulfilling`
  with the deposit correctly debited: nothing is lost, nothing needs
  reconstructing, and nothing is delivered either.
- **Turning `FULFILMENT_ASYNC` off does not return merchant orders to inline
  fulfilment**, and must never be attempted as a way to do so. That is the
  whole point of the call-site override: inline, a supplier purchase would sit
  inside the transaction that debits the deposit.

## Outgoing webhooks: the auto-disable, and turning one back on

The worker drains `merchant_webhook_deliveries` on a second LISTEN channel
(`merchant_webhook_queue`) beside the fulfilment queue, so **a stalled worker
means no webhooks** as well as no fulfilment. Nothing is lost while it is
down: rows stay `pending` and are claimed when it comes back.

**What auto-disable looks like.** After
`MERCHANT_WEBHOOK_DISABLE_AFTER_FAILURES` (default 20) consecutive failed
_attempts_ — retries count — `merchant_webhooks.disabled_at` is set and every
`merchant_users` operator gets one email. One per disable, never one per
attempt. In Loki:

```
merchant_webhook.auto_disabled     merchant_id=… failures=… error=…
merchant_webhook.attempt_failed    delivery_id=… status_code=… outcome=…
```

**The only way back on** is `PUT /api/v1/admin/merchants/{id}/webhook` with the
URL (the same one, or a corrected one). It clears `disabled_at` **and** the
streak, does not rotate the secret, and the queued backlog resumes from where
it stopped. There is deliberately no second re-enable path — do not clear
`disabled_at` by hand in SQL, because the streak would stay at its ceiling and
the very next failure would disable the hook again.

Two things "the backlog resumes" does not mean, and the merchant will ask about
both:

- **Events that happened while the hook was off were never queued.** The
  producer writes nothing for a disabled hook, so re-enabling releases what was
  waiting when it went off and nothing after that. Tell them to reconcile the
  gap by polling the order read; there is no backfill.
- **A queued row keeps the URL it was queued with.** `url` is snapshotted at
  enqueue so the log can say which host answered, which means re-`PUT`ting a
  _corrected_ address does not re-aim the rows already waiting: they will be
  attempted against the old host and fail out. If the endpoint moved, expect the
  backlog to die rather than arrive, and replay what matters (below) so the new
  address gets it.

A backlog also has **no expiry**: rows stay `pending` forever if a merchant
never comes back, so a hook re-enabled after a week delivers a week-old `paid`.
That is a deliberate omission (M4's cabinet is where "discard the backlog"
belongs) and worth checking before you re-enable a long-dead hook:

```sql
-- what a re-enable would release, for one merchant
SELECT event_type, status, count(*), min(created_at) AS oldest
FROM merchant_webhook_deliveries
WHERE merchant_id = '<merchant-id>' AND status = 'pending'
GROUP BY 1, 2;
```

**Reading the delivery log.** One row per event in
`merchant_webhook_deliveries`: `status`, `attempts_count`, `next_attempt_at`,
their `response_code` and the first 2 KB of their `response_body`, plus our own
`last_error`.

```sql
-- "did merchant X hear about order Y, and what did their server say?"
SELECT id, event_type, status, attempts_count, next_attempt_at,
       response_code, last_error, left(response_body, 200) AS body, created_at
FROM merchant_webhook_deliveries
WHERE merchant_id = '<merchant-id>'
  AND payload ->> 'order_id' = '<order-id>'
ORDER BY created_at;
```

There is **no index for that predicate** — the order id lives inside `payload`
JSONB and `(merchant_id, created_at DESC)` is what narrows it. Fine at our
volume, a known limitation for M4's screen; always keep the `merchant_id` on
the query.

```sql
-- queue health, all merchants. There are no metrics for this yet.
SELECT status, count(*), min(next_attempt_at) AS next_due
FROM merchant_webhook_deliveries GROUP BY 1;
```

A growing `pending` count whose `next_due` is in the past means nobody is
draining — check the worker, not the merchants (`worker.consumer.queue_loop_died`
and `docs/runbooks/fulfillment-queue.md`).

Three answers that surprise people:

- `last_error` starting `AddressNotAllowedError` / `UrlNotAllowedError` means
  **we** refused to connect — their hostname resolved to a private or loopback
  address at send time. It is terminal for that row (the row carries a URL
  snapshot), and the fix is on their side plus a re-`PUT`.
- `ResponseTooLargeError` / `ContentEncodingNotAllowedError` mean their server
  **received** the webhook and answered unusably — over 64 KB, or compressed
  when we asked for `identity`. Terminal by design: retrying would deliver a
  second copy of an event they already have. A merchant whose server gzips
  unconditionally will see every delivery fail this way.
- `OutboundBrokenError` is **ours**, not theirs. It never counts toward the
  failure streak and never disables a hook; treat one as a bug report.

**Replaying a failed delivery.** There is no endpoint and no admin screen for
this; it is a deliberate SQL edit on one row, and the drain picks it up on the
next tick (≤ `FULFILMENT_POLL_SECONDS`, default 5 — no NOTIFY needed).

```sql
-- one row, by id, after you have read it and know why it failed
UPDATE merchant_webhook_deliveries
   SET status = 'pending', attempts_count = 0, next_attempt_at = now(),
       last_error = NULL, response_code = NULL, response_body = NULL
 WHERE id = '<delivery-id>' AND status = 'failed';
```

Five things to check before you run it:

- **the hook must be enabled.** A disabled hook's rows are not claimed, so this
  does nothing until `disabled_at` is cleared by a `PUT`.
- **it re-sends the row's own `url` snapshot**, not the currently configured
  address. If the URL was the problem, the fix is a `PUT` _and_ then this — and
  it still goes to the old host, so for a moved endpoint the honest answer is to
  tell the merchant to fetch the affected orders over the API instead.
- **the payload is whatever was queued**, including a `status` the order has
  since moved past. Replaying an old `paid` after a `delivered` is exactly the
  out-of-order case the contract tells receivers to handle, but do not create it
  casually.
- **`attempts_count = 0` restarts the ten-attempt budget.** Leave it alone if
  you want the row to get one more try and then die.
- **never replay a `delivered` row.** It re-delivers an event they processed;
  the delivery id is unchanged, so a receiver that dedupes correctly ignores it,
  and one that does not double-provisions.

Replaying a **batch** (say, everything that crashed while `INVENTORY_ENC_KEY`
was wrong) is the same statement scoped by `last_error LIKE 'CryptoError%'` and
a time window. Count first, and cap it — every released row is an HTTP call to
somebody's production server.

**Not yet verified on real infrastructure** (M3a): every test is loopback or
stubbed, so the first TLS handshake to a real merchant endpoint happens in
staging. Two questions only a staging run answers, and they go together:

- **`AI_ADDRCONFIG` plus the client's no-fallback address pin.**
  glibc-in-container has known quirks (loopback does not count as a
  "configured" address), so confirm a real dual-stack merchant host is actually
  deliverable from the prod worker before a pilot integrates. There is also no
  fallback across a host's other addresses: we pin the first answer, so a
  merchant whose first public address is down fails every attempt until their
  DNS changes.
- **A real SIGTERM.** The worker's shutdown budget is 8 s because Docker's
  **default** `stop_grace_period` is 10 s and neither compose file overrides it
  for `worker` — raising the budget means setting that first, in both files.
  The 8 s is measured against a stuck fake drain, never against a container stop
  with a live Postgres and a real G2B pool.

**Before the deploy: check the DB pool.** The worker now drains two queues from
one connection pool, so its peak is `FULFILMENT_CONCURRENCY +
MERCHANT_WEBHOOK_CONCURRENCY` sessions — **4 + 2** at the defaults, where it
used to be 4. Nobody has checked that against the configured pool size on prod.
If it is short, the symptom is a **connection checkout timeout**, most visibly
on the fulfilment side, which looks nothing like a webhook problem.

**`worker.consumer.queue_loop_died` needs an alert rule** (outside this repo). A
dead queue loop takes the container down on purpose — `run()` exits `1`, so
`restart: unless-stopped` restarts it — but the exit code only helps if
something notices the restart loop. Until that alert exists, the queue-health
query above is the manual check.

**For whoever builds M4's cabinet:** `response_body` is text a merchant's own
server wrote, stored to 2048 characters and rendered on our screen. It is
never escaped on the way in. The auto-disable email is Russian-only, like every
other template in this module, so an English-speaking integrator gets a Russian
notice.

## `POST /merchant/v1/validate/player` keeps answering `error`

`error` on that endpoint means one thing only — **we could not check** — and it
is deliberately the same word for four different causes, because none of them
says anything about the player id and a reseller must not act on any of them as
if it did. Which one it is, in the order worth checking:

1. **The product has no active supplier mapping.** Check this one first: it is
   the likeliest, it is a routine state rather than an outage, and it is
   permanent until somebody fixes it. A product whose form declares
   `check: {provider: "g2b"}` needs an **active** `sku_supplier_mapping`
   (`supplier_slug='g2b'`, `kind='game'`) on one of its SKUs to resolve a game
   code from; without one, every check answers `error` forever. The g2b import
   queue ships the form field before the mapping, and a supplier switch
   deactivates mappings, so both directions happen. It logs
   `player_check_no_game_mapping` with the `product_id`.

   ```sql
   -- which of a brand's products declare a check but cannot resolve one
   SELECT p.slug,
          count(*) FILTER (WHERE m.is_active) AS active_g2b_game_mappings
   FROM products p
   JOIN brands b ON b.id = p.brand_id
   LEFT JOIN skus s ON s.product_id = p.id
   LEFT JOIN sku_supplier_mapping m
          ON m.sku_id = s.id AND m.supplier_slug = 'g2b' AND m.kind = 'game'
   WHERE b.slug = '<brand>'
     AND p.required_fields::text LIKE '%"provider": "g2b"%'
   GROUP BY p.slug
   ORDER BY 2, 1;
   ```

   Zero in the second column is the fault. Fix it by adding the mapping, or by
   dropping the `check` descriptor from the product's form — an honest
   `unsupported` beats a permanent `error`.

2. **The supplier is unconfigured on this stack.** `G2B_API_KEY` (or
   `WAXPEER_API_KEY`) empty makes the adapter report itself unavailable and
   every check answers `error` with no outbound call at all. This is the one
   cause that logs **nothing at all** — now that cause 1 has its own line, an
   `error` with no `player_check*` line of any kind is this.
3. **The circuit is open.** Three consecutive counted failures open
   `breaker:g2b:player_check:open` for 30 s and every check in that window is
   short-circuited to `error`; the log line is
   `player_check_short_circuited`. It closes itself — the key simply expires
   and the next call runs for real (ADR-0059).
4. **The upstream is failing.** `player_check_failed` carries the game code and
   a truncated error, never the player id.
5. **The product is mapped to two G2B game codes.** A misconfiguration, not an
   outage: `player_check_ambiguous_game_code` names the product and the codes,
   and the check refuses rather than validating against the wrong region's game
   (ADR-0048). Fix the `sku_supplier_mapping` rows; region belongs to separate
   products.
6. **The supplier changed its wire format.**
   `player_check_unrecognised_verdict` means we got an HTTP 200 whose `valid`
   field we could not read — the field renamed, or a token we do not know. This
   is the one cause that is an emergency of a different kind: **before
   2026-09-08 it answered `invalid` instead**, i.e. it told every customer and
   every reseller that their perfectly good player id did not exist, with
   nothing in the logs reading as a fault (ADR-0031's 2026-09-08 amendment).
   The line lists the body's top-level keys. Compare them against
   `player_check._G2B_VERDICTS` and raise it with the supplier.

```bash
docker compose -f docker-compose.prod.yml logs --since 30m api \
  | grep -E 'player_check_(failed|short_circuited|ambiguous_game_code|no_game_mapping|unrecognised_verdict)'
```

**`unsupported` is not a fault** and needs no investigation: it means the SKU's
product declares no `check` on any field, which is true of every voucher and
gift-card SKU. Tell the merchant to order without a check.

**A `429` on this endpoint and nowhere else** is one of its two tighter
counters doing its job, and which one matters when you decide what to raise:

- `auth:ipguard:merchant-validate:{ip}`, ceiling `AUTH_IP_GUARD_BUCKET_MAX`
  (120) — per source address.
- `merchants:validate:{merchant_id}`, ceiling `MERCHANT_VALIDATE_RATE_MAX`
  (120) — per merchant account, and the one that actually bounds what a
  reseller can spend, since a multi-node egress pool holds one of the first
  kind per address.

Both against the prefix's 600, because this is the one endpoint that spends a
supplier's quota rather than ours (spec §12). A merchant checking once per
order is nowhere near either; one that trips them is validating in a loop.
Raise the supplier-side quota **before** either ceiling — they protect G2B's
rate limit, not our CPU.

```bash
docker compose -f docker-compose.prod.yml exec redis \
  redis-cli --scan --pattern 'merchants:validate:*'
```

Note that both counters, the 300 s result cache and the supplier breaker all
live in Redis and all fail **open**. A Redis outage therefore removes every one
of them at once: checks stop being throttled, stop being cached and stop being
short-circuited, and the supplier's own limiter is the only thing left. If
Redis is down and G2B starts 429ing us, that is the mechanism — do not go
looking for a change in reseller behaviour.

## A merchant order stuck in `fulfilling`

**Three** very different situations wear this status, and `failure_reason` on
`GET /merchant/v1/orders/{merchant_order_id}` is what separates them: in
progress, delayed on our side, and failed with money still out. A delivery
failure and a stall are both recorded below the order row, so the status alone
tells you only that the order was paid.

**Two things that used to be in this list are not, and both left by being
closed.** Since M3c Task 6 an order whose whole charge came back on its own is
`status: "failed"` within seconds, with
`failure_reason: "fulfillment_failed_refunded"`. Since M3c Task 4 the same is
true of a settlement **you** book: the credit closes the order in the same
transaction, so there is no longer a case where money is fully back and the
order still reads `fulfilling`. Both are under "A merchant order that closed
itself" below, both need nothing further from you, and both are out of the
five-minute stuck-order alert, which is what the changes were for.

**`failure_reason` is `null` — it is genuinely in progress, or the queue is
stalled.** Nothing is wrong with the order. Check queue depth and the worker
(`docs/runbooks/fulfillment-queue.md`); a backlog can be entirely merchant
orders even with the flag off.

**`failure_reason` is `fulfillment_delayed` — the delivery stopped on _our_
side and the order is still ours to finish.** Since M3b Task 4 it means a
fulfilment task went `failed` while the item it was fulfilling stayed open:
the task is in the admin inbox, the item is still `in_progress`, and the
storefront rule that hides this from a retail buyer is unchanged. **This one
is yours, not the merchant's** — they are told to keep polling and not to
refund their end customer, so nobody outside is waiting on a reply. Top the
supplier up and retry the task, or force-complete it if you delivered by hand;
either clears the value on its own, because it is derived from the task and
the item rather than stored. Find the supplier and the shortfall on the task,
never on the order read — the reseller is deliberately not told which supplier
we are short at.

**Query the shape, not the sentinel.** The predicate matches "task failed,
item still open", and a low supplier balance is the only thing that produces
it _today_ — but widening beyond `last_error = 'supplier_low_balance'` is the
entire reason it matches the shape, so a second soft failure added later would
publish "still coming" to a reseller while being invisible both to a
sentinel-filtered query and to the low-balance alert, which is also keyed on
that string. Two queries, and run the first:

```bash
# Every merchant stall, whatever caused it — this is what the reseller is
# reading. The `merchant_id IS NOT NULL` clause is not decoration: the stall
# shape is deliberately retail's rule too, so without it most rows here are
# storefront orders showing "обработка" to a buyer who has a support chat,
# and a B2B incident gets sized off a count that is mostly not B2B.
docker compose -f docker-compose.prod.yml exec postgres psql -U yupay_app -d yupay -c \
  "SELECT t.id, t.supplier, t.last_error, t.failed_at, o.merchant_id,
          o.idempotency_key AS merchant_order_id
     FROM fulfillment_tasks t
     JOIN order_items i ON i.id = t.order_item_id
     JOIN orders o ON o.id = t.order_id
    WHERE t.status = 'failed'
      AND i.fulfillment_state IN ('pending', 'reserved', 'in_progress')
      AND o.merchant_id IS NOT NULL
    ORDER BY t.failed_at DESC LIMIT 20;"

# The low-balance ones, with the numbers the alert quotes.
docker compose -f docker-compose.prod.yml exec postgres psql -U yupay_app -d yupay -c \
  "SELECT t.id, t.supplier, t.metadata->>'current_balance' AS balance,
          t.metadata->>'required' AS required, t.failed_at
     FROM fulfillment_tasks t
    WHERE t.status = 'failed' AND t.last_error = 'supplier_low_balance'
    ORDER BY t.failed_at DESC LIMIT 20;"
```

A row in the first query and not the second is a stall nothing alerted on —
treat it as an incident in its own right, not just as this order's problem.
The per-supplier low-balance alert fires on the first such task with a
15-minute Redis dedupe, so a 50-order backlog is one message, not fifty.

**`failure_reason` is `fulfillment_failed` — the delivery failed and nothing
will move the order on its own.** The order row stays `fulfilling` for good,
because only the item's `fulfillment_state` went `failed`; the status alone
would say "in progress" indefinitely. **Resolving this needs a human.** The
merchant is told that this value (and `fulfillment_failed_refunded`, and
`order_failed`) is terminal and to contact support quoting `order_id`, so by
the time you see it they have already stopped waiting.

Find the order:

```bash
docker compose -f docker-compose.prod.yml exec postgres psql -U yupay_app -d yupay -c \
  "SELECT o.id, o.idempotency_key AS merchant_order_id, o.status, o.created_at,
          i.unit_price_usd, i.fulfillment_state, i.sku_id
     FROM orders o JOIN order_items i ON i.order_id = o.id
    WHERE o.merchant_id = '<merchant-id>'
      AND o.idempotency_key = '<merchant_order_id>';"
```

Then either retry the fulfilment (the ordinary admin order tooling, same as a
retail order) or settle it — next section.

## A merchant order that closed itself

**`status` is `failed` and `failure_reason` is `fulfillment_failed_refunded` —
done, and nothing is owed.** What **every** automatic refund leaves behind: the
delivery failed, the whole charge is already back on the merchant's deposit
(posted by the drain within seconds), and since M3c Task 6 the order is closed
in the same transaction. **Since M3c Task 4 a settlement you booked yourself
leaves the same thing**, because the credit closes the order — see "Settling a
failed order by hand" below, which is now one step and not two. It needs **no
action at all** — the merchant has been told to refund their own end customer
and place a new order if they still want the goods. Do not retry it: that is
refused (`409 deposit_already_returned`) and the refusal is the point.

**`status` is `failed` and `failure_reason` is `order_failed` — also done, and
it means one of two things.** Either support closed the order by hand with
money still out (the usual case, and "contact support" is the right thing to
tell the merchant), or a settlement closed an order whose delivery had **not**
failed — a goodwill return on an order still in flight, which the admin card's
button offers because it gates on "unsettled merchant order" and not on
"failed". Tell them apart with `refunded_usd`: equal to `price_usd` is the
second, anything less is the first.

Three things follow from the closure that are worth knowing before you go
looking for them:

- **It is out of the stuck-order alert**, because `list_stuck_paid_orders`
  selects `paid`/`fulfilling`/`fulfilled`. That is the whole reason the status
  moves; there is no merchant-shaped exception anywhere in that query.
- **There is nothing left to close by hand**, and trying answers
  `409 cannot mark order failed in current status` — the order is already
  `failed`. In the SPA the "Отметить проблемным" button is simply not offered.
  If you need the fulfilment task tidied out of the inbox, cancel the **task**;
  that raises no alert on a square order.
- **The merchant was told by push**, not only by poll: the close emits
  `order.status_changed` with `status: "failed"` right after the
  `balance.credited` for the refund. Neither body carries `failure_reason`, so
  a reseller asking "why?" is reading the order endpoint, and the answer there
  is `fulfillment_failed_refunded`.

**A partial settlement does _not_ close the order**, and that asymmetry is
deliberate: a partial means a person here is mid-decision and the rest is still
owed, so it keeps `status: "fulfilling"`, `failure_reason:
"fulfillment_failed"`, and its place in the stuck-order alert until somebody
finishes it. Crediting the remainder closes it — which is why the order page's
own button is **hidden** on a partly settled order: it posts the whole charge
and would be refused every time. Finish a partial on the merchant's page, where
you type the amount.

## Settling a failed order by hand

**Check `refunded_usd` first — some failed orders now settle themselves.**
Since M3b Task 3 a supplier failure whose money came back to us posts the
refund automatically, within seconds of the failure, as a
`merchant_order_refund` row against the order. **Do not assume either case is
the common one — nobody has counted.** Almost every `g2b` failure from a call
that went out is `unknown` and refunds nothing, so this procedure is far from
dead; `g2b` also has four refusals that never reach a call and do auto-refund,
plus one rejection from a call that did (an invalid player id). See
"Known gaps" below. This procedure is for the rest:
a supplier that kept our money (`spent`), one we cannot get an answer out of
(`unknown` — every `g2b` rejection of a call that went out bar the
invalid-player one, and `gengine`
after a pay may have landed), and an automatic refund that could not post. Those raise a Telegram alert of their own; see "When the
automatic refund does not fire" below.

If the order has already been settled automatically, this procedure will
refuse you with `409 order_already_settled` rather than double-credit the
merchant. That is the guard working, not a problem to route around.

**There is no "close the order" step any more, and M3c Task 4 is why.** It used
to be step 1 and load-bearing: a settlement you booked left
`status: "fulfilling"` and `delivered_at IS NULL`, so `list_stuck_paid_orders`
kept returning it and the five-minute «Оплачен, но не выдан» alert kept firing
about money that was already back. The credit now closes the order itself, in
the same transaction, on the same rule the automatic refund uses — **only on a
full settlement**. So: credit, and you are done. A
`POST /admin/orders/{id}/fail` afterwards answers
`409 cannot mark order failed in current status`, because the order is already
`failed`; that refusal is the change working, not a problem.

**What the merchant reads afterwards is `fulfillment_failed_refunded`, not
`order_failed`.** That is new in M3c Task 6 and it is the better answer: the
precedence now puts "the whole charge is back" ahead of "support closed this",
so a fully settled order tells the reseller to refund their own customer and
stop chasing us. `order_failed` is what they see while anything is still
owed — nothing back, or only part of it — which is exactly when contacting
support is the right instruction. **One exception, and it is not a bug:** the
refunded value needs a **failed item**, so settling an order whose delivery had
not failed reads `order_failed` even at a full settlement. That is true — a
person ended it, nothing about the delivery did.

**For everything else, support settles it as a deposit credit that names the
order** — the `order_id` body field on the deposit-credit endpoint (M3b). Use
it. A credit without it is an ordinary top-up of the balance and is invisible
on the order it was meant to settle, which is what the merchant will be
looking at.

What an attributed credit does, so you can tell a merchant what to expect:

- it moves `balance_usd` on `GET /merchant/v1/me`;
- it appears on `GET /merchant/v1/transactions` as a `merchant_deposit_credit`
  row with a positive `amount_usd` **and their own `merchant_order_id`**, so
  the line reconciles against their books;
- it shows in that order's `refunded_usd` on
  `GET /merchant/v1/orders/{merchant_order_id}` — the field they will check
  first, and the one that read `"0.00"` forever before M3b.

It is still a **balance credit**, not a card reversal: money returns to their
prepaid deposit, never to a bank. Say that plainly.

The steps:

1. **Credit the deposit, naming the order**, for exactly what the order charged
   — the `unit_price_usd` from the query above, which is also `price_usd` on
   the merchant's own order read. `order_items.unit_price_usd` is
   `NUMERIC(20, 6)` so psql prints it as `1.060000`; send `1.06`. (Both are
   accepted — the amount is validated on significant decimals, and a merchant
   price is always a whole cent — but the two-decimal form is what the merchant
   sees and what your `note` should quote.)

   **Use the SPA, and prefer the order page.** Since M3c Task 4 the order's own
   screen carries a **Депозит мерчанта** card — what the order took from the
   deposit, what has come back, and one button that returns the charge. It
   fills the amount and the order id for you, mints one `Idempotency-Key` per
   opened confirmation, names the merchant, the amount and the order before
   anything posts, and says that the order will close. **If it fails with
   anything other than "already settled", the dialog stays open on purpose**:
   press again. That retry carries the _same_ key, so if the first request
   actually landed the ledger replays it instead of crediting twice — closing
   the dialog and starting over from the button mints a new key and would post
   a second credit. It is **hidden** in three cases —
   an order already square (nothing to do), a partly settled one (it posts the
   whole charge, which would be refused), and one whose delivery has not
   terminally failed. The last is a safety rule and not tidiness: settling a
   live order returns the money and **stops nothing**, so the drain can still
   deliver goods the reseller has already been paid back for. Nothing in the
   API refuses that — it predates the button — so if you ever need to settle a
   live order, do it on the merchant's page and **cancel the fulfilment task
   first**. Goodwill beyond the order's price is an unattributed credit, also
   on the merchant's page.

   **The merchant's page** still has the general form: its detail page → the
   deposit-credit form → the **ID заказа** field. It takes our order id, tells
   you so under the label, refuses anything that is not a UUID _before_ posting
   (the API's own refusal for a malformed id is a `404`, which reads as "no
   such order" and sends you hunting in the wrong place), names the order in
   the confirm dialog, and echoes back the order the ledger actually booked
   against. Or, by hand:

   ```bash
   curl -X POST "https://api.yupay.uz/api/v1/admin/merchants/<merchant-id>/deposit-credits" \
     -H "Authorization: Bearer <admin JWT>" \
     -H "Idempotency-Key: refund-<order-id>" \
     -H 'Content-Type: application/json' \
     -d '{"amount":"1.06","order_id":"<order-id>","note":"settlement for failed order <order-id> (<merchant_order_id>)"}'
   ```

   `order_id` is **our** order id — the `id` column from the query above, the
   same one the merchant sees as `order_id` on their order read — not their
   `merchant_order_id`. It must belong to the merchant you are crediting;
   anything else answers `404 order_not_found`, and so does a typo, so a 404
   here means "check the two ids against each other", never "that order is
   somebody else's".

   Leave the field empty for an ordinary prepayment (step 2 of onboarding):
   empty means "no order", not "attach it later" — **a posted attribution
   cannot be re-pointed**, by anyone, ever. That is the one thing to get right
   before you press the button rather than after.

   **Key it on the order id**, as above. That is what makes a retry after a
   timeout safe: the ledger replays by key, so the same
   `Idempotency-Key: refund-<order-id>` can never credit the same failed order
   twice, however many times you run it. The `note` still quotes both ids for
   the human reading the ledger.

   That convention is a habit, not an invariant — the key is whatever you
   type, and a fresh `uuidgen` credits again. Since M3b Task 3 the invariant
   is behind it: an attributed credit that would take the order past what it
   charged is refused with `409 order_already_settled`. If you see that, read
   the order's `refunded_usd` — somebody (or the drain) has already settled
   it.

   **Credit the whole charge in one go, or finish the job.** A credit for
   _part_ of it is accepted — deliberately, so you can settle in stages — and
   it puts the order in the one state that needs you most. From that moment
   three things are true. The merchant still reads `fulfillment_failed`, not
   `..._refunded`, because the label requires the whole amount. The automatic
   refund is refused for good — `AlreadySettledError`, on "something already
   came back". And **Retry and force-complete are refused too**: the guard is
   `deposit_already_returned` and it triggers on _any_ amount, not on a full
   one. One cent parks the order. The way out is forward, not back: credit the
   remainder as a second attributed credit under a **new** key — allowed right
   up to the charge — and the state resolves itself, the order included: since
   M3c Task 4 the credit that reaches the full charge is the one that closes
   it, whichever stage that is. There is no way to un-credit. The order page's
   button is hidden while a partial is outstanding, so the remainder is typed
   on the merchant's page.

   Read the response before you move on. The ledger replays **without
   comparing parameters**, so a key you have used before returns the original
   transaction and books nothing new — and the response's `amount` and
   `order_id` are that original transaction's, not what you just sent. If
   either disagrees with your request, you reused a key: nothing moved.

2. **Verify**, as the merchant will:

   ```bash
   docker compose -f docker-compose.prod.yml exec postgres psql -U yupay_app -d yupay -c \
     "SELECT kind, reference_type, reference_id, actor, created_at
        FROM wallet_transactions
       WHERE reference_type = 'order' AND reference_id = '<order-id>'
       ORDER BY created_at;"
   ```

   You want two rows: the `merchant_order_charge` and your
   `merchant_deposit_credit`, both referencing the order. One row means the
   credit was booked unattributed — it is not lost, it is on the balance, but
   `refunded_usd` will read `"0.00"`. There is no way to re-point a posted
   transaction; book the difference as a fresh, attributed credit only if the
   merchant was under-credited, and otherwise tell them where to find it.

   A `merchant_order_refund` row instead of your credit means the drain got
   there first — this is the automatic refund, `actor = fulfillment`. Nothing
   further is owed on that order.

   The SPA does this half for you at credit time: it prints the order the
   ledger booked against beside the new balance, and raises a red banner
   instead of a success toast when what came back is not what you sent.

3. **Tell the merchant**, quoting their `merchant_order_id`: the order is
   closed as `order_failed`, and the amount is back on their deposit balance —
   visible in `balance_usd`, on `/transactions` against that order, and in the
   order's own `refunded_usd`.

## Known gaps before a pilot integrates

One thing a reseller can meet on day one. It is not a bug in the sense of
"something broke"; it is an omission with a price, and the price is worth
knowing before it is paid. Two other gaps — the ±2% drift giveaway, and error
bodies that did not match the published contract — were closed in M2 and are
recorded at the end so a regression is recognisable.

### Only a supplier that gave our money back refunds automatically

_Why it is built this way, including the gaps below and the product question
the owner settled on 2026-09-09 (a cancelled order's debited deposit stays
with a human): [ADR-0071](../decisions/0071-merchant-refunds.md)._

M3b Task 3 posts the refund itself when the failed task's money outcome is
`returned`. `spent` and `unknown` never do — refunding money we did not get
back is not a safe failure mode — so those still reach a person through the
procedure above.

- **Cost of leaving it:** almost every `g2b` failure **from a call that went
  out** is `unknown`, because their API exposes no refund field and the only
  evidence is a sentence in their documentation (`fulfillment/README.md`). Its
  four **pre-call** refusals — no API key, an order line with no `player_id`, a
  mapping with no `external_variant_id`, no active mapping — are `returned`
  and do settle themselves, because nothing was ordered.
- **The one graded rejection (M3c).** A game create G2B answers with its own
  `HTTP 400 {"message":"Invalid player ID. Please check and try again.","success":false}`
  is `returned` and refunds the reseller within seconds. That rests on a
  **fourth** kind of evidence — their error string plus the owner's ruling of
  2026-09-09 that the balance is not debited for it — and the match is
  deliberately narrow: the status, their JSON envelope, and the **whole**
  message compared after case-folding and whitespace collapse. **Anything else
  from that call, including another 400 and including a reworded version of
  this one, is still `unknown`**, which is the design and not an oversight. If
  G2B rewords the message, these orders go back to parking — the manual lane
  they were in before M3c, which is the cheap way for this to fail. If you see
  a G2B rejection you believe is also free, it needs a ruling and a line here,
  not a looser match.
- **Tell the reseller to place a NEW order.** This is the operator-facing
  change and it is the opposite of what the old behaviour allowed. Before M3c
  the order parked on `unknown`, so once the reseller supplied a corrected
  player id an operator could **Retry** the task and deliver the same order.
  Now the deposit is returned within seconds, and a refunded order can never
  be re-driven: both Retry and Force-complete answer
  `409 deposit_already_returned`, because `charge_deposit` is idempotent on
  the order and a second charge would debit nothing (goods and money both).
  So the recovery is a new `merchant_order_id`, not a repair of this one. The
  merchant sees `refunded_usd` equal to what they were charged and
  `failure_reason: fulfillment_failed_refunded`, which says exactly that.
- **How big is the manual lane? Nobody knows.** Nothing counts merchant
  failures by supplier or by cause. Earlier drafts of this runbook and of
  ADR-0071 said it carried "most" of them; that was never measured and is
  withdrawn. If you need the number, it is a query away — and worth having
  before this gap is priced.
- **Fix:** evidence from G2B, not a softer default. A `returned` we cannot
  substantiate would refund a merchant for goods we paid for.
- **Second gap, smaller:** there is **no operator re-grade path**. An operator
  who chases a `spent` and gets our money back cannot record it, so that order
  will never refund automatically; it is settled by hand instead, which costs
  minutes and not money.

### When the automatic refund does not fire

Three Telegram alerts, all from the fulfilment saga:

- **«Заказ реселлера: депозит не вернётся сам»** (`merchant_money_outcome`) —
  the outcome was `spent` or `unknown`. Working as designed. Settle by hand if
  the merchant is owed, using the procedure above. Deduped per supplier per
  15 minutes, so one supplier outage is one message and the Fulfilment Inbox
  is where the rest of the parked orders are.
- **«Автовозврат депозита не прошёл»** (`merchant_refund_failed`) — the
  outcome _was_ `returned` and the posting failed anyway. Deduped per order
  for an hour, because each one is one reseller's money. The task still reads
  `returned`, so the order is still refundable by hand: settle it with the
  procedure above and file the alert text, which names the refusal.

  The refusals you can meet: `AlreadySettledError` (somebody credited the
  order first — if that was a **partial** settlement, the order still reads
  `fulfillment_failed` to the merchant and the rest is yours to finish),
  `MissingChargeError` (the order has no charge posting at all — that cannot
  happen through the code, so treat it as data damage and escalate), and a
  database error (retry the drain). The alert's log line carries
  `modelled=true` for those and `modelled=false` for a bug in our own refund
  code — the second is an engineering ticket, not a settlement.

  **`AlreadySettledError` no longer leaves the order open — M3c Task 4 closed
  that gap.** This alert means the automatic refund did not post because a
  person's credit got there first; that credit now closes the order itself when
  it completes the charge, so the order is already `failed` and already out of
  the stuck-order alert by the time you read this. Nothing to close. If the
  credit that beat the drain was a **partial**, the order is correctly still
  open and the remainder is yours to finish.

- **«Отменена задача по заказу реселлера»** (`merchant_order_cancelled`) — a
  merchant order's task was cancelled, by an admin or by an order/payment
  cascade, **and the order is not square against what it charged**
  (`refund.settled_in_full`, the same test `failure_reason` uses — not "has
  anything come back"). That second half is part of the trigger, not a caveat:
  tidying the dead task off an order the drain already refunded in full is
  ordinary housekeeping and raises nothing, so an alert you do see is one where
  money is genuinely still out — including a **partial** settlement, which is
  not square and therefore still alerts.
  **No automatic refund reaches this state and none ever will**: a
  cancellation is a decision a person made for a reason this code cannot read,
  and inferring "the supplier gave the money back" from it would be exactly
  the guess the money outcome exists to prevent. What it leaves behind is a
  debited deposit on an order nothing can move again — Retry and
  force-complete both refuse a `cancelled` task. Decide the money yourself and
  settle it with the procedure above; read `refunded_usd` first anyway, as
  that procedure says. Deduped per order for an hour.

**Do not click Retry on a refunded order.** It is refused with
`409 deposit_already_returned`, and the refusal is the point: a second charge
for one order replays its ledger key and debits nothing, so a successful retry
would hand the reseller the goods _and_ their money. If they still want the
order, they place a **new** one. The same refusal guards the force-complete
button.

### Closed in M2: the ±2% drift giveaway

`expected_price` within ±2% of our price used to execute at the **lower** of
the two, so a merchant could read the never-cached `/catalog` and always send
`current × 0.98` — a standing 2% off wholesale on **every** order, ~31% of the
margin at the default 7% markup, and not caught by the margin floor, which is
evaluated on our price before the drift rule and never re-checks what was
charged. The owner ruled on 2026-09-07: the band stays an accept/reject
tolerance and an in-band order is always charged **our** price
(`pricing.price_to_charge`, spec §8.4 as superseded, ADR-0069's amendment).

**Spotting a regression from the outside:** a merchant order whose
`order_items.unit_price_usd` is below the SKU's computed list price for that
merchant. Nothing alerts on it, so this is a query, not a monitor:

```sql
-- merchant orders charged under our own price. Expect zero rows.
SELECT o.id, o.merchant_id, oi.unit_price_usd, s.sku_code, oi.cost_usdt, s.b2b_markup_pct
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN skus s ON s.id = oi.sku_id
WHERE o.merchant_id IS NOT NULL
  AND oi.cost_usdt IS NOT NULL
  AND oi.unit_price_usd < CEIL(oi.cost_usdt * (1 + s.b2b_markup_pct / 100) * 100) / 100;
```

**Read the cost from `order_items`, not from `skus`.** `skus.cost_usdt` is
rewritten by `refresh_supplier_prices` every `price_refresh_interval_minutes`
(default 60), so a supplier raising one SKU's cost overnight would make every
past order of it look under-charged the next morning — and a cost that fell
would hide a real regression. `order_items.cost_usdt` is the frozen snapshot
taken at order time, and it exists for exactly this reason (see the column's
comment in `orders/models.py`). Merchant orders always populate it.

Two things the query still cannot see, so a hit is evidence and not a verdict:
a merchant with a negotiated `markup_adjustment_pp` prices below the computed
figure legitimately, and `b2b_markup_pct` is read live — a markup edited after
the order was placed moves the comparison. Neither is recorded at order time
and **M3b deliberately did not add a stored list price to fix it** (ADR-0071,
decision 10). The reason is worth knowing before somebody files it again: the
charge and the line already come from one number —
`merchants.orders.place` binds `quote.price_for`'s result once and hands it to
both — so a stored "our price" column would be filled from the same expression
this query compares against, and substituting it would turn the check into a
comparison of a value with itself. **What makes this query worth running is
that it recomputes from independent inputs.** Closing the two blind spots
properly means recording the markup that was actually applied, which nothing
does today.

**What M3b did record is the merchant's own quote** (migration 0072), and it
answers a different question the same section used to leave open — how far
resellers quote from our prices, which was previously unmeasurable because
`expected_price` survived only inside a request digest:

```sql
-- how far merchant quotes sit from what we charged. Not a regression check:
-- anything inside +/-2% is normal and is charged at our price by design.
SELECT o.merchant_id,
       count(*)                                                   AS orders,
       round(avg(oi.unit_price_usd - oi.merchant_expected_price_usd), 4) AS avg_gap_usd,
       count(*) FILTER (WHERE oi.merchant_expected_price_usd < oi.unit_price_usd) AS quoted_low
  FROM orders o
  JOIN order_items oi ON oi.order_id = o.id
 WHERE oi.merchant_expected_price_usd IS NOT NULL
 GROUP BY o.merchant_id
 ORDER BY orders DESC;
```

`merchant_expected_price_usd IS NOT NULL` is the whole filter it needs: retail
lines never carry one, and neither do merchant orders placed before 0072, so
the sweep is over exactly the rows that can answer. For a single disputed
charge, read the two columns off that order and quote both to the reseller.

### Closed in M2: the non-conforming validation bodies

`/merchant/v1` used to answer FastAPI's own `{"detail": [ … ]}` — no `type`,
no `code`, `application/json` — for anything the schema itself refused
(`?limit=0`, a malformed order body), while the module README published an RFC
7807 table. `core.errors.problem_json_validation_handler` now renders those as
`422` problem+json with `code: "invalid_request"`, and it is **scoped to the
`/merchant/v1` prefix**: every other path is delegated to FastAPI's own
handler, byte for byte.

That scoping is deliberate and must survive: the generated TypeScript client
types every operation in the repo from the `HTTPValidationError` schema, so
making the handler app-wide would make the client wrong everywhere without
moving the schema — and `openapi-drift` compares the schema to itself, so
nothing in CI would notice. If somebody "simplifies" it later, the test that
fails is
`test_outside_the_merchant_prefix_the_body_is_fastapis_own_byte_for_byte`.

**Spotting a regression from the outside:** a `422` from `/merchant/v1` whose
`content-type` is `application/json` rather than `application/problem+json`.
