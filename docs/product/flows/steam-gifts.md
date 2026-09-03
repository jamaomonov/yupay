# Steam Gifts — browse, buy, receive

Buy any of G-Engine's ~4 200 Steam games/DLC as a gift delivered straight
to the buyer's own Steam account: pick a game, paste a Steam profile/friend
link, pay in UZS, G-Engine's bot sends the gift. See
[ADR-0066](../../decisions/0066-steam-gifts-live-catalog.md) for the
backend design and
[the design spec](../../superpowers/specs/2026-09-02-steam-gifts-design.md)
for the full product brief.

> Customer-facing name (2026-09-03): **«Steam Игры»** — display only. The
> slug, routes, and `STEAM_GIFT_SKU_CODE` all stay `steam-gifts`.

```mermaid
%% See docs/architecture/sequence-diagrams/steam-gift-purchase.mmd for the
%% authoritative, always-in-sync copy of this diagram.
sequenceDiagram
    autonumber
    actor C as Buyer (web)
    participant Web as Web (Next.js)
    participant API as FastAPI (gifts / orders)
    participant Cache as Redis (gifts:*)
    participant GE as G-Engine (/gifts/*)
    participant DB as Postgres
    participant Sched as apps/scheduler (gengine_reconcile, 60s)

    rect rgb(240, 248, 255)
        note over C,GE: Phase 1 — Catalog browsing (no auth, 404s while STEAM_GIFTS_ENABLED=false)
        C->>Web: Open /store/steam-gifts
        Web->>API: GET /gifts/catalog/hot
        API->>Cache: gifts:hot
        alt cache hit
            Cache-->>API: cached items
        else miss
            API->>GE: GET /gifts/apps (pinned + discount scan, 5 pages)
            GE-->>API: items
            API->>Cache: SET gifts:hot (1h) + gifts:hot:stale (24h)
        end
        API-->>Web: our sell price = supplier price x (1+margin) x fx(USD->UZS)
        C->>Web: Search / open a game
        Web->>API: GET /gifts/catalog/{app_id}
        API->>Cache: gifts:detail:{app_id}
        API-->>Web: packages priced per offered zone (CIS/RU/KZ/UA)
        C->>Web: Pick edition (package) + region, paste Steam invite link
    end

    rect rgb(255, 255, 240)
        note over C,DB: Phase 2 — Checkout (steam-gift SKU, Stars-style dynamic pricing)
        C->>Web: Confirm purchase
        Web->>API: POST /orders {sku: steam-gift, fulfillment_data, amount_usd: quoted}
        API->>Cache: gifts:detail:{app_id} (re-fetch, never trusts the client)
        alt price drifted more than 2%
            API-->>Web: 422 {extra.expected_amount_usd}
            Web->>C: re-render at the fresh price
        else within tolerance
            API->>DB: INSERT orders + order_items
            API-->>Web: 201 {order_id, payment_url}
        end
        Web->>C: redirect to acquirer (Click/Payme/Uzum/USDT)
        C->>API: pays; webhook settles the order
    end

    rect rgb(240, 255, 240)
        note over API,GE: Phase 3 — Fulfilment (adopt-don't-rebuy, success at "shipped")
        API->>GE: POST /gifts/orders {invite_url, package_id, region}
        loop every 60s via gengine_reconcile
            Sched->>API: process_webhook_update for in_progress gengine tasks
            API->>GE: GET /gifts/orders/{id}
            alt status in {shipped, delivered}
                API->>DB: task succeeded, order delivered
            end
        end
    end

    rect rgb(255, 245, 245)
        note over C,Web: Phase 4 — the recipient still has to accept it in Steam
        C->>Web: Open /orders/{id}
        Web->>C: "Steam прислал вам подарок — примите его" card
    end
```

## The buyer's steps

1. **Browse.** Web: `/store/steam-gifts`. Telegram Mini App: `/gifts` — its
   own native catalog screen, not the generic top-up form (a deep link or
   stale bookmark to `/topup/steam-gifts` redirects straight there). Both
   surfaces show a hero + «Горячие предложения» carousel of
   pinned/discounted titles and a debounced search box hitting our proxy,
   which hits G-Engine's own server-side search.
2. **Open a game.** Web: `/store/steam-gifts/{appId}`. Mini App:
   `/gifts/:appId`. The game page shows the description, an edition
   («издание» / package) selector — a title routinely ships several
   packages, each its own price per region — a region selector (default
   **CIS**, with RU/KZ/UA offered directly and the rest behind "другой
   регион"), and a Steam invite-link field with a one-picture guide
   («Профиль → скопировать URL»). DLC (some titles carry 400+) renders
   collapsed by default, loaded lazily through the same proxy.
3. **Paste the Steam link.** Accepted shapes: a full profile URL
   (`steamcommunity.com/profiles/{steamid64}`), a vanity URL
   (`steamcommunity.com/id/{name}`), or an `s.team/p/{path}` short link.
   Anything else is rejected before checkout ever starts.
4. **Pay.** Web continues through the normal cart/payment flow. The Mini
   App checks out directly from the game screen via `performCheckout`
   (`POST /orders` + `POST /payments/intents`, currency forced to `UZS` —
   this SKU is variable-amount and the order endpoint rejects `USD` for
   that shape) — Click, Payme, Uzum, or USDT either way, same as any other
   order. The price shown is re-derived server-side at the moment of
   purchase (never the number the client last rendered); if a Steam sale
   moved the price more than 2% since the page loaded, checkout asks the
   buyer to confirm the new price instead of silently charging either the
   old or the new one — the Mini App keeps the buyer's edition/region
   selection across that re-confirm rather than resetting to the game's
   defaults.
5. **Wait.** The order page (web `/orders/{id}`, Mini App `/order/:id`)
   shows "в обработке" while G-Engine's bot sends the gift — expectations
   are set at checkout ("подарок отправляется ботом, обычно до часа"), not
   discovered in support chat. Delivery is minutes to hours, not instant.
6. **Accept in Steam.** Once G-Engine reports the gift `shipped` — this
   is _our_ delivered, and is what the order page shows — the buyer still
   has to open Steam (client, email, or notification) and click "Принять
   подарок" themselves. The order card (web's `OrderStatus` gift branch,
   Mini App's `OrderSuccess` gift branch) says so explicitly, including
   that the sender will be an unfamiliar bot account — Steam's own
   standard warning is expected, not a sign anything went wrong.

## What the buyer never sees

- The wholesale (supplier) price — only the marked-up sell price. The
  customer-facing order response redacts `fulfillment_data.supplier_price_usd`
  (see `orders/schemas.py`'s `_CUSTOMER_HIDDEN_FULFILLMENT_KEYS`); admins
  see it on the admin order view.
- G-Engine's internal order id, status history, or any adopt/retry
  mechanics — the buyer only ever sees the order's own status
  (`fulfilling` → `delivered`) and the delivery card.

## Edge cases the flow handles

- **Price moved between page-load and checkout** — 422 with the fresh
  price; the client re-quotes and the buyer confirms again. No purchase
  happens at a stale price in either direction.
- **G-Engine is briefly unreachable while browsing** — the catalog serves
  a last-known-good snapshot (up to 24h old) instead of an error page; a
  purchase attempt during a _true_ outage (no cache at all) fails cleanly
  with a retryable error rather than silently charging for nothing.
- **The gift is declined after "shipped"** — G-Engine reports `refunded`
  on an order that already counted as delivered on our side. This is not
  a fulfilment failure (the order already succeeded); it is handled by
  the ops refund path, not by the buyer-facing flow — see the runbook.
- **A network hiccup during purchase** — the fulfiller never buys the
  same gift twice; it looks for an order already placed for this exact
  line before ever creating a new one (see ADR-0066 and the runbook's
  "parked gift task" section).

## Surfaces

|            | Web                                | Telegram Mini App                      |
| ---------- | ---------------------------------- | -------------------------------------- |
| Catalog    | `/store/steam-gifts`               | `/gifts`                               |
| Game page  | `/store/steam-gifts/{appId}`       | `/gifts/:appId`                        |
| Checkout   | Normal cart/payment flow           | `performCheckout` from the game screen |
| Order card | `OrderStatus` gift delivery branch | `OrderSuccess` gift delivery branch    |

## Related

- [ADR-0066](../../decisions/0066-steam-gifts-live-catalog.md) — backend decision record
- `docs/runbooks/steam-gifts.md` — operating the feature: flag flip, parked
  tasks, post-shipped refunds, margin changes, launch checklist
- `docs/architecture/module-map.md` — the `gifts` module
- `docs/architecture/cache-keys.md` — every `gifts:*` Redis key
