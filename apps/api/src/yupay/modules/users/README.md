# `users` module

User identity (account + profile + Telegram link).

## Responsibilities

- Own the `users`, `telegram_links`, and `steam_links` tables.
- Find-or-create a `User` from a verified Telegram or Steam identity (called by `auth`).
- Look up a user by id (used by `auth.deps.current_user`).

## Public interface

```python
from yupay.modules.users.api import (
    UserOut,
    get_user_by_id,
    get_user_by_telegram_id,
    upsert_user_by_telegram,
)
```

## Tables owned

- `users` — one row per account. `email` and `telegram_id` are independent identifiers;
  both may be null for guest checkouts, both may be set for fully-linked accounts.
  `photo_url` is `text` (migration 0083 — was `varchar(1024)`, which a real Google
  avatar URL exceeded in production); `display_name` stays `varchar(255)`.
- `telegram_links` — 1:1 with `users` at MVP, kept as a separate table to make
  "link another Telegram" trivially additive later.
- `steam_links` — 1:1 with `users`, same shape as `telegram_links`; Steam's OpenID
  hands back only a steamid64, no email, so the link _is_ the account identity.

## Identity-field guards (`identity_guard.py`)

`photo_url` and `display_name` are copied from whatever an identity provider (Google,
Telegram, Steam) hands back, unvalidated by that provider's own contract. Every write
site (`users.service.upsert_user_by_telegram`/`upsert_user_by_steam`,
`auth.service.google_login`) funnels through `identity_guard.safe_avatar_url` /
`safe_display_name` instead of assigning the raw value:

- `safe_avatar_url` drops (returns `None` for) anything absent, blank, or longer than
  `MAX_AVATAR_URL_LENGTH` (2048 chars) — a truncated URL is a broken link, not a
  smaller picture, so "too long" is treated the same as "not supplied".
- `safe_display_name` truncates to `MAX_DISPLAY_NAME_LENGTH` (255, matching the
  column) instead of dropping — a shortened name is still a usable name.

`upsert_user_by_steam` guards `avatar_url` once and reuses the same value for both
`steam_links.avatar_url` and `users.photo_url` (they write in the same flush, so
guarding only one still leaves the INSERT/UPDATE able to fail on the other), and
guards `persona_name` once the same way for `steam_links.persona_name` and
`users.display_name`. `steam_links.avatar_url` is `text` too (migration 0083 widened
it alongside `users.photo_url`, not for symmetry): "Steam's avatar URLs are short,
fixed-format CDN links" was exactly what was true of Google's avatar URLs until one
exceeded 1024 characters and cost a registration — leaving the sibling column narrow
would have kept that same failure reachable through Steam instead.

## Concurrent first-sight logins (SAVEPOINT, not 500)

`upsert_user_by_telegram`/`upsert_user_by_steam` are find-or-create over a plain
SELECT-then-INSERT, so two concurrent first logins for the same brand-new
`tg_user_id`/`steam_id` race it: both see "not found", both try to insert. Sentry,
production, 2026-09-18: the loser hit `asyncpg.UniqueViolationError` on
`uq_telegram_links_tg_user_id` and 500'd — someone's first-ever login failed for it.

Both functions now run their INSERT inside `session.begin_nested()` (a SAVEPOINT),
with `session.add(...)` called **after** the SAVEPOINT opens — added before it, a
unique-constraint failure would leave the doomed rows in `session.new` and poison
the outer transaction (the same reasoning as `affiliate.partners.apply` and
`fulfillment.service.complete_manual_task`; see their own `begin_nested()` notes).
On `IntegrityError` the loser re-reads the winner's now-committed row and falls
through into the same "existing user" branch a returning visitor would take —
exactly as if it had found the row on the first SELECT — rather than propagating
the exception. `auth.service.google_login`'s equivalent race (unique on
`users.email`) follows the identical shape; see `auth`'s README.

## Soft delete (GDPR)

`users.deleted_at` is the tombstone, set by `DELETE /auth/me`
(`auth/account_deletion.py`). Nothing is scrubbed afterwards — the owner's choice
(2026-10-22). Every read here filters `deleted_at IS NULL`; a Telegram or Steam identity
whose link points at a deleted account gets a fresh account that takes the link over
(`_reclaim_telegram_link`, and the same move inside `upsert_user_by_steam`). See
[`docs/security/pii-handling.md`](../../../../../docs/security/pii-handling.md).

## Admin directory (`GET /admin/users`)

Paged listing. `search` matches display name, email, Telegram username/id and
Steam persona/id. `sort` is server-side (the list is paged 50):

| `sort`                       | Order                                                                                  |
| ---------------------------- | -------------------------------------------------------------------------------------- |
| `created_desc`               | newest first (default); `id` is the OFFSET tiebreak                                    |
| `created_asc`                | oldest first                                                                           |
| `wallet_desc` / `wallet_asc` | USD-equivalent of `user_wallet` (USD/USDT 1:1, other currencies via latest `fx_rates`) |
| `name_asc` / `name_desc`     | `lower(display_name)`, nulls last                                                      |

Each row carries `wallet_balances` (non-zero `user_wallet` buckets). The
payload also has `wallet_totals`: global `user_wallet` liability per currency,
**not** filtered by the current search — that is "how much customer money we
hold". Both reads are one query each (see `wallet.balances`).

## Tests

- `apps/api/tests/unit/test_users_identity_guard.py` — `safe_avatar_url` /
  `safe_display_name` in isolation (drop vs. truncate, boundary lengths).
- `apps/api/tests/integration/test_users_service_identity_guard.py` — the
  Telegram and Steam upsert paths against a real Postgres: an absurd avatar
  URL creates the user with no avatar rather than 500ing; a normal one still
  stores it; a returning user isn't given a bad avatar either.
- `apps/api/tests/integration/test_auth_google.py` — the equivalent for the
  Google path (the one Sentry actually reported), plus its own first-sight
  concurrency race (see below).
- `apps/api/tests/integration/test_users_upsert_race.py` — forces the actual
  interleaving (two real concurrent sessions, one paused mid-request) for
  the Telegram and Steam first-sight races, the same technique
  `test_auth_refresh_race.py` uses for the refresh-rotation race.

## Signup source

`users.signup_source` (migration 0103) records where an account was opened: `web`, `miniapp`,
`mobile` or `unknown`. The sign-in routes read it from `X-Yupay-Surface`; the mini app's
initData route always writes `miniapp`. It is set once, on creation, and a later sign-in from
another surface never changes it. Rows that predate it were backfilled from the best evidence
left (see the migration's docstring); the admin user list shows it under the signup date.
