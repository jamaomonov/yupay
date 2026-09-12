# YuPay — PII handling

## What we collect

| Field                          | Source                       | Stored in                                                                               | Encrypted?                                                                                                                                              |
| ------------------------------ | ---------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Email                          | Guest checkout, registration | `users.email`                                                                           | At-rest via PG encryption (volume-level); column-level on roadmap                                                                                       |
| Guest email (audit trail)      | Guest checkout               | `order_events.actor` (`guest:<truncated email_hash>`)                                   | Not raw — a truncated, non-reversible hash of the email (ADR-0038). Legacy rows written before this fix may still hold the raw address; not backfilled  |
| Telegram user ID               | Telegram OAuth / initData    | `telegram_links.tg_user_id`                                                             | No (operational need)                                                                                                                                   |
| Telegram chat ID               | Telegram Bot API sends       | Not persisted — logs only, and redacted there                                           | N/A — on the log redactor blocklist (ADR-0038); never appears in a log line                                                                             |
| Telegram username / first name | Telegram OAuth               | `users.profile_jsonb`                                                                   | No                                                                                                                                                      |
| IP address                     | All HTTP requests            | Logs (Loki) **and** `order_evidence.ip` on order creation                               | No. Logs: 14 days hot, 90 cold. `order_evidence`: unhashed, admin-read-only, deleted at the per-row `purge_after` (default 600 days) — ADR-0044         |
| User agent                     | All HTTP requests            | Logs, and `order_evidence.user_agent` on order creation                                 | No. Same two retentions as IP above                                                                                                                     |
| Browser hints (tz/locale/size) | Order creation, client-sent  | `order_evidence.client_hints jsonb`                                                     | No. Passive signals only — no canvas/font/audio fingerprinting. Deleted with the rest of the row (ADR-0044)                                             |
| Voucher codes (issued)         | Inventory / supplier         | `inventory_codes.code_ciphertext`, `deliveries.payload_ciphertext`                      | **Yes, column-level (libsodium)**; dedup `code_hash` is HMAC-SHA256 keyed off an HKDF-derived key, not bare SHA-256 (ADR-0038)                          |
| Payment provider metadata      | Webhooks                     | `payment_webhooks.payload jsonb`                                                        | Provider's own redaction policy; we never store PAN. Masked by key (card/pan/cvv/secret/signature/…) before the admin audit feed displays it (ADR-0038) |
| Masked card data (Octo)        | Octo webhook callback        | `payment_webhooks.payload jsonb` (admin-only)                                           | Already masked by Octo (`maskedPan`, `rrn`); full PAN never sent                                                                                        |
| Blog reader cookie             | First public like or view    | Not stored raw. `blog_post_likes.reader_hash` / `blog_post_views.reader_hash` (SHA-256) | HttpOnly cookie `yp_blog_reader`; hash only at rest. Not IP (ADR-0073)                                                                                  |

**Guest email in transit.** Guest order/deliveries lookups (`GET /orders/{id}`,
`GET /orders/{id}/deliveries`) send the guest's email as an `X-Guest-Email` header,
not a `?email=` query parameter (ADR-0038 §7) — it no longer lands in Caddy/proxy
access logs or browser history from those calls. It still travels over the wire on
every such request; this is a transport-location fix, not encryption-in-transit
(TLS already covers that) or an elimination of the value being sent at all.

**Delivery artifact whitelist.** `GET /orders/{id}/deliveries` projects the
`deliveries.artifact` JSONB through `BUYER_SAFE_ARTIFACT_KEYS` (an allow-list
in `apps/api/src/yupay/modules/fulfillment/service.py`, applied by
`buyer_safe_artifact`) before it reaches any frontend. It lives in the service
rather than in the router because it now has two consumers — the storefront's
delivery read and `/merchant/v1`'s order read — and a second copy would default
a forgotten key to _visible_. Only customer-safe keys (`code`/`codes`/`key`/`pin`/`serial`/
`steam_login`/`login`/`message`/`note`/`fulfillment_data`) survive; the upstream
supplier (`source`) and internal/external ids (`external_id`,
`external_order_id`, `inventory_code_id`, `sku_id`, `catalogue_name`, raw
`amount_units`) are never exposed to the customer — admins see the full row via
`/admin/fulfillment`.

**Steam profile URL / steamid64 (gift delivery).** A Steam gift order's
`order_items.fulfillment_data.invite_url` carries the buyer-entered Steam
profile/friend link (`steamcommunity.com/profiles/{steamid64}`,
`.../id/{vanity}`, or an `s.team/p/{path}` short link) — the address the
gift is actually sent to. It is stored there and echoed into G-Engine's
own order metadata (the supplier we hand it to in order to deliver the
gift), never anywhere else. Treated the same as `g2b`'s `player_id`
(`fulfillment/suppliers/g2b.py`): **never logged in plaintext.**
`fulfillment/suppliers/gengine_gifts.py`'s log calls pass only
`order_id`/`error`/task ids — `invite_url` is never one of the logged
keys, by construction, not by redactor coverage (`invite_url` is not on
the `REDACTED_KEYS` blocklist in `core/logging.py`, so a future log call
that added it as a bare kwarg would **not** be automatically redacted —
new code touching this module must keep it off log lines the same
disciplined way `g2b.py` keeps `player_id` off them, or add it to the
blocklist first). It is shown to the buyer themselves (they typed it) and
to admins on the admin order view; it is not exposed on the
customer-facing order response beyond what the buyer already entered, and
never appears in the delivery artifact the customer reads (the artifact
carries only `app_name`/`package_name`/a fixed instruction message — see
`BUYER_SAFE_ARTIFACT_KEYS` above).

The same link also reaches us _before_ any order exists, through the
pre-purchase recipient check (`gifts/profile.py`), and that path is why
**`POST /gifts/steam-profile` takes the link in a request body rather than a
query string.** The reasoning is worth keeping, because "never log it" was not
enough on its own: the `api.yupay.uz` site block in `infra/caddy/Caddyfile.prod`
writes a JSON access log whose `uri` field records the query string verbatim,
and promtail ships that container output to Loki. A `GET
...?invite_url=steamcommunity.com/id/{vanity}` therefore lands a _recipient's_
identity — a third party who never used the site — in our log store, no matter
how careful the application code is, because the leak happens at the edge and
not in a log call we control. Filtering the edge log was considered and
rejected: an unrelated Caddy change undoes it silently, and it only ever covers
the one place we remembered. A body is not recorded anywhere in that chain, so
there is nothing to filter. Application-side, the module keeps the same
discipline as above — the steamid, nickname and avatar never appear in a log
call, only `hash_short(identifier)` — and the Redis verdict cache
(`gifts:steam_profile:{id|sid}:{vanity_or_steamid}`, 6 h) is the only place
the identifier is stored at all, keyed but never logged. The `id:`/`sid:`
segment names the link shape: every steamid64 is also a valid vanity name,
so without it one namespace carried two different meanings for the same
17 digits.

**Ban reason.** `users.ban_reason` is admin-authored free text about a customer.
It is returned only on admin routes, never to the customer or to any public
surface, and is cleared when the suspension is lifted (ADR-0045).

## What we never log

- Email values
- Telegram IDs, including `chat_id` (a private-chat id is itself a Telegram user id)
- Voucher codes
- Auth tokens (access / refresh / guest)
- Blog reader cookie (`yp_blog_reader`) and its stored `reader_hash`
- Provider API keys and acquirer secrets (`octo_secret`, `octo_signature_key`, bearer tokens)
- Card data — masked card fields stay in the admin-only webhook audit row, never in app logs

The structured logger's redactor blocklists these field names. New PII fields **must** be
added to the redactor and to this document in the same PR. The admin **audit feed**
(`audit.list_audit_events`) applies the same blocklist to the payloads it displays —
it is not just a logging concern (ADR-0038 §6): a signature-valid provider webhook's
raw JSON body (e.g. Octo's masked PAN / `rrn`) is shown to admins through that feed,
and is now masked by key before being returned rather than forwarded verbatim.

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
- Blog likes/views: retained with the post, keyed only by `reader_hash`. The
  cookie itself lives 400 days; clearing it is how a guest resets identity.
- Reviews: a review is authored by a `user_id` and shown publicly only as the
  user's `display_name` (or an anonymous label when null) — **never the email**.
  The review `body` is user-controlled free text and is never logged. Reviews are
  retained with the account; deleting the user cascades their reviews (FK
  `ondelete=CASCADE`), and a report's `reporter_user_id` is nulled on account
  deletion (`ondelete=SET NULL`).

- Google Sign-In: we read `sub`, `email`, `email_verified`, `name`, `picture`
  from the verified ID token; only email (as the account identity),
  display name and avatar URL are stored — the Google `sub` is not persisted.
  The raw credential is never logged.
