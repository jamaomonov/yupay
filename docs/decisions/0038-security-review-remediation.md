# 0038. Security-review remediation (2026-07 review cycle)

- **Status**: Accepted
- **Date**: 2026-07-27
- **Deciders**: @jamaomonov
- **Tags**: security | backend | frontend | infra | payments

## Context and problem statement

A security review of the codebase (branch `security/review-fixes`, 13 commits,
`406f4ae..HEAD`) surfaced findings from one HIGH-severity money-safety bug down to
several LOW hardening items. Most fixes are narrow and self-contained (a constant-time
comparison, a redaction rule, a length cap) and don't need their own ADR. A few,
however, change a contract this project already recorded elsewhere — [ADR-0007](./0007-jwt-format-and-rotation.md)'s
token-rotation policy and [ADR-0026](./0026-web-password-auth.md)'s client-storage
choice — or introduce a pattern worth a name (a generic idempotency-replay store, an
image-URL SSRF gate). This ADR is the pointer for those, plus a place to record what
the review found but this pass deliberately did **not** fix, so that stays visible
instead of quietly disappearing.

## Decision drivers

- Two of the fixes complete or reverse a previously-recorded ADR decision; future
  readers of ADR-0007 / ADR-0026 need a signpost to what actually shipped.
- Some residual risk is being knowingly accepted (DNS rebinding, multi-refund,
  CSP `unsafe-inline`, CodeQL cadence) — better written down once than re-discovered
  by the next review.
- Per AGENTS.md §13, a new dependency, a changed public contract, or a decision a
  future maintainer might second-guess gets an ADR.

## Considered options

1. **No bundling ADR — commit messages are the record.** Rejected: the commit log
   doesn't get linked from ADR-0007/0026, and there's no single place to record the
   accepted-risk list.
2. **One ADR per commit.** Rejected: most of the 13 commits are LOW-severity, narrow
   fixes (constant-time compares, a redaction rule, SHA-pinning a GitHub Action) with
   no durable design decision to record — one ADR each would fragment a single,
   contiguous review pass into noise.
3. **One ADR for the whole review pass**, covering only the decisions that changed a
   previously-documented contract or introduced a reusable pattern, plus an explicit
   accepted-risk list; the rest gets a flat summary. **(Chosen.)**

## Decision outcome

**Chosen option: 3.**

### 1. Refresh token moved into an HttpOnly cookie

**Context.** ADR-0007 already specified "browser cookies for access tokens —
rejected at MVP... Refresh is in a cookie (`HttpOnly`, `Secure`, `SameSite=Lax`) on
the web" but this was never actually built — ADR-0026 (2026-06-05) then shipped the
refresh token in the JSON body / `localStorage`, explicitly deferring the cookie as
"future hardening." An XSS regression on any of the three frontends could lift a
30-day session.

**Decision.** The refresh token now rides an `HttpOnly` cookie
(`apps/api/src/yupay/modules/auth/cookies.py`):
`HttpOnly; SameSite=Lax; Path=/`, with `Secure` and `Domain=.yupay.uz` added only in
production (`settings.is_prod`) — dev/test stay host-only over plain `http`, where a
`Secure` cookie would be silently dropped and a `Domain` attribute for a bare
hostname is invalid. `POST /auth/refresh` reads and rotates the cookie instead of a
`refresh_token` body field; `POST /auth/logout` clears it. `TokensOut` no longer has
`refresh_token` / `refresh_expires_in` fields — only `access_token` travels in the
body now. All three frontends (`apps/web`, `apps/admin`, `apps/miniapp`) stopped
persisting a refresh token client-side (legacy `localStorage` keys are purged on
`clearTokens()`) and now call the auth endpoints with `credentials: "include"`.

This **supersedes ADR-0026's Option 3 for the refresh token only** — the access
token is unchanged: it still lives in `localStorage` on web/admin and is still
XSS-exposed for its 15-minute life, per ADR-0026's original tradeoff.

**Consequences.**

- Every refresh token issued before this deploy lived only in client
  `localStorage`/JSON; no cookie was ever set for it. On deploy, already-logged-in
  users keep working until their current access token expires (≤ 15 min), then the
  automatic-refresh call 401s with no cookie present and they land back on the login
  page. One-time re-login for active sessions; no data loss.
- The Mini App surface is unaffected — per ADR-0007 it was never issued a refresh
  token in the first place (Telegram `initData` is its refresh credential).

### 2. Access-token revocation blocklist — now actually implemented

**Context.** ADR-0007's rotation policy documented `auth:revoked:{jti}` as the access
-token blocklist, and the key was already listed in
[`docs/architecture/cache-keys.md`](../architecture/cache-keys.md) — but
`logout`/`current_user` never actually wrote or read it. Logging out only revoked
the refresh-token DB row; a stolen/leaked access token kept working for up to its
full 15-minute life after the user logged out.

**Decision.** `logout` (`apps/api/src/yupay/modules/auth/service.py`) now reads the
`Authorization: Bearer` token on the logout request, verifies it, and — if valid —
`SET`s `auth:revoked:{jti}` in Redis with TTL equal to the token's _remaining_
lifetime. `current_user` does one Redis `GET` on that key per request and raises
`401` if present.

**Limitation (unchanged, noted for the record).** The refresh-reuse trip-wire (ADR
-0007: presenting an already-rotated refresh token signals theft and revokes the
whole session lineage) still cannot blocklist the paired access token — that request
carries no `Authorization` header to blocklist from. Those tokens simply self-expire
within ≤ 15 minutes; this is an accepted gap, not a bug.

### 3. One-refund-per-payment (over-refund fix, HIGH)

`refund_admin` (`apps/api/src/yupay/modules/payments/service.py`) previously guarded
on `payment.status in ("succeeded", "partially_refunded")`, so a payment already
`partially_refunded` could be refunded a second time — each call bounded its amount
against the _original_ payment total rather than a remaining balance, while the
per-payment ledger idempotency key silently no-op'd the second posting. Net effect:
real gateways could be over-refunded while the ledger and FSM diverged from reality.

**Decision.** The guard is now `payment.status != "succeeded"` → reject. Since any
refund (full or partial) moves the status off `succeeded`, at most one refund can
ever occur per payment, which is what makes the existing per-payment ledger key and
the single `last_refund` replay check sufficient.

**Deferred.** Multi/partial refund tracking (e.g. 60 then 40 of a 100 payment) needs
a dedicated `payment_refunds` table recording each refund and deriving the remaining
balance. Out of scope for this pass; a partial refund currently consumes the
payment's only refund.

### 4. Generic idempotency-replay store

Payments/orders/wallet/promo already persist `Idempotency-Key` on their own domain
row. Admin write endpoints that _mutate_ an existing row instead of creating one
(retry/cancel/force-complete a fulfillment task, upsert/delete a sourcing rule or
supplier mapping, ...) had no such column. Migration
[`0033_idempotent_responses`](../../apps/api/migrations/versions/0033_idempotent_responses.py)
adds a generic `idempotent_responses` table — `(scope, idempotency_key)` unique,
storing a `status_code` + JSONB `response_body` snapshot — with `load_replay`/
`save_replay` helpers in `apps/api/src/yupay/core/idempotency.py`. Wired onto the
fulfillment, inventory, sourcing, and integrations admin routes, and (in the
follow-up commit) `admin_force_complete_task`.

This is **policy compliance with AGENTS.md §9**, not a fix for an exploitable bug —
FSM guards and `UNIQUE` constraints already made retries of these specific endpoints
safe. The header is now accepted (and replay-honored) where it previously wasn't.

### 5. Image-URL SSRF validation at the catalog Pydantic layer

`Brand.logo_url` / `Brand.hero_image_url` / `Product.image_url` / `Sku.image_url`
are admin- (and G2B-import-) supplied strings that Next.js's `/_next/image`
optimizer fetches **server-side**. Unvalidated, an admin or the G2B import path could
point one at an internal address and turn the image optimizer into an SSRF proxy.

**Decision.** `validate_public_image_url`
(`apps/api/src/yupay/modules/catalog/image_url_safety.py`) rejects: any non-`https`
scheme; `localhost`/`internal` and anything under `*.local`/`*.localhost`/
`*.internal`; and any host that parses as an IP literal (including the bare-integer
IPv4 bypass, e.g. `http://2130706433/`) in a private, loopback, link-local (covers
the `169.254.169.254` cloud-metadata address), reserved, multicast, or unspecified
range. Wired onto Brand/Product/Sku admin create+update
(`catalog/admin_schemas.py`) and the G2B supplier import (invalid images are skipped,
not fatal — `integrations/service.py`). `apps/web/next.config.ts`'s
`remotePatterns` is separately tightened to the real yupay.uz/R2 hosts.

**Residual risk (documented in the module docstring, repeated here on purpose).**
This only rejects a host that is _already_ an IP literal in a blocked range at
validation time — it cannot detect **DNS rebinding** (a hostname resolving to a
public IP now, then to a private/metadata IP when Next's optimizer actually fetches
it later). Closing that needs the fetcher itself to re-resolve/pin the IP at request
time, which Next's image optimizer doesn't expose a hook for. Treat this as raising
the bar, not a hermetic filter — it also doesn't normalise octal/hex-per-octet IP
obfuscations.

### 6. PII/secret redaction in the audit feed + hashed guest email in `OrderEvent.actor`

The admin audit feed (`apps/api/src/yupay/modules/audit/service.py`) forwarded raw
provider webhook JSON verbatim — e.g. Octo's masked PAN / `rrn` / signature fields
land in `PaymentWebhook.payload` and were shown to admins unmasked at the audit
layer. `list_audit_events` now recursively masks (`<redacted>`) any dict key present
in `core.logging.REDACTED_KEYS` before returning a page, only over the trimmed page
actually returned (not the full per-source fetch). `REDACTED_KEYS` gained generic,
provider-agnostic terms (`card`, `pan`, `cvv`, `cvc`, `secret`, `signature`, `key`) in
the same commit so both the structured logger and the audit reader agree on what's
sensitive.

Separately, `OrderEvent.actor` for a guest order now stores
`guest:<first-40-hex-of-email_hash>` — a deterministic, non-reversible per-email
pseudonym — instead of `guest:<raw email>` (fits the existing `varchar(64)` column).

### 7. Other hardening in this pass

- **Constant-time webhook credential compares** — Payme/Uzum Basic-auth and the g2b
  path secret now use `hmac.compare_digest`, OR-accumulated across every configured
  key/pair (so timing can't reveal _which_ one matched) and fail-closed on the
  `TypeError` `compare_digest` raises for non-ASCII wire input. Rejected-webhook
  audit rows now cap the stored raw body at 4096 chars (pre-auth flood protection).
- **HTML-escaping** of supplier/admin/customer free-text before it's spliced into
  `parse_mode: HTML` Telegram messages (low-balance alert, price-move alert,
  fulfillment-field summaries) — closes a markup-injection / alert-suppression
  vector.
- **Telegram `chat_id` redaction** — added to `core.logging.REDACTED_KEYS` and
  dropped from `notifications/channels/telegram.py` log lines (a private-chat id is
  a Telegram user id — PII per AGENTS.md §9).
- **FX trust-gate extended to fixed-price lines** — `guarded_usd_rate` (the same
  guard variable-amount lines already used) now also prices the fixed-price,
  non-override, non-USD checkout line; a wrong/stale rate now fails the SKU out of
  sale (502) instead of under-charging.
- **Guest email out of the URL** — order/deliveries guest lookups read
  `X-Guest-Email` as a header instead of `?email=` query param (web `OrderStatus`
  updated to send it) — keeps the address out of Caddy/proxy access logs and browser
  history.
- **Account-enumeration timing fix** — `login_password` always runs an argon2
  `verify` (against a precomputed dummy hash when the account or password is
  absent), so response time can't distinguish "no such account" from "wrong
  password"; `forgot`'s email send moved off the request path via the notifications
  scheduler (also fixes a sync-HTTP-in-handler §10 violation).
- **Dev-admin login hardening** — refuses to authenticate when
  `ADMIN_DEV_LOGIN`/`ADMIN_DEV_PASSWORD` are still the shipped `admin`/`admin`
  defaults, compares constant-time, and the route is now rate-limited via
  `guard_ip`.
- **Telegram Login Widget replay guard** — `enforce_widget_single_use` burns the
  widget's HMAC signature on first use via `SET NX auth:tg-widget:{sha256(hash)}`
  (TTL = remaining freshness window); a captured widget payload can no longer be
  replayed within its otherwise-valid window.
- **HMAC-keyed voucher-code dedup hash** — `inventory/crypto.py`'s `code_hash` is now
  HMAC-SHA256 keyed by an HKDF-derived key (domain-separated from the SecretBox
  encryption key, same `INVENTORY_ENC_KEY` input material) instead of bare SHA-256 —
  a leaked `inventory_codes` table can no longer be brute-forced offline against
  low-entropy codes without the server-side key. Safe to change: `inventory_codes`
  was empty at the time (skeleton stage).
- **ReDoS guards** — admin-authored `FormField.pattern` is validated at write time
  (`catalog/schemas.py`: rejects nested-quantifier shapes, oversized bounded
  repeats, overlong patterns, invalid regex); checkout additionally caps the matched
  input at 256 chars before `re.fullmatch` (`orders/validation.py`) as defense in
  depth — the write-time guard is heuristic, not exhaustive (e.g. alternation-based
  blowups aren't caught).
- **CORS prod safety-rail** — the origin-reflecting (`allow_origin_regex=".*"`)
  branch meant for dev tunnels is now gated behind `not settings.is_prod`; a literal
  `"*"` left in `CORS_ALLOW_ORIGINS` in prod is stripped before being passed to
  `CORSMiddleware` (passing it through would let Starlette re-trigger the same
  wildcard-with-credentials reflection) and logged as a misconfiguration warning.
- **`appleboy/ssh-action` SHA-pinned** — `deploy.yml` now references the action by
  its `v1.2.0` commit SHA instead of the mutable tag, so a re-pointed tag upstream
  can't silently swap in code with access to `DEPLOY_SSH_KEY`.

### 8. Explicitly accepted — not fixed in this pass

- **CSP `script-src 'unsafe-inline'`** on the storefront — forced by Next.js SSG; no
  per-request nonce is possible without leaving static generation. Already noted in
  `docs/security/threat-model.md`.
- **CodeQL manual-only** — the repo is private without GHAS, so the scan API rejects
  scheduled runs. Switch `codeql.yml` to a weekly cron once the repo goes public or
  GHAS is purchased (AGENTS.md §9).
- **`semver@6.3.1`** — a transitive, build-tool-only dependency
  (`pnpm-lock.yaml`); never reaches a served bundle or runtime path. Not worth a
  forced-resolution override for this pass.
- **Dev-admin singleton row** (`_ensure_dev_admin`) — the login route itself is
  force-disabled in production (`_dev_login_active` requires `not settings.is_prod`),
  so the underlying singleton-row design isn't attacker-reachable there; the design
  itself is unchanged.

### Positive consequences

- Refresh-token theft via XSS is no longer possible on any of the three frontends;
  access-token theft now has a real, working revocation path instead of a documented
  -but-unbuilt one.
- The over-refund bug can no longer double-post a refund against a real gateway.
- Admins can no longer see raw provider secrets/PII (card fragments, guest emails)
  in the audit feed just by scrolling it.
- The catalog admin surface and G2B import can no longer be used to make the API
  fetch an internal address via the image optimizer (short of DNS rebinding).
- Several previously-silent policy gaps (idempotency-header acceptance, CORS
  wildcard-in-prod, dev-admin defaults) now fail closed or are logged loudly instead
  of failing open.

### Negative consequences

- Every currently-active session forces one re-login after this deploys (see
  decision 1).
- `refund_admin` is strictly less flexible than before for any real partial-refund
  workflow — that has to wait for the `payment_refunds` table.
- The DNS-rebinding gap in image-URL validation, the enumerated residual risks in
  §8, and the refresh-reuse trip-wire's access-token blind spot (§2) are now written
  down as known, accepted gaps rather than silently absent — which is the point,
  but they are still open.

## Validation

- Each of the 13 commits ships with its own focused tests (unit and/or integration);
  see `git log --stat 406f4ae..HEAD` for the full list. Notably:
  `test_payments_wallet_gateway.py` (double-refund rejected),
  `test_auth_routes.py` / `test_auth_password.py` (cookie flow, revocation, replay
  guard), `test_catalog_image_url_safety.py` / `test_catalog_admin_schemas.py`
  (SSRF validator), `test_catalog_pattern_safety.py` / `test_orders_validation.py`
  (ReDoS guard), `test_admin_audit_routes.py` (redaction), `test_inventory_crypto.py`
  (HMAC dedup hash), `test_bootstrap_prod_config_check.py` (CORS prod gate).
- Re-verify at the next security-review cycle that: no session-hijack report
  correlates with a pre-cookie refresh token; the audit feed redaction list still
  covers every provider's webhook shape as new acquirers are added.

## Alternatives considered (detail)

### Refresh-token transport — cookie vs. continuing localStorage vs. a full BFF

ADR-0026 already weighed this (its "Option 4") and deferred to a future hardening
step; this ADR is that step. A full BFF/session-proxy (Caddy or a Next.js API route
holding both tokens server-side, browser never sees either) remains un-chosen for
the same reason ADR-0026 gave: added ops complexity not yet warranted for a
single-VPS deployment, and the access token's 15-minute TTL keeps its
still-client-side exposure bounded.

### Access-token revocation — Redis blocklist vs. shortening the access TTL further

A shorter access TTL (e.g. 5 min) would shrink the same theft window without a
Redis dependency, but was rejected: it increases refresh-endpoint load
proportionally across every authenticated user for a benefit that only matters in
the rare explicit-logout-after-compromise case, which the blocklist already handles
exactly.

## References

- [ADR-0007](./0007-jwt-format-and-rotation.md) — JWT format and rotation (amended
  alongside this ADR)
- [ADR-0026](./0026-web-password-auth.md) — web password auth (amended alongside
  this ADR)
- [`docs/security/threat-model.md`](../security/threat-model.md)
- [`docs/security/pii-handling.md`](../security/pii-handling.md)
- [`docs/architecture/cache-keys.md`](../architecture/cache-keys.md)
- `apps/api/src/yupay/modules/auth/cookies.py` — refresh-cookie helpers
- `apps/api/src/yupay/modules/auth/service.py` — `_blocklist_access_token`,
  `login_password` dummy-hash compare
- `apps/api/src/yupay/modules/auth/telegram.py` — `enforce_widget_single_use`
- `apps/api/src/yupay/modules/payments/service.py` — `refund_admin` guard
- `apps/api/src/yupay/core/idempotency.py`,
  `apps/api/migrations/versions/0033_idempotent_responses.py`
- `apps/api/src/yupay/modules/catalog/image_url_safety.py`
- `apps/api/src/yupay/modules/audit/service.py`, `apps/api/src/yupay/core/logging.py`
- `apps/api/src/yupay/modules/inventory/crypto.py`
