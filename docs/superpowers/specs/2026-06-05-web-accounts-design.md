# Design: Web accounts, order history & order tracking (+ email channel)

**Date:** 2026-06-05
**Status:** Approved (brainstorming) — pending implementation plan
**Surface:** Public web storefront (`apps/web`) + API (`apps/api`: `auth`, `notifications`) + `apps/web` only on the client
**Branch:** `main` (per user instruction)

---

## 1. Problem

The public web storefront (`apps/web`) is guest-only. Purchase is an inline `PurchasePanel`
embedded in the brand page: pick SKU → fill fields → email → pay → redirect to acquirer. After
returning from the acquirer there is **no order status page** — the user sees a static "success +
pay" panel and nothing more. There is **no login/registration, no account, no order history, no
post-payment tracking**. Returning customers cannot see what they bought.

The backend already supports registered users: the **Telegram Login Widget** flow
(`POST /auth/telegram/widget`) mints a full user Bearer token, and `GET /orders` /
`GET /orders/{id}` / `GET /orders/{id}/deliveries` are owner-scoped and ready. What is missing is
(a) a second auth method (email + password), (b) an email channel to support it, and (c) the web
UI: auth pages, an account area, and an order-status page with live polling.

## 2. Goals / Non-goals

**Goals (slice 1)**
- Two web auth methods into one account: **Telegram Login Widget** (backend already done) and
  **email + password** (new).
- Minimal **email channel (Resend)** for email verification and password reset (and, as a bonus
  wired into the existing dispatch, guest order-confirmation / delivery emails).
- Web **account area**: profile + **order history**.
- New web **order-status page** with live polling — works for both logged-in users and guests
  returning from the acquirer (closes the "silence after payment" gap for everyone).
- All three locales (ru/en/uz) for new strings; tests; docs; ADR(s).

**Non-goals (deferred to later slices / future)**
- **Cart** (multi-item checkout) — separate slice; API already accepts `items[]`.
- **Search** — separate slice.
- Auto-merging a Telegram account and an email/password account that share an email.
- Claiming prior **guest orders** into a new account by verified email.
- httpOnly-cookie / BFF session model (localStorage + refresh rotation is used; cookie model is a
  future hardening, noted in the ADR).
- Project-wide rate limiting (separate gap); only a minimal Redis per-IP guard on sensitive auth
  endpoints is in scope here.

## 3. Decisions (locked during brainstorming)

- **Auth:** both **Telegram Login Widget** + **email/password**, both minting the same user
  Bearer/refresh tokens and landing in one account.
- **Email channel:** build a minimal **Resend** channel now (verification + password reset),
  reusing it for guest order/delivery emails.
- **Slice 1 scope:** account + order history + order-status tracking. Guest-order linking and
  account-merge are out.
- **Session storage:** **localStorage + refresh rotation**, mirroring `apps/miniapp/src/lib/api.ts`
  (consistency with existing clients; short 15-min access TTL mitigates XSS exposure; no PII in the
  token).
- **Verification/reset tokens:** stateless **signed JWT** with new `kind`s (`email_verify`,
  `password_reset`) + a **one-time-use Redis marker** for reset. No new DB table.
- **Password hashing:** **argon2id** via `argon2-cffi` (new dependency → ADR).

## 4. Backend

### 4.1 Email channel (`notifications`)
- `apps/api/src/yupay/modules/notifications/channels/email.py` — async Resend client over `httpx`.
- Config (`core/config.py`): `resend_api_key`, `email_from`, `email_from_name` (placeholders; real
  key supplied by the user; dev may use Resend test mode).
- Templates (html + txt): `verify_email`, `password_reset`, and (bonus) `order_confirmation`,
  `order_delivered`.
- **Auth emails** (verify / reset) are sent on the request path (a fast outbound HTTP call) or via a
  worker task — the plan picks one; the request path must not block on a slow provider, so a
  fire-and-forget worker task is preferred if the Dramatiq path is cheap to wire.
- **Order emails** are wired into the existing `notifications/service.py` dispatch next to the
  Telegram branch, gated on `order.guest_email` (and/or the user's email).
- Contract test with `respx` mocking the Resend API (success, 4xx, 429).

### 4.2 Password auth (`auth`)
- **Migration:** add `users.password_hash` (nullable), `users.email_verified_at` (nullable), and a
  **partial unique index** on `lower(email) WHERE deleted_at IS NULL`. Guest checkouts do not create
  user rows (per the `User` model docstring), so existing data cannot violate the constraint; the
  migration verifies no duplicate live emails before adding the index.
- **Dependency:** `argon2-cffi` (argon2id). ADR.
- **Endpoints** (in `auth/routes.py`, thin; logic in `auth/service.py`):
  - `POST /auth/register` `{email, password, locale?}` → create unverified user, mint
    access+refresh tokens, send verification email (non-blocking — the user is logged in
    immediately, with an "unverified" banner on the client).
  - `POST /auth/login` `{email, password}` → verify argon2 hash → mint tokens. Reject (401) if the
    user has no `password_hash` (Telegram-only account) — generic error, no account enumeration.
  - `POST /auth/verify-email` `{token}` → validate `email_verify` JWT → set `email_verified_at`.
  - `POST /auth/password/forgot` `{email}` → always `200` (no enumeration); if the email maps to a
    password user, send a `password_reset` email.
  - `POST /auth/password/reset` `{token, new_password}` → validate `password_reset` JWT, consume the
    one-time Redis marker, set new hash, **revoke all active refresh sessions** for the user.
- **Tokens:** `email_verify` / `password_reset` are short-TTL signed JWTs (reuse the JWT machinery
  and `kind` discriminator). Reset is single-use via a Redis key (`auth:pwreset:{jti}`, TTL = token
  TTL); documented in `cache-keys.md`.
- **Hardening:** a lightweight Redis per-IP counter on `login` and `password/forgot` (e.g. N/min) to
  blunt brute force / email bombing. Full slowapi rate limiting remains a separate gap.
- **Service functions:** `register_user`, `login_password`, `verify_email`,
  `request_password_reset`, `reset_password` — all fully annotated, argon2 hashing isolated in
  `auth/security.py` next to the existing `email_hash` / `hash_token` helpers.
- **Telegram Login Widget:** no backend change (`login_telegram_widget` already verifies the widget
  payload against `telegram_bot_token`).

### 4.3 Order history / tracking
- No backend change. `GET /orders` (list, Bearer user), `GET /orders/{id}` and
  `GET /orders/{id}/deliveries` (owner-only, tolerate Bearer **and** guest actors) already exist and
  are reused by the web client.

## 5. Frontend (`apps/web`)

### 5.1 Auth client
- `src/lib/api.ts` + `src/lib/auth.ts` — mirror `apps/miniapp`: access+refresh in localStorage,
  auto-refresh on 401 via `POST /auth/refresh`, `apiGet`/`apiPost` attaching `Authorization`.
- `AuthProvider` (React context) exposing `user`, `login`, `register`, `logout`,
  `loginWithTelegram`, with a TanStack Query `me` query (`GET /auth/me`).

### 5.2 Pages (under `src/app/[locale]/`)
- `login/page.tsx` — email/password form + Telegram Login Widget button + links to register/forgot.
- `register/page.tsx` — email/password + Telegram widget.
- `auth/forgot/page.tsx` — request reset.
- `auth/reset/page.tsx` — consume `?token`, set new password.
- `auth/verify/page.tsx` — consume `?token`, confirm email.
- `account/page.tsx` — profile (display name, email, locale, display currency) + "verify email"
  banner; auth-gated (redirect to `/login`).
- `account/orders/page.tsx` — order history (`GET /orders`).
- `orders/[orderId]/page.tsx` — **order status with polling** (see §5.4).

### 5.3 Header & checkout integration
- `components/Header.tsx` — auth state: "Войти" when anonymous; account menu (avatar + logout) when
  signed in.
- `components/store/PurchasePanel.tsx` — when signed in, create the order with the user Bearer token
  (so it lands in history) and, on success, route to `/orders/{id}` instead of the dead-end success
  panel. The guest path is preserved for anonymous buyers and also routes to `/orders/{id}?email=…`.

### 5.4 Order-status page
- Polls `GET /orders/{id}` + `GET /orders/{id}/deliveries`, reusing the miniapp `OrderSuccess`
  pattern: `refetchInterval` while the order is in motion (`pending_payment|paid|fulfilling|
  fulfilled`), stop on terminal states, render delivery artifacts, react to `refunded`.
- Auth: logged-in users use the Bearer token; guests use the Guest token + `?email=` carried in the
  link (the same owner check the backend already enforces).

### 5.5 i18n
- New keys in `packages/i18n/locales/{ru,en,uz}/web.json` — namespaces for auth, account, and
  order-status. All three locales in the same PR (AGENTS.md §11).

## 6. Testing (AGENTS.md §8)

- **Backend** (`auth` coverage ≥80%; `payments`/`wallet` untouched):
  - Integration (testcontainers Postgres + Redis): register → login → me; login rejects
    Telegram-only users; verify-email flips `email_verified_at`; forgot is non-enumerating;
    reset consumes the one-time marker, rotates the password, and revokes sessions; the partial
    unique email index is enforced.
  - Contract (`respx`): Resend send on success / 4xx / 429.
- **Frontend** (`apps/web` has no unit suite): `tsc` (0), `lint` (0 on new files), `prettier` clean,
  and a manual run on the live stack — login via both methods, history loads, order-status polling
  advances pending → delivered, guest tracking via the email link.

## 7. Documentation (AGENTS.md §5)

- ADR `docs/decisions/NNNN-web-password-auth.md` — email/password + argon2id, token-storage choice
  (localStorage now, cookie/BFF as future hardening), verification/reset token model.
- ADR `docs/decisions/NNNN-resend-email-channel.md` — Resend dependency, templates, where auth vs
  order emails are sent.
- `docs/architecture/module-map.md` — `auth` gains password flows; `notifications` gains the email
  channel.
- `docs/architecture/cache-keys.md` — `auth:pwreset:{jti}` and any per-IP guard keys.
- Sequence diagrams in `docs/architecture/sequence-diagrams/` — web login/register/verify/reset and
  order tracking.
- `make gen-api` — regenerate `docs/api/openapi.json` + `packages/api-client`.

## 8. Needs from the user (credentials / infra)

1. **Resend** API key + sending domain (e.g. `noreply@yupay.uz`) with DKIM/SPF; dev may use Resend
   test mode. Until provided, config stays a placeholder and email sends are exercised only via the
   `respx` contract test / a dev no-op.
2. **Telegram Login Widget**: bot username + BotFather `/setdomain` binding for the web domain
   (same bot as the miniapp). Until bound, the widget renders only on the configured domain; local
   testing uses the email/password path.

## 9. Definition of Done

- [ ] `POST /auth/register|login|verify-email|password/forgot|password/reset` implemented, validated,
      argon2id hashing, sessions revoked on reset.
- [ ] Email channel (Resend) sends verification + reset; order/delivery emails wired into dispatch.
- [ ] Migration adds `password_hash`, `email_verified_at`, partial unique email index.
- [ ] Web: login/register/forgot/reset/verify pages, account + order history, order-status polling
      page; header auth state; PurchasePanel creates user-owned orders when signed in.
- [ ] Order-status tracking works for both users and guests (email link).
- [ ] All three locales updated; backend tests green; `auth` coverage ≥80%; query-count sane.
- [ ] OpenAPI + TS client regenerated; no drift.
- [ ] ADR(s) + module-map + cache-keys + sequence diagrams updated.
- [ ] `make lint typecheck test` green; web `tsc`/`lint`/`prettier` clean; manual run verified.
