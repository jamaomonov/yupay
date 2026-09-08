# Merchant B2B — M3b: auto-refund, stall visibility, order-attributed money

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** when a supplier refuses an order and gives our money back, the
merchant's deposit gets it back automatically; when the supplier keeps the
money, or we cannot tell, a human decides — and either way the merchant can see
what is happening instead of watching `fulfilling` forever.

**Architecture:** the money-outcome vocabulary already exists in the adapters
(`supplier_refunded`, `needs_reconciliation`); M3b makes it **explicit, total
and typed**, then acts on it. The refund is the exact mirror of M2's charge,
posted against the **order** so it is visible where the merchant looks.

**Tech stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, pytest +
testcontainers.

**Spec:** `docs/superpowers/specs/2026-09-07-merchant-m3-requirements.md`
(items 2, 3, 3b), which the owner wrote after M2's reviews.

## Global Constraints

- **Money:** `Decimal` only, USD, serialised as strings. The refund legs are the
  exact mirror of `charge_deposit` — the module README's posting table is the
  contract; **do not re-derive directions.**
- **Contract stability:** `/merchant/v1` is consumed by third-party code nobody
  but its owner can redeploy. Every addition here is **additive** — a new
  `failure_reason` value, a populated `refunded_usd`, new `transactions` rows.
  Nothing is renamed, retyped or removed.
- **Never refund on an unknown outcome** _(owner)_. Refunding money we did not
  get back is not a safe default; the unknown case gets a named state and a
  human. Equally, never silently _not_ refund a case we know was returned.
- **Retail parity is a question to answer, not an assumption.** The same
  supplier-refunded-us case exists on the retail path; find out what it does
  today and say whether the two now diverge deliberately or accidentally.
- mypy --strict, ruff, Google docstrings; migrations pair schema with indices;
  `make gen-api` committed when a response shape moves; `pnpm exec prettier
--check .` before finishing any task touching MD/JSON.
- Never `git stash` or `git checkout <path>` — several agents share this
  worktree and it has destroyed work before. Use `git show HEAD:<path>`.
- The mutation harnesses under `apps/api/tests/tools/` edit source in place and
  must never run beside a test suite.

## What the codebase already gives you — read this before designing

The distinction the spec asked M3 to invent is **already recorded**, by two
adapters, in their own words:

- `gengine.py:503,530` — `extra_metadata["supplier_refunded"] = order.is_refunded`,
  a real field from their API, with the comment: _"A refunded order needs no
  money chased; one that failed without a refund does, and only the flag tells
  them apart."_
- `waxpeer.py:375-383` — `canceled` sets `supplier_refunded = True`
  (_"waxpeer refunded the amount to our balance"_); `error` sets
  `needs_reconciliation = True` (_"it does not auto-refund this case — needs
  manual reconciliation"_).
- `g2b.py:204` — only a comment that _their docs say_ FAILED orders auto-refund
  the balance. **No field.** That is a weaker basis than the other two and must
  be treated as such.
- `inventory` — our own warehouse. No supplier money is involved at all, so a
  failure there spends nothing externally.

M3b's job is not to invent this vocabulary. It is to make it **total** (every
adapter, every terminal failure, no default), **typed** (not a dict key that a
typo makes falsy), and **acted upon**.

---

### Task 1: A typed, total money outcome on a failed task

**Files:**

- Modify: `modules/fulfillment/suppliers/base.py`, `g2b.py`, `gengine.py`,
  `waxpeer.py`, `manual.py`, `mock.py`, `_stub.py`, `inventory` routing,
  `modules/fulfillment/service.py`
- Test: `apps/api/tests/unit/test_supplier_money_outcome.py`

**Interfaces:**

- Produces a three-valued `MoneyOutcome` — `RETURNED` / `SPENT` / `UNKNOWN` —
  carried on the terminal-failure path and persisted on the task, replacing the
  two ad-hoc `extra_metadata` keys as the _source of truth_ (keep writing them
  if anything reads them; the typed value is what M3b acts on).
- Consumes nothing new.

**Rules:**

- **No default.** Every adapter decides explicitly for every terminal failure it
  can produce. A test walks the registry and fails if an adapter has a failure
  path with no mapping — the pattern `test_outbound_ssrf.py` uses over
  `OutboundError.__subclasses__()`.
- `g2b`'s mapping rests on their documentation, not on a field. Whatever you
  choose, the docstring must say that plainly, so the next person knows which
  of the three is evidence and which is a promise.
- A low-supplier-balance failure (`_LOW_BALANCE_ERROR`) is **not** terminal —
  it is Task 4's stall. Do not classify it here.

- [ ] **Step 1: failing tests** — every adapter's terminal failures mapped;
      the registry walk; the two existing metadata keys still written.
- [ ] **Step 2-4:** FAIL → implement → pass.
- [ ] **Step 5: commit** `feat(api/fulfillment): say whether a failed order kept our money`

---

### Task 2: Order-attributed deposit movements

**Files:**

- Create: `apps/api/migrations/versions/0072_*.py` **only if** a column is
  needed — check first
- Modify: `modules/merchants/deposit.py`, `admin.py`, `admin_routes.py`,
  `docs/runbooks/merchant-b2b.md`
- Test: `apps/api/tests/integration/test_merchant_deposit_attribution.py`

**The defect M2 left behind.** `refunded_for_order` filters ledger transactions
on `reference_type == "order"`, but `credit_deposit` — the only surface that
credits a deposit today — posts `Reference(type="merchant", id=merchant_id)`.
So the manual credit support actually performs is **invisible on the order by
construction**, and `refunded_usd` can only ever be `"0.00"`.

**Rules:**

- A deposit credit may now optionally carry an order reference. The admin
  endpoint gains an optional `order_id`; when present, the posting references
  the order and `refunded_usd` sees it.
- The manual stopgap in the runbook is rewritten to use it — that procedure
  currently produces a credit the merchant cannot tie to anything.
- Existing credits keep working unchanged; this is additive.

- [ ] **Step 1: failing tests** — a credit with an `order_id` shows in that
      order's `refunded_usd` and in `/transactions`; one without behaves exactly
      as today; an `order_id` belonging to another merchant is refused.
- [ ] **Step 2-4:** FAIL → implement → pass.
- [ ] **Step 5: commit** `feat(api/merchants): let a deposit credit name the order it belongs to`

---

### Task 3: The auto-refund

**Files:** `modules/merchants/deposit.py`, `modules/fulfillment/service.py` (the
terminal-failure site), `modules/merchants/refund.py` (new); tests alongside.

**Interfaces:**

- Produces `refund_order(db, *, order, reason)` — the exact mirror of
  `charge_deposit`, idempotent on a key shaped like `merchant-order:{order_id}`
  (choose the refund's own key with the same discipline), referencing the
  **order**.

**Rules:**

- Fires only on `MoneyOutcome.RETURNED`. `SPENT` and `UNKNOWN` never refund
  automatically _(owner)_.
- `UNKNOWN` and `SPENT` put the order in a **named state a human can find**, and
  alert ops. Do not reuse a state that means something else; a merchant reading
  the API must be able to tell "we are refunding you" from "a human is deciding".
- Idempotent under a re-driven fulfilment, an admin retry, and a concurrent
  drain. Test all three; the concurrency test must exercise a real interleave,
  not two coroutines on one event loop — that shape was proven useless on this
  branch twice.
- The order's terminal `status` and `failure_reason` are contract; document what
  each of the three outcomes produces.

- [ ] **Step 1: failing tests** — a RETURNED failure refunds exactly once and
      the deposit rises by exactly the charged amount; SPENT and UNKNOWN refund
      nothing and are visibly parked; the refund appears on `refunded_usd` and
      in `/transactions`; the three idempotency cases.
- [ ] **Step 2-4:** FAIL → implement → pass. Run the FULL orders, payments,
      fulfilment and wallet suites — this is the money path.
- [ ] **Step 5: commit** `feat(api/merchants): refund the deposit when the supplier gave our money back`

---

### Task 4: The stall says it is stalled

**Files:** `modules/fulfillment/service.py`, `modules/merchants/order_status.py`,
`machine_schemas.py`; tests alongside.

Today a low-supplier-balance failure leaves the order `fulfilling` with
`failure_reason: null` — indistinguishable from one placed thirty seconds ago,
indefinitely. Retail's rule is right for a buyer with a support chat; a reseller
has an SLA and a polling loop with no terminal condition.

**Rules:**

- A third, **non-terminal** `failure_reason` value: _in progress, delayed on our
  side — do not re-order, do not refund your customer yet._ `status` stays
  `fulfilling`.
- **Retail must not change.** The storefront keeps showing "обработка"; this is
  a merchant-facing field only. Prove it.
- The README's "treat a long `fulfilling` as in progress" guidance is replaced
  by something a machine can act on.

- [ ] **Step 1: failing tests** — a low-balance failure sets the value and keeps
      `fulfilling`; a retail order's storefront view is byte-identical; the value
      clears when the admin tops up and the task succeeds.
- [ ] **Step 2-4:** FAIL → implement → pass.
- [ ] **Step 5: commit** `feat(api/merchants): a stalled order says so`

---

### Task 5: Record what we quoted, and the contract

**Files:** migration for the list-price column, `modules/merchants/orders.py`,
`modules/merchants/README.md`, `docs/api/README.md`,
`docs/decisions/0071-merchant-refunds.md`, `docs/runbooks/merchant-b2b.md`,
`docs/architecture/sequence-diagrams/merchant-refund.mmd`

**Spec item 3b:** store the **computed list price** at order time beside the
merchant's quote, so the runbook's regression query stops recomputing from a
live markup and a pilot arguing about a charge has a record.

ADR-0071 records: the three-valued money outcome and why an unknown never
auto-refunds; why the refund references the order; the idempotency key; and
which adapter mappings are evidence versus documented promise.

**The contract text must state**, and each must be true of the code:

- what a merchant sees for each of the three outcomes;
- that `refunded_usd` is now real, and what it counts;
- the stall value and what a receiver should do with it (and not do);
- that a refund appears in `/transactions` and how to reconcile it.

- [ ] **Steps:** write → verify every falsifiable claim against the code →
      `pnpm exec prettier --check .` → commit `docs(merchants): refunds and the stall`

---

## Self-review notes

- Ordering: 1 (the fact) → 2 (where money can point) → 3 (the refund, needs
  both) → 4 (unrelated to 1-3, and deliberately after the money path) → 5.
- Task 3 is the money path and gets the full-suite gate.
- Task 1's "no default" registry walk is the guard that stops a future adapter
  silently inheriting a refund policy nobody chose for it.
- Out of scope: M4's cabinet; anything about the webhook outbox (M3a, merged).
