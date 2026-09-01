# Push the catalogue into Google Merchant Center over the Merchant API

- Status: accepted
- Date: 2026-09-01

## Context and Problem Statement

Brand pages carry per-SKU `Product` JSON-LD and an image sitemap, but rich
results sourced from crawling are discretionary and slow to update. The
competitors whose SKU images show a «price · в наличии» badge in Google
Images (Voodoo Market et al.) get it from a Merchant Center feed: free
listings state price and availability authoritatively and update within
minutes of a push, not on the crawler's schedule. A Merchant Center account
(5833475365) with a Merchant API data source («api v2», 10718106908,
Узбекистан, free listings + ads) already exists.

## Decision Drivers

- The price Google shows must be the price the customer pays — one pricing
  path, not a second one.
- A SKU the supplier delisted (catalog watchdog) must leave Google
  automatically.
- No new framework: plain JSON over OAuth fits the house httpx style.

## Considered Options

1. Merchant API push from a scheduler job (chosen).
2. A scheduled XML/TSV feed file fetched by Google — simpler auth, but
   updates on Google's fetch schedule (daily-ish) and delivers none of the
   push-on-change behaviour the watchdog and price refresh already have.
3. Content API for Shopping — predecessor of the Merchant API, sunset path;
   new integrations are told to use the Merchant API.

## Decision Outcome

`integrations/merchant_feed.py` maps every active fixed-price SKU to one
Merchant API product (`offerId = sku_code`, `contentLanguage=ru`,
`feedLabel=UZ`): title «Бренд — номинал», the SKU/product/hero image, the
brand-page URL, `availability` from the live `in_stock`, and the price
resolved by the storefront's own `_resolve_fixed_price` (per-currency
override, then FX) in UZS micros. Variable-amount and quantity-priced SKUs
are excluded — a rate is not a price. `identifierExists=false` because
digital goods carry no GTIN.

The scheduler job `integrations.merchant_feed` runs hourly right after the
price refresh and the catalog watchdog: it upserts every desired item
(insert-by-offerId replaces within the data source), then lists the
account's products and deletes what we no longer sell — self-healing, so a
SKU deactivated while the feed was down is removed on the first healthy
tick. Per-item failures are counted and logged, never raised.

Auth is a Google service account (JSON key mounted as a secret file, path in
`MERCHANT_CENTER_KEY_FILE`) with the `content` scope, refreshed via the new
dependency **google-auth** — the standard, self-contained implementation of
Google's service-account JWT flow; hand-rolling RS256 assertions to avoid
one dependency is how signature bugs happen. The blocking refresh runs in a
thread. The job no-ops (logged) until `MERCHANT_CENTER_ACCOUNT_ID`,
`MERCHANT_CENTER_DATA_SOURCE_ID` and `MERCHANT_CENTER_KEY_FILE` are set.

### Consequences

- Good: price/stock changes reach Google within an hour; deactivations too.
- Good: one pricing path — the feed calls the same resolver the catalog API
  serves the storefront from.
- Bad: Google's digital-goods moderation may refuse individual items; the
  per-item error counting and MC's «Диагностика» page make that visible
  rather than fatal (see the runbook).
- Neutral: +google-auth (+cachetools, pyasn1, rsa transitively) in the api
  package.
