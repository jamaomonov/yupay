# Glossary

| Term | Meaning |
|---|---|
| **SKU** | A specific sellable variant of a product (e.g. "Steam Wallet Code — 100 RUB"). |
| **Voucher** | A digital code redeemable on a third-party service. |
| **Top-up** | A direct credit to a player account/game ID via supplier API (no code returned). |
| **Supplier** | Upstream vendor we buy digital goods from. |
| **Aggregator** | A supplier that itself sells many vendors' products through one API. |
| **Gateway** | A payment processor (Stripe, YooKassa, Click, ...). |
| **Intent** | A payment intent — a started, not-yet-completed payment. |
| **Outbox** | A DB table used to publish domain events transactionally with the data that caused them. |
| **Saga** | A multi-step process with compensating actions on failure. |
| **Ledger** | The double-entry accounting record of every wallet operation. |
| **Posting** | A single debit or credit entry in the ledger. |
| **Reservation** | A temporary hold on inventory codes during checkout. |
| **Fulfillment** | The act of turning a paid order into a delivered code or top-up. |
| **Guest checkout** | Buying without an account, identified only by an email. |
| **Mini App** | A Telegram-hosted web app, opened from a bot or inline keyboard. |
| **initData** | The signed payload Telegram passes to a Mini App identifying the user. |
| **FX snapshot** | A frozen USD → target-currency rate stored alongside an order. |
| **Idempotency key** | A client-supplied or system-derived key that makes a write safe to retry. |
