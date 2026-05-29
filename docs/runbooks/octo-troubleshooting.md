# Runbook — Octo acquirer troubleshooting

Octo (`secure.octo.uz`) is the card acquirer behind the miniapp "Карта" method
(provider slug `octo`). Hosted payment page, one-stage (`auto_capture=true`).
See ADR-0020 and `apps/api/src/yupay/modules/payments/gateways/octo.py`.

## Quick checks

- **"Карта" is missing / disabled in the miniapp.** The gateway is
  `available` only when both `OCTO_SHOP_ID` and `OCTO_SECRET` are set. Confirm
  with `GET /api/v1/payments/providers` — `octo` should be in the list. Empty
  creds → it's hidden and the method auto-falls-back; this is intended.
- **Config.** `OCTO_SHOP_ID`, `OCTO_SECRET`, `OCTO_SIGNATURE_KEY`,
  `OCTO_BASE_URL` (`https://secure.octo.uz`), `OCTO_TEST_MODE`,
  `OCTO_REQUEST_TIMEOUT_SECONDS`. Secrets live only in the env file; never
  commit them.

## `create_intent` fails (409 "payment provider rejected the request")

The reason is passed through from the gateway:

- `octo error 2: Wrong secret` → `OCTO_SECRET` (or `OCTO_SHOP_ID`) is wrong.
- `octo does not support currency 'XXX'` → the order currency is not UZS/USD/RUB.
  Card payments should be UZS; check how the order was created.
- `octo network error` / `octo upstream error: HTTP 5xx` → Octo is down or
  unreachable; the client already retried. Retry the checkout later.
- `octo prepare_payment: missing octo_pay_url` → Octo returned `error:0` but an
  unexpected shape; capture the response and contact Octo support.

## Webhook not arriving / order stuck in `pending_payment`

Octo POSTs callbacks to `{BASE_URL}/api/v1/webhooks/payments/octo`.

1. **`BASE_URL` must be publicly reachable.** In dev, run a tunnel
   (cloudflared/ngrok) and set `BASE_URL` to the tunnel host. In prod it's
   `https://api.yupay.uz`.
2. **Check the audit feed.** Admin → payments/webhooks, or
   `GET /api/v1/admin/webhooks?provider=octo`. A row with `signature_ok=false`
   means the callback reached us but failed verification (see below). No row at
   all means it never arrived → tunnel / notify_url problem.
3. **Re-verify on Octo's side.** Octo's merchant dashboard shows the
   transaction status; if it's `succeeded` there but we have no webhook row,
   the callback didn't reach us.

## Webhook returns 422 (`signature_ok=false`)

`verify_webhook` recomputes `SHA1(unique_key + octo_payment_UUID + status)` and
compares to the callback's `signature` field.

- **`octo signature key not configured`** → `OCTO_SIGNATURE_KEY` is empty. This
  key (Octo's `unique_key`) is issued by Octo tech support, separately from the
  merchant secret. Until it's set, **prod rejects all callbacks by design** — we
  never trust an unsigned card-payment callback.
- **`signature mismatch`** → the configured `unique_key` doesn't match the one
  Octo signs with, or Octo changed the formula. Confirm the key with Octo
  support. Do NOT disable verification.

## Webhook returns 200 `{duplicate}`

Expected. Dedup key is `octo_payment_UUID:status`; Octo retries the same
terminal callback and we collapse replays. No action needed.

## Intermediate callbacks (`created` / `waiting_for_capture`)

Mapped to the `pending` outcome — recorded in the webhook audit row, no FSM
change. We wait for the terminal `succeeded` / `canceled` callback. No action
needed.

## Refunds

Admin → payment → Refund (`POST /api/v1/admin/payments/{id}/refund`). This calls
Octo `POST /refund` (partial supported) and books the
`D house_refunds / C provider_clearing:octo` ledger entry. If Octo rejects the
refund the admin action 409s with Octo's message and no ledger entry is made.

## Test mode

Set `OCTO_TEST_MODE=true` in dev — `prepare_payment` sends `test:true` so Octo
treats the charge as a test transaction. Combine with a tunnel so the signed
callback can reach the webhook.
