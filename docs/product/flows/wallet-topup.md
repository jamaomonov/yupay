# Wallet top-up (mini app)

Customer funds `user_wallet` in the same currency they pay with. No FX.
See [ADR-0058](../../decisions/0058-wallet-customer-topup.md).

```mermaid
sequenceDiagram
    autonumber
    actor C as Customer
    participant MA as Mini App
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

Limits: UZS 10 000–5 000 000 (whole so'm); USDT 5–500 (0.01). Paying from
the YuPay wallet is refused.
