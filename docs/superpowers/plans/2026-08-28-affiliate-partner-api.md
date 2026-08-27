# Partner authentication and panel API — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let someone apply to become a partner, let an admin-approved partner set a password and sign in, and give them an API for their codes, statistics, balance and withdrawals.

**Architecture:** A partner authenticates with its own token kind and its own session table, but reuses the project's existing cryptography rather than growing a second implementation of it. Every panel endpoint resolves the partner from the token and scopes its query to that partner — no endpoint takes a partner id from the caller.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), Pydantic v2, argon2id via `auth.security`, EdDSA JWT via `auth.jwt`.

**Spec:** `docs/superpowers/specs/2026-08-27-affiliate-program-design.md`
**Previous plans:** `2026-08-27-affiliate-core.md`, `2026-08-28-affiliate-discount.md`, `2026-08-28-affiliate-checkout-field.md`

**Plan 4 of 7.** Steps 5–7 remain: `apps/partners`, admin screens, infrastructure.

## Global Constraints

Carried forward from the earlier plans; the ones that bit are repeated.

- `mypy --strict` no worse than the `main` baseline (1026 as of 2026-08-27). A `-> str` function returning a model attribute **is** a new error — return the model.
- Import `wallet.service`, not `wallet.api`. Do not re-export a router from `affiliate.api`: `orders.service` and `payments.service` import that facade, and a router there closes an import cycle. `api/v1` imports `affiliate.routes` directly.
- A row inserted under a `UNIQUE` must be added **inside** `db.begin_nested()`, not before it. Added before, a failed flush poisons the whole session with `PendingRollbackError`.
- Alembic revision ids ≤ 32 characters.
- Coverage gate for this module is **95%**.
- Money is `Decimal`. **Card numbers are PII and must never reach a log line.**
- Commit after every green test run. **Do not push or deploy** without an explicit instruction.

## Security decisions

**Partner tokens get their own `kind`.** `auth.jwt.verify` compares `kind` against an expected value and rejects a mismatch, so minting partner tokens as `"partner_access"` makes a partner token structurally unusable on a buyer endpoint and a buyer token unusable on a partner one. The alternative — reusing `"access"` and relying on a partner id not being found in `users` — works today by accident and stops working the moment anything looks up a subject less strictly.

**No second implementation of password hashing or token signing.** `auth.security.hash_password` / `verify_password` (argon2id, already tuned, already behind a `CapacityLimiter(4)` so a login burst cannot eat 2.5 GB) and `auth.jwt` are used as they are. A second hand-rolled auth is where holes live.

**Every panel endpoint scopes to the token's partner.** No endpoint accepts a `partner_id` argument. This is the rule that keeps one partner from reading another's earnings, and it is worth stating because a "list commissions for partner X" signature is the natural thing to write and is wrong here.

**The set-password link is single-use and short-lived.** It is a `password_reset`-shaped token bound to the partner id, consumed on use. An approval email that stays valid forever is a permanent backdoor into a money account.

**Applications are public and therefore rate-limited**, on both axes: per IP and per email.

## File Structure

**Created:**

| File                                                        | Responsibility                                                           |
| ----------------------------------------------------------- | ------------------------------------------------------------------------ |
| `apps/api/src/yupay/modules/affiliate/partners.py`          | Apply, approve, set password, sign in, rotate, sign out.                 |
| `apps/api/src/yupay/modules/affiliate/panel.py`             | The reads a signed-in partner makes: codes, stats, balance, commissions. |
| `apps/api/src/yupay/modules/affiliate/payouts.py`           | Requesting a withdrawal, and the ledger reservation behind it.           |
| `apps/api/src/yupay/modules/affiliate/deps.py`              | `current_partner` FastAPI dependency.                                    |
| `apps/api/tests/integration/test_affiliate_partner_auth.py` | Auth, including the negative cases.                                      |
| `apps/api/tests/integration/test_affiliate_panel.py`        | Panel reads and payout requests.                                         |

**Modified:**

| File                                                    | Change                                                          |
| ------------------------------------------------------- | --------------------------------------------------------------- |
| `apps/api/src/yupay/modules/auth/jwt.py`                | `"partner_access"` in `TokenKind`; `mint_partner_access`.       |
| `apps/api/src/yupay/modules/affiliate/schemas.py`       | Request/response models for everything below.                   |
| `apps/api/src/yupay/modules/affiliate/routes.py`        | The partner router.                                             |
| `apps/api/src/yupay/modules/affiliate/ledger.py`        | `post_payout_hold`, `post_payout_paid`, `post_payout_rejected`. |
| `apps/api/src/yupay/modules/notifications/templates.py` | The approval email.                                             |
| `apps/api/src/yupay/core/config.py`                     | Partner token TTLs.                                             |

---

### Task 1: A partner token kind

**Files:**

- Modify: `apps/api/src/yupay/modules/auth/jwt.py`
- Modify: `apps/api/src/yupay/core/config.py`
- Test: `apps/api/tests/integration/test_affiliate_partner_auth.py`

**Interfaces:**

- Produces `mint_partner_access(*, sub: str, sid: str, settings: Settings | None = None) -> str`, and `"partner_access"` as a `TokenKind`.

- [ ] **Step 1: Write the failing test**

```python
async def test_a_partner_token_is_not_a_buyer_token() -> None:
    """The two token kinds must not be interchangeable.

    Reusing "access" for partners would work today only because a partner id is
    not found in `users` — an accident, not a boundary.
    """
    from yupay.core.errors import UnauthorizedError
    from yupay.modules.auth import jwt as authjwt

    token = authjwt.mint_partner_access(sub="p-1", sid="s-1")
    assert authjwt.verify(token, expected_kind="partner_access").sub == "p-1"
    with pytest.raises(UnauthorizedError):
        authjwt.verify(token, expected_kind="access")

    buyer = authjwt.mint_access(sub="u-1", sid="s-1")
    with pytest.raises(UnauthorizedError):
        authjwt.verify(buyer, expected_kind="partner_access")
```

- [ ] **Step 2: Run it; expect an AttributeError on `mint_partner_access`.**

- [ ] **Step 3: Add the kind and the minter**

Extend `TokenKind` with `"partner_access"`, and add beside `mint_access`:

```python
def mint_partner_access(
    *,
    sub: str,
    sid: str,
    settings: Settings | None = None,
) -> str:
    """Issue a short-lived access JWT for an authenticated **partner**.

    A distinct ``kind`` from ``mint_access`` on purpose: ``verify`` rejects a
    kind mismatch, so this token cannot be presented to a buyer endpoint and a
    buyer's token cannot be presented to the panel. Relying instead on a
    partner id not existing in ``users`` would be an accident that holds only
    until something resolves a subject less strictly.
    """
```

Add `affiliate_access_ttl_seconds` (default 900) and `affiliate_refresh_ttl_seconds` (default `60 * 60 * 24 * 30`) to `Settings`.

- [ ] **Step 4: Green, lint, typecheck, commit.**

---

### Task 2: Apply, approve, set a password

**Files:**

- Create: `apps/api/src/yupay/modules/affiliate/partners.py`
- Modify: `apps/api/src/yupay/modules/notifications/templates.py`
- Test: `apps/api/tests/integration/test_affiliate_partner_auth.py`

**Interfaces:**

- `submit_application(db, *, email, display_name, contact, channel) -> AffiliatePartner`
- `approve(db, *, partner_id, admin_id) -> str` — returns the single-use set-password token
- `reject(db, *, partner_id, admin_id, note) -> None`
- `set_password(db, *, token, password) -> None`

- [ ] **Step 1: Write the failing tests**

Cover: an application lands in `pending`; a second application from the same email does not create a second row (`UNIQUE(email)`) and does not leak whether the first exists; approving moves it to `active` and yields a token; the token sets a password once and is refused the second time; an expired token is refused; setting a password on a `pending` or `rejected` partner is refused.

That last one matters: an approval token plus a later rejection must not still open the account.

- [ ] **Step 2–4:** implement, green, commit.

`approve` mints an `password_reset`-kind token bound to the partner id and sends the approval email. Store nothing but the hash of the token's `jti` so it can be consumed exactly once — the same shape `auth` uses for its reset links; read `auth/service.py` for it rather than inventing a second one.

---

### Task 3: Sign in, rotate, sign out

**Files:**

- Modify: `apps/api/src/yupay/modules/affiliate/partners.py`
- Create: `apps/api/src/yupay/modules/affiliate/deps.py`
- Test: `apps/api/tests/integration/test_affiliate_partner_auth.py`

**Interfaces:**

- `login(db, *, email, password) -> tuple[str, str]` — `(access, refresh)`
- `rotate(db, *, refresh_token) -> tuple[str, str]`
- `logout(db, *, refresh_token) -> None`
- `deps.current_partner` — FastAPI dependency returning `AffiliatePartner`

- [ ] **Step 1: Write the failing tests**

Cover: a correct password returns a pair; a wrong one does not, **and takes the same shape of answer as an unknown email** — a login that distinguishes them is a partner-email oracle; a `suspended` or `pending` partner cannot log in even with the right password; a refresh token rotates and the old one stops working; a logged-out token stops working; `current_partner` rejects a buyer's access token.

- [ ] **Step 2–4:** implement, green, commit.

`login` runs `verify_password` even when the email is unknown, against a dummy hash, so the timing does not answer the question the response refuses to. `auth/service.py` already does this — copy the shape.

Sessions rotate: each refresh revokes the row it came from and writes a new one. A refresh token presented twice must fail, because the second presentation is either a bug or a stolen token.

---

### Task 4: Panel reads

**Files:**

- Create: `apps/api/src/yupay/modules/affiliate/panel.py`
- Test: `apps/api/tests/integration/test_affiliate_panel.py`

**Interfaces:**

- `profile(db, *, partner) -> PartnerProfileOut` — the partner plus their codes
- `stats(db, *, partner_id, period) -> PartnerStatsOut` — `period` is `day | week | month | year`
- `balance(db, *, partner_id, currency) -> PartnerBalanceOut` — available and held
- `commissions(db, *, partner_id, limit, offset) -> PartnerCommissionListOut`

- [ ] **Step 1: Write the failing tests**

The two that carry weight:

**Balance comes from the ledger, not from summing the table.** Assert that `available` equals the `partner_balance` account balance and `held` the `partner_pending` one, and that a matured commission moves the number between them. This is the property the whole three-account split exists for, and a panel that recomputed it from `affiliate_commissions` would quietly reintroduce the second source of truth.

**A partner sees only their own numbers.** Seed two partners with commissions and assert each sees only theirs. Write it even though the query is scoped by construction — this is the assertion that fails loudly if someone later adds a `partner_id` parameter.

Also: the four periods bucket correctly; an empty partner reads as zeroes rather than erroring.

- [ ] **Step 2–4:** implement, green, commit.

---

### Task 5: Payout requests

**Files:**

- Create: `apps/api/src/yupay/modules/affiliate/payouts.py`
- Modify: `apps/api/src/yupay/modules/affiliate/ledger.py`
- Test: `apps/api/tests/integration/test_affiliate_panel.py`

**Interfaces:**

- `request_payout(db, *, partner_id, amount, currency, card_number, card_holder) -> AffiliatePayout`
- `ledger.post_payout_hold(db, *, payout_id, partner_id, amount, currency) -> None`

Admin-side approval, rejection and marking paid land in step 6 with the admin screens; the two postings they need (`post_payout_paid`, `post_payout_rejected`) are written here so all five affiliate postings live in one file.

- [ ] **Step 1: Write the failing tests**

**The one that matters most: two concurrent requests cannot overdraw.** Request the full balance twice; the second must fail. The reservation is what makes this true — `D partner_payout_hold / C partner_balance` moves the money out of `partner_balance` at request time, so the second request's balance check sees the reduced figure rather than the original.

Also: a request below `affiliate_min_payout` is refused; a request above the available balance is refused; held (unmatured) commission is not withdrawable; the card number never appears in any log record emitted during the request.

That last one is a real test, not a formality — `CLAUDE.md` §9 forbids PII in logs, and a card number is the worst thing in this module.

- [ ] **Step 2–4:** implement, green, commit.

---

### Task 6: Routes

**Files:**

- Modify: `apps/api/src/yupay/modules/affiliate/routes.py`
- Modify: `apps/api/src/yupay/modules/affiliate/schemas.py`
- Test: `apps/api/tests/integration/test_affiliate_partner_auth.py`, `test_affiliate_panel.py`

| Method | Path                           | Auth          | Guard                          |
| ------ | ------------------------------ | ------------- | ------------------------------ |
| POST   | `/affiliate/applications`      | public        | `ip_guard` on IP **and** email |
| POST   | `/affiliate/auth/set-password` | token in body | `ip_guard`                     |
| POST   | `/affiliate/auth/login`        | public        | `ip_guard` on IP **and** email |
| POST   | `/affiliate/auth/refresh`      | refresh token | —                              |
| POST   | `/affiliate/auth/logout`       | refresh token | —                              |
| GET    | `/affiliate/me`                | partner       | —                              |
| GET    | `/affiliate/stats`             | partner       | —                              |
| GET    | `/affiliate/balance`           | partner       | —                              |
| GET    | `/affiliate/commissions`       | partner       | —                              |
| GET    | `/affiliate/payouts`           | partner       | —                              |
| POST   | `/affiliate/payouts`           | partner       | idempotency key                |

- [ ] **Step 1:** failing route tests (auth required on every partner path — assert 401 without a token on each, in a loop, so a route added later without auth fails this).
- [ ] **Step 2:** schemas, then routes.
- [ ] **Step 3:** `make gen-api`, `npx prettier --check .`, full backend suite.
- [ ] **Step 4:** README, module map, commit.

---

## Definition of Done for this plan

- [ ] Full backend suite green.
- [ ] Coverage of `yupay/modules/affiliate/*` ≥ 95%.
- [ ] `ruff` clean; `mypy` no worse than baseline.
- [ ] Every partner route 401s without a token, asserted in a loop over the route table.
- [ ] A card number appears in no log record.
- [ ] `make gen-api` run; `npx prettier --check .` clean on tracked files.
- [ ] Module README updated with the auth model and the payout postings.
- [ ] Nothing pushed or deployed.

## Not in this plan

Admin approval screens (step 6) — until then a partner is approved by calling the service from a shell or by an admin route added in step 6. `apps/partners` (step 5). Infrastructure (step 7).
