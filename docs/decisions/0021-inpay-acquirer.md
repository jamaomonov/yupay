# 0021. InPay (inpay.uz) card acquirer integration

- **Status**: Accepted
- **Date**: 2026-05-29
- **Deciders**: @jamaomonov
- **Tags**: backend | payments | integrations

## Context and problem statement

Following Octo (ADR-0020), we add a second real UZS card acquirer, **InPay**
(`inpay.uz`), an aggregator that fronts Click, Payme, Uzcard and Humo on one
hosted checkout. It plugs into the same `PaymentGateway` machinery. Two traits
differ from Octo and shape the design:

1. **Two-step auth.** A short-lived (24h) bearer token is obtained from
   `GET /authorization` (merchant_id + merchant_token) and then used on
   `POST /create`.
2. **Unsigned callbacks.** InPay's webhook carries no signature/HMAC, so the
   body cannot be trusted on its own.

## Decision drivers

- Reuse the existing payments service, FSM, dedup and the generic
  `/webhooks/payments/{provider}` route — no service changes.
- Authenticate inbound callbacks despite the missing signature.
- Keep secrets out of logs.

## Decision

### One adapter, hosted checkout

`payments/gateways/inpay.py` holds `InpayClient` (httpx) and `InpayGateway`.
`create_intent`: validate currency is **UZS** (InPay charges in so'm only, no
currency field) and amount ≥ **1000 so'm**; ensure a bearer token; `POST /create`
→ `order_id` (our `Payment.external_id`) + `pay_url` (our `intent_url`).

### Bearer-token caching

The 24h token is cached on the singleton `InpayGateway` instance
(`_bearer` + `_bearer_exp`, ~23h TTL) and refreshed on expiry. Each worker
process authorizes at most ~once/day. No Redis dependency for v1.

### Unsigned callback → re-verify, don't trust

InPay does not sign callbacks. `verify_webhook` therefore reads only the
`order_id` from the body and **re-fetches the authoritative status** via
`GET /transactions?order_id=` before returning a `WebhookEvent`. A forged
callback for a real `order_id` cannot promote a payment unless InPay itself
reports `success`. This is the same "webhook is a signal, the API is the truth"
model used for G2B. Status mapping: `success → succeeded`, `failed → failed`,
`cancelled → cancelled`, `pending`/unknown → `pending` (the no-op outcome from
ADR-0020). Dedup key: `order_id:{verified_status}`.

### No refund API

InPay exposes only authorization/create/transactions. `refund` raises a clear
error instructing the operator to refund from the InPay dashboard; the admin
refund action surfaces it as a 409 rather than booking a false reversal.

### Surfacing

A dedicated **"InPay"** method in the miniapp (provider `inpay`, UZS), shown
alongside the existing "Карта" (Octo) method. Both are card acquirers; keeping
them as separate buttons lets ops run them in parallel. With no credentials a
gateway reports `available=false` and its button disappears automatically.

## Consequences

- Two card acquirers now coexist behind distinct slugs; checkout offers whichever
  is configured.
- InPay refunds are a manual, dashboard-side operation (documented in the runbook).
- The `pending` no-op outcome (added for Octo) is reused for InPay's
  re-verified intermediate statuses.

## Security

- `inpay_merchant_token` and the bearer token are in the structured-log redactor
  and are sent only in query/body/headers, never logged.
- Re-verification via `/transactions` is the authenticity control that replaces a
  webhook signature.
- InPay callbacks carry no card data (only amount/status/order_id/transaction_id).

## Alternatives considered

- **Trust the callback body** (no re-verify): rejected — unsigned, forgeable.
- **Secret-in-URL webhook route** (как у G2B): rejected — re-verification already
  authenticates, and the generic route keeps all acquirers uniform.
- **Reuse the "Карта" button** for InPay: rejected — the user wants both acquirers
  visible and selectable.

## References

- InPay docs: https://inpay.uz/api/ (authorization, create, transactions, callback)
- ADR-0020 (Octo acquirer), ADR-0012 (payments skeleton)
