# Reviews & Ratings — Design

**Date:** 2026-07-28
**Status:** Approved (brainstorming complete)
**Author:** brainstorming session
**Related ADR:** `docs/decisions/0039-reviews-and-ratings.md` (to be written)
**Migration:** `0034_reviews`

## Goal

Let verified buyers rate a **brand** (1–5 stars) with an optional text comment, show
per-brand aggregate ratings across the storefront (web + Mini App), and feed Google
rich snippets via structured data — to raise trust and organic conversion.

## Decisions (locked)

| Decision          | Choice                                                                            | Rationale                                                                                                                 |
| ----------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Rated entity      | **Brand**                                                                         | Matches the storefront page unit (`/store/[brandSlug]`); rating doesn't fragment across SKUs.                             |
| Who can review    | **Verified buyers only**                                                          | Logged-in user with a `delivered` order containing that brand. High trust, low spam. Guest reviews are a later extension. |
| Moderation        | **Post-moderation**                                                               | Publish immediately; admin can hide/remove; users can report. Verified-purchase gate already limits spam.                 |
| Content           | **1–5 stars + optional text**                                                     | E-commerce standard; feeds SEO rich snippets.                                                                             |
| Surfaces          | **Web + Mini App**                                                                | SEO structured data on web only.                                                                                          |
| Cardinality       | **One review per `(user, order, brand)`**                                         | Anchored to a delivered order as proof of purchase.                                                                       |
| Editability       | **Immutable**                                                                     | No user edit (`PATCH` dropped). Once posted, the review freezes — simpler, SEO snapshot stable, no rating drift.          |
| User delete       | **No** (MVP)                                                                      | Only admin `hide`/`remove`; users can `report`.                                                                           |
| Aggregate storage | **Reviews-owned `brand_rating_stats` table + `api.py` batch lookup** (Approach A) | Cheap reads on the `/store` grid (no N+1), histogram built-in, module boundaries clean.                                   |

### CTA behaviour

After a purchase is `delivered`, the order-history surface shows a passive
"Rate your purchase" CTA per un-reviewed `(order, brand)`. Once the review is
submitted the CTA disappears permanently. **No reminders, no push nagging.**

## Architecture

New modular-monolith module `apps/api/src/yupay/modules/reviews/`:
`api.py` (public interface + routers), `routes.py`, `service.py`, `models.py`,
`schemas.py`, `tests/`. Public router + `admin_router` mounted in
`apps/api/src/yupay/api/v1/__init__.py` (alphabetical).

### Data model (migration `0034_reviews`)

**`reviews`**

- `id` UUID PK
- `brand_id` FK→`brands` (indexed)
- `user_id` FK→`users` (indexed)
- `order_id` FK→`orders` — proof-of-purchase anchor
- `rating` SMALLINT, `CHECK (rating BETWEEN 1 AND 5)`
- `body` TEXT NULL, application-capped at 2000 chars
- `status` VARCHAR(16) NOT NULL DEFAULT `'published'` — one of `published` / `hidden` / `removed`
- `locale` CHAR(3) — captured from request for display
- `created_at`, `updated_at` TIMESTAMPTZ
- **UNIQUE `(user_id, order_id, brand_id)`**
- Index `(brand_id, status, created_at DESC)` for keyset list queries

**`review_reports`**

- `id` UUID PK
- `review_id` FK→`reviews` (indexed)
- `reporter_user_id` FK→`users` NULL
- `reason` VARCHAR(64)
- `created_at` TIMESTAMPTZ
- **UNIQUE `(review_id, reporter_user_id)`** — no double-reporting

**`brand_rating_stats`** (reviews-owned aggregate; only `published` counted)

- `brand_id` PK, FK→`brands`
- `count` INT NOT NULL DEFAULT 0
- `sum_rating` BIGINT NOT NULL DEFAULT 0
- `avg` NUMERIC(3,2) NOT NULL DEFAULT 0
- `count_1`..`count_5` INT NOT NULL DEFAULT 0 (histogram)
- `updated_at` TIMESTAMPTZ

Indices are added in the same migration as the queries that need them.

### Service logic (`service.py`)

- **`create_review(user, order_id, brand_id, rating, body, locale)`**
  - Verify the order belongs to `user`, is in status `delivered`, and contains an
    `OrderItem` whose `sku → product → brand` equals `brand_id`. Else `403`/`409`.
  - Enforce `(user_id, order_id, brand_id)` uniqueness (→ `409 ConflictError`).
  - Insert review (`status='published'`) and bump `brand_rating_stats` in **one
    transaction** with `SELECT … FOR UPDATE` on the stats row.
  - Honour `Idempotency-Key` (project write-endpoint rule).
- **`report_review(review_id, reporter, reason)`** — insert report; when distinct
  report count crosses a configurable threshold (default 3), auto-set `status='hidden'`
  and adjust stats; emit an audit event for the admin queue.
- **`admin_set_status(review_id, status)`** — hide/unhide/remove; recompute the stats
  delta (a review leaving `published` decrements; returning increments).
- **`list_reviews(brand_id, cursor, limit)`** — `published` only, keyset pagination,
  newest-first (MVP sort).
- **`get_stats(brand_ids) -> dict[str, BrandRatingStats]`** — public `api.py` batch
  lookup for catalog enrichment (no N+1).
- **Reconcile job** (scheduler `recompute_brand_rating_stats`, nightly) — recomputes
  every brand's stats from `published` reviews as a safety net against drift.

### API (v1)

Public:

- `GET /v1/brands/{brandSlug}/reviews?cursor=&limit=` — aggregate + paginated list
- `POST /v1/reviews` — auth; body `{order_id, brand_id, rating, body?}`; `Idempotency-Key`
- `POST /v1/reviews/{id}/report` — auth; body `{reason}`

Admin:

- `GET /v1/admin/reviews?status=&reported=&cursor=` — moderation queue
- `POST /v1/admin/reviews/{id}/hide` · `POST /v1/admin/reviews/{id}/unhide`
- `POST /v1/admin/reviews/{id}/remove`

Catalog enrichment: `store` / `brand` DTOs gain `rating: {avg, count}` via
`reviews.api.get_stats`. New fields are **optional** on the DTO so the SSG build
against the live API doesn't crash (see [[web-ssg-prerenders-against-deployed-api]]).

### Frontend

**Web** (`apps/web`)

- `/store/[brandSlug]`: rating summary (avg stars + count + histogram bars) → reviews
  list (paginated) → review form for eligible logged-in buyers.
- `/store` grid cards: `avg ★ (count)`.
- `account/orders`: passive "Rate your purchase" CTA per un-reviewed delivered `(order, brand)`.
- JSON-LD `Product`/`Brand` with `aggregateRating` + up to N `review` on the brand page.

**Mini App** (`apps/miniapp`)

- Brand / TopUp view: summary + list + form.
- `History` page: "Rate" CTA per eligible order.

**i18n:** every new string added to `ru/en/uz` in the same PR. Star/plural counts via
ICU MessageFormat.

### SEO

`aggregateRating` + `review` JSON-LD on brand pages → Google star rich snippets. The
verified-purchase gate satisfies Google's genuine-reviews policy (no admin editing of
user content).

### Anti-abuse & security

- Verified-purchase gate; one review per `(user, order, brand)`.
- Report mechanism + auto-hide over threshold.
- Rate-limit `POST /v1/reviews` and `.../report` (slowapi) at the FastAPI edge.
- Body length cap; **escape UGC on render** (XSS) on both surfaces.
- Show author `display_name`, never email (PII). Reviews never log PII.

## Out of scope (YAGNI)

Merchant replies, helpful/not-helpful voting, photos, language filtering, guest reviews,
ML anti-spam. The `review_reports` table and `status` enum keep the model extensible.

## Testing

- Unit + integration (testcontainers) for `create_review` eligibility matrix
  (delivered vs not, brand-in-order vs not, duplicate → 409), stats transactionality,
  report auto-hide threshold, admin status transitions and stats deltas.
- List endpoint integration test **asserts query count** (no N+1) per project rule.
- TS: component tests for the rating summary, form, and card badge.
- Coverage: module ≥ 80% (reviews is not in the 95% payments/wallet/fulfillment tier).

## Docs (same PR)

- `docs/architecture/module-map.md` + `apps/api/src/yupay/modules/reviews/README.md`
- Sequence diagrams: `docs/architecture/sequence-diagrams/leave-review.mmd`,
  `.../review-moderation.mmd`
- ADR `docs/decisions/0039-reviews-and-ratings.md` (new module + denormalized aggregate
  - SEO structured-data choice)
- `docs/api/openapi.json` regen (`make gen-api`) + `packages/api-client`
- `docs/security/threat-model.md` (UGC/XSS) + `pii-handling.md` (author identity)
- `docs/architecture/cache-keys.md` if brand-stats reads get a Redis cache
