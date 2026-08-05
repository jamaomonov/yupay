# YuPay API

The single source of truth for the API surface is **`docs/api/openapi.json`**, regenerated
by CI on every PR from the FastAPI app via `make gen-api`. Don't hand-edit it.

## How the schema flows

```
apps/api  ──▶  FastAPI.openapi()  ──▶  docs/api/openapi.json
                                       │
                                       └──▶ @hey-api/openapi-ts ──▶ packages/api-client/src/generated/
                                                                     ▼
                                                       imported by apps/web and apps/miniapp
```

## Conventions

- All endpoints live under `/api/v1/`. Webhooks live under `/webhooks/{provider}` (no auth
  header — signature-verified instead).
- JSON only; `snake_case` keys; ISO-8601 timestamps; cursor pagination
  (`?cursor=...&limit=...`).
- Errors are RFC 7807 `problem+json` with stable `type` URIs.
- All write endpoints accept an `Idempotency-Key` header (>=16 chars). Enforced today on
  `POST /orders`, `POST /payments/intents`, `POST /admin/payments/{id}/refund` —
  **missing/short key → 422**; a repeated key replays the original result.
- Money is `{ "amount": "12345.678", "currency": "USD" }` — strings to preserve precision.

## Content-managed brand SEO copy

Brand marketing copy — `brand_translations.highlights` (the value-prop chips), plus
`short_description` / `description` / `instructions`, and the `brand_faqs` — is **content,
not fixtures**. It is not populated by `scripts/seed.py` and not shipped as an Alembic data
migration. It lives in idempotent seed SQL under `scripts/seed/` and is applied by an operator
(psql), gated by the standing deploy rule.

The `steam` brand's pack is `scripts/seed/steam_seo.sql` (ru/en/uz): it `UPDATE`s the three
`brand_translations` rows in place and rebuilds the FAQs via delete-then-insert, all inside a
single transaction. Re-running yields identical content. It depends on migration
`0032_brand_highlights` (adds the `highlights` column) being applied first.

## Auth

| Surface                     | Header                                                          |
| --------------------------- | --------------------------------------------------------------- |
| Web (logged-in user)        | `Authorization: Bearer <access-jwt>`                            |
| Web (guest checkout)        | `Authorization: Guest <guest-token>`                            |
| Telegram Mini App           | `Authorization: tma <raw initData>` (HMAC-verified server-side) |
| Service-to-service (future) | `Authorization: Service <signed-jwt>`                           |

## WebSocket

`POST /api/v1/realtime/handshake` (normal `Authorization: Bearer <access-jwt>` auth) mints a
60-second, single-purpose `kind="ws"` token scoped to the caller's own channel
(`channel="user:{id}"`). The client then opens
`wss://api.yupay.uz/api/v1/realtime/ws/orders?token=<ws-token>` — the browser `WebSocket` API
can't set headers, so the token rides the query string (60s TTL; tradeoff documented in
`docs/security/threat-model.md` and ADR-0040). The server verifies the token, subscribes the
socket to the Redis pub/sub channel `realtime:user:{id}`, and forwards every published message
plus a 25-second keepalive ping. The protocol is a discriminated-union JSON envelope; see
`packages/api-client/src/realtime/messages.ts`.

This endpoint pair doesn't fully show up in `openapi.json`: OpenAPI 3.1 has no WebSocket
operation object, so FastAPI omits `@router.websocket(...)` routes from the generated schema —
only `POST /realtime/handshake` (a normal HTTP route) appears there and regenerates like any
other endpoint. Guests never connect (`useOrderSocket` mounts only for a logged-in user, and
`publish_order_event` no-ops for guest orders), so guest checkout keeps polling
`GET /orders/{id}` unchanged. See `docs/decisions/0040-order-realtime-ws.md` and
`apps/api/src/yupay/modules/realtime/README.md`.

## Webhooks per provider

| Provider | Path                          | Signature header                                                   |
| -------- | ----------------------------- | ------------------------------------------------------------------ |
| Stripe   | `/webhooks/payments/stripe`   | `Stripe-Signature`                                                 |
| PayPal   | `/webhooks/payments/paypal`   | `PAYPAL-AUTH-ALGO` + `PAYPAL-CERT-URL` + `PAYPAL-TRANSMISSION-SIG` |
| YooKassa | `/webhooks/payments/yookassa` | IP allowlist + HMAC over body                                      |
| Click    | `/webhooks/payments/click`    | HMAC over body                                                     |
| Payme    | `/webhooks/payments/payme`    | Basic auth + signed payload                                        |
| Uzum     | `/webhooks/payments/uzum`     | HMAC over body                                                     |
| Crypto   | `/webhooks/payments/crypto`   | HMAC over body                                                     |

Each webhook is documented in detail in `apps/api/src/yupay/modules/payments/gateways/<provider>.py`
(docstring on the gateway class).

## Reviews

Public: `GET /reviews/brands/{slug}` (published reviews + aggregate, keyset
`cursor`), `POST /reviews` (body `{order_id, brand_slug, rating, body?}`;
**requires `Idempotency-Key`**; a repeat for the same `(order, brand)` returns
`409 already_reviewed` — the client treats that as "already submitted"),
`GET /reviews/mine`, `POST /reviews/{id}/report` (auth, Idempotency-Key).
Admin: `GET /admin/reviews?status=&reported=` + `POST /admin/reviews/{id}/{hide,unhide,remove}`
(each requires `Idempotency-Key`; the actions are naturally idempotent). Catalog
brand DTOs (`GET /catalog/brands`, `/catalog/brands/{slug}`) carry an optional
`rating: {avg, count}`. See `docs/decisions/0039-reviews-and-ratings.md`.

`POST /reviews` accepts **either** a logged-in user (`Authorization: Bearer
<access-jwt>`) **or a guest** (`Authorization: Guest <guest-jwt>` +
`X-Guest-Email: <email>`) — the same dual-actor resolution
(`resolve_request_actor`) as guest order-view (see the Auth table above); the
guest JWT's `email_hash` claim is cross-checked against the `X-Guest-Email`
header server-side. `GET /reviews/mine` and `POST /reviews/{id}/report` stay
Bearer-only — a guest cannot list their reviews across orders or report
another review. Web only; the Mini App has no guest checkout.

`GET /reviews/eligibility?order_id=<id>` runs the same actor resolution as
`POST /reviews` (Bearer or Guest+`X-Guest-Email`) against the given order and
returns `{brand_slug: string | null, delivered: boolean, already_reviewed:
boolean}`, letting the client gate a "rate your purchase" CTA/form without a
failed POST. `guest_email` is a capability credential only — it is never
returned in any reviews response body and never logged.

## Guest delivered-code access (magic link)

`GET /orders/{id}/deliveries` returns the order's delivered voucher/gift codes.
A logged-in owner uses `Authorization: Bearer <access>`. A **guest** must present
an order-scoped `guest_order` token (`Authorization: Guest <jwt>` + `X-Guest-Email`)
— **not** the freely-mintable email-only `guest` token, which no longer unlocks
codes. The `guest_order` token is minted server-side and delivered as the `?access=`
param of the link in the order's delivered email; it names the exact `order_id` it
unlocks, so knowing the buyer's email is not enough to read another order's codes.

`POST /orders/{id}/code-access` (body `{email}`) re-mails a fresh magic link + the
codes to the **order's own address**. It is **non-enumerating** (always `204`,
per-IP `guard_ip` throttled) and never mails the caller's input, so it cannot
exfiltrate codes to an attacker-controlled address. See
`docs/decisions/0042-guest-code-access-magic-link.md`.
