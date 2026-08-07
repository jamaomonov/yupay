# 0045. Account suspension (ban / unban)

- **Status**: Accepted
- **Date**: 2026-08-07
- **Deciders**: @jamaomonov
- **Tags**: backend | frontend | security

## Context and problem statement

Support had no way to cut off an account. When a customer is running stolen
cards, farming promo codes, or abusing refunds, the only levers were deleting
the account (destroys order history we are legally required to keep) or waiting
for the acquirer to notice — which, per [ADR-0044](./0044-chargeback-evidence-capture.md),
ends with our payouts being debited and possibly the merchant agreement pulled.

## Decision drivers

- A ban must bite **immediately**. An access token lives 15 minutes; a control
  that leaves a suspended customer fully operational for the rest of that window
  is not a control — that is long enough to place several more orders.
- It must not be reversible by the customer. Logging out, logging back in, or
  refreshing the token cannot lift it.
- It must not be walkable around by simply not logging in. Guest checkout
  creates no user row, which is the obvious hole.
- It must not be able to lock us out of our own admin panel.
- The customer must be told what happened. A suspension that surfaces as "wrong
  email or password" sends them round the password-reset loop and lands in
  support anyway, at higher cost.

## Considered options

1. **A `banned` flag checked at login only** — cheapest, and wrong: it leaves the
   existing access token working for up to 15 minutes.
2. **A flag checked at login plus revoking every session on ban** — closes the
   window, but adds a second mechanism that must stay correct forever; miss one
   session-minting path and the ban silently leaks.
3. **A flag checked at the single dependency every authenticated request already
   passes through**, plus a refusal at session-open.

## Decision outcome

**Chosen option: 3.**

- `auth.current_user` — the one gate every authenticated route resolves through —
  raises on a banned account. That is what makes the ban immediate: a token
  minted seconds before the click stops working on the very next call, with no
  session bookkeeping to keep in sync.
- `auth._open_session` — the one function every login path _and_ refresh rotation
  converges on — refuses too. Not redundant with the above: handing a suspended
  account a token that dies on first use is a worse experience than a refusal,
  because nothing explains it.
- **`AccountSuspendedError` is 403, never 401.** Both frontends answer 401 by
  refreshing the session, so a 401 here would loop and then log the customer out
  with no explanation at all. Its own `type_uri` lets the storefront say what
  happened, following the `email-unverified` precedent.
- **Guest checkout under a banned account's email is refused.** Without it a ban
  is lifted by not logging in.
- **Two guards on the action itself**: an admin cannot ban themselves (the
  straightforward way to lose the only admin account), and cannot ban another
  admin (a dispute between two admins should be settled by a human in the
  database, not by whoever clicks first). The admin UI hides the control on an
  admin account rather than showing a button that only fails.
- **Two endpoints, `/ban` and `/unban`**, not one toggle taking a boolean: intent
  is explicit at the call site, and a replayed request cannot mean the opposite
  of what was intended.

### What a ban deliberately does NOT do

- **It does not stop the person, only the account.** Guest checkout from another
  email address still works. Closing that would need device or payment-instrument
  identity, which is the anti-fraud work ADR-0044's capture is groundwork for —
  not something a ban button can pretend to deliver.
- **It does not hide past orders.** A banned customer keeps read access to orders
  they already paid for, including delivered codes. Taking away goods already
  bought is a refund decision, not a moderation one, and conflating them invites
  chargebacks we would deserve.
- **It does not delete anything.** Deletion has its own flow (`users.deleted_at`
  plus the scrub job) with its own legal constraints.

## Positive consequences

- One enforcement point, so there is one place to audit and one place to break.
- `banned_at` is a timestamp and `banned_by` a foreign key, so "since when and by
  whom" is answerable without reading an audit log.

## Negative consequences

- Every authenticated request now reads one more column. It rides the existing
  user load, so no additional query — but the ban does depend on that load never
  being cached across requests.
- The email-based guest block only works for accounts that have an email at all.
  A Telegram-only account has none, so a person behind one can guest-checkout
  freely. Stated here rather than left to be discovered.

## Validation

Integration tests cover the walk-arounds, not just the happy path: a token minted
before the ban, a fresh login afterwards, guest checkout on the same address, an
admin banning themselves, and an admin banning another admin.

## References

- [ADR-0044](./0044-chargeback-evidence-capture.md) — the evidence capture this
  complements; a ban is the manual lever, that table is the future automatic one
- [ADR-0007](./0007-jwt-format-and-rotation.md) — the token/session model whose
  15-minute access window shapes this decision
