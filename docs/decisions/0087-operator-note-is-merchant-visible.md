# 0087. The operator's note on a manual deposit movement is merchant-visible, from the write forward

- **Status**: Accepted
- **Date**: 2026-09-21
- **Deciders**: @jamaomonov
- **Tags**: backend | security

## Context and problem statement

Every movement on a reseller's prepaid deposit explains itself except two.
An order charge and a refund name an order — `order_id` and the reseller's
own `merchant_order_id` are both on the row, and the Заказы screen is one
click away. A **manual credit** and a **manual debit** name nothing: they
carry `reference_type: merchant`, by design, because attributing a debit to
an order would publish it on that order's `refunded_usd` as money the
merchant never got back (ADR-0086).

So `GET /merchant/v1/transactions` showed a reseller a bare signed number
against their own balance, with no way to find out why except to write to
us. The answer already existed: the admin form makes a reason **mandatory**
on a debit and optional on a credit, and it lands in
`wallet_transactions.metadata` under `deposit.OPERATOR_NOTE_KEY`. It simply
never left the admin panel.

The complication is that the admin form told operators the opposite, in as
many words: «(обязательно; **видно только нам**, попадёт в историю
депозита)». Notes were written under that promise. Production reads were
not available while this was decided, so what those notes say could not be
reviewed.

## Decision drivers

- A debit a reseller cannot explain is a support ticket we already wrote the
  answer to.
- A promise made in a form is a promise, even when the form is ours and the
  audience is one operator.
- `extra_metadata` is an unvalidated JSON blob shared by every writer on the
  ledger; anything published out of it must be published by name.

## Considered options

1. **Publish `OPERATOR_NOTE_KEY` for every row.** One line in the reader.
2. **Publish nothing; add a second, merchant-facing field to the forms.**
   Two texts per movement, and an operator who fills one of them.
3. **Publish only notes written after the promise changed**, flagged at the
   write.

## Decision outcome

**Chosen option: 3.** `MerchantTransactionOut` gains a `description` field,
and `transactions._operator_note` returns a note only when the row also
carries `deposit.NOTE_VISIBLE_KEY` — a boolean the two admin writers set as
they write. Rows booked before the flag existed have no flag and stay
internal forever. Both admin hints now say the text is read by the merchant.

The gate is a flag rather than a rule about the note key, so that the safe
answer is the default: a future writer that sets a note without the flag
publishes nothing, which is a missing feature rather than a leak.

### Positive consequences

- The question a debit provokes is answered on the screen that provokes it,
  in the API and in the statement CSV.
- The promise made to operators about existing notes is kept exactly, with
  no reliance on anyone's memory of what those notes say.
- One field is projected by name; the rest of `metadata` stays internal, so
  a key added later for our own bookkeeping is not published by accident.

### Negative consequences

- Two keys now describe one note, and an operator reading the ledger row in
  Postgres sees a flag whose absence means "old", not "hidden on purpose".
- Operators must write for an audience. The forms say so; nothing enforces
  it, and a note that names another merchant would now be readable by the
  wrong one. That is a training and wording matter, not a technical control.
- Notes already written stay invisible even where they would have helped,
  including the one debit on production at the time of writing.

## Validation

`tests/unit/test_merchant_statement_note.py` pins the gate directly —
flagged notes publish, unflagged ones do not, and a falsy or non-boolean
flag is not consent. Two integration tests in
`test_merchant_api_transactions.py` cover the field end to end. The decision
is wrong if an operator's note ever has to be retracted; the signal would be
a support request asking us to remove a line from a statement.

## References

- [ADR-0086](./0086-merchant-deposit-debit.md) — why a debit names no order
- `apps/api/src/yupay/modules/merchants/README.md` — the metadata axes
