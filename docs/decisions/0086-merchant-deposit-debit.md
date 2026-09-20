# 0086 — Taking money off a merchant's deposit: an operator movement with a floor, a mandatory reason, and no webhook

- Status: accepted
- Date: 2026-09-20
- Predecessors: ADR-0068 (the deposit ledger and its two original movements),
  ADR-0069 (the machine API the balance is published on), ADR-0071 (the third
  movement — the automatic refund, whose module shape this one follows)

## Context

The deposit ledger shipped with two movements (ADR-0068) and gained a third in
M3b (ADR-0071). All three add money to a merchant's balance or spend it
against one of their own orders. **Nothing could take money off a balance for
any other reason.**

The gap surfaced on 2026-09-20: a live merchant had been funded for testing
and the owner wanted the remaining balance removed. There was no endpoint, no
service function, and no ledger movement that could express it. The only
routes available were to hand-write postings into production — bypassing
`wallet.service.post` and with it the double-entry invariant and
idempotency — or to leave the balance standing.

This is not an exotic case. A top-up credited to the wrong merchant, a test
account being cleaned up, a settlement agreed outside the system: each is an
operator holding a correct number in their head and a wrong number in the
ledger, with no way to close the gap.

## Decisions

### 1. It is a fourth ledger movement, not an edit

`C merchant_deposit / D house_payments_received`, posted through
`wallet.service.post` like the other three, in a new module `debit.py`
(`deposit.py` is past AGENTS.md's split point, and `refund.py` set the
precedent for where a movement goes when it does).

The rejected alternative was an admin "set balance to N" control. A balance is
a **derived sum** over postings, not a column — the README says so in its
first sentence — so "set" has no meaning that does not either write a
compensating posting anyway or corrupt the ledger. Expressing the correction
as what it actually is keeps `SUM(D) == SUM(C)` true and keeps the movement on
the merchant's own statement, where a reseller reconciling their account can
see it.

### 2. The floor is zero, enforced under a locked row

A debit may not take a deposit negative. A negative prepaid balance is a debt
we have no mechanism to collect, no endpoint that can explain it, and no
reseller-facing contract that describes it; `GET /merchant/v1/me` would simply
publish a minus sign.

The guard is `charge_deposit`'s, deliberately in the same shape and not a new
one: `SELECT … FOR UPDATE` on the account row, **then** read the balance. A
debit and a concurrent order charge therefore serialise instead of both
passing on the same pre-spend number. It answers `409 insufficient_deposit` —
the code the order path already publishes for "the deposit cannot cover
this" — rather than a new one, because it is the same fact.

### 3. `reason` is required; `order_id` is not accepted

Required, unlike the credit's optional `note`: a debit is the only movement
whose justification is **entirely outside the system**. A charge has its
order, a refund has its supplier outcome, a credit usually has a payment. A
debit has a person's intent and nothing else, so the ledger row is the only
place it can be recorded, and an operator who cannot name a reason is one who
should not be taking the money.

Not accepted, unlike the credit's `order_id`: `refunded_usd` is published to
the reseller as "how much of `price_usd` has come back". Attributing a debit
to an order would add to that sum money the merchant never received. A debit
is booked against the merchant (`reference_type: merchant`), and correcting an
order's settlement stays the credit's job.

While writing this, the metadata key turned out to be the same
writer/reader-disagreement shape ADR-0071's `ORDER_REFERENCE_TYPE` came back
to fix: `credit_deposit` wrote the literal `"note"` and `admin_routes` read
the literal `"note"`, unvalidated JSON on both sides. A debit writing
`"reason"` there would have moved the money and shown a blank line in the
audit trail, with nothing failing. Both sides now go through
`deposit.OPERATOR_NOTE_KEY`.

### 4. No webhook, and the merchant is not notified

A credit enqueues `balance.credited` (spec §10). A debit enqueues nothing.

There is no `balance.debited` in the published event set. Adding one would
deliver a third event type to receivers written against a table of two — and
the event set is a wire contract third parties implement against, not an
internal list. The movement is not hidden: it appears on
`/merchant/v1/transactions` with its own `kind` and a negative signed amount
the moment it posts, which is where a reseller reconciles a statement.

Be plain about the cost, because it is real: a reseller who only listens to
webhooks will not learn about the debit from us. That is accepted on the
grounds that the operator taking money off a balance is a person who can say
so directly, and that inventing an event unilaterally is the more expensive
mistake. Publishing `balance.debited` is a `/merchant/v2` decision.

### 5. A frozen merchant may be debited

The mirror of ADR-0068's rule that support can always credit a frozen
merchant. Freezing blocks orders, never the ledger — and an account under
review is exactly the one whose balance an operator is most likely to be
correcting.

## What this does not decide

- **Where the money goes afterwards.** The debit moves the balance to the
  house counter, which is bookkeeping, not a payout. Returning cash to a
  reseller happens outside the system and is not modelled.
- **Whether resellers should be notified.** Decision 4 declines to invent an
  event; it does not argue that the silence is right forever. A `v2` event set
  is the place to revisit it.
- **A self-serve withdrawal.** Nothing here reaches the cabinet: this is an
  admin-gated operator action, and a reseller-initiated withdrawal would need
  its own approval flow, limits and payout rail.
- **Bulk or scheduled debits.** One merchant, one amount, one reason, one key.

## Consequences

- The ledger gains a fourth `kind`, `merchant_deposit_debit`, published
  verbatim on the merchant's statement. `WalletTransaction.kind` is a free
  `String(48)`, so no migration is needed — but a reseller parsing `kind`
  against a closed set will meet a value they have not seen. The field was
  always open; this is the first time that has been exercised.
- `transactions.build` needed no change: the statement's signed amount comes
  from the posting's direction, so the debit reads as negative automatically.
  That is the payoff of ADR-0068's "no caller re-derives a direction".
- The admin surface gains one endpoint. The admin SPA has no control for it
  yet — the API is the surface today.
- Four ledger-key families now share one namespace, so their disjointness is
  pinned over all four at once in `tests/unit/test_merchant_debit_keys.py`
  rather than pairwise. `wallet.service.post` replays by key without comparing
  parameters, so a collision would return somebody else's transaction and call
  it a debit.

## References

- `apps/api/src/yupay/modules/merchants/debit.py` — the movement
- `apps/api/src/yupay/modules/merchants/README.md` — the posting table, which
  is authoritative for all four movements
- `docs/api/README.md` — the admin endpoint's contract
- ADR-0068, ADR-0071 — the ledger and the third movement
