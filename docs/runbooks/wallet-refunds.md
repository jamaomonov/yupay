# Runbook — refunding a wallet-funded order

When a customer paid for an order **from their YuPay wallet balance**
(`payment.provider == "wallet"`), an admin refund must return the money to that
same balance. This is handled automatically by
`payments.service.refund_admin` (see [ADR-0023](../decisions/0023-wallet-refund-reversal.md));
this runbook is for verifying it and triaging when a customer reports a
missing refund.

## How a wallet refund books

Original charge (at checkout):

```
C user_wallet:<user>        amount   (balance ↓)
D house_payments_received   amount
```

Refund (admin, full or partial) — the exact inverse:

```
D user_wallet:<user>        amount   (balance ↑)
C house_payments_received   amount
```

External providers (card / Click / Payme / crypto) instead book
`D house_refunds / C provider_clearing:<provider>` — money returns through the
acquirer, not the wallet.

## Issuing the refund

Admin UI → Payments → open the payment → **Refund** (full or partial). Or via
the API:

```sh
curl -X POST https://api.yupay.uz/api/v1/payments/admin/<payment_id>/refund \
  -H "Authorization: Bearer <admin_jwt>" \
  -H "Content-Type: application/json" \
  -d '{"amount": null, "reason": "customer request"}'   # amount=null → full refund
```

- Full refund (`amount` omitted/null or equal to the charge): payment →
  `refunded`, order → `refunded`.
- Partial refund (`amount` < charge): payment → `partially_refunded`, order
  **keeps** its current state (e.g. `delivered`). Partial refunds are an
  accounting concern, not an FSM transition.

## Symptom: "I refunded a wallet order but the balance didn't go up"

1. **Confirm it was a wallet payment.** In the admin payment detail, `provider`
   must be `wallet`. If it's an external provider, the money returns through the
   acquirer, not the balance — this runbook does not apply.
2. **Check the ledger transaction.** There must be a `payment.refund`
   transaction with `idempotency_key = refund:<payment_id>` whose legs are
   `D user_wallet / C house_payments_received`. If instead you see
   `D house_refunds / C provider_clearing:wallet`, the deployed code predates
   ADR-0023 — redeploy `main`.
3. **Check the customer is looking at the right currency.** The refund lands in
   the order's currency. A USD refund does not change a UZS balance row.
4. **Miniapp shows stale balance.** The header/finance views refresh on wallet
   query invalidation (after checkout, and when the order page observes a
   `refunded` status). A hard reload always reflects the ledger truth — if a
   reload shows the credited balance, it was only a client cache-staleness
   issue, not a ledger problem.

## Double refund / idempotency

`refund_admin` keys the ledger posting on `refund:<payment_id>`, so re-running a
refund for the same payment does not double-credit. The service also rejects a
refund once the payment is already fully `refunded`. Cumulative partial refunds
beyond the original amount are rejected by the `amount > payment.amount` guard;
the skeleton does not track cumulative partials across calls (one partial per
payment) — add a `payment_refunds` ledger table if that's needed.

## Verify after a refund

```sh
# Balance restored (full refund of a $5 charge from a $20 wallet → $20):
curl -s https://api.yupay.uz/api/v1/wallet -H "Authorization: Bearer <user_jwt>"
# Order status:
curl -s https://api.yupay.uz/api/v1/orders/<order_id> -H "Authorization: Bearer <user_jwt>"
```
