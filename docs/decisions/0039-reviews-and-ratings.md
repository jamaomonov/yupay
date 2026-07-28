# 0039. Brand reviews & ratings

- **Status**: Accepted
- **Date**: 2026-07-28
- **Deciders**: @jamaomonov
- **Tags**: backend | frontend | data

## Context and problem statement

The storefront had no social proof: a hardcoded testimonials block on the web
home and a fake "4.9★" chip in the Mini App (pulled during the security audit as
"trust present but unearned"). We want genuine, per-brand ratings that raise
buyer trust and feed Google rich snippets, without opening a spam/abuse hole.

## Decision drivers

- Trust + conversion on a guest-friendly storefront; SEO rich snippets.
- Anti-abuse: only real buyers, no ballot-stuffing, moderation for the tail.
- The `/store` grid renders many brand cards — reading a rating must not N+1.
- Keep module boundaries (no cross-module SQL joins; `api.py` is the surface).

## Considered options

1. **Brand-level, verified-buyer, denormalized aggregate table** (Approach A).
2. Product/SKU-level reviews — more granular but fragments the rating and the
   storefront is brand-centric (`/store/[brandSlug]`).
3. Compute `AVG()` on the fly + Redis cache — simpler writes, but every grid
   render aggregates/join and needs cache invalidation per review (more moving
   parts, drift risk).

## Decision outcome

**Chosen option: 1.** Reviews attach to the **brand**; only a logged-in user
with a `delivered` order containing that brand may post; one review per
`(user, order, brand)`; reviews are immutable and post-moderated (publish
immediately, admin hide/unhide/remove, user report with auto-hide at ≥3 distinct
reports). A reviews-owned `brand_rating_stats` table holds the denormalized
aggregate (count, sum, avg, 1–5 histogram), bumped transactionally under a row
lock on every status change; `catalog` reads it through `reviews.api.get_stats`
in a single batch call. A nightly scheduler job recomputes stats as a drift
safety net. The web brand page emits `schema.org/AggregateRating`.

`catalog.service` imports `reviews.service` **directly** (not `reviews.api`)
because the module's `api` pulls its `routes` → the whole `api/v1` router stack,
which would be a circular import at bootstrap.

### Positive consequences

- Cheap grid reads (one batched stats query); histogram for free.
- Verified-purchase gate satisfies Google's genuine-reviews policy and blocks
  the bulk of spam; report + auto-hide handles the tail.
- Clean module boundary; storefront enrichment is additive and SSG-safe (new
  DTO fields optional).

### Negative consequences

- Denormalized stats can drift if a bump is missed — mitigated by doing bumps
  inside the same transaction as the status change and the nightly reconcile.
- Post-moderation means an abusive review is briefly visible before a report or
  admin acts. Accepted: the verified-buyer gate already limits volume.
- Immutable reviews mean a buyer cannot fix a rating; acceptable for MVP (keeps
  the SEO snapshot and aggregate stable, no drift from late edits).

## Validation

Integration tests cover the eligibility matrix, stats transactionality, the
report threshold, admin transitions, and a query-count assertion proving the
grid enrichment is not N+1. Success = rich snippets appear for reviewed brands
and the aggregate stays consistent with the nightly reconcile finding no drift.
