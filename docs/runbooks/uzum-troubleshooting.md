# Runbook — Uzum Bank Merchant API troubleshooting

Uzum Bank (`uzumbank.uz`) is the third Uzbek acquirer, behind the miniapp
"Uzum" method (provider slug `uzum`). Like Payme, Uzum does not deliver a
webhook to us — **we run five plain HTTP/JSON endpoints** that Uzum calls
over the life of each transaction, at `POST /api/v1/payments/uzum/{check,
create,confirm,reverse,status}`. Unlike Payme, **we** own the transaction
state machine — Uzum signals a replay with a dedicated error code rather
than expecting us to echo back its own protocol state. See
[ADR-0035](../decisions/0035-uzum-merchant-api.md) and
`apps/api/src/yupay/modules/uzum/README.md` for the full endpoint/error
reference.

## Quick checks

- **"Uzum" is missing / disabled in the miniapp.** The gateway is
  `available` only when `UZUM_SERVICE_ID` is set **and** either
  (`UZUM_LOGIN` + `UZUM_PASSWORD`) or (`UZUM_TEST_LOGIN` +
  `UZUM_TEST_PASSWORD`) are both set. Confirm with
  `GET /api/v1/payments/providers` — `uzum` should be in the list.
- **Config.** `UZUM_SERVICE_ID`, `UZUM_LOGIN`/`UZUM_PASSWORD` (production),
  `UZUM_TEST_LOGIN`/`UZUM_TEST_PASSWORD` (sandbox), `UZUM_OPEN_SERVICE_URL`
  (default `https://www.uzumbank.uz/open-service`). Secrets live only in the
  env file; `UZUM_PASSWORD`/`UZUM_TEST_PASSWORD` are redacted from logs —
  never paste them into a ticket or chat.
- **The endpoints always answer HTTP 200.** A Uzum-side "connection error"
  report almost never means our route 500'd — it means Uzum couldn't reach
  us at all (tunnel down, DNS, Caddy). Check the access log for the request
  first; if it's not there, it's a reachability problem, not an application
  error. Every outcome — success or business error — is rendered as
  `{"status": ..., ...}` or `{"status": "FAILED", "errorCode": ...}` at HTTP
  200; the only exception is a stray non-`POST` request, which is also
  answered `10003` at HTTP 200, never a 405.

## Sandbox setup

1. Generate a Basic `login`/`password` pair and a placeholder `serviceId`
   for the sandbox — for Uzum, unlike Payme, we generate these ourselves for
   testing (the production credential-issuance model is confirmed with Uzum
   separately; see ADR-0035's documentation-gaps list).
2. Point our endpoint at a publicly reachable host — a tunnel
   (cloudflared/ngrok) in dev, or the deployed staging host.
3. Set `UZUM_SERVICE_ID`, `UZUM_TEST_LOGIN`, `UZUM_TEST_PASSWORD` in the env.
4. Hand Uzum's integration engineer:
   - **Callback base URL:** `https://<our-host>/api/v1/payments/uzum`
     (endpoints `/check` `/create` `/confirm` `/reverse` `/status`).
   - **Basic auth** `login`/`password` (the sandbox pair from step 1).
   - **`serviceId`** (the placeholder from step 1).
   - **Postman collection** `docs/api/uzum.postman_collection.json` — all
     five endpoints, Basic auth pre-filled from `{{login}}`/`{{password}}`
     variables, example bodies.
5. Uzum's manual tester drives the sequence directly:
   `/check` → `/create` → `/confirm` (or `/reverse` before confirming) →
   `/status` to confirm the reported state. This exercises the same paths
   `apps/api/tests/integration/test_uzum_webhook.py` covers.
6. All checks passing is the sandbox-ready milestone — do not go live before
   this is confirmed with Uzum.

## Go-live switch

1. Obtain the **production** `login`/`password`/`serviceId` — confirm with
   Uzum whether they issue these or expect us to generate them (unresolved
   as of ADR-0035; do not assume either way without confirming).
2. Set `UZUM_LOGIN`/`UZUM_PASSWORD`/`UZUM_SERVICE_ID` to the production
   values.
3. Leave `UZUM_TEST_LOGIN`/`UZUM_TEST_PASSWORD` configured — the endpoint
   accepts **either** pair, so sandbox testing keeps working after go-live
   without a second endpoint or a code change.
4. The Caddy IP allowlist is **not yet active** (see below) — Uzum has not
   published webhook source IPs. Basic auth (`10001`) is the production gate
   until that range is confirmed and the commented-out block in
   `infra/caddy/Caddyfile.prod` is filled in.

## Reading a stuck transaction

Every Uzum transaction is one `uzum_transactions` row, keyed by Uzum's own
`trans_id` (not our internal `Payment.id`).

1. Find the transaction. There is no admin list endpoint for
   `uzum_transactions` directly; cross-reference via the order or payment:
   ```
   GET /api/v1/admin/payments?order_id=<order_id>
   ```
   The `uzum` payment's `external_id` is `uzum:<order_id>`.
2. **Ask Uzum directly** with a manual `/status` call (or Uzum's own
   transaction search) to see what Uzum's side currently believes the state
   is. Our row and Uzum's belief should agree; if they don't, one of Uzum's
   calls never reached us (see "reachability" above) or arrived and failed
   before it could write.
3. **`status` meanings**: `CREATED` (transaction registered, buyer hasn't
   finished paying in the Uzum app, or Uzum hasn't called `/confirm` or
   `/reverse` yet), `CONFIRMED` (order should be `paid`, fulfilment
   started), `REVERSED` (either cancelled before confirming — no money moved
   — or a refund after confirming — the order should show a ledger
   reversal), `FAILED` (the 30-min timeout swept it — no money was ever
   settled).
4. **Order stuck in `pending_payment` with a `CREATED` transaction older
   than 30 minutes**: the timeout job (below) should have swept it to
   `FAILED`. If it hasn't after several sweep intervals, check the scheduler
   logs for `uzum_timeout.transaction_failed` with that transaction's id.

## The `/status` reconciliation loop

Uzum's own retry contract: after a `/confirm` call that fails or times out
on Uzum's side, **Uzum retries `/status` up to 10 times** until we report a
terminal state. This is expected traffic, not a bug — do not "fix" repeated
`/status` calls for the same `trans_id` as abusive polling.

- Because `/confirm` settles the payment and writes `status: "CONFIRMED"`
  inside **one** DB transaction before the HTTP response is sent, a
  `CONFIRMED` row is durable the moment `/confirm` returns — a subsequent
  `/status` retry always reports it correctly. There is no window where
  `/confirm` "succeeded on our side" but `/status` still reports `CREATED`.
- If Uzum reports it never received a successful `/confirm` response but our
  side shows `CONFIRMED` (order `paid`, fulfilment started): the response
  was lost in transit (network blip, timeout on Uzum's end) after we
  committed. This is exactly the case the `/status` retries exist to
  reconcile — Uzum's own polling will pick up the `CONFIRMED` state on a
  later attempt. No manual action needed unless the retries have exhausted
  (check with Uzum's engineer how many attempts were actually made).
- If `/status` keeps reporting `CREATED` past 10 retries and 30 minutes
  elapse, the timeout sweep (below) will move it to `FAILED` on its own —
  Uzum's client-side retry loop and our sweep converge independently; no
  coordination between them is required.

## The 30-minute timeout job

`apps/scheduler/src/yupay_scheduler/jobs/uzum_timeout.py` runs every 5
minutes and fails (`CREATED` → `FAILED`) any transaction Uzum registered but
never confirmed or reversed for 30 minutes (`TIMEOUT_MS = 1_800_000`). This
is the dead-letter case for a buyer who opened the Uzum checkout and
abandoned it, or whose `/confirm` never arrived at all (contrast the
`/status` reconciliation above, which covers a `/confirm` that _did_ arrive
but whose response was lost). Each stale row is re-checked `FOR UPDATE`
immediately before writing, so a concurrent `/confirm`/`/reverse` call from
Uzum is never clobbered — only a still-`CREATED` row at write time is
touched.

**Log lines to watch:**

- `uzum_timeout.tick` — one per scheduler run, with `checked` / `failed` /
  `errored` counts. `checked: 0` most ticks is normal (no stale backlog);
  a persistently large `checked` count with a growing `errored` count
  means something is wrong with the sweep itself (DB connectivity, a bad
  row shape) and needs investigation.
- `uzum_timeout.transaction_failed` — one per row the sweep could not fail
  cleanly, with `transaction_id` and `error` (never account/key/PII). A
  transaction stuck past 30 minutes with no corresponding
  `transaction_failed` log line but also no `FAILED` status is a sign the
  scheduler process itself isn't running — check it's up before debugging
  individual rows.
- `uzum.merchant.internal_error` / `uzum.merchant.rollback_failed` — from
  the webhook routes, not the scheduler; logged whenever a webhook call hit
  an unexpected exception (rendered to Uzum as `99999` at HTTP 200
  regardless). Check these first if Uzum reports a transaction "stuck" in a
  way the timeout job wouldn't explain (e.g. a `/confirm` that should have
  succeeded).

**Money-safety invariant:** this job only ever fails a `CREATED` transaction
(payment still `pending`) — it never touches a `CONFIRMED` one. If you ever
see a `CONFIRMED` transaction move to `FAILED`, that is a bug, not expected
sweep behavior; escalate immediately rather than assuming it's the timeout
job's normal operation.

## Auth debugging (`10001`)

`10001` means the Basic-auth header didn't match either the production
(`UZUM_LOGIN`/`UZUM_PASSWORD`) or sandbox (`UZUM_TEST_LOGIN`/
`UZUM_TEST_PASSWORD`) pair — or one side of a pair is blank (a blank
login/password never matches, even against an equally blank request, so an
unconfigured acquirer rejects every request rather than silently accepting
empty credentials).

1. **Confirm what Uzum is actually sending.** The header must be
   `Authorization: Basic base64(login:password)` — a missing header, a
   non-`Basic` scheme, or malformed base64 all collapse to the same `10001`
   (never a more specific code, since revealing "your base64 was malformed"
   vs. "your credentials were wrong" would leak information to an
   unauthenticated caller).
2. **Confirm which pair should match.** If this is sandbox traffic, it
   should match `UZUM_TEST_LOGIN`/`UZUM_TEST_PASSWORD`; production traffic
   matches `UZUM_LOGIN`/`UZUM_PASSWORD`. Check both are actually set in the
   deployed env — a `10001` on every single call (not just malformed ones)
   usually means one side is still blank post-deploy.
3. **Never debug by logging the credentials.** `UZUM_PASSWORD`/
   `UZUM_TEST_PASSWORD` are redacted by the structured logger; verify by
   checking the env file directly (`make logs service=api` will show
   `[REDACTED]`, not the value) or with a config-value confirmation endpoint
   if one exists — never paste the raw secret into a ticket or chat.
4. **`10006` is a separate failure** — a valid auth pair but a `serviceId`
   that doesn't match `UZUM_SERVICE_ID`. Don't conflate the two: `10001`
   means "who are you", `10006` means "which service is this for".

## Error codes — what they mean to an operator

| Code    | Operator-facing meaning                                                                | Action                                                                                                                                    |
| ------- | -------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `10001` | Basic-auth credentials didn't match                                                    | See "Auth debugging" above                                                                                                                |
| `10002` | Request body wasn't valid JSON                                                         | Check for a proxy/tunnel mangling the body                                                                                                |
| `10003` | Uzum (or something else) sent a non-`POST` request                                     | Should never happen from Uzum itself; check for a stray health-checker                                                                    |
| `10005` | A required field was missing from the request                                          | Check the raw body in the access log against the expected shape for that endpoint                                                         |
| `10006` | `serviceId` didn't match `UZUM_SERVICE_ID`                                             | Confirm the configured `serviceId` matches what Uzum registered for this service                                                          |
| `10007` | `params.order_id` doesn't match any order                                              | Checkout link/params was malformed or the order was deleted                                                                               |
| `10008` | Order has already been paid                                                            | Customer double-paid or reused a stale link; verify the order's actual status                                                             |
| `10009` | Order isn't payable (cancelled, expired, refunded, or otherwise not `pending_payment`) | Verify the order's actual status; likely a stale checkout link                                                                            |
| `10010` | A transaction with this `transId` already exists                                       | Uzum's own replay signal — usually harmless (a retried `/create`); check `/status` for the existing row                                   |
| `10011` | Amount Uzum sent doesn't match the order's price                                       | Usually a stale checkout link (order price changed); ask the customer to restart checkout                                                 |
| `10012` | Amount below minimum                                                                   | Defined in the catalogue, not currently raised by our handlers (Uzum may enforce this itself — see ADR-0035)                              |
| `10013` | Amount exceeds maximum                                                                 | Defined in the catalogue, not currently raised by our handlers (Uzum may enforce this itself — see ADR-0035)                              |
| `10014` | Uzum referenced a `transId` we don't have                                              | Check reachability — did an earlier `/create` actually land?                                                                              |
| `10015` | `/confirm` on a `REVERSED`/`FAILED` transaction                                        | The transaction was already cancelled (manually or by the timeout sweep) before `/confirm` arrived                                        |
| `10016` | `/confirm` replay on an already-`CONFIRMED` transaction                                | Harmless — Uzum's own idempotency signal; confirm via `/status` that the order is `paid`                                                  |
| `10017` | `/reverse` refused — order already (partially) delivered                               | Needs **manual** reconciliation — check what was delivered (`GET /api/v1/admin/fulfillment/tasks?order_id=<order_id>`) and settle by hand |
| `10018` | `/reverse` replay on an already-`REVERSED` transaction                                 | Harmless — Uzum's own idempotency signal                                                                                                  |
| `99999` | Unexpected internal error inside our handler                                           | Check API logs for `uzum.merchant.internal_error` with a stack trace, keyed by `endpoint`                                                 |

## Fulfilment-delivered refund guard (`10017`)

`10017` on a `/reverse` call means Uzum tried to reverse a `CONFIRMED`
transaction whose order already has goods delivered — either the whole
order reached `fulfilled`/`delivered`, or a single `FulfillmentTask` on a
multi-item order already reached `succeeded` even though the order overall
is still `fulfilling`. This is the intended money-safety guard (see
ADR-0035): such an order is never auto-refunded. To resolve: check what was
actually delivered
(`GET /api/v1/admin/fulfillment/tasks?order_id=<order_id>`) and settle the
discrepancy by hand (a partial admin refund of the undelivered portion, if
applicable) rather than expecting Uzum's `/reverse` to succeed on retry — it
won't, until the underlying delivery state changes.
