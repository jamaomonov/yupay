# Flow: browsing CS2 skins

The read-only half of the CS2 skins section (ADR-0093). Buying is a later plan.

```mermaid
sequenceDiagram
    participant C as Customer (browser)
    participant W as web (/skins)
    participant A as api (/skins/*)
    participant P as Postgres + Redis
    participant X as Waxpeer

    C->>W: GET /skins?category=rifles&max=500000
    W->>A: GET /skins/catalog?category=rifles&max_uzs=500000&sort=popular
    A->>P: filter and sort on stored sell_price_usd / discount_percent
    P-->>A: 48 rows + next cursor
    A-->>W: items priced in soʻm
    W-->>C: grid (server-rendered, filters are links)

    C->>W: GET /skins/ak-47-redline-field-tested
    W->>A: GET /skins/{slug}
    A->>P: item + its wear family
    A-->>W: detail
    W-->>C: item page

    C->>A: GET /skins/{slug}/listings (from the browser)
    alt cache fresh
        A->>P: skins:listings:{slug}
    else budget left and breaker closed
        A->>X: search-by-name (4 s timeout)
        X-->>A: auto listings with float, seed, stickers, inspect
    else rate-limited or Waxpeer down
        A->>P: stale cache or the snapshot's cheapest listings
    end
    A-->>C: listings (float/inspect absent on the fallback)
```

Prices everywhere are our sell price from `pricing.quote()`, stored per row by
`repricing.reprice_rows` after every price sync and every pricing change, so a
filter bound, a sort and a card always agree.

## Mini app

`/cs2-market` (catalogue) and `/cs2-market/:slug` (item) in the Telegram mini app read the
same `/skins/*` endpoints from the browser; the query model is shared with web through
`@yupay/utils` (`parseSkinQuery`, `skinQueryString`).

- Filters live in the route's query string. A filter change **replaces** the history entry,
  so Telegram's back button from an item returns to the same filtered grid, and from the
  grid leaves the market instead of undoing filters one tap at a time. Wear tiles on the
  item page also replace, for the same reason.
- Wear, rarity, StatTrak and the soʻm price range sit in a bottom sheet applied together;
  sort is a native select beside it.
- While the API has skins switched off, `/skins/facets` 404s and the page shows the
  «Скоро» screen — the mini app has no flag of its own.
