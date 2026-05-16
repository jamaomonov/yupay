# 0010. Admin authentication via Telegram + role-on-User

- **Status**: Accepted
- **Date**: 2026-05-15
- **Deciders**: founding team
- **Tags**: backend, frontend, auth, security

## Context

YuPay needs a backoffice — manage brands, products, SKUs, view orders, refund, etc.
Two reasonable models:

1. A separate `admin_users` table with email + password + MFA, fully isolated from the
   customer auth surface.
2. A `roles` field on the existing `users` table; admins log in through the same
   Telegram path as customers, and admin endpoints simply require ``admin`` in
   ``users.roles``.

Both work. The first gives the strongest blast-radius isolation (a compromised
customer account can never escalate to admin). The second is dramatically simpler:
one auth flow, one session table, one place to revoke. For a team of < 10 admins
who all already use Telegram, the second model wins on ergonomics and on time-to-MVP.

## Decision

Admins are **regular `users` rows with an `admin` role**.

### Schema change

```
ALTER TABLE users ADD COLUMN roles jsonb NOT NULL DEFAULT '[]'::jsonb;
CREATE INDEX ix_users_roles_admin ON users USING gin (roles jsonb_path_ops)
  WHERE roles ? 'admin';
```

`roles` is an array of strings. Today the only role is ``admin``; ``support``,
``operator``, ``finance`` are reserved for the obvious near-term expansion.

### Auth flow

1. The admin SPA renders the same Telegram Login Widget as the public web.
2. The backend's `POST /api/v1/auth/telegram/widget` mints an access JWT — identical
   to the customer flow.
3. Admin endpoints depend on ``require_admin``: it resolves ``current_user`` and
   checks ``"admin" in user.roles``. Non-admin tokens get **403 Forbidden** (not 401,
   so the SPA can distinguish "not logged in" from "logged in but not allowed").

### Bootstrapping the first admin

`scripts/grant_admin.py` adds ``admin`` to a user's ``roles`` array by telegram id
or user id. Run via:

```
docker compose exec api python -m yupay.scripts.grant_admin --tg-id 123456789
docker compose exec api python -m yupay.scripts.grant_admin --user-id 019e2a0f-... 
```

The first admin logs in via Telegram once (creating the `users` row), then a
deployer runs the script with the tg-id from the logs.

### Token surface

The admin SPA uses the **same** access JWT as web / mini-app. No separate token
kind. The JWT already carries ``sub`` (the user id); the role check happens at the
DB layer per-request — that costs one indexed lookup but lets us revoke admin in
real time (just remove `admin` from `roles`).

Embedding `roles` in the JWT was rejected: revocation would have to wait for the
15-minute access TTL to expire (or a manual blocklist push), which is too slow for
an "oh, fire this admin now" scenario.

### Cookie / storage

Admin SPA stores the access JWT in **`localStorage`** (single-page app, no SSR, no
cookie). The refresh-token rotation flow is identical to the customer one. The SPA
auto-refreshes on 401 once before redirecting to `/login`.

## Consequences

- One auth flow, one session table, one revocation surface.
- Admin compromise == account compromise. We mitigate via:
  - **Per-request role check** (cheap revocation),
  - **Telegram 2FA / passcode** at the OS level (Telegram itself),
  - **IP allow-list** at Caddy for `admin.yupay.io` (deferred, recorded as TODO).
- Adding new roles is one entry; the role check helper is generic from day one.
- Migration to a fully isolated `admin_users` is not blocked by this — it would
  reuse the same `roles` interface contract.

## Alternatives considered

- **`admin_users` with email + password + MFA** — rejected for MVP: more code, two
  auth flows, two recovery paths, and the team is already on Telegram.
- **JWT-embedded roles** — rejected: hot-revocation latency = access TTL.
- **Single global `is_admin` boolean** — rejected: we will want `support`,
  `finance`, etc. very soon.

## References

- [ADR-0007 — JWT format and rotation](./0007-jwt-format-and-rotation.md)
- [`apps/api/src/yupay/modules/auth/`](../../apps/api/src/yupay/modules/auth)
- [`apps/admin/`](../../apps/admin)
