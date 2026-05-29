# Runbook — InPay acquirer troubleshooting

InPay (`inpay.uz`) is a UZS card aggregator behind the miniapp "InPay" method
(provider slug `inpay`). Two-step auth (24h bearer token), unsigned callbacks
re-verified via `/transactions`. See ADR-0021 and
`apps/api/src/yupay/modules/payments/gateways/inpay.py`.

## Quick checks

- **"InPay" missing / disabled in the miniapp.** The gateway is `available`
  only when both `INPAY_MERCHANT_ID` and `INPAY_MERCHANT_TOKEN` are set. Confirm
  with `GET /api/v1/payments/providers` — `inpay` should be listed.
- **Config.** `INPAY_MERCHANT_ID`, `INPAY_MERCHANT_TOKEN`, `INPAY_BASE_URL`
  (`https://inpay.uz/api/v1`), `INPAY_REQUEST_TIMEOUT_SECONDS`. Secrets live only
  in the env file.

## `create_intent` fails (409 "payment provider rejected the request")

- `inpay only charges in UZS` → the order currency isn't UZS. The "InPay" method
  charges UZS; ensure the order was created in UZS.
- `inpay minimum amount is 1000 UZS` → order total is below InPay's floor.
- `inpay error: ...` → InPay returned `success:false`; the message is passed
  through (bad token, etc.). Check `INPAY_MERCHANT_ID` / `INPAY_MERCHANT_TOKEN`.
- `inpay authorization: missing bearer_token` → the `/authorization` response was
  malformed; verify credentials and that the merchant is active.
- `inpay network error` / `inpay upstream error: HTTP 5xx` → InPay unreachable;
  the client already retried. Try again later.

## Order stuck in `pending_payment` after the customer paid

InPay POSTs callbacks to `{BASE_URL}/api/v1/webhooks/payments/inpay`.

1. **`BASE_URL` must be publicly reachable** (a tunnel in dev). If InPay can't
   reach us, no callback arrives.
2. **Check the audit feed** (`GET /api/v1/admin/webhooks?provider=inpay`). No row
   → callback never arrived (tunnel / callback_url). A row whose processing
   raised → see below.
3. **Re-verification is authoritative.** Even with a callback, we promote the
   payment only if `GET /transactions?order_id=` returns `success`. If InPay's
   own status is still `pending`, the order correctly stays awaiting payment —
   wait for the terminal callback or the customer to finish paying.

## Webhook returns 422

`verify_webhook` failed — usually the `/transactions` re-verify call failed
(network/5xx) or the body had no `order_id`. InPay retries on non-200. If it's a
transient `/transactions` outage, it self-heals on retry. Persistent failure →
check `INPAY_BASE_URL` and credentials (the re-verify call also needs the bearer
token).

## Webhook returns 200 `{duplicate}`

Expected. Dedup key is `order_id:{verified_status}`; replays collapse.

## Bearer token

Cached in-process for ~23h per worker. If you rotate the merchant token, restart
the api/worker so the cache is dropped (or wait out the TTL).

## Refunds

**InPay has no refund API.** The admin Refund action will 409 with
"InPay has no refund API — issue the refund from the InPay merchant dashboard".
Refund the customer manually in the InPay merchant cabinet; record it
out-of-band. (Internal ledger refund accounting for InPay is a future item.)
