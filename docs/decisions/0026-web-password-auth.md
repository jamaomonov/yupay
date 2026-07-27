# 0026. Web accounts via email/password alongside Telegram Login Widget

- **Status**: Accepted
- **Date**: 2026-06-05
- **Deciders**: @jamaomonov
- **Tags**: backend | frontend | security

## Context and problem statement

The public web storefront (`apps/web`) was entirely guest-only. Customers filled an
email at checkout but never created a persistent account, could not log in, and had no
order history. The only auth path that existed in the backend was the **Telegram Login
Widget** (`POST /auth/telegram/widget`) — already backed and minting full
access+refresh tokens — but it requires a Telegram account and is not suitable as the
sole option for a general web storefront.

We need (a) a second auth method (email + password) that works without Telegram, (b)
associated email-verification and password-reset flows, and (c) web UI surfaces (auth
pages, account area, order history, order-status polling). The new method must fit the
existing session/JWT machinery rather than introducing a second authentication stack.

## Decision drivers

- Guests already supply an email at checkout; giving them a password-based login path
  has zero friction beyond setting a password.
- The existing JWT/session machinery (`_open_session`, EdDSA-signed tokens, Redis-backed
  refresh rotation, `auth_sessions` table) is proven and audited — reusing it avoids a
  second token surface.
- No PII in tokens, 15-minute access-token TTL, refresh rotation: the existing posture
  is sound; only the _issuance path_ changes.
- argon2id is the current OWASP recommendation for password hashing.
- Verification/reset tokens must be stateless (no new DB table) yet single-use for
  reset; a signed JWT + a short-lived Redis marker achieves both without migrations.
- The project runs on a single VPS; avoiding a BFF proxy keeps ops simple. Client-side
  localStorage is acceptable for a v1 given the 15-min access TTL and no PII payload,
  with httpOnly-cookie/BFF noted as future hardening.

## Considered options

1. **Magic-link only** — no persistent password; every session starts from an emailed
   one-time link.
2. **Password only** — no Telegram widget on the web; separate session model.
3. **Email/password + Telegram widget, localStorage + refresh rotation** (chosen).
4. **httpOnly-cookie / BFF session model from the start** — Caddy or a thin Next.js
   API route acts as the token keeper; the browser never sees raw tokens.

## Decision outcome

**Chosen option: Option 3.**

Both **Telegram Login Widget** and **email/password** are supported on the web.
Each mints exactly the same `access` + `refresh` token pair via the same
`_open_session` helper; the caller (widget vs password route) is the only difference.

**Password hashing.** `argon2-cffi` provides argon2id via `hash_password` /
`verify_password` helpers isolated in `auth/security.py`. The PasswordHasher uses
library defaults (time-cost=2, memory=64 MB, parallelism=1).

**Email verification + password reset.** Short-TTL signed JWTs with new `kind`
discriminators (`email_verify`, `password_reset`) reuse the existing JWT encoder. The
TTL is `jwt_email_token_ttl_seconds` (1800 s / 30 min). Reset is **single-use** via a
Redis marker: `auth:pwreset:{jti}` is SET with NX and TTL = token TTL; a second call
with the same token finds the key present and returns 401. On reset, all active refresh
sessions for the user are revoked via `_revoke_all_for_user`.

**One live account per email.** Enforced by the **pre-existing** partial unique index
`uq_users_email_alive ON users (email) WHERE email IS NOT NULL AND deleted_at IS NULL`.
Because `email` is CITEXT, that index is already case-insensitive, so the migration
(`0020_user_passwords`) adds only the `password_hash` and `email_verified_at` columns —
**no new email index** is created (an early draft proposed a redundant `lower(email)`
index; it was dropped). Guest checkouts do not insert user rows, so existing data cannot
violate the constraint.

**IP guard.** A lightweight Redis per-IP INCR counter on `POST /auth/login` and
`POST /auth/password/forgot` (key `auth:ipguard:{bucket}:{ip}`, TTL =
`auth_ip_guard_window_seconds` / 60 s) blunts brute-force and email-bombing attacks.
The guard **fails open** (Redis errors are suppressed) so a cache hiccup never locks out
legitimate users. Full edge rate limiting (slowapi / Caddy) is a separate, broader gap.

**Non-enumeration.** Both `POST /auth/login` (wrong email, Telegram-only account, wrong
password) and `POST /auth/password/forgot` (unknown email) return the same response;
attackers cannot distinguish between "no account" and "wrong password".

**Session storage on the client.** `localStorage` + refresh rotation, mirroring
`apps/miniapp/src/lib/api.ts`. The 15-minute access-token TTL limits the XSS exposure
window; the token payload contains no PII. `httpOnly`-cookie / BFF is explicitly
deferred as a future hardening step (see _Alternatives considered_ below).
**Superseded 2026-07-27 for the refresh token** — see _Amendments_ below; the access
token described here is unchanged.

**v1 account-model limitations.**

- Telegram and email/password produce **separate accounts** — they are not auto-merged
  even when the Telegram account's email matches the registered password account email.
- Claiming prior **guest orders** by verified email is deferred to a future slice.
  A returning guest can see new orders (created while logged in) but not older ones.

### Positive consequences

- A general web auth path without Telegram dependency; any email-address holder can
  register.
- No new session table or token format; the proven `auth_sessions` + EdDSA JWT
  machinery is reused unmodified.
- Stateless verification/reset tokens keep the DB schema minimal (two new nullable
  columns + one index).
- Reset invalidates all sessions — a security-positive side-effect.
- Non-enumeration on all sensitive endpoints makes user-existence discovery harder.
- argon2id is CPU/memory-hard and resistant to GPU-assisted cracking.

### Negative consequences

- `argon2-cffi` is a new C-extension dependency (adds ~500 µs per hash on commodity
  hardware; acceptable for auth paths that are not latency-critical).
- `localStorage` tokens are readable by same-origin JavaScript; XSS is a more
  direct threat than with `httpOnly` cookies. Mitigated by the short access TTL
  and absence of PII in the token, but not eliminated. **(Applies to the access
  token only as of 2026-07-27 — see _Amendments_.)**
- Telegram and email accounts are siloed in v1; a user who authenticates both ways
  has two separate accounts with separate order histories.

## Validation

- Integration tests: register → login → `GET /auth/me`; login rejects Telegram-only
  account (no `password_hash`); `verify-email` flips `email_verified_at`; `forgot`
  returns 204 for an unknown email; `reset` changes the password, revokes sessions, and
  the token is single-use; duplicate registration is rejected (409) by the
  pre-existing live-email unique index.
- `auth` module coverage ≥ 80% in CI.
- The IP guard returns 429 after `auth_ip_guard_max` attempts within the window.

## Alternatives considered (detail)

### Option 1 — Magic-link only

Pros: no password storage; no brute-force surface; simpler credential lifecycle.
Cons: requires a working email channel before _any_ login is possible; user must have
access to email _each time_ they want to log in (no offline/bookmark access); Resend
rate limits / delivery delays become a UX blocker.

### Option 2 — Password only (no Telegram widget on web)

Pros: single auth path; simpler code.
Cons: loses the already-built Telegram widget integration; users with a Telegram
account would need a separate password. The miniapp already uses Telegram; having
the web require a different credential for the same account creates confusion.

### Option 4 — httpOnly-cookie / BFF sessions from the start

Pros: tokens are inaccessible to JavaScript, eliminating the XSS token-theft vector.
Cons: requires a Next.js API route or thin Caddy proxy to act as the token keeper,
adding infra complexity that is not warranted for a v1. The short 15-minute access TTL
and no-PII-in-token stance make the risk acceptable for now. Noted as the preferred
future hardening step.

## Amendments

- **2026-07-27 — refresh token moved from `localStorage` to an `HttpOnly` cookie.**
  A security-review remediation pass took the future-hardening step flagged in
  Option 4 above, but only for the refresh token: `POST /auth/refresh` now reads
  and rotates the refresh token from an `HttpOnly; SameSite=Lax` cookie instead of
  the JSON body, and `apps/web`/`apps/admin`/`apps/miniapp` no longer persist a
  refresh token client-side at all (their `setTokens()`/`clearTokens()` helpers no
  longer touch a refresh key; legacy `localStorage` entries are purged on
  `clearTokens()`). **The access token is unchanged** — it still lives in
  `localStorage` on web/admin, still carries no PII, and still expires in 15
  minutes, exactly as decided above; a reader should not infer from this
  amendment that the access token became cookie-based or ceased to be
  JS-readable. See [ADR-0038](./0038-security-review-remediation.md) for the full
  change (cookie attributes, the `TokensOut` shape, and the one-time re-login
  consequence for sessions active at deploy time).

## References

- [ADR-0001](./0001-project-meta.md) — project identity and scope
- [ADR-0027](./0027-resend-email-channel.md) — Resend email channel (verification/reset emails)
- [ADR-0038](./0038-security-review-remediation.md) — moves the refresh token to an
  `HttpOnly` cookie (see _Amendments_ above)
- `docs/architecture/cache-keys.md` — `auth:pwreset:{jti}`, `auth:ipguard:{bucket}:{ip}`
- `docs/architecture/sequence-diagrams/web-auth.mmd` — register/verify/login/reset flows
- `docs/superpowers/specs/2026-06-05-web-accounts-design.md` — feature design spec
- `apps/api/src/yupay/modules/auth/security.py` — argon2id helpers
- `apps/api/src/yupay/modules/auth/ip_guard.py` — per-IP guard
- `apps/api/migrations/versions/0017_user_passwords.py` — schema migration
