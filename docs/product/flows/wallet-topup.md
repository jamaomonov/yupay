# Wallet top-up and paying from the balance

Customer funds `user_wallet` in the same currency they pay with. No FX.
See [ADR-0058](../../decisions/0058-wallet-customer-topup.md).

```mermaid
sequenceDiagram
    autonumber
    actor C as Customer
    participant MA as Mini App / Web
    participant API as FastAPI
    participant P as Click / Payme / Uzum
    participant L as Ledger

    C->>MA: amount + method
    MA->>API: POST /wallet/topup {amount, provider}
    API->>API: reject wallet, clamp amount, currency from provider
    API->>API: insert orders(purpose=wallet_topup)
    API->>P: create_intent(order)
    API-->>MA: PaymentOut {intent_url, order_id}
    MA->>P: open hosted pay page
    MA->>API: GET /orders/{id} (poll)
    P->>API: prepare/complete (or Payme Perform)
    API->>API: payment succeeded, order paid
    API->>L: D user_wallet / C provider_clearing (kind=topup)
    API->>API: order delivered (no fulfilment)
    API-->>MA: status=delivered
    MA->>C: balance updated
```

Limits: UZS 10 000–5 000 000 (whole so'm); USDT 5–500 (0.01). Topping the
wallet up _from_ the wallet is refused.

## Surfaces

Both storefronts run the same endpoints; only the entry points differ.

|           | Mini App                     | Web                                                    |
| --------- | ---------------------------- | ------------------------------------------------------ |
| Balance   | wallet tab                   | chip in the header (desktop), account menu, mobile nav |
| Top-up    | `/wallet/top-up`             | `/account/wallet/top-up`                               |
| Acquirers | `click_miniapp`, Payme, Uzum | `click`, Payme, Uzum                                   |

Click bills through a per-surface merchant service, so the web must send
`click` and the mini app `click_miniapp`. `X-Yupay-Surface` (set by each
app's API client) is what records the order's `source`.

## Paying an order from the balance

`WalletGateway` is not an acquirer: it posts against our own ledger inside
`create_intent` and returns `status="succeeded"` with `intent_url: null`, so
there is no hosted page and no webhook. The storefront's existing
"no intent_url" branch already lands on the order, which is why paying from
the balance needed no second checkout path.

```mermaid
sequenceDiagram
    autonumber
    actor C as Customer
    participant W as Web / Mini App
    participant API as FastAPI
    participant L as Ledger

    C->>W: pick "Balance", Pay
    W->>API: POST /orders
    W->>API: POST /payments/intents {provider: "wallet"}
    API->>L: lock user_wallet, check balance
    alt covers the order
        API->>L: C user_wallet / D house_payments_received (kind=wallet_payment)
        API->>API: payment succeeded, order paid, fulfilment starts
        API-->>W: PaymentOut {intent_url: null, status: succeeded}
        W->>C: order page (already paid)
    else short
        API-->>W: 409 insufficient balance
    end
```

The whole order is charged or none of it: there is no split between the
balance and a card. The storefront therefore refuses the tile before
submitting — showing the shortfall — rather than letting the gateway answer
409 after the order row exists.
