# reviews

Brand reviews & ratings. Verified buyers rate a **brand** (1–5 stars + optional
text); aggregates feed the storefront and Google rich snippets.

## Rules

- **Who:** a logged-in user with a `delivered` order that contains an item of
  the brand (`sku → product → brand`). Guests cannot review.
- **Cardinality:** one review per `(user_id, order_id, brand_id)` (UNIQUE). A
  repeat submit returns `409 already_reviewed`.
- **Immutable:** no user edit or delete. Admins `hide`/`unhide`/`remove`; users
  `report`.
- **Post-moderation:** a review is `published` on creation. Only `published`
  reviews count toward stats and appear in public lists. A review crossing
  `_REPORT_AUTO_HIDE_THRESHOLD` (default 3) distinct reports is auto-hidden.

## Tables

- `reviews` — the review (rating 1–5 CHECK, `status` published/hidden/removed,
  `body` ≤ 2000, `locale`). Anchored to `order_id` as proof of purchase.
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
(buyer, Idempotency-Key), `GET /reviews/mine`, `POST /reviews/{id}/report`.
Admin: `GET /admin/reviews` (queue), `POST /admin/reviews/{id}/{hide,unhide,remove}`.

## Notes

- Author identity exposed as `display_name` or `null` — **never** the email.
- UGC (`body`) is escaped by the frontends on render; the service never logs it.
- Moderation actions are naturally idempotent (a no-op status transition does
  not double-adjust stats), so they require the header but need no replay store.

See `docs/decisions/0039-reviews-and-ratings.md`.
