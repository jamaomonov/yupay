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

## Amendment: guest reviews (2026-07-29)

### Context

Reviews launched user-only. Guest checkout (web) is a large share of first-time
orders, and those buyers never create an account — the original "logged-in
user" gate silently excluded them from the social-proof loop that the ADR set
out to build.

### Decision

Extend `POST /reviews` and the new `GET /reviews/eligibility` to accept a
**guest actor**, resolved by `auth.deps.resolve_request_actor`: `Authorization:
Bearer <access-jwt>` → user, or `Authorization: Guest <guest-jwt>` +
`X-Guest-Email` → guest (the guest JWT's `email_hash` claim is cross-checked
against the header, mirroring the order-view capability check). This is
**deliberately the same capability model as guest order-view** — order UUID
(effectively unguessable) + the email the buyer used at checkout — not a new
emailed magic-link/review token. No new secret, no new email to send, no new
abuse surface beyond what order-view already accepts.

Schema (`reviews` table): `user_id` becomes nullable; a new `guest_email
CITEXT` column holds the buyer's email for guest-authored reviews; a
`CHECK ((user_id IS NULL) <> (guest_email IS NULL))` enforces exactly one
identity per row. The uniqueness constraint moves from `(user_id, order_id,
brand_id)` to **`(order_id, brand_id)`** — one review per order per brand
regardless of whether the buyer was logged in, since an order has exactly one
buyer identity (user XOR guest) and a repeat submit under either identity is
the same abuse case the original constraint guarded against.

`reviews.service.create_review` takes `user_id: str | None` and `guest_email:
str | None` (exactly one set) instead of a bare `user_id`; ownership,
`delivered`, and brand-membership checks branch on which one is present but
are otherwise unchanged. `GET /reviews/eligibility?order_id=` runs the same
actor resolution and returns `{brand_slug, delivered, already_reviewed}` so
the web can gate the CTA/form without a failed POST.

Guest-authored reviews render with the same anonymous label as a user review
that opted out of a display name (`author_name: null` in `ReviewOut` —
`list_published` LEFT JOINs `users` on `Review.user_id`, which is simply
`NULL` for a guest row, so no branching is needed there). Reporting
(`POST /reviews/{id}/report`) stays **user-only**; a guest cannot report a
review, matching the existing "no guest write access beyond their own order"
posture elsewhere in the API.

### Privacy

`guest_email` is a capability credential, not a public identity: it is never
serialized in any response DTO (`ReviewOut`, `AdminReviewOut`, etc. expose
`author_name` / `user_id`, never `guest_email`) and never appears in a log
line (`review.created` logs `brand_id` + `rating` only, same as the
user-authored path).

### Scope

Web only. The Telegram Mini App has no guest checkout — every Mini App order
is tied to the Telegram user — so there is no guest-review surface to add
there.

### Consequences

- Positive: closes the largest gap in review coverage (guest checkout orders)
  without inventing a new auth primitive or a new "please verify your email"
  flow.
- Negative: the uniqueness relaxation from `(user, order, brand)` to `(order,
brand)` means a user who checks out as a guest and later claims that order
  (order-linking is out of scope for this change) cannot review the same
  order twice under two identities — accepted, since a single order has one
  buyer identity by construction and this only forecloses a scenario that was
  never possible anyway.

## Amendment: the review is asked for in place (2026-08-21)

### Context

The logged-in web ask was a "rate your purchase" CTA in the delivered modal
linking to `/store/{brand}?order={id}#reviews`. In practice that traded a
one-tap ask for a page load onto the brand's marketing page — and usually at
the top of it, because `WriteReviewPanel` is client-only and auth-gated, so the
browser resolves `#reviews` before the form exists. The buyer arrived where
they did not ask to be and had to find the form. The Mini App never had this
problem: its delivered dialog opens `ReviewsSheet` in place.

### Decision

`OrderDeliveredModal` collects the review itself: it renders the shared
`ReviewForm` (new `variant="bare"`, which drops the card frame that would
otherwise nest a panel inside the dialog panel) and submits through
`submitReview`, with the same `idle | sending | done | already | error`
orchestration `GuestReviewPanel` and `WriteReviewPanel` use. Success
invalidates `["my-reviews"]` so the remaining CTAs stop offering to rate a
rated order, and the submit state resets on `orderId` change — the modal is
mounted once per session, so a second delivery must open on a form, not on
"спасибо за отзыв". The now-unused `web.orderResult.rateCta` key is dropped
from all three locales.

The brand-page form stays for the two entry points that are deliberately
navigations (the order page and the account order list, where the buyer chose
to act on a past order). For those, `WriteReviewPanel` scrolls `#reviews` into
view itself when `?order=` is present rather than trusting the hash.

### Consequences

- Positive: the ask costs one tap and no page load; web and Mini App now
  collect the review the same way.
- Negative: the modal no longer doubles as a route to the brand page, so a
  buyer who wanted to read other reviews navigates there themselves —
  accepted, that was never what the CTA promised.

## Amendment: one-tap rating, 15-minute body amend, next-session catch-up (2026-09-11)

### Context

Buyers tap a star while the delivery dialog is still on screen, then leave
to check the game. They rarely come back the same session, so a form that
asks for a comment _before_ POST loses the rating. A delayed Telegram/email
nudge would be a new notification job and a second ping on top of "order
delivered". Catch-up on the _next Mini App (or logged-in web) open_ is the
same ask, at the moment they actually return.

### Decision

1. **Tap a star = `POST /reviews` immediately** (rating only). Optional chips
   and a textarea follow; they are not required to persist the score.
2. **`PATCH /reviews/{id}`** accepts `{body}` only, from the same actor as
   POST (Bearer or Guest), for **15 minutes** after `created_at`. Rating
   stays frozen (aggregates and the SEO snapshot do not move). After the
   window: `403` with `code=amend_window_closed`. Idempotency-Key required.
   The client owns one draft: chips toggle their label in the textarea
   (joined with `. `); free text is the same field. **PATCH runs only from
   an explicit Submit** — not on chip tap or blur — so a catch-up dialog
   that refetches `pending-ask` (now null) cannot unmount the form before
   the comment is sent. Custom text and chips never live in two parallel
   states that later get concatenated.
3. **`GET /reviews/pending-ask`** (Bearer only) returns the newest delivered
   catalog order that has no review, with `delivered_at` between **2 hours
   and 14 days** ago, or `null`. Merchant and `wallet_topup` orders are
   excluded. Clients show this on calm screens (web: logged-in layout minus
   checkout/that order page; Mini App: `/` and `/history`) and never over
   the live delivery dialog. Dismiss is local (`localStorage`), not a server
   send log — no new table.
4. **No delayed Telegram/email job.** The existing "Заказ выдан" Telegram
   message gains one `web_app` button, URL `{telegram_miniapp_url}/?review={order_id}`.
   The Mini App reads `?review=` (or `start_param` `review_<uuid>`) and
   opens `/order/{id}`.

### Consequences

- Positive: the rating survives the "I went to check UC" gap; the next-open
  prompt is the natural time to ask "how did it go?"; no extra outbound
  ping and no migration.
- Negative: a 2-hour floor misses a same-evening return under two hours
  (the live dialog already asked); a local dismiss means another device
  may ask again — accepted, that is one extra prompt, not a second review
  row (`UNIQUE (order_id, brand_id)`).
- The original "immutable" rule now means **rating is immutable**; body may
  change once, briefly.
