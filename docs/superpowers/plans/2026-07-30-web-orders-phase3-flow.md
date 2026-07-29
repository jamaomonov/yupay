# Web Orders — Phase 3 (Post-payment + guest orders + enforced verification) Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After paying, the customer lands on their live order; guests get a persistent order list that migrates into their account on login; and email verification is enforced at login (with existing users grandfathered) so the claim is trustworthy.

**Architecture:** Backend enforces `email_verified_at` at password login (Telegram exempt), stops auto-logging-in on register, auto-logs-in on verify, and adds resend; a data migration grandfathers existing users. A new `POST /orders/claim` reassigns guest orders to the verified user. Payment intents get a `return_url` pointing at the order page (from `web_base_url`, client-supplied value validated same-origin). Web mints a `Guest` token for guest order views, saves guest orders to `localStorage`, shows the guest list, and calls claim in the single post-auth funnel.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2 / Alembic / Pydantic v2; Next.js 15 web (next-intl, TanStack Query); Vitest + Playwright.

## Global Constraints

- **Enforcement is password-login-only.** `login_telegram_*` and the guest/admin-dev paths must NOT be gated (Telegram users have no email to verify). The gate lives in `login_password` only.
- **No existing user may be locked out:** the grandfather migration sets `email_verified_at = now()` for every user where it is `NULL`, in the SAME change as the login gate.
- **Never trust an unverified email for a claim.** `POST /orders/claim` reassigns only where `guest_email == user.email` AND `user_id IS NULL` AND `user.email_verified_at IS NOT NULL`, in one UPDATE satisfying the `ck_orders_actor_exclusive` XOR CHECK.
- **return_url is UX, not a security boundary** (payment truth is the webhook), but a client-supplied `return_url` must be validated same-origin as `settings.web_base_url` to avoid open-redirect.
- All write endpoints keep `Idempotency-Key` support where the module already uses it; claim is idempotent by nature (re-running reassigns nothing).
- `mypy apps` 0 errors; ruff+prettier clean; `tsc` clean web; auth + orders test coverage stays green (auth is sensitive — cover the new branches). OpenAPI regenerated, no drift.
- i18n: every new user-facing string in ru/en/uz (`web.json`) in the same task.
- Money/PII rules unchanged; never log the guest email.

---

### Task 1: Backend — enforce email verification at password login + grandfather migration

**Files:**

- Modify: `apps/api/src/yupay/core/errors.py` (add `EmailUnverifiedError`)
- Modify: `apps/api/src/yupay/modules/auth/service.py` (`login_password` — gate on `email_verified_at`)
- Create: `apps/api/alembic/versions/XXXX_grandfather_email_verified.py` (data migration)
- Test: `apps/api/tests/integration/test_auth_verification_gate.py` (create)

**Interfaces:**

- Produces: `EmailUnverifiedError` (403, `type_uri=".../email-unverified"`); `login_password` raises it for unverified users.

- [ ] **Step 1: Add the error type**

In `apps/api/src/yupay/core/errors.py`, after `ForbiddenError`:

```python
class EmailUnverifiedError(AppError):
    """Login attempted before the account's email was verified."""

    status_code = 403
    type_uri = "https://app.yupay.uz/errors/email-unverified"
    title = "Email not verified"
```

- [ ] **Step 2: Write the failing test**

Create `apps/api/tests/integration/test_auth_verification_gate.py`:

```python
"""Password login is blocked until the account's email is verified."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_login_blocked_until_verified(integration_client: AsyncClient) -> None:
    email = "verify-gate@example.com"
    reg = await integration_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "s3cret-passw0rd", "locale": "ru"},
    )
    assert reg.status_code in (200, 202), reg.text
    # Registration does NOT hand back a session anymore (Task 2 enforces this;
    # this task only asserts login is blocked while unverified).
    login = await integration_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "s3cret-passw0rd"},
    )
    assert login.status_code == 403, login.text
    assert login.json()["type"].endswith("/email-unverified")
```

- [ ] **Step 3: Run and watch fail**

Run: `cd apps/api && uv run pytest tests/integration/test_auth_verification_gate.py -v`
Expected: FAIL — login currently returns 200/201 (no gate). (If register still returns tokens at this point, the 403 assert still fails on login — that's the target.)

- [ ] **Step 4: Gate `login_password`**

In `apps/api/src/yupay/modules/auth/service.py`, in `login_password` (after the password is verified and the user is loaded, before `_open_session`), add:

```python
    if user.email_verified_at is None:
        raise EmailUnverifiedError(
            "Confirm your email address before signing in."
        )
```

Import `EmailUnverifiedError` from `yupay.core.errors`. Do NOT touch `login_telegram_*`, `login_guest`, or `login_admin_dev` — Telegram/guest/dev users are exempt.

- [ ] **Step 5: Write the grandfather migration**

Create a new Alembic revision (`cd apps/api && uv run alembic revision -m "grandfather email_verified"` then fill it), setting existing users verified so enforcement is forward-only:

```python
def upgrade() -> None:
    op.execute(
        "UPDATE users SET email_verified_at = now() "
        "WHERE email_verified_at IS NULL AND deleted_at IS NULL"
    )


def downgrade() -> None:
    # Non-reversible data backfill; verification state is not restored on downgrade.
    pass
```

Use the current head as `down_revision` (check `uv run alembic heads`). Add a docstring explaining the one-time forward-only backfill.

- [ ] **Step 6: Make the test pass (verify path)**

The test above asserts the block. Extend it to prove verification unblocks login — append:

```python
    from yupay.modules.auth import jwt as authjwt
    from yupay.core.config import get_settings

    # Mint a verify token the way register's email does, then verify.
    # (get the user's id via the admin/db fixture the suite already uses; if the
    # suite exposes a helper to read a user by email, use it — otherwise decode
    # from the verify email captured by the test mailer.)
```

If the suite has no easy id lookup, instead drive verification through the real endpoint using the token the test mailer captured (the integration suite uses a capturing mailer — check `conftest.py` for `sent_emails`/mailhog). Assert that after `POST /auth/verify-email` the same login now returns a session (200 with `access_token`). Keep the test honest — it must exercise the real verify → login unblock.

- [ ] **Step 7: Run tests + migration check + lint/type**

Run: `cd apps/api && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head` (in a test DB / or rely on testcontainers migration in the suite) to confirm the migration applies. Then `uv run pytest tests/integration/test_auth_verification_gate.py tests/integration/test_auth_*.py -v`, `uv run ruff check src tests`, and (repo root) `uv run mypy apps`.
Expected: PASS, clean. (Existing auth tests that logged in a freshly-registered user WILL break here — that's expected; fix them in this task to verify first, per Step 8.)

- [ ] **Step 8: Fix existing auth tests broken by the gate**

Any existing test that registers then immediately logs in / uses the session must now verify first. Update those tests (do NOT weaken them) to call the verify step. Grep: `cd apps/api && grep -rln "auth/register\|register_user\|login_password" tests/`. For each, insert verification before the authenticated action. Run the full auth suite green.

- [ ] **Step 9: Commit**

```bash
git add apps/api/src/yupay/core/errors.py apps/api/src/yupay/modules/auth/service.py apps/api/alembic/versions/ apps/api/tests/
git commit -m "feat(api/auth): enforce email verification at password login

login_password now rejects unverified accounts with a distinct
email-unverified 403 (Telegram/guest/dev logins exempt). A forward-only
migration grandfathers all existing users as verified so none are locked out.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Backend — register returns no session; verify auto-logs-in; resend endpoint

**Files:**

- Modify: `apps/api/src/yupay/modules/auth/schemas.py` (`RegisterOut`, `ResendVerificationIn`)
- Modify: `apps/api/src/yupay/modules/auth/routes.py` (register response, verify response, new resend route)
- Modify: `apps/api/src/yupay/modules/auth/service.py` (verify issues a session; resend service)
- Regenerate: `docs/api/openapi.json`
- Test: extend `tests/integration/test_auth_verification_gate.py` + auth route tests

**Interfaces:**

- Produces: `POST /auth/register` → `RegisterOut{status:"verification_required", email}` (no tokens); `POST /auth/verify-email` → `TokensOut` (+ refresh cookie); `POST /auth/resend-verification` → 204.

- [ ] **Step 1: Add schemas**

In `apps/api/src/yupay/modules/auth/schemas.py`:

```python
class RegisterOut(BaseModel):
    """Registration accepted; the user must verify their email before login."""

    status: Literal["verification_required"] = "verification_required"
    email: EmailStr


class ResendVerificationIn(BaseModel):
    email: EmailStr
```

Add both to `__all__`. Import `Literal` if not present.

- [ ] **Step 2: Write failing tests**

Extend the gate test: assert `register` returns `{"status": "verification_required"}` and NO `access_token`; assert `POST /auth/verify-email` returns a session (`access_token` present); assert `POST /auth/resend-verification` for the unverified email returns 204, and for an unknown email ALSO returns 204 (no user enumeration).

- [ ] **Step 3: Register returns no session**

In `apps/api/src/yupay/modules/auth/routes.py` `register_route`: change `response_model` to `RegisterOut`, keep `status_code=201`, and return `RegisterOut(email=<normalised email>)` instead of `_session_response(...)`. The account + verify-email send still happen in `register_user` (unchanged). Do NOT set the refresh cookie on register anymore.

- [ ] **Step 4: Verify auto-logs-in**

In `verify_email_route` + service: after `user.email_verified_at` is set, open a session and return `TokensOut` (+ set the refresh cookie via the same helper login uses — `_session_response`/`_open_session`). Change the route `response_model=TokensOut`, drop the 204. The service `verify_email` should return the user (or session) so the route can issue tokens.

- [ ] **Step 5: Resend endpoint**

Add `POST /auth/resend-verification` (rate-limited like other unauthenticated auth routes — mirror `forgot_route`'s limiter), body `ResendVerificationIn`, `status_code=204`. Service `resend_verification(db, *, email, settings, web_base)`: look up the user by email; if found AND `email_verified_at IS NULL`, mint a verify token + send the email (same helper as register); ALWAYS return None (204) regardless, so it never reveals whether the email exists or its state.

- [ ] **Step 6: Regenerate + tests + lint/type**

Run: `make gen-api`; `cd apps/api && uv run pytest tests/integration/test_auth_verification_gate.py tests/integration/test_auth_*.py -v`; `uv run ruff check src tests`; repo-root `uv run mypy apps`.
Expected: PASS, clean, openapi shows `RegisterOut` + resend route + verify→TokensOut.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/yupay/modules/auth/ apps/api/tests/ docs/api/openapi.json
git commit -m "feat(api/auth): register requires verification; verify auto-logs-in; add resend

Register no longer issues a session (returns verification_required); verify-email
now returns a session so the link flow ends logged-in; new rate-limited
resend-verification endpoint that never enumerates users.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Backend — `POST /orders/claim`

**Files:**

- Modify: `apps/api/src/yupay/modules/orders/service.py` (`claim_orders_for_user`)
- Modify: `apps/api/src/yupay/modules/orders/routes.py` (`POST /orders/claim`)
- Modify: `apps/api/src/yupay/modules/orders/schemas.py` (`ClaimOut`)
- Modify: `apps/api/src/yupay/modules/orders/api.py` (export)
- Regenerate: `docs/api/openapi.json`
- Test: `apps/api/tests/integration/test_orders_claim.py` (create)

**Interfaces:**

- Produces: `claim_orders_for_user(db, *, user) -> int`; `POST /orders/claim` → `ClaimOut{claimed: int}`.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/integration/test_orders_claim.py`: create a guest order with `guest_email == <email>`; register+verify+login a user with that same email; `POST /api/v1/orders/claim` (Bearer); assert `200 {"claimed": 1}`; assert the order now has `user_id == user.id` and appears in `GET /orders`; assert a second claim returns `{"claimed": 0}` (idempotent); assert an order with a DIFFERENT guest_email is NOT claimed.

- [ ] **Step 2: Run and watch fail**

Run: `cd apps/api && uv run pytest tests/integration/test_orders_claim.py -v`
Expected: FAIL (404/route missing).

- [ ] **Step 3: Service**

In `apps/api/src/yupay/modules/orders/service.py`:

```python
async def claim_orders_for_user(db: AsyncSession, *, user: User) -> int:
    """Reassign the user's guest orders to their account.

    Reassigns every order where ``guest_email`` equals the user's email, the
    order is still a guest order (``user_id IS NULL``), and the user's email is
    verified. Sets ``user_id`` and nulls ``guest_email`` in one statement so the
    ``ck_orders_actor_exclusive`` XOR CHECK always holds. Idempotent. Returns the
    number of orders claimed.
    """
    if user.email_verified_at is None:
        return 0
    result = await db.execute(
        update(Order)
        .where(
            Order.user_id.is_(None),
            func.lower(Order.guest_email) == user.email.lower(),
        )
        .values(user_id=user.id, guest_email=None)
    )
    return result.rowcount or 0
```

(Import `update`, `func` from sqlalchemy; `Order`, `User` as already used. `guest_email` is CITEXT so the compare is case-insensitive already — `func.lower` is belt-and-suspenders and harmless.)

- [ ] **Step 4: Schema + route + export**

`schemas.py`: `class ClaimOut(BaseModel): claimed: int` (+ `__all__`). `routes.py`, on the `/orders` router:

```python
@router.post("/claim", response_model=ClaimOut, summary="Claim guest orders for the logged-in user")
async def claim_orders_route(
    db: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
) -> ClaimOut:
    count = await svc.claim_orders_for_user(db, user=user)
    return ClaimOut(claimed=count)
```

Export `ClaimOut` + `claim_orders_for_user` via `orders/api.py`.

- [ ] **Step 5: Regenerate + tests + lint/type**

`make gen-api`; `uv run pytest tests/integration/test_orders_claim.py -v`; ruff; repo-root `uv run mypy apps`.
Expected: PASS, clean, `/orders/claim` in openapi.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/yupay/modules/orders/ apps/api/tests/integration/test_orders_claim.py docs/api/openapi.json
git commit -m "feat(api/orders): POST /orders/claim — migrate guest orders to the user

Reassigns guest orders whose guest_email matches the (verified) user's email to
their account in one UPDATE that preserves the actor XOR constraint. Idempotent.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Backend — return_url from `web_base_url` + same-origin validation

**Files:**

- Modify: `apps/api/src/yupay/modules/payments/service.py:168-172` (default return_url from settings)
- Modify: `apps/api/src/yupay/modules/payments/gateways/octo.py:303` (octo default)
- Modify: `apps/api/src/yupay/modules/payments/service.py` (validate client return_url same-origin)
- Test: `apps/api/tests/integration/test_payments_return_url.py` (create or extend a payments test)

**Interfaces:**

- Produces: a `_safe_return_url(candidate: str | None, settings) -> str` helper; intents use the web order page as the default/validated return.

- [ ] **Step 1: Write the failing test**

Assert: creating an intent with no `return_url` uses a URL under `settings.web_base_url` (not the old `app.yupay.uz/checkout/return`); creating one with a `return_url` on a foreign origin (`https://evil.example/x`) is rejected (422) or coerced to the safe default (pick reject → 422 `ValidationError`); a same-origin `return_url` under `web_base_url` is accepted verbatim.

- [ ] **Step 2: Implement the helper + wire it**

In `payments/service.py`, add:

```python
def _safe_return_url(candidate: str | None, settings: Settings) -> str:
    """Resolve the acquirer return URL, defaulting to the web order surface and
    rejecting any client-supplied URL that isn't same-origin as web_base_url."""
    base = (settings.web_base_url or settings.base_url).rstrip("/")
    if not candidate:
        return f"{base}/checkout/return"
    from urllib.parse import urlparse

    want, got = urlparse(base), urlparse(candidate)
    if (got.scheme, got.netloc) != (want.scheme, want.netloc):
        raise ValidationError("return_url must be on the storefront origin")
    return candidate
```

Replace the hardcoded default at service.py:171 with `_safe_return_url(return_url, s)`. In `octo.py:303`, replace `return_url or s.telegram_miniapp_url` with just `return_url` (it now always arrives resolved from the service).

- [ ] **Step 3: Tests + lint/type + regen (no schema change expected) + commit**

Run the new test, ruff, repo-root mypy. `make gen-api` (should be no drift — no schema change). Commit:

```bash
git add apps/api/src/yupay/modules/payments/ apps/api/tests/
git commit -m "fix(api/payments): return to the storefront order page after paying

Default the acquirer return_url to the web storefront (from web_base_url) and
validate any client-supplied return_url is same-origin, closing the 'lands on
the game page' dead-end and preventing open redirects.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Web — guest order-view auth (Guest token) + return_url + guest-orders localStorage

**Files:**

- Create: `apps/web/src/lib/guest-orders.ts` (localStorage helpers)
- Modify: `apps/web/src/components/order/OrderStatus.tsx` (mint + send Guest token for guests)
- Modify: `apps/web/src/components/store/PurchasePanel.tsx` (send `return_url`; save guest order)
- Test: `apps/web/src/lib/guest-orders.test.ts`

**Interfaces:**

- Produces: `saveGuestOrder(entry)`, `listGuestOrders(): GuestOrder[]`, `removeGuestOrders(orderIds: string[])`, `GuestOrder` type. OrderStatus authorizes guest fetches with a minted `Guest` token.

- [ ] **Step 1: Write failing localStorage tests**

Create `apps/web/src/lib/guest-orders.test.ts` (jsdom): `saveGuestOrder` appends + dedupes by `orderId`, caps at (say) 50 newest; `listGuestOrders` returns newest-first; `removeGuestOrders` drops the given ids; corrupt JSON yields `[]` (never throws).

- [ ] **Step 2: Implement `guest-orders.ts`**

```typescript
const KEY = "yupay.web.guest_orders";
const CAP = 50;

export interface GuestOrder {
  orderId: string;
  email: string;
  brandSlug: string;
  brandName: string;
  createdAt: string; // ISO
}

export function listGuestOrders(): GuestOrder[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    const arr = raw ? (JSON.parse(raw) as GuestOrder[]) : [];
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

export function saveGuestOrder(entry: GuestOrder): void {
  if (typeof window === "undefined") return;
  const existing = listGuestOrders().filter((o) => o.orderId !== entry.orderId);
  const next = [entry, ...existing].slice(0, CAP);
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* storage blocked — ignore */
  }
}

export function removeGuestOrders(orderIds: string[]): void {
  if (typeof window === "undefined") return;
  const drop = new Set(orderIds);
  const next = listGuestOrders().filter((o) => !drop.has(o.orderId));
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* ignore */
  }
}
```

- [ ] **Step 3: Guest order-view auth in OrderStatus**

In `apps/web/src/components/order/OrderStatus.tsx`, for a guest (an `email` prop and no logged-in `user`), mint a `Guest` token once (`mintGuestToken(email)` from `@/lib/guest`) and send it: the order + deliveries `apiFetch` calls must include `Authorization: Guest <token>` alongside `X-Guest-Email`. Use `opts.anonymous: true` so `apiFetch` doesn't overwrite Authorization with a stale Bearer, and pass the header explicitly. Mint the token in a `useQuery`/`useMemo` keyed on email (cache it; it's short-lived, re-mint on demand). Do NOT change the logged-in (Bearer) path. This fixes the cold-link 401.

- [ ] **Step 4: PurchasePanel — send return_url + save guest order**

In `apps/web/src/components/store/PurchasePanel.tsx` `pay()`:

- Add `return_url` to the intent body: `${window.location.origin}${pathFor(locale, \`/orders/${order.id}${emailSuffix}\`)}`(absolute URL to the order page; includes`?email=` for guests).
- For the guest branch, before `window.location.href = intent.intent_url` (line ~512) AND before the mock `setDone` (line ~515), call `saveGuestOrder({ orderId: order.id, email, brandSlug: selProduct.brand.slug, brandName: selProduct.brand.name, createdAt: new Date().toISOString() })`.

- [ ] **Step 5: Tests + typecheck + commit**

Run: `pnpm --filter @yupay/web exec vitest run src/lib/guest-orders.test.ts && pnpm --filter @yupay/web exec tsc --noEmit`. eslint the changed files.

```bash
git add apps/web/src/lib/guest-orders.ts apps/web/src/lib/guest-orders.test.ts apps/web/src/components/order/OrderStatus.tsx apps/web/src/components/store/PurchasePanel.tsx
git commit -m "feat(web/orders): guest order auth + return_url + persist guest orders

Order page mints a Guest token from the email so cold guest links load;
checkout sends return_url to the order page and records guest orders in
localStorage for the guest order list.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 6: Controller Playwright verification** — NOTE: after review, verify a guest order link loads WITHOUT the earlier route-injection hack (the app now mints its own Guest token), and that post-payment (mock) lands on the order page.

---

### Task 6: Web — guest orders list + claim on login + verify/resend UX + i18n

**Files:**

- Modify: `apps/web/src/app/[locale]/account/orders/page.tsx` (guest → localStorage list)
- Modify: `apps/web/src/lib/auth.tsx` (`afterTokens` → claim + clear localStorage; register flow change; login `email_unverified` handling)
- Modify: the login/register form component(s) (verify-required + resend UX) — locate via `openLogin`/auth modal
- Modify: `packages/i18n/locales/{ru,en,uz}/web.json` (`orders`/`auth` strings)
- Test: `apps/web/src/app/[locale]/account/orders/*.test.tsx` or a component test for the guest list

**Interfaces:**

- Consumes: `listGuestOrders`/`removeGuestOrders` (Task 5), `POST /orders/claim`, `POST /auth/resend-verification`, the new register/verify responses (Task 2).

- [ ] **Step 1: i18n keys (ru/en/uz)**

Add under `orders`: `guestListTitle`, `guestListEmpty`, `guestListHint` ("Заказы на этом устройстве"). Under `auth`: `verifyRequiredTitle`, `verifyRequiredBody` ("Мы отправили ссылку на {email}…"), `resend`, `resendSent`, `loginUnverified` ("Подтвердите email, чтобы войти"), `checkEmail`. Provide EN + RU + UZ values verbatim; run the i18n parity check.

- [ ] **Step 2: Guest orders list**

In `account/orders/page.tsx`: instead of bouncing a guest to login, when `!user && !authLoading` render the `listGuestOrders()` entries — each a card linking to `pathFor(locale, \`/orders/${o.orderId}?email=${encodeURIComponent(o.email)}\`)`, showing `brandName`+ a formatted`createdAt`. Empty → a friendly empty state (`guestListEmpty`) with a link to the catalog. Keep the logged-in list unchanged.

- [ ] **Step 3: Claim on login + clear localStorage**

In `apps/web/src/lib/auth.tsx` `afterTokens` (the single funnel), after seeding `/auth/me`: call `apiFetch<{claimed:number}>("/orders/claim", { method: "POST" })` (Bearer is set by then); on success, `removeGuestOrders(listGuestOrders().map(o => o.orderId))` for entries whose email matches the user's (or simply clear all — they're now claimed or not this user's). Swallow claim errors (non-fatal). Invalidate the `["orders"]` query so the account list refreshes.

- [ ] **Step 4: Register / verify / resend UX**

- `register` in `auth.tsx` no longer receives tokens (Task 2) — change it to surface the `verification_required` state instead of logging in; the form shows the `verifyRequired*` copy + a **resend** button calling `POST /auth/resend-verification`.
- `login` must catch the `email_unverified` 403 (detect via the ApiError status + the response `type`) and show `loginUnverified` + the resend button, rather than a generic error.
- (Verify-email page/route, if one exists on web, now receives a session from the API — ensure it stores tokens + runs claim via `afterTokens`. If verification is link-only to the API, the API sets the cookie; ensure the web verify landing calls `afterTokens` with the returned access token.)

- [ ] **Step 5: Tests + typecheck + i18n parity + commit**

Run the web unit tests for the guest list + any auth-flow test, `tsc --noEmit`, eslint, prettier, and the i18n parity check.

```bash
git add apps/web/src/app/[locale]/account/orders/ apps/web/src/lib/auth.tsx apps/web/src/components/**/*auth* packages/i18n/locales/ru/web.json packages/i18n/locales/en/web.json packages/i18n/locales/uz/web.json
git commit -m "feat(web/orders): guest order list + claim on login + verify/resend UX

Guests see their device-local order list; on login the user's guest orders are
claimed and cleared; register shows a verify-your-email state and login surfaces
the unverified block, both with a resend action. ru/en/uz.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 6: Controller Playwright verification** — NOTE: guest checkout (mock) → order page → guest list shows the order → register+verify → order migrates into the account list; login-while-unverified shows the block + resend.

---

## Self-Review

- **Spec coverage:** enforce verification at login ✅ T1; register no-session + verify auto-login + resend + grandfather ✅ T1/T2; claim ✅ T3; return_url from web_base_url + same-origin ✅ T4; guest order-view Guest-token auth ✅ T5; guest orders localStorage + save ✅ T5; guest list page ✅ T6; claim-on-auth + clear ✅ T6; verify/resend UX ✅ T6; i18n ✅ T6. Playwright verification ✅ controller steps.
- **Placeholder scan:** i18n step names every key and asks for verbatim EN/RU/UZ; the auth-form file is located at execution time (T6 Step 4) because the modal component path must be confirmed in-repo — flagged, not hand-waved.
- **Type consistency:** `EmailUnverifiedError` (api) ↔ web detects via ApiError status 403 + `type` ".../email-unverified"; `RegisterOut.status` literal ↔ web reads `verification_required`; `ClaimOut.claimed:int` ↔ web reads `.claimed`; `GuestOrder` shape identical between `saveGuestOrder` (T5) and the list page (T6).
- **Ordering:** T1→T2 (auth flow) must land before T6 (web consumes the new responses); T3 before T6 (claim call); T5 before T6 (localStorage helpers). Backend T1–T4 are independent of each other except T2 depends on T1's test-fixups; execute in numeric order.
- **Risk notes for the executor:** T1 Step 8 WILL touch many existing auth tests (every register-then-use flow) — budget for it; do not weaken them, add the verify step. The integration suite's mailer/verify-token capture mechanism must be found (conftest) to drive verification in tests.
