# 0071 — Merchant deposit refunds: a typed money outcome, an order-referenced posting, and a human on every doubt

- Status: accepted
- Date: 2026-09-08
- Spec: `docs/superpowers/specs/2026-09-07-merchant-m3-requirements.md` (items 2, 3, 3b)
- Plan: `docs/superpowers/plans/2026-09-08-merchant-b2b-m3b.md`
- Predecessors: ADR-0068 (the deposit ledger), ADR-0069 (the machine API whose
  contract these values are published on), ADR-0064 (the Postgres fulfilment
  queue this seam runs inside), ADR-0063 (the _other_ auto-refund — see
  decision 8)

## Context

M2 gave a reseller a deposit and a way to spend it. When a supplier then
refused an order, three things were true at once and none of them was written
down: the deposit stayed debited, `refunded_usd` read `"0.00"` on every order
by construction, and an order that had stalled for a reason we could fix in
minutes was byte-identical to one placed thirty seconds ago — indefinitely.
The reseller's own contract told them to poll a field that could never change.

The owner ruled on 2026-09-07 (spec item 3): when the supplier **refuses and
returns the funds**, refund the merchant's deposit automatically; when we
cannot tell, a named state and a human, never a guess.

This ADR records the decisions M3b made in answering that, and the gaps it
knowingly leaves open — decision 5 and everything under "What this does not
decide". The wire contract third parties implement against lives
in `apps/api/src/yupay/modules/merchants/README.md` and is deliberately not
duplicated here.

## Decisions

### 1. The money question is a separate, three-valued, defaultless answer

"The order failed" and "our money is gone" are different facts, and M3b makes
the second one explicit. `MoneyOutcome` (`fulfillment/suppliers/base.py`) is
`RETURNED` / `SPENT` / `UNKNOWN`, and it is a **required** field on
`FulfillResult`, `FulfillStatus` and on **both** supplier exceptions — because
`process_task` turns a raise into a failed task, so a raise is a terminal
failure too. mypy refuses an adapter exit that does not decide; a
`__post_init__` invariant refuses one that claims an outcome on a success.

That is stronger than "no default", which was the plan's wording: it is
"cannot compile without deciding". The guard behind it
(`tests/unit/test_supplier_money_outcome.py`) **walks** the registry rather
than listing paths, and follows each fulfiller module's imports inside the
suppliers package — the hop that reaches `gengine_gifts.py`, a file with real
failure exits and no `Fulfiller` class that a registry-only walk misses
entirely. Its rules are run against a synthetic adapter that breaks all of
them, so the guard cannot itself become a test that checks nothing.

`UNKNOWN` is **not** a polite `SPENT`. It is the same shape M3a settled one
milestone earlier and for the same reason: a two-valued "did it arrive" has to
file a timeout under "no", and a timeout is precisely the case where it may
have arrived — so `Delivery` became `NOT_SENT | UNKNOWN | RECEIVED`
(ADR-0070 decision 3). Here neither `SPENT` nor `UNKNOWN` refunds, but they say
different things to the person who ends up looking at the order, and collapsing
them would lose which of our suppliers we actually have an answer from.

### 2. `UNKNOWN` never refunds automatically — the owner's decision, not a default we tuned

`SPENT` and `UNKNOWN` post nothing and raise an ops alert. Refunding money we
did not get back is not a safe failure mode: it is a real loss, taken silently,
on the word of a supplier who never said it. The symmetric error — never
refunding a case we know was returned — is what decision 1 exists to prevent,
and the two are not tradeable against each other by an engineer changing a
default.

The cost is stated rather than smoothed over, and stated no further than the
evidence goes: **every `g2b` failure from a call that actually went out is
`UNKNOWN`** and therefore reaches a person (decision 3). How big that lane is
we **do not know** — nothing counts merchant failures by supplier or by cause,
`g2b` also has four pre-call refusals that auto-refund, and this milestone
shipped without a single production data point. An earlier draft of this ADR
said the manual lane carries "most" merchant failures; that number was never
measured and has been withdrawn rather than restated. Counting is the cheap
thing to do before anyone decides the lane is affordable.

### 3. The three confidences are kept apart, and `g2b` is the weak one

| Adapter     | Evidence                                                                                                            | Mapping                                                                                                                                                                       |
| ----------- | ------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `gengine`   | **A field.** `order.is_refunded` from their API                                                                     | refunded → `RETURNED`; a customer-fault status (`invalid_account`, `invalid_amount`) on a task no pay request has ever gone out for → `RETURNED`; everything else → `UNKNOWN` |
| `waxpeer`   | **Observed behaviour**, and ADR-0032 states it in writing                                                           | `canceled` → `RETURNED`; `error` and under-delivery → `SPENT`                                                                                                                 |
| `g2b`       | **A sentence in their documentation** for anything a call reached; **our own control flow** for anything before one | every failure from a call that went out → `UNKNOWN`; four refusals raised **before any call** (`_NEVER_SENT`) → `RETURNED`                                                    |
| `inventory` | Our own warehouse. No supplier money is involved at all                                                             | `RETURNED` (`INVENTORY_FAILURE_MONEY_OUTCOME`)                                                                                                                                |

Flattening these into one confidence was the available shortcut and it is the
one that loses money. `waxpeer`'s `SPENT` is a **positive fact** — their
non-refunding is documented behaviour, not an absence of evidence — and that is
exactly what separates it from `g2b`'s `UNKNOWN`. `g2b`'s adapter carries a
note saying which of the three its answer is and naming what would promote it:
a field, not a softer default. A `RETURNED` we cannot substantiate refunds a
merchant for goods we paid for.

**`g2b` is two answers, not one, and the split is where the call happens.**
`_FAILURE_MONEY_OUTCOME` (`UNKNOWN`) covers every exit from a call that went
out. `_NEVER_SENT` (`RETURNED`) covers four refusals raised **before** one
does — no `G2B_API_KEY`, an order line with no `player_id`, a mapping with no
`external_variant_id`, and no active `SkuSupplierMapping` at all — and those
rest on **our own control flow**, not on anything G2B says: nothing was
ordered, so nothing was charged. That is a firmer basis than the `UNKNOWN`
half, and the same shape as `gengine`'s pre-pay refusals. It is worth stating
plainly because these auto-refund, and because the last of the four is
reachable in ordinary operation: deactivating a retiring SKU's mapping between
an order and its drain refunds that reseller automatically.

`gengine`'s `invalid_account` was the one **inference** in the table, and it
was made true rather than re-graded: the adapter now carries a committed
"a pay may have landed" breadcrumb, written on every exit an invocation takes
once it has called `pay_recharge_order`, so `RETURNED` there requires that this
call never reached pay. `is_refunded` still outranks the breadcrumb, because an
**observed refund** and an **absence of spend** are different facts and only the
first survives a demotion rule.

### 4. Knowledge about our own money only accumulates: `RETURNED < UNKNOWN < SPENT`

`record_money_outcome` never moves a task **down** that ladder. Every
`RETURNED` an adapter can produce is a fact about **one attempt**, and a task
outlives its attempts:

1. `pay` is charged and then returns HTTP 500 → `UNKNOWN`, correctly.
2. An admin clicks Retry — the ordinary response to that failure.
3. The replay trips a transient outage before it creates anything →
   `RETURNED`, also correctly, _for that attempt_.
4. Without the ladder, the deposit is refunded for goods we have already paid
   for.

`retry_task` therefore does **not** clear the value: it is the only memory the
next attempt has of what the previous one may have spent. Upward stays open,
because learning that the money **is** gone is new knowledge rather than an
older attempt's absence of it.

### 5. There is no operator re-grade path, in either direction, and there is no plan for one

This is the deliberate gap this ADR exists to record, so that it is found here
rather than rediscovered in an incident.

- A `SPENT` an operator successfully chases stays `SPENT` **forever**. Waxpeer
  writes it for an `error` top-up, the runbook's answer is "go and get the
  money back", and the operator who does has no way to record it. That order
  will never refund automatically.
- A spurious early `UNKNOWN` is equally permanent, and it closes the automatic
  refund for that task for good.

Both are safe **only while a terminal supplier verdict is the only thing that
writes one**. The constraint is in `record_money_outcome`'s docstring and in
`fulfillment/README.md` rather than in a ledger note, because the next person
to add a recording site is who needs it: a caller that started recording on
_transient_ errors would make every supplier outage a permanent `UNKNOWN` on an
otherwise healthy task.

The cost today is operator minutes and not money — the manual settlement in
`docs/runbooks/merchant-b2b.md` still works on any of these — which is why the
gap is recorded rather than closed. It stops being cheap if the g2b lane grows.

### 6. The refund references the **order**, not the merchant, and that is the whole of M2's defect

`refunded_usd` sums the **debit** legs on the merchant's `merchant_deposit`
account across every ledger transaction whose reference is this order. Until
M3b, the only surface that credited a deposit wrote
`Reference(type="merchant", id=merchant_id)` while that reader filtered on
`order` — so the field could only ever answer `"0.00"`, and the hand
settlement support performed after a failed delivery appeared **nowhere on the
order it paid for**.

Referencing the order is therefore not a convenience. It is the axis the
merchant's own question is asked on ("what came back on _this_ order?"), and it
is what let the automatic refund land on a published field with **no change to
the reader and none to the contract**: the reader reads a _direction_, not a
transaction kind, so it did not have to learn the name M3b gave its posting.

Two guards make that reference hard to lose. Both words are spelled once
(`deposit.ORDER_REFERENCE_TYPE` / `MERCHANT_REFERENCE_TYPE`) and read back
through one function, so a writer and a reader can no longer disagree silently
— `reference_type` is a free-form `String(32)` that nothing validates, and a
posting spelled `merchant_refund`, which is the natural thing to write, would
move the money and read `"0.00"` on the order. And `credit_deposit`'s
`order_id` is a **required keyword with no default**, because the second axis
of the same defect is omission: a default would have put the invisible
behaviour on it, with mypy happy and no test failing.

### 7. The idempotency key is a money invariant, not a naming preference

The refund posts under `merchant-order-refund:{order_id}`; the charge under
`merchant-order:{order_id}`. **`wallet.service.post` replays by key without
comparing parameters.** A key collision therefore does not raise. The refund's
own pre-read finds the **charge** under that key, returns it as "the refund is
already posted", and the caller logs a successful refund carrying the charge's
transaction id — while no money moves at all. `refunded_usd` stays `"0.00"`
(the charge is a credit leg, which that sum excludes by direction), the order
goes on reading `fulfillment_failed`, and nothing anywhere raises.

The property that makes the two safe is that **neither prefix is a prefix of
the other**, which no order id on either side can close.
`tests/unit/test_merchant_refund_keys.py` pins exactly that, rather than the
two strings — a test asserting the literals would pass through the rename that
breaks the property.

The same mechanism runs the other way. A **hand** settlement is keyed
`merchant-credit:{merchant}:{whatever the operator typed}`, which is a
different namespace, so `post()` cannot dedupe the two paths for us: support
settling at 10:00 and the drain refunding at 10:05 would credit one order's
deposit twice and publish `refunded_usd: "2.14"` on a `"1.07"` order. Both
directions are closed by explicit guards rather than by the key —
`refund_order` refuses an order anything has already returned money on, and
`credit_deposit` refuses a credit that would take an order past what it
charged.

### 8. Its relationship to ADR-0063, which also says "auto-refund"

They move **different money on different rails** and cannot meet.

- **ADR-0063** returns a **retail buyer's card or wallet payment** to the
  acquirer, on an order that `orders.risk` put on hold and nobody triaged
  before `risk_hold_auto_refund_hours` elapsed. Mechanism:
  `payments.service.refund_admin` from a scheduler sweep, actor
  `admin:auto-refund-sweep`.
- **ADR-0071** returns a **reseller's own prepaid deposit**, on our internal
  ledger, when a supplier failed the order and gave our money back. Mechanism:
  `wallet.service.post` from the fulfilment saga, actor `fulfillment`.

The sweep cannot select a merchant order for two independent reasons: its
selection requires an `order.held_for_review` event, and the only two callers
of `hold_for_review` are in `payments/service.py`, which no merchant order ever
reaches (a merchant order is paid from the deposit by
`mark_merchant_order_paid`, never through an acquirer); and it additionally
requires a **succeeded payment row**, which a merchant order has none of.

### 9. The refund runs outside the drain's savepoint, and catches everything

`drain_pending_tasks` runs each task inside a `SAVEPOINT` whose crash arm
records `UNKNOWN` — the one value decision 4 will never let anything move back
down. A refund that raised **inside** that savepoint would roll back the
`RETURNED` it was acting on and replace it with a permanent "we cannot tell":
_the attempt to refund would make the order unrefundable_. So the seam runs
after the savepoint is released, at each of the four sites that can terminally
fail a merchant task.

Having moved out there, it must catch everything, and the rule it appears to
break is worth stating: "no bare `except Exception` on the money path" exists
because `main`'s 64decbd hid a circular import behind one for six weeks. That
rule forbids **swallowing**, not **surviving**. Propagating buys nothing and
costs the queue — a deterministic fault escapes the drain, rolls the batch
back, returns every row to `pending` and re-crashes next tick, taking the
**storefront's** fulfilment down with the reseller's. Nothing is swallowed:
every exception is logged at `error` with the order id, raises an ops alert,
and is tagged `modelled=true|false`, so an ordinary "support already settled
this" and an `ImportError` from the lazy import are one query apart. The
classification resolves `RefundError` through `sys.modules` and **imports
nothing**, because an `except` arm is outside its own `try` and an import
there fails on exactly the case the arm exists to report.

### 10. Spec item 3b: record the merchant's quote; do **not** record the list price

Item 3b asked for two things at order time. Only one of them was missing.

`quote.price_for` returns `pricing.price_to_charge`'s result, which since the
owner's 2026-09-07 amendment is **our** current price or nothing —
`expected_price` is an accept/reject tolerance and never a bid.
`merchants.orders.place` binds that one value to `price` and passes the same
object to `unit_price_usd_override` and to `charge_deposit`. So
`order_items.unit_price_usd` **is** the computed list price at order time,
already frozen and already selected by the runbook's regression query.

A second column beside it would be filled from that same expression, so it
could not disagree — and substituting it into the regression query would turn
a check into a comparison of a value with itself. That query earns its keep by
**recomputing** the price from `order_items.cost_usdt` and the SKU's markup;
recomputation from independent inputs is the whole of its value. Its two
stated blind spots (a live `b2b_markup_pct`, a negotiated
`markup_adjustment_pp`) are real and are **not** closed by this milestone.

What was genuinely unrecorded is the merchant's own `expected_price`. It
reached exactly one durable place — `_request_digest`'s SHA-256, which answers
"same request?" and nothing else — so a pilot disputing a charge could not be
shown their own number, and the drift between what resellers quote and what we
charge was unmeasurable after the fact. Migration 0072 adds
`order_items.merchant_expected_price_usd`, written on merchant lines only and
**read by no code path**. No index — not because nothing filters on it (the
runbook's drift sweep filters on exactly this column) but because its only
reader is an operator running that sweep by hand, where a sequential scan costs
nothing and an index costs every checkout. Were it ever to need one it would
want a **partial** index over the merchant lines rather than a btree over a
price, and per AGENTS.md §10 that belongs in the migration of the query that
needs it.

### 11. `failure_reason` stays `string | null` in the schema — an `enum` was considered and refused

The vocabulary is published in the module README and **not** in
`docs/api/openapi.json`, where the field is a bare nullable string.

An `enum` would give integrators a generated type and make an added value a
visible schema diff. It would also make the set **closed in a
machine-checkable way**, and this milestone is the counter-example: M3b added
_two_ values to it, so a client generated before M3b would carry a type that
excludes a value we now send, and a strict generated validator would reject the
response outright. That converts an additive server change into a client-side
outage — on a surface whose defining constraint (ADR-0069) is that nobody but
its owner can redeploy the receiver.

The README's rule is the opposite instruction and cannot be expressed in an
`enum` at all: **a value you do not recognise is not a stop condition — treat
it as non-terminal and keep polling.** A `description` was the middle option
and was refused for a smaller reason: it would put a second copy of a
four-value contract in a file that nothing checks against the first, and this
branch has spent four review rounds on facts with two homes. The README says
plainly what the schema publishes, so the two agree instead of overlapping.

This is revisitable, and the condition is nameable: once the vocabulary stops
growing, an `enum` becomes safe and worth adding.

## What this does not decide

- **Cancellation leaves a debited deposit that no automatic path resolves.**
  `_apply_cancel` records no money outcome, so nothing refunds; the deposit
  stays debited and the order becomes unmovable, because `retry_task` and
  `complete_manual_task` both refuse a `cancelled` task. It is also the shape
  **most likely** to have left our money with us, since a cancel usually
  precedes any supplier verdict — which is exactly why inferring a refund from
  it would be the guess decision 2 forbids: cancelling is a human action taken
  for a reason this code cannot read. Three review rounds made the state loud
  (`log.warning` plus a per-order alert, deduped hourly) and correctly gated:
  it fires unless the order is **square against what it charged**, so closing
  an order the drain has already refunded — the ordinary support step, and the
  feature's commonest path — raises nothing, while a one-cent partial still
  does. **What should happen to that money is a
  product decision nobody has made.** The shape of an answer: either a
  cancelling operator is asked for the money outcome at the point of
  cancelling, or the cabinet (M4) grows a "settle this order" action that
  records one. Both are decisions about who is accountable for the judgement,
  not about code.
- **Whether `g2b` really refunds.** Decision 3's `UNKNOWN` half rests on their
  documentation rather than on an observation, which is exactly why it refunds
  nothing; its `RETURNED` half rests on our own control flow and needs no
  supplier claim at all. Either way, nothing in this milestone tested a real
  supplier refund end to end, and nothing measures how often each arm fires.

## Consequences

- **Every `g2b` failure from a call that went out still reaches a person**, and
  will until `g2b` exposes a refund field. The runbook's known-gaps entry says
  so with the reason, so that a manual lane reads as designed rather than as
  broken — and says, equally plainly, that its size is unmeasured.
- **`refunded_usd` is a sum, not a flag, and one cent is now load-bearing.** A
  partial attributed credit — an operator mid-decision — leaves the order
  reading `fulfillment_failed`, refuses the automatic refund
  (`AlreadySettledError`), refuses both re-drive buttons
  (`deposit_already_returned`, which triggers on any amount) and still raises
  the cancellation alert, because the order is not square. All of it is loud,
  and the recovery is to credit the remainder by hand, which is permitted right
  up to the charge.
  The comparison lives in **one** pure function (`refund.settled_in_full`)
  shared by the contract field and the cancellation alert, because a sum read
  as a flag is the defect this milestone met twice.
- **A refunded order may never be re-driven.** `charge_deposit` is idempotent
  on the order, so a second charge replays and debits nothing: refund, then
  Retry, and the reseller has the goods _and_ the money. Both buttons refuse
  with `409 deposit_already_returned`, and the refusal catches a **hand**
  settlement too — that loophole predates the automatic refund.
- **Money reaches a reseller by push; order state only by poll.** The refund
  emits `balance.credited`, because the hand settlement it replaces already
  did and an automatic path that went silent would have removed a notification.
  No `order.status_changed` fires for a failure, a stall or a refund, because
  none of them moves `orders.status`. The contract says so.
- **Retail is untouched and pays one indexed read to stay that way.**
  `INVENTORY_FAILURE_MONEY_OUTCOME` is `RETURNED` and fires whenever an
  inventory route runs dry with nothing to fall back to (`service.py`'s
  `decision.strict or decision.fallback is None` — a dry warehouse **with** a
  supplier fallback re-routes instead of failing), so the `merchant_id` gate is
  doing real work rather than documenting an impossibility. A retail task pays one indexed
  read here and returns before any savepoint is opened, any `merchants` module
  is imported, or any other row is read.
- **`fulfillment/service.py` is 2415 lines and `merchants/deposit.py` 770**
  (measured at this commit), both well past AGENTS §6's split point. M3b added a new module
  (`fulfillment/stall.py`) rather than either. The split is a scheduled item.
- **The two mutation harnesses this milestone produced carry mechanisms the
  other three do not** — an exact-set `expect` per row and `--check-anchors`.
  Both were proven by constructing the failures they catch, and both are worth
  adopting in the siblings.

## References

- Contract: `apps/api/src/yupay/modules/merchants/README.md` (the
  `failure_reason` table, `refunded_usd`, `/transactions`)
- Operations: `docs/runbooks/merchant-b2b.md`
- Flow: `docs/architecture/sequence-diagrams/merchant-refund.mmd`
- Vocabulary and adapter mappings: `apps/api/src/yupay/modules/fulfillment/README.md`
- [ADR-0063](./0063-precharge-veto-and-auto-refund.md) — the retail auto-refund
- [ADR-0064](./0064-postgres-fulfilment-queue.md) — the queue this seam runs in
- [ADR-0068](./0068-merchant-b2b-foundation.md), [ADR-0069](./0069-merchant-machine-api.md), [ADR-0070](./0070-merchant-webhooks.md)
