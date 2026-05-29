# 0020. Octo (octo.uz) card acquirer integration

- **Status**: Accepted
- **Date**: 2026-05-29
- **Deciders**: @jamaomonov
- **Tags**: backend | payments | integrations

## Context and problem statement

YuPay has a complete payments skeleton (ADR-0012): a `PaymentGateway`
protocol, a registry with a working `mock`, a synchronous `wallet`, and six
reserved stubs (`click`, `payme`, `uzum`, `yookassa`, `tinkoff`, `crypto`).
No real card acquirer was wired up. The business needs to accept real card
payments for the Uzbek market.

The chosen first acquirer is **Octo** (`secure.octo.uz`), an aggregator that
covers Uzcard, Humo and international bank cards behind one hosted payment
page. The integration must slot into the existing payments machinery without
reworking the order FSM, the webhook deduplication, or the refund ledger.

## Decision drivers

- **No FSM changes.** `payments.service._mark_payment_succeeded` stays the
  single point that moves an order to `paid`. Octo flows through it like any
  gateway.
- **Reuse the generic webhook.** Octo signs callbacks in the body, so it fits
  `POST /api/v1/webhooks/payments/{provider}` — no dedicated webhook route.
- **Test-first.** Real merchant credentials are not available yet; the adapter
  ships with `test` mode and is proven by respx contract tests + a testcontainers
  integration test.
- **Security.** Card-acquirer secrets and signatures must never leak into logs;
  callbacks must be authenticated before any state change.

## Decision

### One adapter, hosted one-stage page

`payments/gateways/octo.py` holds `OctoClient` (thin httpx wrapper) and
`OctoGateway` (implements `PaymentGateway`). We use the **one-stage** hosted
page (`auto_capture=true`): `POST /prepare_payment` returns `octo_pay_url`
(our `intent_url`) and `octo_payment_UUID` (our `Payment.external_id`); the
customer pays on Octo's page and is returned to `return_url`. Two-stage
auth/capture is out of scope — digital goods are fulfilled instantly, so a
hold-then-capture step adds no value.

`shop_transaction_id` is a fresh UUID per `prepare_payment` (a previous failed
attempt's id can't clash upstream); it is stored in `Payment.extra_metadata`.

### Currency

Octo accepts `UZS`, `USD`, `RUB`. The gateway validates `order.currency`
against that set and refuses otherwise. `order.total_charged` is already in the
order currency's **major units** (`orders.service`), so it is sent as-is
(quantized to 2 dp) — no minor-unit conversion. The miniapp routes the existing
"Карта" method to provider `octo` and labels it UZS.

### Webhook authenticity

Octo signs the callback body: `signature = SHA1(unique_key + octo_payment_UUID
+ status)`, where `unique_key` is a secret issued out-of-band by Octo support
(distinct from the merchant `octo_secret`). `verify_webhook` recomputes and
compares case-insensitively with `hmac.compare_digest`. An empty signature key
is a hard refusal — we never accept an unverifiable callback. Because the
signature covers `(uuid, status)` and the amount is taken from our own
`Payment` row (not the callback), signature verification alone is sufficient
authority for the status transition; we do not additionally re-poll status.

Dedup key: `external_event_id = "{octo_payment_UUID}:{status}"` — replays of
the same status collapse via the existing `(provider, external_event_id)`
unique constraint, while distinct statuses remain separate events.

### `WebhookOutcome` gains `pending`

Octo only calls back on a terminal status for one-stage payments, but does not
guarantee it. A signed-but-non-terminal callback (`created`,
`wait_user_action`, `waiting_for_capture`) must not 400 (which would make Octo
retry and pollute the audit feed with false `signature_ok=False` rows).
Therefore `WebhookOutcome` is extended with `"pending"`, and
`service.handle_webhook` records the audit row but performs no FSM transition
for it. `mock` and `wallet` never emit `pending`, so the change is backward
compatible.

### Refunds

`OctoGateway.refund` calls `POST /refund` (partial supported). The existing
`payments.service.refund_admin` already books the
`D house_refunds / C provider_clearing:octo` ledger entry and walks the order —
no payments-service change for refunds.

## Consequences

- Adding the next acquirer remains "implement `PaymentGateway` + register slug".
- The protocol now has a `pending` no-op outcome that future async acquirers can
  reuse for intermediate callbacks.
- Live end-to-end verification is deferred until Octo issues `octo_shop_id`,
  `octo_secret`, and `unique_key`; until then the gateway reports
  `available=False` and the "Карта" method is hidden automatically.

## Security

- `octo_secret` and `octo_signature_key` are in the structured-log redactor and
  are sent only in request bodies, which are never logged.
- The callback may carry a **masked** PAN + `rrn`; that lands only in the
  admin-only `PaymentWebhook.payload` audit row, never in INFO logs. Octo never
  sends a full PAN.
- SHA1 is mandated by Octo's signature scheme — used only to authenticate their
  callback, not to protect data at rest.

## Alternatives considered

- **Dedicated `/webhooks/octo/{secret}` route** (как у G2B): rejected — Octo
  signs in the body, so the generic signed-webhook path fits without a parallel
  stack.
- **Two-stage capture**: rejected for instant digital fulfilment.
- **A new `WebhookEvent` "ignore" exception** instead of the `pending` outcome:
  rejected — it would skip the audit row and is less explicit than a mapped
  outcome.

## References

- Octo docs: https://help.octo.uz (prepare_payment, notifications, refunds, statuses)
- ADR-0012 (payments skeleton), ADR-0004 (double-entry ledger)
