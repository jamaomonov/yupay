# Getting the buyer back from the bank (web)

How the web storefront hands a buyer to an acquirer and — the part that was
missing until 2026-09-06 — how it gets them back to their order.

Applies to both web checkout paths, gifts (`GiftPurchasePanel`) and top-ups
(`PurchasePanel`). The Mini App has its own answer already: it opens the
acquirer with `openExternalLink` from inside Telegram and its order screen
fetches `GET /payments/by-order/{id}` for a «Оплатить» button.

## What went wrong

Pressing «Оплатить» used to assign the acquirer URL to `window.location.href`.
Every acquirer we use (Click, Payme, Uzum) hands back an ordinary `https://`
checkout URL, and on a phone the OS claims those URLs and opens the bank's own
app — so **no browser navigation happens**. The tab is still showing the game
page. None of the three return the customer to us on their own, so the buyer
finishes paying, switches back to the browser by hand, and lands on the product
they were about to buy, with nothing on screen saying an order exists.

The order page could not rescue them either: it never fetched the payment, so
there was no way back into paying. The order sat at `pending_payment` until
`ORDER_EXPIRY_SECONDS` (10 min) killed it.

Confirmed on production: a `steam-gift` order created 2026-09-05 22:27 with a
valid Uzum `intent_url`, `payment.status = cancelled`, `order.status =
expired` — created, never paid, dead on the expiry. A guest order.

On a desktop the same URL at least opens the acquirer's page, so the damage was
mobile-shaped; roughly all of our traffic is mobile.

## What happens now

The browser goes to the **order page first**, and the order page opens the
acquirer.

```mermaid
sequenceDiagram
    autonumber
    actor C as Buyer (phone)
    participant P as Checkout panel<br/>(gifts / top-ups)
    participant O as Order page
    participant API as FastAPI
    participant B as Bank app<br/>(Click / Payme / Uzum)

    C->>P: «Оплатить»
    P->>API: POST /orders  →  POST /payments/intents
    API-->>P: {intent_url}
    P->>P: render "Заказ создан" (fallback if the push never lands)
    P->>O: router.push(/orders/{id}?email=…&pay=1)
    Note over O: the tab is now the order page —<br/>whatever happens next, this is what the buyer returns to
    O->>API: GET /payments/by-order/{id}?email=…
    API-->>O: PaymentOut {status: pending, intent_url}
    O->>O: spend the one-shot, strip ?pay=1 from the URL
    O->>B: window.location.href = intent_url
    Note over C,B: the OS opens the bank app; the tab stays on the order page
    C->>B: pays
    C->>O: switches back to the browser by hand
    Note over O: ?pay=1 is gone and the one-shot is spent —<br/>nothing re-opens the bank app
    O->>API: GET /orders/{id} (poll / WS)
    API-->>O: paid → fulfilling → delivered
```

If the buyer comes back **without** paying, the order page is still
`pending_payment` and carries a «Оплатить» button pointing at the same
`intent_url` — as many times as they need, until the order expires.

## The three rules this obeys

1. **Only a payable payment gets a button.** `GET /payments/by-order/{id}`
   returns only `pending` / `requires_action` payments (404 otherwise), and
   `resumableIntentUrl` re-checks the same two states client-side plus a
   non-null `intent_url`. A succeeded, cancelled, failed or expired payment
   offers nothing.
2. **A wallet payment and the dev `mock` provider never touch this path.**
   `WalletGateway` charges the balance inside `create_intent` and answers with
   `intent_url: null`; `mock`'s URL resolves nowhere. Both go to the order page
   with no flag, exactly as before.
3. **A created order is never lost.** Both panels record the order and render
   the "Заказ создан" card _before_ navigating, and the navigation itself is
   wrapped so a failure leaves that card standing — with a link to the order
   page and one to the acquirer — instead of falling into a generic error.

## Why the flag can only fire once

`?pay=1` is a one-shot. Three independent guards, any one of which is enough,
because the failure they prevent is nasty: a buyer who finishes at the bank,
switches back, and is thrown straight into the bank app again, forever.

| Guard                                     | Covers                                                            |
| ----------------------------------------- | ----------------------------------------------------------------- |
| `useRef` latch in `OrderPayNow`           | re-renders, polls, WS pushes, React StrictMode's double effects   |
| `sessionStorage` mark per order id        | a reload, or a tab the browser evicted and restored               |
| `router.replace` stripping `pay` in place | the URL the buyer actually returns to, and anything they bookmark |

Only the `sessionStorage` mark survives a reload, and only the stripped URL
survives a new browser session, so all three are kept.

## Why not the alternatives

- **`window.open(intent_url)` from the order page** — a popup blocker eats it,
  because the open happens from an effect, not a click.
- **A hard `location.assign` to the order page instead of `router.push`** —
  same guarantee (the order page is what opens the acquirer either way), one
  extra full page load in the middle of a payment.
- **Keeping the redirect and adding a return URL** — we already send
  `return_url`; the acquirers do not use it to come back from their app. That
  is the fact this whole flow is built around.
- **Only stripping the URL, no `sessionStorage`** — the strip is a router
  transition and a phone can background the tab before it lands.

## Where it lives

| Piece                                | File                                                  |
| ------------------------------------ | ----------------------------------------------------- |
| flag, one-shot, payability, the open | `apps/web/src/lib/payment-return.ts`                  |
| button + auto-open on the order page | `apps/web/src/components/order/OrderPayNow.tsx`       |
| mounted into the order page          | `apps/web/src/components/order/OrderStatus.tsx`       |
| gift checkout                        | `apps/web/src/components/gifts/GiftPurchasePanel.tsx` |
| top-up checkout                      | `apps/web/src/components/store/PurchasePanel.tsx`     |

## Still open

The wallet deposit page (`/account/wallet/top-up`) still assigns the acquirer
URL to `window.location.href` and has the same mobile shape: the buyer comes
back to the top-up form with no sign a deposit is in flight. It is less costly
than a lost order — the deposit's own `return_url` is `/account/wallet?topup=1`
and the balance settles on its own — but it is the same bug and is not fixed
here.
