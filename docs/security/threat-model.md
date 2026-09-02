# YuPay — Threat model

> Living document. Review at least quarterly. Update whenever auth, payments, or supplier
> integrations change.

## Trust boundaries

```mermaid
flowchart LR
    Internet -->|TLS| Caddy
    Caddy --> Web
    Caddy --> MiniApp
    Caddy --> API
    API --> DB[(Postgres)]
    API --> Redis[(Redis)]
    API --> MinIO[(MinIO)]
    API --> Worker
    Worker --> ExtPay[Payment Gateways]
    Worker --> ExtSup[Supplier APIs]
    Worker --> Email[Email Provider]
    Worker --> Telegram[Telegram Bot API]
    ExtPay -.->|webhooks, signed| Caddy
    ExtSup -.->|webhooks, signed| Caddy
    Telegram -.->|webhooks, signed| Caddy
```

## STRIDE

| Threat                     | Where                                                                                                                          | Mitigation                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Spoofing**               | Telegram Mini App initData forgery                                                                                             | HMAC validation against bot token, server-side, on every request                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **Spoofing**               | Telegram Login Widget payload replay                                                                                           | HMAC + `auth_date` freshness check, plus single-use enforcement (`auth:tg-widget:{hash}` Redis `SET NX`) — a captured, still-fresh payload can't be replayed a second time (ADR-0038 §7)                                                                                                                                                                                                                                                                                                                                                                          |
| **Spoofing**               | Webhook source forgery                                                                                                         | Per-provider signature verification before parsing body, using constant-time compares (`hmac.compare_digest`, OR-accumulated across configured keys) so response timing can't leak which credential matched (ADR-0038 §7)                                                                                                                                                                                                                                                                                                                                         |
| **Tampering**              | Payment amounts modified in transit                                                                                            | TLS + provider signs the webhook body                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **Tampering**              | Ledger postings altered                                                                                                        | Append-only DB constraint; updates/deletes rejected at the data layer                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **Tampering**              | Second refund posted against an already-refunded payment                                                                       | `refund_admin` only admits `status == "succeeded"`; any refund (full or partial) moves the status off `succeeded`, so a second call is rejected (ADR-0038 §3). Multi/partial refund tracking is a deferred `payment_refunds`-table follow-up                                                                                                                                                                                                                                                                                                                      |
| **Repudiation**            | Customer disputes order                                                                                                        | Order events table + ledger trail; all webhooks persisted with `external_event_id`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **Information disclosure** | PII in logs                                                                                                                    | Structured logger redactor; PII fields blocklisted (now includes Telegram `chat_id`, ADR-0038 §7)                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| **Information disclosure** | Provider secrets/PII surfaced verbatim in the admin audit feed                                                                 | `audit.list_audit_events` recursively masks any key on the redaction blocklist (card/pan/cvv/secret/signature/…) before returning a page — closes raw webhook JSON (e.g. Octo masked PAN/`rrn`) reaching the UI unmasked (ADR-0038 §6)                                                                                                                                                                                                                                                                                                                            |
| **Information disclosure** | Voucher codes stolen                                                                                                           | Codes encrypted at rest (libsodium / pgcrypto); dedup `code_hash` is HMAC-SHA256 keyed off an HKDF-derived key (not bare SHA-256), so a leaked table alone can't be brute-forced against low-entropy codes (ADR-0038 §7)                                                                                                                                                                                                                                                                                                                                          |
| **Information disclosure** | Prometheus `/metrics` on public API host                                                                                       | Blocked at Caddy (`respond 404`); Prometheus scrapes `api:8000` over the internal docker network only                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **Information disclosure** | Guest email in URLs / proxy logs / browser history                                                                             | Guest order/deliveries lookup reads `X-Guest-Email` as a header, not a `?email=` query param (ADR-0038 §7); `OrderEvent.actor` stores a truncated email hash, never the raw address (ADR-0038 §6)                                                                                                                                                                                                                                                                                                                                                                 |
| **Tampering**              | Stored XSS via catalog-sourced JSON-LD (brand names, FAQ)                                                                      | `serializeJsonLd` escapes `<` so `</script>` can't terminate the tag; storefront CSP pins `default-src`/`object-src`/`base-uri`/`form-action` (`script-src 'unsafe-inline'` remains — forced by Next.js SSG, no per-request nonce possible; accepted risk, ADR-0038 §8)                                                                                                                                                                                                                                                                                           |
| **Tampering**              | Admin-authored regex (`FormField.pattern`) causes ReDoS                                                                        | Write-time guard rejects nested-quantifier/oversized-bound/overlong patterns; checkout additionally caps matched input at 256 chars before `re.fullmatch` — defense in depth, not exhaustive (ADR-0038 §7)                                                                                                                                                                                                                                                                                                                                                        |
| **SSRF**                   | Catalog image URL (`image_url`/`logo_url`/`hero_image_url`) used to make the Next.js image optimizer fetch an internal address | Pydantic validator rejects non-`https`, `localhost`/`*.internal`/`*.local`, and IP-literal hosts in private/loopback/link-local (incl. `169.254.169.254`)/reserved/multicast ranges, at both admin write and G2B import (ADR-0038 §5). **Residual: DNS rebinding is not closed** — validated at write time, not at fetch time                                                                                                                                                                                                                                     |
| **DoS**                    | Public endpoints flooded                                                                                                       | FastAPI slowapi per-IP limit on every route (ADR-0028) + Redis `ip_guard` on auth; Caddy-layer limit pending (stock image lacks `rate_limit`), Cloudflare as escalation                                                                                                                                                                                                                                                                                                                                                                                           |
| **DoS**                    | Supplier API rate-limited                                                                                                      | Per-supplier outbound token bucket; circuit breaker                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **DoS**                    | Rejected-webhook audit rows used to flood storage                                                                              | Raw body capped at 4096 chars before persisting a signature/parse-failure row (ADR-0038 §7)                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **EoP**                    | Guest checkout token used outside scope                                                                                        | Token scoped to `email` + `order_id`; backend enforces                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **EoP**                    | Refresh token leaked (XSS or otherwise)                                                                                        | Rides an `HttpOnly; SameSite=Lax` cookie, never JS-readable and never in the JSON body/`localStorage` (ADR-0007, implemented per ADR-0038 §1); stored hashed in DB; rotation on every use; reuse triggers full session-lineage revocation                                                                                                                                                                                                                                                                                                                         |
| **EoP**                    | Access token still usable after logout                                                                                         | `auth:revoked:{jti}` Redis blocklist, set on logout and checked in `current_user` (ADR-0007, implemented per ADR-0038 §2). **Residual:** the refresh-reuse trip-wire can't blocklist the paired access token (no `jti` on that request) — it self-expires within ≤ 15 min                                                                                                                                                                                                                                                                                         |
| **Spoofing**               | WebSocket handshake token reused to read another user's order events                                                           | `kind="ws"` JWT's `channel` claim is always the caller's own `user:{id}` (server-minted at handshake, never client-supplied); the WS route subscribes to `realtime:user:{sub}` derived from the verified token, not from anything the client sends (ADR-0040)                                                                                                                                                                                                                                                                                                     |
| **Information disclosure** | Handshake token exposed via the WS URL (`?token=`) instead of a header                                                         | Unavoidable — the browser `WebSocket` API can't set request headers. Mitigated by `wss://` (TLS) in transit, a 60-second TTL, and the token carrying no PII (just `sub`/`channel`, both the caller's own id). **Residual:** the token can appear in server/proxy access logs for that 60s window (ADR-0040)                                                                                                                                                                                                                                                       |
| **Information disclosure** | Email-link tokens (`/auth/verify?token=`, `/auth/reset?token=`) reported to Yandex Metrika, then crawled by Yandex             | `SENSITIVE_PARAMS` (`lib/scrubUrl.ts`) strips `access`, `email` and `token` from every URL leaving the browser for analytics; the counter's inline snippet generates its `delete` calls from that same list so the first pageview and SPA hits can't scrub different sets. `/auth/` is `Disallow`ed in robots.txt so a JS-rendering crawler never fetches — and so never spends — a single-use token. **Found in production:** Yandex's crawl log listed `/en/auth/verify?token=eyJhbGciOi…` because `token` was missing from a hand-kept second copy of the list |

## PII inventory

See `pii-handling.md`.

## User-generated content — reviews

- **XSS via review text:** review `body` is user-supplied. It is stored raw and
  **escaped on render** by both frontends (React text nodes / Next.js — never
  `dangerouslySetInnerHTML`; the admin queue renders it as plain text too). The
  API never interpolates it into HTML.
- **Spam / fake reviews:** mitigated by the verified-purchase gate (only a buyer
  with a `delivered` order for the brand can post), one-per-`(user, order, brand)`,
  the global rate limiter on `POST /reviews`, and a report → auto-hide (≥3
  distinct reporters) + admin moderation path.
- **Reviewer de-anonymisation:** the public API exposes the author's
  `display_name` or `null`, **never** the email; the service never logs `body`.

## WebSocket (realtime order updates)

- **Handshake token, not a bearer token:** `POST /realtime/handshake` (behind
  the normal `current_user` bearer-token auth) mints a **60-second**,
  single-purpose `kind="ws"` JWT whose `channel` claim is always the caller's
  own `user:{user.id}`. The client cannot request another user's channel —
  there is no field to ask for one — and the WS route
  (`WS /realtime/ws/orders?token=`) subscribes to `realtime:user:{sub}` using
  the `sub` decoded from the _verified_ token, never a client-supplied id.
- **Per-user channel isolation:** one Redis pub/sub channel per user
  (`realtime:user:{id}`, see `docs/architecture/cache-keys.md`); a socket
  subscribes to exactly one for its whole lifetime. There is no code path
  that lets a connection read another user's channel — the channel name is
  computed server-side from the token, never accepted as a parameter.
- **`?token=` query-string tradeoff:** the browser `WebSocket` API has no way
  to set an `Authorization` header, so the handshake token rides the URL
  (`wss://api.yupay.uz/api/v1/realtime/ws/orders?token=...`). Accepted:
  `wss://` (TLS) protects it in transit, the TTL is 60 seconds, and the token
  carries no PII. The residual risk is the token appearing in server/proxy
  access logs for that short window (ADR-0040).
- **No message replay / history:** on reconnect the client re-handshakes and
  gets no backlog — every message is a nudge that triggers an authoritative
  `GET /orders/{id}` refetch, never trusted as payload of record. A
  leaked/expired token is useless once its 60 seconds elapse, even before any
  socket is opened with it.
- **Guests never get a socket:** `publish_order_event` no-ops when
  `order.user_id is None`, and the frontends only mount the socket hook for a
  logged-in user — guest checkout is unaffected and keeps polling.
- **No PII in the wire payload:** messages carry `orderId`/`status`/
  timestamps only (see `packages/api-client/src/realtime/messages.ts`) — no
  email, phone, or Telegram id ever crosses the socket.

## Order claim, email verification & payment return (Phase 3 web-orders)

- **Email verification enforced at password login:** `login_password` rejects
  accounts with `email_verified_at IS NULL` (`EmailUnverifiedError`, 403).
  Telegram, guest-checkout, and admin-dev logins are exempt (no email to
  verify). Register no longer issues a session; verify-email does. This makes a
  user's email a trustworthy identity key for the order claim below. Existing
  users were grandfathered to verified by migration `0036` (forward-only), so
  enforcement applies only to signups from that point on.
- **Verify-email tokens are single-use:** consumed via `SET NX
auth:emailverify:{jti}` (same pattern as `auth:pwreset:{jti}`), so a leaked or
  replayed verify link cannot repeatedly mint sessions within its TTL. Recovery
  is the resend endpoint if a scanner/double-click burns the token.
- **Resend-verification is non-enumerating:** always 204, and the email send is
  scheduled off the request path (like `request_password_reset`) so response
  latency doesn't reveal whether the address exists or is already verified.
- **Order claim cannot cross accounts:** `POST /orders/claim` requires a Bearer
  session (guests are rejected before the handler), re-checks
  `email_verified_at`, and reassigns only orders where `user_id IS NULL` and
  `guest_email` matches the caller's email, in one XOR-safe UPDATE. It can never
  move an order to a non-matching or unverified account.
- **Guest order-view capability is unchanged:** a guest token is minted from an
  email but grants access only to orders whose `guest_email` matches (the
  backend re-hashes `X-Guest-Email` against the token). Knowing an unguessable
  order id **and** its email remains the capability — no escalation added.
- **Payment `return_url` open-redirect hardening:** the acquirer return URL
  defaults to the storefront (`web_base_url`) and any client-supplied
  `return_url` is validated same-origin (scheme+host) as `web_base_url`, so it
  can only ever bounce the customer back to our own storefront. Payment truth is
  the webhook, never the return; the return is UX only. **Deploy invariant:**
  `WEB_BASE_URL` must equal the canonical web origin (`https://yupay.uz`) — a
  mismatch/unset value makes web card intents 422 (see the email-verification
  runbook).

## Out of scope (we do not handle)

- Card data (PAN, CVV) — all card collection redirected to hosted provider fields.
- KYC documents — none collected at MVP.
- Children's data — TOS requires 18+.

## Google Sign-In (2026-09-02)

Linking is by Google-verified email. Attack considered: seed an account with
someone else's email + password, wait for the victim to «sign in with
Google» into it. Mitigations: password login refuses unverified emails, and
a Google login landing on an unverified-email account clears any stored
password hash before marking the email verified. The GIS credential is
verified server-side (signature, audience, expiry) via google-auth; the
`/auth/google` route sits behind the same `ip_guard` family as the other
credential endpoints (IP axis; the email is unknown pre-verification).

## Steam Sign-In (2026-09-02)

OpenID 2.0. The assertion is verified by round-tripping the exact parameter
set back to Steam (`check_authentication`); Steam marks assertions used, so
replay dies at their side. A `return_to` outside our callback URL is refused
before any network call. Identity is the steamid64 only (no email), stored
in `steam_links`; the endpoint sits behind `ip_guard` (`steam-login`).
