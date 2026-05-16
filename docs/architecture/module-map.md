# YuPay — Module Map

Each module owns its tables and exposes a narrow Python interface via `apps/api/src/yupay/modules/<name>/api.py`. **No cross-module SQL joins.** Other modules call `api.py` or react to outbox events. This is the single rule that keeps future microservice extraction a refactor rather than a rewrite.

| Module | Responsibility | Tables (key) |
|---|---|---|
| `core` | Shared kernel: config, DB session, logging, errors, clock, id-gen, outbox runner, event bus | `outbox_messages`, `idempotency_keys`, `processed_events` |
| `auth` | Telegram OAuth (initData + Login Widget), guest sessions, JWT issuance (EdDSA) | `auth_sessions`, `telegram_links` |
| `users` | Profile, locale, KYC-lite flags | `users`, `user_profiles` |
| `catalog` | Products, categories, games, SKUs, denominations, multilingual content | `products`, `categories`, `skus`, `sku_prices`, `product_translations` |
| `inventory` | In-house code warehouse: bulk uploads, reservations, atomic issuance | `inventory_codes`, `inventory_reservations`, `inventory_uploads` |
| `integrations` | Supplier API adapters (one per vendor); pure I/O — no business rules | `suppliers`, `supplier_credentials`, `supplier_order_log` |
| `sourcing` | Decides where a SKU is fulfilled from (in-house vs supplier A vs supplier B + fallback) | `sku_sourcing_rules` |
| `orders` | Order aggregate, lifecycle FSM, idempotent creation, pricing snapshot | `orders`, `order_items`, `order_events` |
| `payments` | Gateway abstraction, intents, attempts, webhook verification & dispatch | `payments`, `payment_attempts`, `payment_webhooks` |
| `wallet` | Double-entry ledger; balance is a projection; cashback, refunds, payouts | `wallet_accounts`, `wallet_postings`, `wallet_transactions` |
| `promotions` | Promo codes, cashback rules, referral program | `promo_codes`, `promo_redemptions`, `cashback_rules`, `referrals` |
| `fulfillment` | Saga orchestrator (reserve → pay → fulfill → deliver, with compensations) | `fulfillment_tasks`, `fulfillment_attempts` |
| `delivery` | Final hand-off to user channels (in-app, email, telegram) | `deliveries` |
| `notifications` | Channel abstraction: email, telegram, WebSocket (via Redis pub/sub fan-out) | `notification_log` |
| `fx` | FX rate provider chain, Redis cache, fallback, snapshot for orders | `fx_rates`, `fx_snapshots` |
| `i18n` | Locale resolution, dictionaries, formatters | `translations` (or files) |
| `realtime` | WebSocket gateway + Redis pub/sub bridge | — |
| `admin` *(stub)* | Reserved namespace for later (SQLAdmin or custom Next.js admin) | — |

## Dependency direction

```mermaid
flowchart TB
    auth --> core
    users --> core
    catalog --> core
    inventory --> core
    integrations --> core
    sourcing --> catalog
    sourcing --> inventory
    sourcing --> integrations
    orders --> catalog
    orders --> users
    orders --> sourcing
    payments --> orders
    payments --> wallet
    wallet --> core
    promotions --> wallet
    promotions --> users
    fulfillment --> orders
    fulfillment --> payments
    fulfillment --> sourcing
    fulfillment --> inventory
    fulfillment --> integrations
    fulfillment --> delivery
    delivery --> notifications
    notifications --> realtime
    fx --> core
    i18n --> core
```

Cycles are prohibited. When a "downstream" module needs to influence an "upstream" one, it does
so by emitting an event consumed by the upstream module's handler — not by importing it.
