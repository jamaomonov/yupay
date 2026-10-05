# Flow — paying a storefront order by card transfer (P2P)

ADR-0097. The buyer picks «Перевод на карту» at checkout, transfers the exact amount to the
owner's Humo card from a banking app, and the order pays itself when the @HUMOcardbot
notification reaches the API through the Telegram Business bot (ADR-0094).

```mermaid
sequenceDiagram
    autonumber
    participant B as Buyer
    participant W as Web (checkout / order page)
    participant A as API (payments + p2p)
    participant T as Telegram Business bot
    participant H as @HUMOcardbot

    B->>W: pick «Перевод на карту», press «Оплатить»
    W->>A: POST /orders, POST /payments/intents {provider: p2p}
    A->>A: reserve exact soʻm amount on a card until order.expires_at (bump if held)
    A-->>W: PaymentOut {intent_url: null, p2p: {pan, holder, amount_uzs, expires_at}}
    W->>B: order page: card, holder, exact amount, countdown
    B->>B: transfer the amount in the banking app
    H->>T: «Пополнение … UZS … HUMOCARD *3311»
    T->>A: POST /webhooks/telegram/p2p (secret, pinned connection)
    A->>A: match amount + card → reservation (purpose=order) → settle_provider_payment
    A->>A: order → paid → fulfilment
    W->>A: GET /orders/{id} (poll)
    A-->>W: status paid / delivered
```

What can go wrong and what the buyer sees:

- The exact total is held by another payer → the amount shown is bumped by a few soʻm; the
  page says «ровно».
- The window ends before the transfer → «Время на перевод вышло», the order expires; a
  transfer that still arrives pays it late (paid-after-expiry runbook).
- Provider in maintenance → the tile is greyed out; disabled → not shown.
- Bot not connected or no active card → «перевод на карту сейчас недоступен» at «Оплатить».
