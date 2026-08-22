# 0058. Customer wallet top-up (1:1, no FX)

- **Status**: Accepted
- **Date**: 2026-08-22
- **Deciders**: @jamaomonov
- **Tags**: backend | frontend | payments | wallet | security

## Context and problem statement

The mini app already has a wallet top-up form (`WalletTopUp`) and a spend path
(pay an order from `user_wallet`). Submit was a toast: "Пополнение скоро".
Customers cannot fund the balance themselves; ops credit by hand.

Catalog checkout cannot carry this. Variable-amount SKUs price USD→UZS through
the FX guard (ADR-0032). A deposit must be **1:1 in the acquirer's currency** —
50 000 UZS via Click becomes 50 000 UZS on `user_wallet`, never a rate.

Payments today require an `orders` row (`payments.order_id` NOT NULL). Every
Click / Payme / Uzum adapter takes that order. Decoupling payments from orders
would touch every gateway and webhook.

## Decision drivers

- Do not invent a second payment stack. Reuse `create_intent` +
  `settle_provider_payment`.
- Never convert FX on a deposit.
- Never accept `provider=wallet` (pay-from-balance to fund the same balance).
- Credit only after the acquirer settles, in the same DB transaction as
  `payment → succeeded`. Replay must not double-credit.
- A refund of a deposit must reverse `user_wallet`, not book
  `house_refunds / provider_clearing` (that would print money, same class of
  bug as ADR-0023).
- Customer order history stays product orders. Ops still see the funding row.

## Considered options

1. **Hidden catalog SKU** — reuse `POST /orders`. FX and GMV pollution.
2. **Nullable `payments.order_id`** — new payment purpose, change every adapter.
3. **Synthetic order `purpose=wallet_topup`**, no line items, amount copied
   onto `total_charged` in the provider's currency.

## Decision outcome

**Chosen option:** Option 3.

`POST /api/v1/wallet/topup` `{amount, provider}` (auth required,
`Idempotency-Key` required):

1. Reject `wallet`. Currency is derived from the provider, never from the
   client. Amount is quantized and clamped (UZS 10 000–5 000 000 whole so'm;
   USDT 5–500 at 0.01).
2. Insert `orders` with `purpose='wallet_topup'`, `items=[]`,
   `total_charged=amount`, `total_usd=0`, `currency` = provider currency.
3. Call existing `payments.create_intent`.

On `settle_provider_payment` / `_mark_payment_succeeded`:

```
D user_wallet:<user>                 amount   (balance ↑)
C provider_clearing:<provider>       amount
kind = topup
idempotency_key = topup:payment:{payment.id}
```

Then the order walks `paid → delivered` in the same transaction. Fulfilment
and `notify_order_delivered` are skipped (there is no SKU and no code).

Refund of a `wallet_topup` payment is the inverse, and only if the customer's
`user_wallet` still covers the amount:

```
C user_wallet:<user>                 amount   (balance ↓)
D provider_clearing:<provider>       amount
```

Insufficient balance → 409, ops alert. We do not overdraft.

`GET /orders` (customer) hides `purpose=wallet_topup`. `GET /orders/{id}` of
the owner's own funding row still works so the mini app can poll after Click.
Admin list shows them as «Пополнение кошелька».

### Positive consequences

- Click / Payme / Uzum / mock webhooks stay the single settlement chokepoint.
- Ledger stays double-entry; deposit and spend are opposite pairs.
- Mini app form is already the right UX; only the submit path changes.

### Negative consequences

- Funding rows live in `orders` (empty items, `total_usd=0`). Admin must
  read `purpose`.
- Click has no merchant-initiated refund today; the ledger branch is for
  mock, Payme cancel, and a future Click refund.
- USDT top-up waits on the `crypto` adapter being `available`.

## Validation

- Integration: mock settle credits once; replay does not double-credit;
  `provider=wallet` is 422; refund reverses; spent refund is 409; customer
  list omits the row.
- After production release: Bugbot + security-review on the live path.

## References

- [ADR-0004](./0004-double-entry-ledger.md)
- [ADR-0014](./0014-wallet-skeleton.md)
- [ADR-0023](./0023-wallet-refund-reversal.md)
- [ADR-0012](./0012-payments-skeleton-and-provider-stubs.md)
