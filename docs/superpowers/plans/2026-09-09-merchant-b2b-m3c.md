# Merchant B2B — M3c: the operator's side of the refund

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** M3b's refund works and was proven on production. This milestone closes
what the first live test exposed: a merchant order that an operator cannot
recognise, cannot read the real state of, and cannot settle without leaving the
page — plus one supplier rejection we now know costs us nothing, which should
stop waiting for a human.

**Where it came from.** Two live orders on 2026-09-09 (`m3b-parkA-1`,
`m3b-refundB-1`). The owner used the admin UI on the result and found three
things in a minute that five review rounds had not, because they are only
visible to someone holding the operator's job.

## Global constraints

- **Money:** `Decimal`, USD, minor-unit discipline. No new posting path —
  Task 4 links to the posting that exists, and it is already guarded against
  double settlement by `order_already_settled`.
- **The owner's standing rule is unchanged:** an unknown outcome never refunds
  automatically. Task 1 does not weaken it; it **narrows what counts as
  unknown**, on evidence.
- Contract stability: `/merchant/v1` is third-party code. Additive only.
- mypy --strict, ruff, Google docstrings, `prettier --check` on MD/JSON, three
  locales for every user-facing string.
- Never `git stash` or `git checkout <path>` — use `git show HEAD:<path>`.
- The mutation harnesses under `apps/api/tests/tools/` edit source in place and
  must never run beside a suite. They now share `_falsify.py`, assert an exact
  red set, and have `--check-anchors`. Copy that shape.

---

### Task 1: an invalid player id is money we never spent

**Files:** `modules/fulfillment/suppliers/g2b.py`, tests alongside, a harness row.

**The owner's ruling (2026-09-09):** when g2b answers a _create_ with
`HTTP 400 {"message":"Invalid player ID. Please check and try again.","success":false}`,
they do not debit our balance. So the order should refund automatically instead
of parking for a human.

**Rules:**

- The site is `g2b.py:432`, the one raise that today answers `_MAY_HAVE_SPENT`
  for every non-low-balance `G2bError` from create.
- **This matcher must be tight, and the reason is the opposite of its
  neighbour's.** `_looks_like_low_balance` is deliberately loose because its
  false positive is cheap. A false positive **here refunds money we may have
  spent**, so match narrowly — the status _and_ the shape of their message —
  and say so in the docstring, next to the neighbour that says the opposite.
- A rejection we do not recognise keeps answering `UNKNOWN`. Falling back to
  the safe answer is the behaviour, not a gap.
- **Grade the evidence.** ADR-0071's table says which mappings rest on a field,
  which on observed behaviour, and which on a sentence in a vendor's document.
  This one is new: _a supplier's error string, plus the owner's knowledge that
  it is not billed._ Weaker than a field, stronger than a promise. Amend the
  table and the `g2b` row rather than leaving the ADR describing the old three.
- Retail is unaffected by construction (the refund seam is gated on
  `merchant_id`), but the **outcome** is recorded for retail too, because it is
  a fact about the supplier and not about who bought. Prove retail is unchanged.

- [ ] **Step 1: failing tests** — the exact live body maps to `RETURNED`; a 400
      with a different message stays `UNKNOWN`; a 500 stays `UNKNOWN`; the
      low-balance shape still wins its branch; a merchant order with this
      rejection refunds end to end.
- [ ] **Step 2-4:** FAIL → implement → pass, with the red observed per test.
- [ ] **Step 5: commit** `feat(api/fulfillment): an invalid player id costs us nothing, so refund it`

---

### Task 2: an order says whose it is

**Files:** the admin order DTO + routes, `apps/admin/src/features/orders/`,
`packages/i18n/locales/{ru,en,uz}`.

Orders have had **three** actor arms since M2 (`ck_orders_actor_exclusive`:
user, guest, merchant). The admin UI has two: `{order.guest_email ?? "Гость"}`
(`OrderDetailPage.tsx:298`). A merchant order therefore reads as a guest order
in the list _and_ the detail page, and the only trace is a raw uuid in one
timeline line.

**Rules:**

- The DTO gains the merchant's id **and title** — an operator recognises a name,
  not a uuid.
- List and detail both. A filter by merchant if it is cheap; say so if not.
- Do not invent a fourth actor rendering: the exclusivity is a CHECK constraint,
  so the display is a three-way switch with an exhaustive default.

- [ ] **Step 1: failing tests** — a merchant order renders the merchant, a guest
      order is unchanged, a user order is unchanged.
- [ ] **Step 2-4:** FAIL → implement → pass.
- [ ] **Step 5: commit** `feat(admin/orders): a merchant order says whose it is`

---

### Task 3: the state an operator can act on

**Files:** the admin order DTO, `apps/admin/src/features/orders/`, locales.

A terminal fulfilment failure deliberately does not move `order.status` — that
is retail's rule and it stays. So the admin list shows **«В работе»** forever on
a dead order, which is what the owner hit. `/merchant/v1` grew `failure_reason`
for exactly this and the admin never did.

**Rules:**

- **Share the logic, do not copy it.** `order_status._failure_reason` and
  `fulfillment.stall.order_is_stalled` are the definitions; a second spelling in
  the admin is how the two drift.
- Render alongside the status, not instead of it: "В работе · Провалено,
  возвращено" / "· Провалено, решает человек" / "· Задерживается".
- Three locales.

- [ ] **Step 1: failing tests** — each of the four states renders; a healthy
      in-flight order renders nothing extra.
- [ ] **Step 2-4:** FAIL → implement → pass.
- [ ] **Step 5: commit** `feat(admin/orders): show the fulfilment state the merchant already sees`

---

### Task 4: settle a merchant order without leaving the page

**Files:** `apps/admin/src/features/orders/`, locales. **No new API.**

An operator looking at a failed merchant order has no refund affordance:
the admin's refund path goes through a payment row, and a merchant order has
none (**«Платежи (0)»** on the live one). The money is returned by the
attributed deposit credit M3b Task 2 built — which lives on the _merchant's_
page. The operator is standing where the button is not.

**Rules:**

- **One button on the order page.** It posts the existing attributed credit for
  the amount the order was charged, with the order id already filled in.
- **It is not an auto-refund and must not read as one.** The owner's decision of
  2026-09-09 stands: after a human action, a human decides. The button is how a
  human decides quickly — a confirmation naming the merchant, the amount and
  the order, then the same posting support does today.
- It must be **impossible to double-settle from here**: `order_already_settled`
  already refuses, so surface that refusal as a clear message rather than a raw
  409, and hide or disable the button on an order already square.
- Three locales. `Idempotency-Key` minted per attempt, as the existing form does.

- [ ] **Step 1: failing tests** — the button appears only on an unsettled
      merchant order; it posts the charged amount with the order id; a second
      press is refused and says why; a retail order never shows it.
- [ ] **Step 2-4:** FAIL → implement → pass.
- [ ] **Step 5: commit** `feat(admin/orders): settle a failed merchant order from the order page`

---

### Task 5: the stuck-order alert says a number that is not the amount

`apps/scheduler/src/yupay_scheduler/jobs/stuck_orders.py:90` formats the money as
`f"{order.total_charged:,.0f}"` — **zero decimal places**. Reproduced:
`0.64 -> "1"`, `0.24 -> "0"`, `1.50 -> "2"`.

The format was written for UZS, where whole sums are right and the thousands
separator earns its place. USD orders arrived with M2 and nothing revisited it.
**"0 USD" on a money alert is worse than an imprecise number**: it reads as
"nothing at stake" on the one line whose whole job is to say the opposite.

**Rules:**

- Format by the order's currency, not by one hard-coded shape. UZS keeps whole
  units and the space separator; USD gets two decimals.
- The alert is Telegram HTML — keep the escaping.
- A test per currency, and one that fails if the decimals come back.

- [ ] commit `fix(scheduler): the stuck-order alert rounded 0.24 USD to "0"`

---

### Task 6: a refunded merchant order is over, and its status should say so

**The owner's ruling (2026-09-09), and the reasoning behind it is theirs:** an
order that has been automatically refunded sits at `status: "fulfilling"`
forever, and that is a lie. The reason the status is deliberately left alone on
a fulfilment failure — _an operator may still top up, retry, or deliver by
hand_ — is **false for a refunded order**: `retry_task` and
`complete_manual_task` both refuse it with `409 deposit_already_returned`,
because delivering it would hand the merchant the goods and their money. Every
exit is closed while the state says "in progress".

**Use `failed`, not `refunded`, and the contract is why.** The module README's
`status` row says: _"New values may be added — treat an unknown one as still in
flight."_ A client written today would therefore read a new `refunded` as **not
terminal** and poll forever, never settling with its own customer — strictly
worse for existing integrators than doing nothing. `failed` is already in the
published vocabulary, already documented as reachable "from any of the first
three", and already terminal. The money detail is carried by
`failure_reason: fulfillment_failed_refunded` and `refunded_usd`, which exist.

**The interaction that must not be missed.** `order_status._failure_reason`
tests `order.status == "failed"` **first** and returns `REASON_ORDER_FAILED`.
So setting the status naively collapses the reason to `order_failed` — "support
closed this by hand" — and destroys the "your money is back" signal in the same
commit that adds the status. The precedence has to be adjusted so a fully
settled order still reads `fulfillment_failed_refunded`.

**Rules:**

- **Only on a full settlement** (`refund.settled_in_full`, the same pure
  predicate the cancellation alert uses). A partial is a human mid-decision and
  the order is not over.
- **Only in the merchant arm.** The refund seam is already gated on
  `merchant_id`; retail must be byte-identical and the proof must fail if the
  gate is removed.
- Three consequences, all of which should be **verified rather than assumed**:
  the admin list shows a terminal status; `list_stuck_paid_orders` stops
  matching (its `STUCK_STATUSES` is `paid`/`fulfilling`/`fulfilled`), which is
  what silences the 05:30 alert **without** a gate; and the status move fires
  `order.status_changed`, so a webhook subscriber learns about the refund by
  push instead of by poll. Say in the README that this is now true — it
  currently says the opposite for this case.
- **Enumerate the siblings anyway.** M3b gated one alert and did not look for
  the others, which is why an owner found this one at 05:30 instead of a
  review. Name every job or query that reasons about "paid but not delivered"
  and say, for each, whether this change fixes it, whether it still needs
  something, or why it does not apply. A partial retail refund leaves
  `payment.status = "partially_refunded"` — check whether the order still nags,
  and report it either way rather than guessing.

- [ ] **Step 1: failing tests** — a fully refunded merchant order reaches
      `failed` and still reads `fulfillment_failed_refunded`; a partial does
      not move the status; retail is unchanged; the stuck-order query no longer
      returns it; the webhook fires.
- [ ] **Step 2-4:** FAIL → implement → pass, red observed per test.
- [ ] **Step 5: commit** `feat(api/merchants): a refunded order is over, and says so`

---

### Task 7: an order says where it came from

`orders.source` is `CHECK (source IN ('web','miniapp','bot','unknown'))`, so a
merchant order lands in `unknown` and the admin list shows «—».

**Rules:**

- Migration widens the vocabulary to include `merchant_api` **and**
  `merchant_panel` — the cabinet is M4 and a second migration for one string is
  waste, but the panel value must be unreachable until something sets it.
- `merchants.orders.place` sets `merchant_api`. The panel value stays unused,
  with a comment saying which milestone claims it.
- The admin list and detail render it; three locales.
- The column is client-declared for retail (`X-Yupay-Surface`) and an
  **operator's "where did this come from", never an authorisation input** — the
  existing comment on the column says so and stays true: the merchant value is
  set server-side, which is stronger, not weaker.

- [ ] commit `feat(api/merchants): a merchant order records the surface it came from`

---

## Self-review notes

- Ordering: 1 is the money rule and stands alone; 2 → 3 → 4 are the operator's
  page, in the order a person meets them (who is this, what happened, what do I
  do).
- **Task 6 reverses this plan's own out-of-scope note, on the owner's
  reasoning.** It originally said moving `order.status` was a contract change
  and a retail behaviour change, and that Task 3 removed the reason anyone
  wanted it. The owner asked the obvious question — _why is a refunded order
  still "in progress"?_ — and the note does not survive it: the justification
  for leaving the status alone is that an operator may still deliver, and for a
  refunded order every delivery path is **already refused** by
  `deposit_already_returned`. The narrow case is not the broad change the note
  declined. The contract risk is real and is answered by using `failed`, a value
  already published as terminal, instead of a new one the README tells clients
  to treat as still in flight.
- Also out of scope: M4's cabinet, and the Sentry gap the deploy exposed
  (`SENTRY_DSN` is unset on prod, so there is no error reporting at all).
