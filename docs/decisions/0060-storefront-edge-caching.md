# 0060. Get the storefront back to static, and let the edge serve it

- **Status**: Accepted
- **Date**: 2026-08-26
- **Deciders**: @jamaomonov
- **Tags**: frontend | infra | performance

## Context and problem statement

A marketing agency is about to switch on paid advertising. Ad traffic lands on
`/store/<brand>` — and measurement showed every one of those clicks was being
rendered on the origin, by a single Next.js process, on a VPS shared with an
unrelated production stack.

Two independent things caused it, and neither announced itself.

**The store subtree was not prerendered at all.** Production served
`cache-control: private, no-cache, no-store` with no `x-nextjs-cache` header on
every brand page, while `/` and the legal pages cached normally. `next build`
gave no warning: it printed the routes as `● (SSG)` and listed all 54 paths.
But the Revalidate column was blank where the working routes showed `5m / 1y`,
the per-locale store directories under `.next/server/app` contained brand
folders with no `.html`/`.rsc`/`.meta` in them, and the prerender manifest had
zero store entries — reproduced byte-for-byte from the deployed image.

**Cloudflare cached no HTML whatsoever**, including the pages that _were_
properly ISR'd. `cf-cache-status: DYNAMIC` on `/`, which the origin serves with
a perfectly cacheable `s-maxage=300`.

## Investigation

Bisected by building the image in isolation (the host `.next` is bind-mounted
into a running dev container, so a host build would have broken dev):

| Change                                        | Store routes in the prerender manifest |
| --------------------------------------------- | -------------------------------------- |
| as deployed                                   | **0**                                  |
| remove the two `loading.tsx`                  | **108**                                |
| also move the `?cat=` read off `searchParams` | **111**                                |

So `loading.tsx` under `/store` was suppressing the whole subtree — brand
pages, how-to pages and the index alike — and `searchParams` additionally cost
the three index pages.

The skeletons were added to cover a slow first paint. One of their own
docstrings said so: _"Brand pages are ISR'd, so a cold segment can take a
moment to stream."_ They were covering the slowness they were causing.

Cloudflare's `DYNAMIC` had its own cause: extensionless HTML does not match the
default cache rules, so nothing was eligible in the first place. Adding a Cache
Rule moved the status to `BYPASS` rather than `HIT` — because next-intl's
middleware set `NEXT_LOCALE` on every response, and Cloudflare will not cache a
response carrying `Set-Cookie`. Nothing read that cookie: `localeDetection` was
already off and a grep across `apps/` and `packages/` found no consumer.

## Decision outcome

**Delete the `loading.tsx` files.** Once the pages are static there is nothing
to wait for — the skeleton was buying a worse version of the problem it hid.
Client-side navigation keeps the previous page on screen until the next one is
ready, which for a cached page is immediate.

**Move the category filter to the client** (`components/store/StoreFilter`) so
`/store` stops reading `searchParams`.

The first attempt at this used `useSearchParams()` inside a `<Suspense>`
boundary and was wrong in an instructive way: that hook _suspends during
prerender_, so the prerendered HTML contained the fallback — no chips, no
tiles, an empty catalogue for crawlers and for first paint, with the whole grid
shipped as serialized props instead. The shipped version reads
`location.search` in an effect, which keeps every tile in the server-rendered
DOM. The cost is one extra render on a direct hit to `?cat=x`.

**Set `localeCookie: false`** so no HTML response carries `Set-Cookie`.

**Pin the revalidate at the fetch, not the segment.** `export const revalidate
= 300` on the brand page did _not_ override the 60s on `getBrandReviews` — a
segment takes the lowest revalidate of everything it fetches. The reviews fetch
now uses 300, which is what actually moved the header.

**Cloudflare cache rules**, appended to the existing R2 media rule:

- storefront HTML (`/`, `/store*`, `/legal*`, and their `/en` and `/uz`
  prefixes) — cache eligible, edge TTL from the origin, **cache key excluding
  the query string entirely**;
- `/_next/image` — cache eligible, edge TTL from the origin, query string
  _kept_ in the key because `url`/`w`/`q` select the variant.

The query-string exclusion is the part that decides whether any of this works
for ads. Cloudflare's default cache key includes the query string, and paid
traffic arrives as `?utm_source=…&fbclid=…` — a unique key per click, so every
single ad visitor would have missed.

Also added: a rate-limiting rule on the four argon2 endpoints (`login`,
`register`, `password/reset`, `admin-dev`) at 20 requests / 10s per IP. The
Free plan permits exactly one such rule, a 10s window and a 10s timeout, so
those numbers are the plan's, not a judgement. `/refresh` and `/me` are
deliberately excluded — they fire during ordinary browsing.

### Positive consequences

- Prerendered routes went from 49 to 160; 111 of them are store pages at
  `revalidate=300`.
- Every storefront page now answers `s-maxage=300` with no `Set-Cookie`, which
  is what Cloudflare needs to serve them from the edge.
- The cacheable surface is 18 brands × 3 locales ≈ 54 URLs, so origin fetches
  settle at roughly one per second regardless of how much traffic arrives.

### Negative consequences

- No skeleton during client-side navigation into the store. Acceptable while
  the pages are cached; if it is missed, the boundary belongs _inside_ the page
  around a genuinely slow part, not at the segment.
- A newly published review appears within five minutes instead of one. There is
  no `revalidateTag("reviews")` anywhere yet — worth revisiting if on-demand
  invalidation lands.
- A direct hit on `/store?cat=x` paints everything for one frame before
  filtering.
- The Cloudflare rules live in a dashboard, not in this repo. They are recorded
  here and in `docs/runbooks/traffic-surge.md`; there is no drift check.

## Validation

- `apps/web/src/app/prerender-guard.test.ts` fails if a `loading.tsx` returns
  under `/store` — the regression is invisible in the build output, so it needs
  a test rather than a reviewer.
- `apps/web/src/i18n/routing.test.ts` pins `localeCookie: false`.
- Verified against a locally built production image: `/`, `/store`,
  `/store/<brand>` and `/store/<brand>/how-to` all return `s-maxage=300` with
  no `Set-Cookie`, and the brand grid and category chips are present in the
  markup with scripts stripped.
- After deploy, the check is `cf-cache-status` on a brand page: it should reach
  `HIT`. It currently reads `BYPASS`, which is the rule matching and the cookie
  still blocking — the old code is what is deployed.
