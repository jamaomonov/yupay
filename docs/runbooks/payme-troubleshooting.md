# Runbook — Payme (Paycom) Merchant API troubleshooting

Payme (`checkout.paycom.uz` / `test.paycom.uz`) is the second Uzbek card
acquirer, behind the miniapp "Payme" method (provider slug `payme`). Unlike
Octo, Payme does not deliver a webhook to us — **we run a JSON-RPC server**
that Payme calls at `POST /api/v1/payments/payme/merchant` over the life of
each transaction. See [ADR-0034](../decisions/0034-payme-merchant-api.md) and
`apps/api/src/yupay/modules/payme/README.md` for the full method/error
reference.

## Quick checks

- **"Payme" is missing / disabled in the miniapp.** The gateway is
  `available` only when `PAYME_MERCHANT_ID` is set **and** either
  `PAYME_KEY` or `PAYME_TEST_KEY` is set. Confirm with
  `GET /api/v1/payments/providers` — `payme` should be in the list.
- **Config.** `PAYME_MERCHANT_ID`, `PAYME_KEY` (production/cabinet key),
  `PAYME_TEST_KEY` (sandbox key), `PAYME_LOGIN` (default `Paycom`),
  `PAYME_CHECKOUT_URL` (`https://checkout.paycom.uz` in production,
  `https://test.paycom.uz` in sandbox). Secrets live only in the env file;
  `PAYME_KEY`/`PAYME_TEST_KEY` are redacted from logs — never paste them into
  a ticket or chat.
- **The endpoint always answers HTTP 200.** A Payme-side "connection
  error"/500 report almost never means our route 500'd — it means Payme
  couldn't reach us at all (tunnel down, DNS, Caddy). Check the access log
  for the request first; if it's not there, it's a reachability problem, not
  an application error.

## Sandbox setup

1. Get a merchant registered in Payme's business cabinet and obtain the
   sandbox (test) key.
2. Point our endpoint at a publicly reachable host — a tunnel
   (cloudflared/ngrok) in dev, or the deployed staging host.
3. Set `PAYME_MERCHANT_ID` + `PAYME_TEST_KEY` in the env, and
   `PAYME_CHECKOUT_URL=https://test.paycom.uz`.
4. In the Payme cabinet (or the sandbox registration flow at
   `test.paycom.uz`), register the merchant's **Endpoint URL** as
   `https://<our-host>/api/v1/payments/payme/merchant` and the login/key as
   configured above (`PAYME_LOGIN`, default `Paycom`).
5. Run Payme's **automated sandbox test suite** from `test.paycom.uz` against
   that Endpoint URL. It exercises the same two sequences as
   `apps/api/tests/integration/test_payme_merchant.py`:
   - **Unconfirmed**: wrong auth (`-32504`) → invalid amount (`-31001`) →
     unknown account (`-31050`) → `CheckPerformTransaction` →
     `CreateTransaction` → `CancelTransaction` (state `1`→`-1`).
   - **Confirmed**: `CheckPerformTransaction` → `CreateTransaction` (order
     stays reserved) → `PerformTransaction` (order → `paid`, fulfilment
     starts) → `CancelTransaction` (state `2`→`-2`, refund reconciled).
6. All checks passing in the Payme cabinet is the sandbox-ready milestone —
   do not go live before this is green.

## Go-live switch

1. Obtain the **production** key from the Payme cabinet (`PAYME_KEY`).
2. Set `PAYME_CHECKOUT_URL=https://checkout.paycom.uz`.
3. Update the merchant's registered Endpoint URL in the cabinet to the
   production API host if it isn't already.
4. Leave `PAYME_TEST_KEY` configured — the endpoint accepts **either** key,
   so sandbox testing keeps working after go-live without a second endpoint
   or a code change.
5. Confirm the Caddy IP allowlist (below) is in place in production — it is
   not needed in dev/staging tunnels.

## Reading a stuck transaction

Every Payme transaction is one `payme_transactions` row, keyed by Payme's own
`payme_id` (not our internal `Payment.id`).

1. Find the transaction. There is no admin list endpoint for
   `payme_transactions` directly; cross-reference via the order or payment:
   ```
   GET /api/v1/admin/payments?order_id=<order_id>
   ```
   The `payme` payment's `external_id` is `payme:<order_id>`.
2. **Ask Payme directly** with `CheckTransaction` semantics — from the Payme
   cabinet's own transaction search (searchable by our order id, since
   `account.order_id` is what we handed Payme) — to see what Payme's side
   currently believes the state is. Our row and Payme's row should agree;
   if they don't, one of Payme's calls never reached us (see "reachability"
   above) or arrived and failed before it could write.
3. **`state` meanings**: `1` created (buyer hasn't finished paying on
   Payme's UI, or Payme hasn't called `PerformTransaction`/`CancelTransaction`
   yet), `2` performed (order should be `paid`), `-1` cancelled before
   performing (no money moved), `-2` cancelled after performing (a refund —
   the order should be `refunded`).
4. **Order stuck in `pending_payment` with a state-`1` transaction older than
   12h**: the timeout job (below) should have swept it. If it hasn't after
   several sweep intervals, check the scheduler logs for
   `payme_timeout.transaction_failed` with that transaction's id.

## The refund-via-cabinet flow

Payme's Merchant API has **no merchant-initiated refund call**. Refunds are
issued from the **Payme cabinet** by an operator; Payme then calls our
`CancelTransaction` on the performed transaction, and we auto-reconcile — the
order flips to `refunded` and the ledger is reversed through the same core an
admin refund uses (`_apply_refund_reversal`). Consequently:

- **The admin "Refund" button on a Payme payment returns 409.** This is
  intended, not a bug — the 409 message points the operator at the Payme
  cabinet. Do not attempt to work around it; there is no API path that would
  actually move money.
- **To refund a Payme order**: open the transaction in the Payme cabinet and
  issue the refund there. Payme calls `CancelTransaction` back to us within
  its own SLA; confirm the order reached `refunded` via
  `GET /api/v1/admin/payments/{payment_id}`.
- **`-31007` on a cabinet refund attempt** means Payme itself refused — the
  order (or one of its items) already shows a completed delivery on our end
  by the time Payme's `CancelTransaction` landed. This is the intended
  money-safety guard (see ADR-0034): a partially-fulfilled multi-item order
  where at least one item already shipped is never auto-refunded. Such a
  case needs a **manual** reconciliation — check what was actually delivered
  (`GET /api/v1/admin/fulfillment/tasks?order_id=<order_id>`) and settle the
  discrepancy by hand (partial admin refund of the undelivered portion, if
  applicable) rather than retrying the cabinet refund.

## The 12h timeout job

`apps/scheduler/src/yupay_scheduler/jobs/payme_timeout.py` runs every 5
minutes and cancels (state `1` → `-1`, `reason 4`) any transaction Payme
created but never followed up on (no `PerformTransaction`, no
`CancelTransaction`) for 12 hours (`TIMEOUT_MS = 43_200_000`). This is the
dead-letter case for a buyer who opened Payme's checkout and abandoned it.
Each stale row is re-checked `FOR UPDATE` immediately before writing, so a
concurrent Perform/Cancel call from Payme is never clobbered. Check
`payme_timeout.tick` log lines (checked/cancelled/failed counts) if orders
seem to be sitting past 12h without releasing.

## Caddy IP allowlist

`infra/caddy/Caddyfile.prod` restricts
`POST /api/v1/payments/payme/merchant` to Payme's documented source range
`185.234.113.0/28` (covers `.1`–`.15`) via `client_ip` (not `remote_ip` — the
shared edge proxy in front of this host rewrites `X-Forwarded-For`, so
`client_ip` is the one that resolves to Payme's real address). This is
**defense-in-depth alongside** the Basic-auth check (`-32504` in
`yupay.modules.payme.routes`) — it does not replace it. If sandbox testing
from a different network gets a bare `403` (not a JSON-RPC body at all),
that's this allowlist, not the application; it only applies in production —
dev/staging tunnels are not behind it.

## Error codes — what they mean to an operator

| Code     | Operator-facing meaning                                                                                         | Action                                                                                    |
| -------- | --------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `-31001` | Amount Payme sent doesn't match the order's price                                                               | Usually a stale checkout link (order price changed); ask the customer to restart checkout |
| `-31003` | Payme referenced a transaction id we don't have                                                                 | Check reachability — did an earlier `CreateTransaction` actually land?                    |
| `-31007` | Cancel/refund refused — order already (partially) delivered                                                     | See "refund-via-cabinet" above — needs manual reconciliation                              |
| `-31008` | Operation not valid for the transaction's current state (e.g. Perform on a cancelled tx)                        | Usually a client-side retry race; check `CheckTransaction` for the real state             |
| `-31050` | `account.order_id` doesn't match any order                                                                      | Checkout link/account was malformed or the order was deleted                              |
| `-31051` | Order isn't payable (already paid, or not in `pending_payment`)                                                 | Customer double-paid or reused a stale link; verify the order's actual status             |
| `-31099` | Order already has a different in-progress transaction (a second `CreateTransaction` with a new id)              | Payme mandates this account-range code for a busy order; check `CheckTransaction`/`GetStatement` for the live tx |
| `-32001` | `SetFiscalData` referenced an unknown transaction                                                               | Same as `-31003` — check reachability of the earlier calls                                |
| `-32300` | Payme sent something other than POST                                                                            | Should never happen from Payme itself; check for a stray health-checker                   |
| `-32400` | Unexpected internal error inside our handler                                                                    | Check API logs for `payme.merchant.internal_error` with a stack trace                     |
| `-32504` | Basic-auth credentials didn't match                                                                             | Confirm `PAYME_LOGIN`/`PAYME_KEY`/`PAYME_TEST_KEY` match what's registered in the cabinet |
| `-32600` | Malformed JSON-RPC envelope (missing/mistyped field)                                                            | Payme-side bug or a manual test request; check the raw body in the access log             |
| `-32601` | Unknown method name                                                                                             | Payme called a method we don't implement (see ADR-0034 "out of scope")                    |
| `-32700` | Request body wasn't valid JSON                                                                                  | Check for a proxy/tunnel mangling the body                                                |

## Fiscal data

`SetFiscalData` stores whatever Payme pushes (`fiscal_data`, keyed by
`PERFORM`/`CANCEL`) on the transaction row and acknowledges `success: true`.
YuPay does **not** generate its own fiscal receipt for Payme orders — Payme
fiscalizes on its own systems, which is the point of using Merchant API
instead of Subscribe API (ADR-0034). There is nothing to troubleshoot here
beyond confirming the transaction row's `fiscal_data` is non-empty after a
performed payment.
