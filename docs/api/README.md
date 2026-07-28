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

`wss://api.yupay.io/ws/orders?token=<short-lived-jwt>` — the token is a 60-second JWT minted
from the user's access token via `POST /api/v1/auth/ws-token`. After handshake the server
subscribes the connection to the appropriate Redis pub/sub channel. The protocol is a
discriminated-union JSON envelope; see `packages/api-client/src/realtime/messages.ts`.

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
`cursor`), `POST /reviews` (auth; body `{order_id, brand_slug, rating, body?}`;
**requires `Idempotency-Key`**; a repeat for the same `(user, order, brand)`
returns `409 already_reviewed` — the client treats that as "already submitted"),
`GET /reviews/mine`, `POST /reviews/{id}/report` (auth, Idempotency-Key).
Admin: `GET /admin/reviews?status=&reported=` + `POST /admin/reviews/{id}/{hide,unhide,remove}`
(each requires `Idempotency-Key`; the actions are naturally idempotent). Catalog
brand DTOs (`GET /catalog/brands`, `/catalog/brands/{slug}`) carry an optional
`rating: {avg, count}`. See `docs/decisions/0039-reviews-and-ratings.md`.
