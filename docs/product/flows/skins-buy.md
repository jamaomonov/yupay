# Flow: buying a CS2 skin

The customer picks one offer on the item page (web `/skins/{slug}`, mini app
`/cs2-market/{slug}`), pays, and receives a Steam trade offer from the seller within about a
minute.

```mermaid
%% see docs/architecture/sequence-diagrams/skins-purchase.mmd for the full diagram
sequenceDiagram
    participant C as Customer
    participant Y as YuPay
    participant X as Waxpeer
    participant S as Steam
    C->>Y: sign in, pick an offer, paste trade link, pay
    Y->>X: buy that listing for the trade link
    X->>S: seller sends the offer (~1 min)
    S-->>C: trade offer (accept within 30 min)
    alt accepted
        Y-->>C: «Получено» — protected by Steam for 7 days
    else declined / expired / sold out
        Y-->>C: «Деньги вернулись на баланс»
    end
```

Rules the customer meets:

- **Sign-in is required.** A failed purchase refunds to the YuPay balance, which a guest
  does not have. A card refund is a support request.
- **The trade link** is checked before paying (private inventory, trade ban, a hold because
  the account has no Steam Guard mobile authenticator for 7 days). If the customer signed in
  with Steam, the link must be that account's.
- **The offer they chose** is what is bought. If it sold in the meantime, a same-name offer
  no dearer is bought instead; if none, the money goes back to the balance.
- **Order page states**: `buying` → `offer_sent` (link to the offer, seller's name and avatar,
  accept-by time) → `accepted` (Steam protection until `release_date`) → `released`; or
  `failed` with `not_accepted` / `sold_out` (refunded to the balance) or `support` / `other`
  (we could not confirm the purchase — support, no refund promised).

## UI states

Item page, buy panel (shown only when the item API names `buy_sku_id`):

| State                       | What the customer sees                                                                 |
| --------------------------- | -------------------------------------------------------------------------------------- |
| Guest (web only)            | «Войдите, чтобы купить» opens the sign-in modal. The mini app is always signed in.     |
| Default                     | The cheapest offer is selected; a row's «Купить» selects another («Выбран»).           |
| Trade link empty / checking | Prefilled from the last skin order; checked as typed. The button says what is missing. |
| Link refused                | Private inventory, trade ban, Steam hold, not a trade link — the button stays off.     |
| Check unavailable           | Nothing is said and paying is allowed: the check is advisory.                          |
| Ready                       | «Оплатить {price}» with the balance tile and Payme / Click / Uzum.                     |
| Price moved                 | «Цена изменилась: теперь $X» — nothing is charged; the customer presses again.         |
| Offer sold                  | «Этот лот уже купили. Следующий — $X», the next offer selected; or «закончились».      |
| Link of another account     | «Эта ссылка от другого аккаунта Steam — укажите свою».                                 |

After paying, the customer lands on the order page. Its status hero never says "credited"
or "back to your card" for a skin: in flight it says the trade is coming, a refund says the
YuPay balance, a failure says support. The trade card below it follows the states above.

In the order list and on the order page a skin line is named and pictured as the skin
bought — the name snapshotted at checkout, the picture from the catalogue
(`skins/order_display.py`) — not as the generic `cs2-skin` SKU. Its checkout data (slug,
listing, trade link) is never listed; only the float is.
