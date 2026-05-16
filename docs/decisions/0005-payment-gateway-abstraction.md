# 0005. Payment gateway abstraction

- **Status**: Accepted
- **Date**: 2026-05-15
- **Deciders**: founding team
- **Tags**: backend, payments

## Context

YuPay must support Stripe and PayPal (international), YooKassa and Tinkoff/SBP (Russia),
Click, Payme, Uzum (Uzbekistan), and a USDT crypto acquirer. Each provider has its own
intent lifecycle, webhook signature scheme, currency support, and refund semantics. Coupling
business code to any specific provider would be ruinous.

## Decision

A `PaymentGateway` Python protocol defines the surface every provider implements:

```python
class PaymentGateway(Protocol):
    provider: str
    async def create_intent(self, order: OrderSnapshot, return_url: str) -> Intent: ...
    async def verify_webhook(self, headers: Mapping[str, str], body: bytes) -> WebhookEvent: ...
    async def refund(self, payment_id: str, amount: Money) -> RefundResult: ...
    def supported_currencies(self) -> set[str]: ...
```

Implementations live in `apps/api/src/yupay/modules/payments/gateways/<provider>.py`. They
are registered in a registry keyed by provider slug. Webhook routes
(`/webhooks/payments/{provider}`) load the matching gateway, call `verify_webhook` **before**
parsing the body, persist `(provider, external_event_id)` to `payment_webhooks` (unique
constraint = dedup), then emit a `payment.received` outbox event. Downstream consumers
update `payments` and emit `payment.succeeded` / `payment.failed`.

## Consequences

- Adding a new provider is a localised change (one new file + a registry entry + an ADR if
  the contract bends).
- Webhook signature verification is mandatory — gateways must reject bad signatures with
  400; we never 200-OK to "hide" forgeries.
- Sandbox tests against each provider run nightly, gated by secret presence.

## Alternatives considered

- **Direct integration per provider in business logic** — rejected: high coupling, painful
  rollout.
- **Adopting an aggregator** (e.g. one international, one Uzbek aggregator) — useful where
  feasible, but Uzbekistan's regulatory landscape requires direct relationships for now.

## References

- [ADR-0002](./0002-use-modular-monolith.md)
- [`docs/architecture/module-map.md`](../architecture/module-map.md)
