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

## Self-review notes

- Ordering: 1 is the money rule and stands alone; 2 → 3 → 4 are the operator's
  page, in the order a person meets them (who is this, what happened, what do I
  do).
- Out of scope: moving `order.status` for a terminal fulfilment failure. That is
  a contract change for `/merchant/v1` **and** a retail behaviour change, and
  Task 3 removes the reason anyone wanted it. If it is still wanted afterwards,
  it needs its own decision.
- Also out of scope: M4's cabinet, and the Sentry gap the deploy exposed
  (`SENTRY_DSN` is unset on prod, so there is no error reporting at all).
