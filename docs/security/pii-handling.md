# YuPay — PII handling

## What we collect

| Field                          | Source                       | Stored in                                                          | Encrypted?                                                        |
| ------------------------------ | ---------------------------- | ------------------------------------------------------------------ | ----------------------------------------------------------------- |
| Email                          | Guest checkout, registration | `users.email`                                                      | At-rest via PG encryption (volume-level); column-level on roadmap |
| Telegram user ID               | Telegram OAuth / initData    | `telegram_links.tg_user_id`                                        | No (operational need)                                             |
| Telegram username / first name | Telegram OAuth               | `users.profile_jsonb`                                              | No                                                                |
| IP address                     | All HTTP requests            | Logs only (Loki)                                                   | Retained 14 days hot, 90 days cold, then deleted                  |
| User agent                     | All HTTP requests            | Logs only                                                          | Same retention as IP                                              |
| Voucher codes (issued)         | Inventory / supplier         | `inventory_codes.code_ciphertext`, `deliveries.payload_ciphertext` | **Yes, column-level (libsodium)**                                 |
| Payment provider metadata      | Webhooks                     | `payment_webhooks.payload jsonb`                                   | Provider's own redaction policy; we never store PAN               |
| Masked card data (Octo)        | Octo webhook callback        | `payment_webhooks.payload jsonb` (admin-only)                      | Already masked by Octo (`maskedPan`, `rrn`); full PAN never sent  |

## What we never log

- Email values
- Telegram IDs
- Voucher codes
- Auth tokens (access / refresh / guest)
- Provider API keys and acquirer secrets (`octo_secret`, `octo_signature_key`, bearer tokens)
- Card data — masked card fields stay in the admin-only webhook audit row, never in app logs

The structured logger's redactor blocklists these field names. New PII fields **must** be
added to the redactor and to this document in the same PR.

## Right to deletion

Implemented as a tombstone:

- `users.deleted_at` is set on a deletion request.
- A periodic job (`users.scrub_deleted`) nulls PII columns (email, profile_jsonb) and
  blanks the user's referral code while preserving order history (legally required for
  accounting).
- Audit trail of the deletion is kept in `users_deletion_log`.

## Data subject access

A read-only export endpoint (`GET /api/v1/users/me/export`) returns all PII a user has with
us, in JSON. Implemented in the `users` module.

## Retention

- Orders: indefinite (financial records).
- Logs: 14 days hot, 90 days cold (R2).
- Webhook payloads: 1 year, then archived to cold storage.
- Auth sessions: 30 days TTL on the refresh token; access JWTs are stateless and expire in 15 min.
