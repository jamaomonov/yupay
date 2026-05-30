# 0023. Wallet-funded refunds reverse the original charge to the customer balance

- **Status**: Accepted
- **Date**: 2026-05-30
- **Deciders**: @jamaomonov
- **Tags**: payments | data

## Context and problem statement

`payments.service.refund_admin` is the single admin entry point for refunds. It
booked **one** ledger posting for every provider:

```
D house_refunds                 amount
C provider_clearing:<provider>  amount
```

That is correct for an **external** acquirer (card / Click / Payme / crypto):
the money physically leaves through the provider, so the refund is a house
expense (`house_refunds`) that the provider will settle against its clearing
account.

It is **wrong** for a **wallet** payment. When a customer pays from their
in-house wallet (`payments.gateways.wallet`), the original charge was a purely
internal movement:

```
C user_wallet:<user>        amount   (customer balance ↓)
D house_payments_received   amount
```

Refunding that with `D house_refunds / C provider_clearing:wallet` never touches
`user_wallet`, so the customer's balance is **not** restored and a fictitious
`provider_clearing:wallet` liability is created against a provider that does not
exist. Observed in production: an admin refunded a wallet-funded order and the
money never came back to the customer's balance.

## Decision drivers

- A refund of a wallet payment must put the money back where it came from — the
  customer's `user_wallet` balance — immediately and within the same DB
  transaction.
- The double-entry ledger invariant (`SUM(D) == SUM(C)` per currency, see
  [ADR-0004](./0004-double-entry-ledger.md)) must hold.
- No fake `provider_clearing:wallet` account: there is no external party to
  settle with for an in-house balance.
- External-provider refunds must keep working unchanged.

## Considered options

1. **Branch on `provider == "wallet"`** — reverse the exact original charge
   (`D user_wallet / C house_payments_received`); keep the
   `house_refunds / provider_clearing` posting for every other provider.
2. **Always credit `user_wallet`** regardless of provider — refund any payment
   to the wallet as store credit.
3. **Two postings for wallet** — book `house_refunds` *and* credit the wallet —
   to keep refund-expense reporting uniform across providers.

## Decision outcome

**Chosen option: Option 1.** For `provider == "wallet"`, `refund_admin` posts:

```
D user_wallet:<order.user_id>   amount   (customer balance ↑, NORMAL=D)
C house_payments_received       amount   (reverses the original receipt)
```

which is the exact inverse of the wallet `create_intent` posting. Every other
provider keeps the existing `D house_refunds / C provider_clearing:<provider>`
posting. The branch lives in `payments.service.refund_admin`; the wallet
gateway's `refund()` hook stays ledger-free (it has no `db` handle — it only
returns the inverse `external_refund_id` for the audit feed).

`payment.currency == order.currency` (set at `create_intent`) and the wallet
charge required `order.currency == wallet_currency`, so the refund account
currency is unambiguous. Partial refunds credit only the refunded slice and
leave the order in its terminal state; full refunds walk the order to
`refunded`. Idempotency key stays `refund:{payment.id}`.

### Positive consequences

- Wallet refunds actually restore the customer's balance, visible immediately in
  the miniapp (header pill + finance tab) once the wallet query is invalidated.
- `house_payments_received` nets to zero for a fully-refunded wallet order — an
  accurate "received then returned" trail rather than a phantom provider
  liability.
- External-provider accounting is untouched.

### Negative consequences

- `refund_admin` now has a provider-conditional ledger branch. Acceptable: the
  two postings are genuinely different accounting events, not a refactor smell.
- Refund-expense reporting is no longer uniform — wallet refunds don't hit
  `house_refunds`. That is correct (no expense was incurred; it was internal
  credit), but finance dashboards that sum `house_refunds` must remember wallet
  refunds are excluded by design.

## Validation

`apps/api/tests/integration/test_payments_wallet_gateway.py`:

- `test_wallet_full_refund_credits_user_wallet` — pay $5 from a $20 wallet, full
  refund → balance back to $20, order `refunded`, payment `refunded`.
- `test_wallet_partial_refund_credits_partial_amount` — $2 of $5 refunded →
  balance $17, payment `partially_refunded`, order stays `delivered`.

## Alternatives considered (detail)

### Option 2 — always credit the wallet

Turns every refund into store credit, removing the customer's ability to get
money back to their card. A product/policy decision we are not making here, and
it would mishandle external settlement. Rejected.

### Option 3 — two postings for wallet

Crediting the wallet *and* booking `house_refunds` double-counts: it records an
expense that never happened and unbalances the "received" bucket. Rejected in
favour of the clean inverse.

## References

- [ADR-0004](./0004-double-entry-ledger.md) — double-entry ledger model
- [ADR-0012](./0012-payments-skeleton-and-provider-stubs.md) — payment gateway abstraction
- [ADR-0014](./0014-wallet-skeleton.md) — wallet skeleton (`NORMAL_SIDE`, `post()`)
- `docs/runbooks/wallet-refunds.md`
