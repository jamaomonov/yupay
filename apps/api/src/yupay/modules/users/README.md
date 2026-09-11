# `users` module

User identity (account + profile + Telegram link).

## Responsibilities

- Own the `users` and `telegram_links` tables.
- Find-or-create a `User` from a verified Telegram identity (called by `auth`).
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
- `telegram_links` — 1:1 with `users` at MVP, kept as a separate table to make
  "link another Telegram" trivially additive later.

## Soft delete (GDPR)

`users.deleted_at` is the tombstone. A periodic job (planned in the `users` module) nulls
PII columns after deletion while keeping order history intact for accounting. See
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
