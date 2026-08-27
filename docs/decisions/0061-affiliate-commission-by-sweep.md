# 0061. Accrue affiliate commission from a scheduled sweep, not at delivery

- **Status**: Accepted
- **Date**: 2026-08-27
- **Deciders**: @jamaomonov
- **Tags**: backend | payments

## Context and problem statement

The affiliate program pays a partner 1–2% of every delivered order placed by a
buyer attributed to them. Something has to notice that an order was delivered
and turn that into money in the partner's ledger accounts.

The obvious place is the transaction that marks the order delivered. It is
already open, it already knows the order, and the commission would appear in
the partner's panel instantly.

That transaction is also the end of the fulfilment path — the slowest path in
the system, and the one where a customer is sitting on an order page waiting
for a code. It already holds a database connection across supplier calls whose
worst case is measured in minutes (see the `idle_in_transaction_session_timeout`
of 600s set for exactly this reason).

## Decision drivers

- **A lost accrual is a partner's lost money.** Whatever we build must not have
  a failure mode that silently skips an order.
- **The fulfilment path must not get slower or more fragile.** It is the money
  path and the customer-visible latency path at once.
- **No reconciliation job.** Anything that needs a human to periodically check
  that the numbers add up will not get checked.
- **Freshness is nearly worthless here.** Commission is held for 14 days before
  a partner can withdraw it.

## Considered options

1. **Inline accrual** — post the commission inside the delivery transaction.
2. **Scheduled sweep** — a periodic job finds delivered, attributed orders with
   no commission row and accrues them.
3. **Dramatiq task** — enqueue an accrual job when an order is delivered.

## Decision outcome

**Chosen option:** the scheduled sweep, every 5 minutes, because it is the only
one of the three whose correctness does not depend on any single moment going
right.

`UNIQUE(order_id)` on `affiliate_commissions` makes the sweep idempotent by
construction, and the ledger posting is keyed off the commission row's own id,
so a retry replays rather than doubles. An order missed for any reason —
crash, deploy, timeout, a bug fixed later — is picked up by the next pass
without anyone noticing it was missed.

### Positive consequences

- No accrual can be lost, and none can be paid twice.
- The fulfilment path gains no work at all.
- A backlog (say, after the feature ships against existing delivered orders)
  drains on its own, in batches, with no migration or backfill script.
- The sweep can be run by hand against production to repair anything.
- The same job does maturation, so there is one place to look.

### Negative consequences

- Commission appears in the partner panel up to 5 minutes late. This costs
  nothing: a 14-day hold sits in front of withdrawal either way.
- The sweep scans for work even when there is none. The query is indexed and
  the tables are small; at 5-minute intervals this is negligible.
- The `except IntegrityError` branch that handles two sweeps racing is not
  covered by a test — the losing INSERT blocks on the unique index until the
  winner commits, so it cannot be interleaved inside one test without hanging.

## Validation

The design is correct if running the sweep twice over the same delivered order
produces exactly one commission row and one ledger posting. That is asserted
directly by `test_accrual_is_idempotent`.

Operationally: if `affiliate_commissions` ever holds two rows for one order, or
the sum of `partner_pending` and `partner_balance` for a partner disagrees with
the sum of their non-void commissions, this decision was implemented wrong.

## Alternatives considered (detail)

### Inline accrual in the delivery transaction

Instant, and atomic with the delivery itself — genuinely attractive.

Rejected because it couples the money path to affiliate logic and lengthens the
slowest transaction in the system. It also makes the affiliate module a
dependency of fulfilment, which inverts the direction those modules should
depend on each other, and it offers nothing to repair an order that was
delivered before the feature existed.

### Dramatiq task enqueued on delivery

Keeps the work off the request but delivers it promptly.

Rejected for now on two grounds. The worker has no actors at all yet —
fulfilment still runs inline in the request, per ADR-0013's open follow-through
— so this would be the first, for a non-urgent job. More importantly, an
enqueue that fails after the delivery transaction commits loses the accrual
silently, which is precisely the failure the sweep design does not have. Adding
an outbox to fix that is more machinery than the sweep is in total.

Worth revisiting only if commission ever needs to be visible in seconds, which
the hold period makes unlikely.

## References

- `docs/superpowers/specs/2026-08-27-affiliate-program-design.md`
- `apps/api/src/yupay/modules/affiliate/README.md`
- [ADR-0013](./0013-fulfillment-skeleton-and-provider-stubs.md) — the inline fulfilment saga this
  deliberately does not attach to
- [ADR-0029](./0029-promo-codes.md) — the posting shape copied here
