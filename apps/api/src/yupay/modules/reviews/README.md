# reviews

Brand reviews & ratings. Verified buyers rate a **brand** (1–5 stars + optional
text); aggregates feed the storefront and Google rich snippets.

## Rules

- **Who:** a logged-in user, **or a guest**, with a `delivered` order that
  contains an item of the brand (`sku → product → brand`). The actor is
  resolved by `auth.deps.resolve_request_actor`: `Authorization: Bearer
<access-jwt>` → user, or `Authorization: Guest <guest-jwt>` +
  `X-Guest-Email` → guest — the same capability model (order UUID + checkout
  email) as guest order-view, not a new emailed token. Web only; the Mini App
  has no guest checkout.
- **Cardinality:** one review per `(order_id, brand_id)` (UNIQUE) — an order
  has exactly one buyer identity (user XOR guest), so this covers both actor
  kinds. A repeat submit returns `409 already_reviewed`.
- **Rating is immutable** after create (aggregates / SEO snapshot stay put).
  **Body** may be replaced via `PATCH /reviews/{id}` for 15 minutes
  (`amend_window_closed` after that). Clients send that PATCH from an
  explicit Submit (one draft: chips toggle labels in the same textarea as
  free text). Catch-up dialogs snapshot `pending-ask` so the follow-up is
  not unmounted when the query goes null after the rating POST. No user delete. Admins
  `hide`/`unhide`/`remove`; users `report`.
- **Post-moderation:** a review is `published` on creation. Only `published`
  reviews count toward stats and appear in public lists. A review crossing
  `_REPORT_AUTO_HIDE_THRESHOLD` (default 3) distinct reports is auto-hidden.

## Tables

- `reviews` — the review (rating 1–5 CHECK, `status` published/hidden/removed,
  `body` ≤ 2000, `locale`). Anchored to `order_id` as proof of purchase.
  `user_id` is nullable; a guest-authored row instead carries `guest_email`
  (CITEXT). `CHECK ((user_id IS NULL) <> (guest_email IS NULL))` enforces
  exactly one identity per row.
- `review_reports` — abuse reports, UNIQUE `(review_id, reporter_user_id)`.
- `brand_rating_stats` — denormalized per-brand aggregate (`count`, `sum_rating`,
  `avg`, `count_1..5` histogram), bumped transactionally under `FOR UPDATE` on
  every status change. Only `published` reviews are counted.

## Public surface (`api.py`)

- `get_stats(db, brand_ids) -> dict[str, BrandRatingStats]` — batch aggregate
  lookup used by `catalog` to attach `rating` to brand DTOs (no N+1).
- `recompute_all_stats(db) -> int` — full rebuild from published reviews; the
  scheduler runs it nightly as a drift safety net.
- `router` (`/reviews`) + `admin_router` (`/admin/reviews`).

## Endpoints

Public: `GET /reviews/brands/{slug}` (list + aggregate), `POST /reviews`
(buyer — Bearer **or** `Guest <jwt>` + `X-Guest-Email` — Idempotency-Key;
rating-only is enough — `body` is optional), `PATCH /reviews/{id}` (same
actor; `{body}` only; 15-minute window; Idempotency-Key),
`GET /reviews/eligibility?order_id=` (same actor resolution; returns
`{brand_slug, delivered, already_reviewed}` so the caller can gate a CTA/form
without a failed POST), `GET /reviews/pending-ask` (user-only; one
2h–14d-old unreviewed catalog delivery or `null` — next-session catch-up),
`GET /reviews/mine` (user-only), `POST /reviews/{id}/report` (user-only — a
guest cannot report).
Admin: `GET /admin/reviews` (queue), `POST /admin/reviews/{id}/{hide,unhide,remove}`.

## Notes

- Author identity exposed as `display_name` or `null` — **never** the email.
  A guest-authored review renders with the same `null`/anonymous label as a
  user review with no display name; `guest_email` itself is **never**
  serialized in any response DTO and **never** logged (`review.created` logs
  only `brand_id` + `rating`).
- UGC (`body`) is escaped by the frontends on render; the service never logs it.
- Moderation actions are naturally idempotent (a no-op status transition does
  not double-adjust stats), so they require the header but need no replay store.

See `docs/decisions/0039-reviews-and-ratings.md`.
