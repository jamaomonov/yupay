# Guest reviews — design spec

**Date:** 2026-07-28
**Status:** approved (design), pending implementation plan
**Module:** `reviews` (extension) · surfaces: `apps/web` only

## Problem

The `reviews` module gates review creation on an authenticated user (`Review.user_id`
is `NOT NULL`, the POST route depends on `current_user`, uniqueness is
`(user_id, order_id, brand_id)`). But web checkout defaults to **guest** checkout
(`Order` = `user_id` XOR `guest_email`), so guest buyers — the majority of first-time
customers on a no-account store — can never review. The trust asset stays empty even as
real orders are delivered.

## Approach (chosen: A — reuse order-access)

A guest already proves order ownership with the **same capability the order page uses**:
the unguessable order UUID (delivered to them by email as `/orders/{id}`) plus their
email. The order GET (`GET /orders/{id}`) accepts `Authorization: Guest <jwt>` +
`X-Guest-Email`, verifying `email_hash(email, pepper) == jwt.email_hash`. The guest JWT is
freely mintable from any email (`POST /auth/guest`) and carries no secret — the real
security boundary is knowledge of the order UUID. Guest reviews reuse this exact
mechanism; no new emailed token or email send is introduced (rejected alternative B).

Scope is **web only**: in the Mini App the user is always identified via Telegram initData,
so there are no guests there.

## Data model — migration `00NN_guest_reviews`

Alter `reviews`:
- `user_id` → **nullable**.
- add `guest_email` **CITEXT NULL**.
- add CHECK `(user_id IS NULL) <> (guest_email IS NULL)` (exactly one set), mirroring the
  `orders` table invariant.
- **drop** `UniqueConstraint(user_id, order_id, brand_id)`; **add**
  `UniqueConstraint(order_id, brand_id)`. An order has exactly one buyer (user or guest),
  so one review per order+brand is the correct invariant for both and enforces the guest
  one-per-order rule with a single index.
- keep `ix_reviews_user` (`list_own` by `user_id`).

No backfill: existing rows all have `user_id` set and satisfy the new CHECK and unique key.

## Backend (`reviews` module)

**`service.create_review`** becomes actor-aware:
- signature accepts `user_id: str | None` and `guest_email: str | None` (exactly one
  non-null; assert).
- ownership check: user → `order.user_id == user_id`; guest → `order.guest_email == guest_email`
  (case-insensitive via CITEXT / normalised lower). Otherwise `ForbiddenError("not your order")`.
- unchanged: order must exist, `order.status == "delivered"`, order must contain the brand.
- persists `user_id` **or** `guest_email` accordingly; `status="published"`.
- conflict on `(order_id, brand_id)` → `ConflictError("already reviewed", code="already_reviewed")`.

**POST `/reviews`** route resolves the actor exactly like `GET /orders/{id}`:
- `Authorization: Bearer <access>` → user (existing `current_user` resolution).
- `Authorization: Guest <jwt>` + `X-Guest-Email` header → `verify_jwt(expected_kind="guest")`,
  compare `email_hash`; on match, actor is the normalised guest email; mismatch/absent →
  `UnauthorizedError` / `ValidationError`. Reuse the `Actor` + resolution logic that
  `orders/routes.py` already implements (extract a shared helper rather than duplicate).
- `Idempotency-Key` still required. Body still `{order_id, brand_slug, rating, body}`.
- `locale`: for a user, `user.locale`; for a guest, the request `Accept-Language` (first 3
  chars), defaulting to `ru`.
- response `ReviewOut.author_name`: user → `display_name`; guest → `None`.

**`service.list_published`**: change the `users` join from INNER to **LEFT OUTER** so guest
reviews (null `user_id`) appear; their `author_name` resolves to `None`. `ReviewOut.author_name`
is already `str | None` and the web renders `None` as the existing anonymous label
(`web.brandReviews.anonymous` = "Покупатель"/"Xaridor"/"Customer"). No schema change.

**New `GET /reviews/eligibility?order_id=...`** (actor-aware, same Bearer/Guest resolution):
returns `{ brand_slug: str | None, delivered: bool, already_reviewed: bool }` for the order
that the actor owns, so the web can suppress the CTA once a guest has reviewed. Owner check
identical to `create_review` (404/forbidden if the actor doesn't own the order). Single
indexed query on `(order_id, brand_id)` — no N+1. Logged-in users keep their existing
`GET /reviews/mine` gating unchanged; only the guest path needs this endpoint (users may
optionally be migrated to it later — out of scope here).

## Frontend (`apps/web`)

- The rate CTA / `WriteReviewPanel` gating changes from `Boolean(user)` to:
  **order delivered AND not already reviewed AND (logged-in user OR guest with a known email)**.
- Guest submit path: mint a guest token the same way checkout does
  (`POST /auth/guest { email }`), then submit the review with `Authorization: Guest <token>`
  + `X-Guest-Email` via `apiFetch(..., { anonymous: true, headers })` so no `Bearer` is added.
  Factor the guest-token mint into a small reusable helper (checkout + review share it).
- The guest's email at review time comes from the order page context (the `?email=` the
  order-success flow already carries, or the value the page already holds to view the order).
  A guest returning cross-device without their email is naturally limited exactly as
  order-viewing is — out of scope, consistent with existing behaviour.
- The guest CTA lives on the order-status page (a guest gets no global WS delivered modal —
  the realtime channel is user-only), gated via the new eligibility endpoint.

## Security & abuse

- Capability model identical to guest order-viewing: order UUID (from the buyer's email) +
  email. No weaker, no stronger.
- One review per `(order_id, brand_id)` — DB-enforced, covers guest spam per order.
- `Idempotency-Key` required (existing). Rate-limit the POST at FastAPI (slowapi) and Caddy,
  as for every public write.
- Post-moderation and auto-hide at ≥3 distinct reports remain (existing).
- Reporting stays user-only (`report_review` keys on `reporter_user_id`; the report unique
  constraint is `(review_id, reporter_user_id)`). Guests do not report.
- PII: `guest_email` is stored (like `orders.guest_email`) but is **never** returned in any
  response (`author_name` is `None` for guests) and is never logged (order ids and ratings
  are fine to log per project rules).

## Tests (coverage stays within the `reviews` gate)

- guest create success → published, `author_name` null, stats bumped.
- guest with wrong email for the order → `ForbiddenError`.
- guest on a not-`delivered` order → `ForbiddenError`.
- guest on an order that doesn't contain the brand → `ForbiddenError`.
- second guest review of the same order+brand → `ConflictError("already_reviewed")`.
- a user reviewing a guest-checkout order they don't own → forbidden (and vice-versa).
- `list_published` returns a guest review (LEFT join) with `author_name = None`.
- `GET /reviews/eligibility` for user and guest actors: delivered/already_reviewed/brand_slug.
- integration: actor resolution for `Guest` scheme (email_hash match / mismatch / missing header).

## Docs

- ADR: append a short amendment to `docs/decisions/0039-reviews-and-ratings.md` (guest path,
  actor model, uniqueness change) — no new ADR needed (same decision family).
- Update the reviews module `README.md` and the reviews sequence diagram to show the guest actor.
- Regenerate `docs/api/openapi.json` (new eligibility endpoint + guest auth on POST).
- No new user-facing strings expected (reuse `brandReviews.*`); if any are added, all three
  locales in the same PR.

## Out of scope

- Emailed "rate us" review magic-link (alternative B) — not needed under Approach A.
- Cross-device guest review without the email in hand — same limitation as order-viewing.
- Migrating logged-in users off `GET /reviews/mine` onto the eligibility endpoint.
- Mini App (no guests there).
