# Affiliate admin — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin run the programme: approve or reject applications, issue codes and set their rates, suspend a partner, and settle withdrawal requests.

**Architecture:** An admin router in the `affiliate` module and three screens in the existing admin SPA. Nothing new is invented — the service layer already does all of this (`partners.approve`, `payouts.mark_paid`, and so on); this step exposes it and puts a person in front of it.

**Tech Stack:** FastAPI + `require_admin`; Vite + React 19 + React Router 7 in `apps/admin`.

**Spec:** `docs/superpowers/specs/2026-08-27-affiliate-program-design.md`
**Previous plans:** the five earlier `affiliate` plans.

**Plan 6 of 7.** Step 7 remains: DNS, TLS, Caddy, CI, deploy.

**After this step the feature is complete.** A partner can be recruited, approved, given a code, and paid — end to end, by a person, without a shell.

## Global Constraints

Carried forward. The ones that have bitten:

- Do not re-export a router from `affiliate.api` — `orders.service` and `payments.service` import that facade and a router there closes an import cycle. `api/v1` imports `affiliate.routes` directly.
- A row inserted under a `UNIQUE` goes **inside** `db.begin_nested()`.
- Measure coverage so the root `pyproject.toml` is read, or `COVERAGE_CORE=sysmon`.
- Coverage gate for this module is **95%**.
- **Card numbers are PII.** The admin who makes the transfer needs the full number; nobody else does, and no log line does.
- Commit after every green test run. **Do not push or deploy** without an explicit instruction.

## The one real decision in this step

**The admin who settles a payout must see the full card number** — they are typing it into a banking app. Every other surface masks it: the partner sees four digits, the list view shows four digits, the logs contain none.

So the full number is returned by exactly one endpoint, `GET /admin/affiliate/payouts/{id}`, which is a deliberate single door rather than a field on a list that a screenshot of the queue would leak. The list is what an admin looks at all day; the detail view is what they open when they are about to pay someone.

## Admin endpoints

| Method | Path                                         | Does                                   |
| ------ | -------------------------------------------- | -------------------------------------- |
| GET    | `/admin/affiliate/applications?status=`      | The queue, newest first                |
| POST   | `/admin/affiliate/applications/{id}/approve` | Approve, mint the link, send the email |
| POST   | `/admin/affiliate/applications/{id}/reject`  | Reject with a note                     |
| GET    | `/admin/affiliate/partners`                  | All partners, with their code counts   |
| POST   | `/admin/affiliate/partners/{id}/codes`       | Issue a code with its two rates        |
| PATCH  | `/admin/affiliate/codes/{id}`                | Change rates or deactivate             |
| POST   | `/admin/affiliate/partners/{id}/suspend`     | Switch a partner off                   |
| GET    | `/admin/affiliate/payouts?status=`           | The queue, masked                      |
| GET    | `/admin/affiliate/payouts/{id}`              | One request, **card unmasked**         |
| POST   | `/admin/affiliate/payouts/{id}/paid`         | Record the transfer                    |
| POST   | `/admin/affiliate/payouts/{id}/reject`       | Refuse and return the money            |

All behind `require_admin`, mounted the way `promo`'s admin router is.

---

### Task 1: Issuing and managing codes

**Files:** `affiliate/admin.py` (new), `affiliate/schemas.py`, tests.

**Interfaces:**

- `issue_code(db, *, partner_id, code, discount_percent, commission_percent) -> AffiliateCode`
- `update_code(db, *, code_id, discount_percent=None, commission_percent=None, active=None) -> AffiliateCode`
- `suspend_partner(db, *, partner_id) -> None`

- [ ] **Step 1: failing tests.** A code is normalised to uppercase before insert; a duplicate code is a conflict, not a crash; percentages outside 3–10 and 1–2 are refused **by the service with a readable message**, not only by the CHECK constraint — an admin typing 15 should be told the range, not shown a constraint name. Suspending a partner stops their code applying at checkout (assert through `resolve_code`), and revokes their sessions.

  That last one matters: a suspended partner whose panel session keeps working can still request a payout.

- [ ] **Step 2–4:** implement, green, commit.

---

### Task 2: The admin router

**Files:** `affiliate/routes.py`, `api/v1/__init__.py`, tests.

- [ ] **Step 1: failing tests.** Every admin path 401s without a token and 403s for a non-admin — enumerated from the live app, the way the partner routes are, so a route added later without `require_admin` fails here.
- [ ] **Step 2:** the list endpoint returns `card_last4`; the detail endpoint returns `card_number`. **A test asserts the list does not contain a full number** — that is the whole point of splitting them.
- [ ] **Step 3:** approve sends the email. Assert the send is attempted and that a send failure does not roll back the approval — an approved partner with an undelivered email is recoverable by re-sending; an approval lost because SMTP was down is not.
- [ ] **Step 4:** `make gen-api`, green, commit.

---

### Task 3: The applications screen

**Files:** `apps/admin/src/features/affiliate/ApplicationsPage.tsx`, router and nav entries.

- [ ] Queue with a pending count in the navigation — otherwise applications sit unnoticed, and an applicant's first experience of the programme is silence.
- [ ] Approve and reject, with a note field on reject.
- [ ] Follow `features/promo/PromoPage.tsx` for the shape; it is the closest existing screen.

---

### Task 4: The partners screen

**Files:** `apps/admin/src/features/affiliate/PartnersPage.tsx`

- [ ] List with status, code, both rates, and lifetime earnings.
- [ ] Issue a code: the form must state the allowed ranges **before** submission.
- [ ] Suspend, with a confirmation that says what it does — it stops their code working and signs them out, which is not obvious from the word.

---

### Task 5: The payouts screen

**Files:** `apps/admin/src/features/affiliate/PayoutsPage.tsx`

- [ ] Queue with a pending count.
- [ ] A detail view that fetches the full card number **on open**, not with the list.
- [ ] Mark paid / reject, each with a note.
- [ ] A confirmation before marking paid. It is the only irreversible action in the programme: rejecting returns the money, but "paid" says a transfer happened and there is no undo.

---

## Definition of Done for this plan

- [ ] Full backend suite green; module coverage ≥ 95%.
- [ ] Admin SPA typecheck, lint and tests clean.
- [ ] Every admin route refuses a non-admin, asserted by enumeration.
- [ ] The payouts list contains no full card number, asserted.
- [ ] `make gen-api`; `npx prettier --check .` clean on tracked files.
- [ ] Module README and the module map updated.
- [ ] Nothing pushed or deployed.

## Not in this plan

Step 7: DNS for `partners.yupay.uz`, its TLS certificate, the Caddy site block, a Dockerfile and compose service for the new app, CI build and deploy.
