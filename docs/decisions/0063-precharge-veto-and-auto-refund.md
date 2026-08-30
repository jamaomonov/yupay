# 0063. Pre-charge geo veto and timed auto-refund

- **Status**: Accepted
- **Date**: 2026-08-30
- **Deciders**: @jamaomonov
- **Tags**: backend | payments | security

## Context and problem statement

ADR-0062's identity windows stop the _goods_, not the _charge_: a stolen card
is still debited, and the hold only parks the order for a human to look at.
The cardholder — the actual victim, not the merchant — sees `YUPAY` on their
statement with nothing to show for it, and that line item is a complaint, a
chargeback, or worse aimed at us. Two gaps produce it: nothing refuses a
charge before it happens, even when an order is fraudulent beyond reasonable
doubt at creation time; and a held order keeps the victim's money
indefinitely — the hold waits on an operator with no deadline.

Measured grounding (production, delivered orders, 14 days, see ADR-0062):
browser timezone alone separated a carding run on liquid brands almost
perfectly, but a real diaspora segment (Uzbek buyers on Uzbek instruments,
`Europe/Moscow` browsers) sits inside the same signal. Any pre-charge rule
has to refuse the former without amputating the latter.

## Decision drivers

- All three acquirers already hand us a pre-charge stage built for exactly
  this question ("may this be paid?"): Payme `CheckPerformTransaction`,
  Click `Prepare`, Uzum `Check`. Refusing there costs nothing new to build.
- A held order with no deadline is a merchant holding stolen funds
  indefinitely on an alert that can be missed — the alert already tells an
  operator to release or refund; nothing enforced that they do.
- The trusted-buyer exemption from the hold rule (an account with real
  delivery history) is the same shape needed here — build it once, reuse it
  at both the pre-charge stage and creation.
- Refusing checkout for an honest buyer needs a human-readable reason near
  the pay button; the acquirer's own decline screen is generic, unbrandable,
  and arrives too late (after they already tried to pay).

## Considered options

1. **Only harden the post-payment hold** (tighter thresholds, more window
   rules) — no pre-charge refusal, no auto-refund deadline.
2. **Refuse before the charge; refund a stalled hold on a deadline** — a
   pure decision core shared by every enforcement point, plus a scheduler
   sweep for holds nobody acted on.
3. **Block checkout entirely for any foreign signal**, trusted or not.

## Decision outcome

**Chosen option: 2.** Three pieces, all built on the trusted-buyer exemption
and one pure decision core so they can never drift from each other:

**Refuse before the charge, not just before the goods.** `precharge_veto`
reads `order_evidence.ip_country` (Cloudflare's edge-resolved country, new in
migration 0060) — falling back to the browser-reported timezone only when
country is absent — against `risk_home_countries`/`risk_home_timezones`, for
a guest or an account with zero delivered orders. A signed-in buyer with at
least one delivered order is exempt outright: registration costs a carder
thirty seconds, so the exemption is earned by something real having shipped,
not by having an account. Two enforcement points share the pure core
(`_veto_decision`):

- **Point A — the acquirers' own pre-charge stages** (Payme
  `CheckPerformTransaction`, Click `Prepare`, Uzum `Check`), fed from the
  stored evidence row, each mapping a veto to its protocol's own "not
  payable" answer. The backstop: catches orders created before the rule
  existed, races, and a context that changed between creation and payment.
- **Point B — order creation itself**, fed from the live request (the
  `cf-ipcountry` header and submitted client hints, not a stored row —
  refusing here rolls the transaction back, so there is nothing to read
  yet). Returns **422** `payment-unavailable-abroad` with a message the
  storefront and Mini App render near the pay button, so a refused honest
  buyer sees a reason instead of a broken shop.

**Indistinguishable refusal.** Both country and timezone map to the same
outward-facing decline — the acquirer's own error code at point A, one fixed
i18n string at point B (`store.errAbroad`/`topup.errAbroad`). Nothing outside
`order_events.payload` ever says which of `VETO_FOREIGN_COUNTRY` /
`VETO_FOREIGN_TIMEZONE` fired — or that geography was involved at all: the
point-B copy deliberately names no reason. It offers the one hint that helps
only a legitimate buyer (sign in to the account you have ordered with
before) and is useless to a prober, since a freshly registered account earns
nothing. The honest foreign newcomer without any history is routed to
support instead — a rare case, priced in. Probing still narrows things down
eventually (nothing stops A/B testing from two networks), but the message
itself hands over neither the signal nor the fix.

**A deadline, not an indefinite hold.** `auto_refund_expired_holds`
(`apps/scheduler`'s `held_order_refund` job, every 15 minutes) refunds a
still-`paid`, still-held catalog order once `risk_hold_auto_refund_hours`
passes with nobody releasing or refunding it by hand — through the existing
`payments.service.refund_admin` chokepoint where the gateway supports a
merchant-initiated refund (`octo`, `wallet`), no new money primitive, no new
FSM state. `risk_hold_auto_refund_hours` ships **disarmed** (`0`): flipping
it straight to a live default would auto-refund whatever backlog of held
orders already existed the day this shipped, before an operator ever looked
at it. An operator triages that backlog by hand once, then arms the sweep
with `RISK_HOLD_AUTO_REFUND_HOURS=24` (the same value the sweep runs at
everywhere the veto is live). For Payme, Click, and Uzum — the three UZ
acquirers, all cabinet-refund-only, see `docs/architecture/module-map.md` —
`refund_admin` would just fail every tick with no operator ever told, so the
sweep does not attempt it: it writes one `order.auto_refund_escalated` event
and sends one admin alert instead, pointing the operator at the acquirer's
own cabinet, then excludes that order from every later selection so it is
never re-alerted or re-attempted. The refund itself is made in the cabinet
and reconciles back automatically via the acquirer's own cancel/reverse
callback — see the runbook's escalation section for the exact steps.
Selection re-verifies eligibility under a row lock immediately before
refunding, not only at batch-selection time: up to 50 orders are processed
sequentially with real gateway calls in between, long enough for an operator
to release the order or the fulfilment saga to deliver it while this order
is still waiting its turn in the batch, so a stale snapshot alone is not
enough to trust. `status="paid"` rules out a _released_ order
(`fulfillment.start_for_order` is the only thing that moves a paid order to
`fulfilling`) and a wallet top-up, but — see the Negative consequences below
— it does not by itself mean nobody has acted on the hold. Every hold reason
otherwise stays in scope, including `REASON_PAID_AFTER_EXPIRY` — if no human
decided within the deadline, returning the money (or escalating it to a
human to return from the cabinet) is the safe default for both fraud and
simple confusion.

Option 3 was rejected: it would refuse the measured diaspora segment right
alongside the carding run, trading a fraud problem for a churn problem.
Option 1 was rejected because it leaves the actual harm — a real charge on a
victim's card — in place; a hold only ever protects the goods, never the
money already taken.

### Positive consequences

- A charge that would only ever be refunded now never happens: no acquirer
  fee round-trip, no statement line item, no chargeback exposure on an order
  that was never going anywhere.
- The trusted-buyer exemption is one predicate (`_is_trusted_buyer`), reused
  by both the pre-charge veto and read the same way the post-payment hold's
  geo rule already reasons about signed-in buyers — no second definition of
  "trusted" to drift out of sync.
- A held order now has a hard upper bound on how long it can sit once an
  operator arms the sweep (`RISK_HOLD_AUTO_REFUND_HOURS=24` is the value
  every environment arms it at), tunable per environment, `0` to disarm
  again — the ships-off default, and also the fire-drill lever for a week
  where auto-refund needs to pause.
- Both veto call sites are decision-core-identical (`_veto_decision`); a
  fourth acquirer or a second creation path only has to supply inputs, never
  reimplement the rule.

### Negative consequences

- `risk_home_countries` is a new list to keep current alongside
  `risk_home_timezones` as the business expands markets (the RU launch is
  `RISK_HOME_COUNTRIES=UZ,RU` plus `Europe/Moscow` in the timezone list —
  one env change, not a deploy).
- The auto-refund sweep hands an operator a deadline they didn't have
  before: a hold landing Friday night refunds Saturday night (or, on a
  cabinet-only provider, pages the operator to refund it Saturday night)
  whether or not anyone was on shift. `RISK_HOLD_AUTO_REFUND_HOURS` is the
  release valve if that cadence doesn't match staffing.
- Point B trusts the `cf-ipcountry` header, which only means anything behind
  Cloudflare — the edge strips it from any request that didn't arrive via
  Cloudflare, but a misconfigured origin bypass would silently degrade the
  veto to the timezone fallback rather than fail loudly. Worth a health
  check if the country signal ever goes quiet in the `precharge_vetoed`
  counts.
- The sweep's refund actor is stamped `admin:auto-refund-sweep` — a
  synthetic id, not a real operator — deliberately, to keep it grep-able in
  the audit trail without adding a system-actor variant to
  `payments.service.refund_admin` for one caller.
- **Known gaps in the auto-refund net, left open on purpose rather than
  chased by broadening the selection query:** an admin can close a held
  order via `orders.service.mark_order_failed_admin` (`POST
/admin/orders/{id}/fail`) without moving any money — that walks the order
  to `failed`, which drops it out of this sweep's `status="paid"` selection
  with its payment still `succeeded`, so the money sits until someone
  explicitly refunds it (the runbook now tells operators to refund, then
  fail — never a bare fail on a held order). Separately, a held order an
  admin partially refunds by hand stays `paid` (partial refunds never walk
  the order FSM) with its payment `partially_refunded`; the sweep's
  selection excludes it explicitly (a succeeded-payment filter) rather than
  re-attempting and failing `refund_admin`'s "already refunded" guard every
  tick — finishing that order the rest of the way is the operator's to do
  manually, the sweep will not touch it again.

## Validation

Unit tests pin `_veto_decision`'s full branch table (kill switch, trusted
buyer, fresh account treated as guest, country hit, country miss, timezone
fallback, no evidence). Integration tests exercise all three acquirer
pre-charge stages against a real evidence row (one `order_events` row across
repeated retries; a trusted buyer passes) and order creation's 422 path.
Integration tests for the sweep: a hold past the deadline is refunded through
the mock/wallet/octo gateways with an audit event; a hold on a cabinet-refund-
only provider (Payme/Click/Uzum) is escalated instead — one
`order.auto_refund_escalated` event, one admin alert, no `refund_admin`
attempt, and never re-escalated on a later tick; a fresh hold, a released
order, and a wallet top-up are all left alone; a second tick is a no-op (no
second refund call); `0` disables the sweep entirely; an order released
between batch selection and its own turn to process is skipped, not refunded
(the row-locked re-check); a partially refunded hold is never selected, so it
never turns into a standing per-tick error. Operationally: the rollout ships the
veto on the timezone fallback only (country is `NULL` everywhere until the
Cloudflare **IP Geolocation** toggle is flipped), so there is no day-one
cliff — see the runbook's rollout section.

## References

- `docs/superpowers/specs/2026-08-30-precharge-geo-veto-design.md` — full
  design, the production numbers behind it, and the rollout plan
- [ADR-0062](./0062-antifraud-identity-windows.md) — the post-payment hold
  this pre-charge veto complements, and the trusted-buyer reasoning it reuses
- [ADR-0044](./0044-chargeback-evidence-capture.md) — `order_evidence`,
  extended by migration 0060 with `ip_country`
- `docs/runbooks/order-held-for-review.md` — the deadline, the veto, and the
  Cloudflare toggle from an operator's side
