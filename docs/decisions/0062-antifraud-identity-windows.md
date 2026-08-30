# 0062. Identity windows on the order risk gate

- **Status**: Accepted
- **Date**: 2026-08-30
- **Deciders**: @jamaomonov
- **Tags**: backend | payments | security

## Context and problem statement

ADR-0047 holds any single order at or above `manual_review_threshold_usd` for
a human to look at before fulfilment. It worked, so the attackers adapted:
carders paying with stolen cards found the edge of the threshold and split
their volume into many orders priced under it, aimed at the most liquid goods
(Roblox vouchers, Telegram Stars). Measured on production over 14 days: one
buyer identity placed 10 Roblox orders averaging $18 ($180 through a $40 gate
that never fired); one IP produced 16 orders under 2 buyer identities; one
Telegram username received Stars from 7 orders across different buyers; and
browser-reported timezone separated the fraud on liquid brands almost
perfectly (roblox 15/19 delivered orders from non-Uzbek timezones vs.
mobile-legends 1/46). None of this is visible to a rule that looks at one
order at a time.

## Decision drivers

- The per-order threshold is a property of one order; the attack is a
  property of a _group_ of orders sharing an identity. The gate needs a way
  to see the group.
- Chargebacks land weeks later, by which point the goods are redeemed and
  resold — prevention has to happen between payment and fulfilment, which is
  exactly where the existing gate already sits.
- A control an attacker can explain to a lawyer beats one nobody on the team
  can explain to a customer whose order was held: legible, tunable rules over
  a black-box score.
- No new external dependency: no geo-IP database, no card-network fraud
  score, no third-party service with its own licence and false-positive
  profile to manage.

## Considered options

1. **Machine-learned risk score** — train a model on historical orders and
   hold above a probability cut-off.
2. **Geo-IP / ASN lookups** — flag orders whose IP resolves to a
   datacenter, VPN, or a country outside the usual customer base.
3. **Rule-based identity windows** — extend `orders/risk.py` with a handful
   of legible, env-tunable rules over trailing windows keyed on identities
   the order already carries.

## Decision outcome

**Chosen option: 3**, for four rules layered onto the existing amount gate,
none of them blocking a sale — only ever adding a hold:

- **Rolling sum** (`REASON_ROLLING_SUM`) — orders sharing an identity (buyer,
  IP, device, or delivery target) whose combined total over a trailing 24h or
  7d window reaches `risk_sum_24h_usd` / `risk_sum_7d_usd`. The direct
  counter to "many small orders instead of one large one."
- **Velocity** (`REASON_VELOCITY`) — orders sharing an identity whose count
  over 24h reaches `risk_velocity_24h`, regardless of amount: a burst of
  cheap orders is itself a signal.
- **Shared identity** (`REASON_SHARED_IDENTITY`) — one IP or device used by
  `risk_distinct_buyers_7d` or more distinct buyer identities within 7 days.
  Matched on IP/device only, not buyer or delivery target, because those two
  are what a resale ring rotates on purpose and a single physical actor
  cannot fake cheaply.
- **Geo mismatch** (`REASON_GEO_MISMATCH`) — a guest order touching a
  cash-equivalent brand (`risk_liquid_brands`) whose browser reports a
  timezone outside the storefront's home markets (`risk_home_timezones`).

Three decisions inside that shape a future maintainer might otherwise
second-guess:

**Rules, not a model.** Option 1 was rejected mainly for legibility, not
accuracy. An operator staring at a held order needs to read _why_ in one
sentence and be able to move a number in the environment if it is wrong —
a probability from a model trained on ~600 orders would be neither
trustworthy nor explainable, and there is no labelled fraud dataset to train
it on anyway.

**Browser timezone, not IP geolocation.** Option 2 was rejected because none
of the UZ acquirers in use (Click, Payme, Uzum) hand us a usable IP
enrichment, and buying a geo-IP/ASN database adds a licence, an update
cadence, and a new false-positive profile (VPNs, corporate NAT, mobile
carrier CGNAT) to manage forever. `client_hints.timezone`, already captured
by the `evidence` module (ADR-0044) for chargeback defence, separated the
measured attack almost perfectly at zero marginal cost — it is weak evidence
alone (a travelling customer is not a fraudster), which is exactly why it is
the last rule to fire and only fires alongside the other two conditions
(guest + liquid brand).

**Hold, never block.** Same philosophy as ADR-0047: the money is already
taken by the time any of these rules run. The only question left is whether
a human looks before the goods leave, and holding is reversible in one click
(`fulfillment.start_for_order`, unchanged) while an issued game code is not.
No new order status was introduced; the customer still sees "processing,"
which is what it honestly is.

**Threshold jitter on rule 1.** The attackers found $40 by probing, so the
effective per-order threshold is now randomized within `[0.6, 1.0) ×
manual_review_threshold_usd`, deterministically per order id (stable across
retries and tests, unguessable from outside). This turns a single edge a
prober can map into a fuzzy band whose floor is what they'd actually have to
stay under. Applied only to rule 1 — the window rules have no edge worth
probing, because the prober cannot see their counters.

### Positive consequences

- The split-order and shared-IP patterns measured on production are now
  caught without touching the amount threshold that guards ordinary
  large-but-legitimate sales.
- Every rule ships with its own env kill switch (`0` or empty disables it),
  so a false-positive storm at 3 a.m. is stoppable by env var and restart,
  not by revert and deploy.
- No new table, no new external dependency, no new order status. The
  release path an operator already uses for ADR-0047 holds is unchanged.

### Negative consequences

- Four more numbers for an operator to tune, and tuning happens by
  redeploy-adjacent env change (see the runbook) rather than in an admin
  panel — same limitation ADR-0047 already accepted for the base threshold.
- `REASON_SHARED_IDENTITY` and `REASON_GEO_MISMATCH` can hold a genuine
  travelling or shared-connection customer. Both cost that customer one
  operator click, which is the trade already made by ADR-0047.
- The admin orders list has no search by IP or device — only order id, user
  id, or guest email (`orders.service._admin_search_clause`). Finding the
  rest of a shared-identity group means opening the held order's evidence
  pack for the IP, not a one-click "show me the group" view. Acceptable for
  now at current alert volume; worth revisiting if the queue grows.
- A card identity key (fifth window key) is not implemented: none of the
  live UZ acquirers reliably hand us a card fingerprint. When a
  card-carrying acquirer goes live, it slots into the same mechanism as a
  fifth identity — nothing else about the design changes.

## Validation

Unit tests pin each rule's boundary (fires at the threshold, not below;
`0`/empty disables), identity normalisation (email case, `@user` vs `user`),
jitter's range and determinism, and the degraded path when the evidence
gather fails or an order has no evidence row. Integration tests pay real
orders through the webhook and assert the group case end to end: two paid
orders from one IP under two guest emails hold the third with
`REASON_SHARED_IDENTITY`, and release still goes through the unmodified
`fulfillment.start_for_order` path. Operationally: if `order_held_for_review`
alert volume climbs enough to bury genuine reviews, that is the signal to
widen a window via env, not to disable the rule outright.

## References

- `docs/superpowers/specs/2026-08-30-antifraud-velocity-design.md` — full
  design, the production numbers behind each default, and the rollout plan
- [ADR-0047](./0047-manual-review-of-large-orders.md) — the amount gate this
  extends, and the hold-not-block precedent
- [ADR-0044](./0044-chargeback-evidence-capture.md) — `order_evidence`, whose
  IP, device fingerprint, and `client_hints.timezone` these rules read
- `docs/runbooks/order-held-for-review.md` — operator procedure for all six
  hold reasons
