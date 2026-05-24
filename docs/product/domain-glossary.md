# Product domain glossary

The product team's authoritative definitions. The engineering glossary in
`docs/onboarding/glossary.md` is a subset of this file.

## Customer-facing terms

| Term       | Definition                                                                                    | Notes                                                         |
| ---------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| Top-up     | Adding currency/credits to an external account (Steam wallet, PUBG UC, etc.) via supplier API | No code returned to the customer                              |
| Voucher    | A code the customer redeems on a third-party platform                                         | Single-use; we deliver the code text                          |
| Gift card  | A subtype of voucher with branding (e.g. "Steam Gift Card 25 USD")                            | Higher margin, more curated                                   |
| Wallet     | The customer's internal YuPay balance                                                         | One per currency per user                                     |
| Cashback   | Percentage of an order amount credited back to the wallet                                     | Configurable per SKU/category                                 |
| Promo code | A discount code applied at checkout                                                           | One per order                                                 |
| Referral   | A user who signed up via someone else's link                                                  | The referrer receives a bonus on the referee's first purchase |

## Order states

`pending_payment → paid → fulfilling → fulfilled → delivered`
On failure paths: `cancelled`, `refunded`, `partially_refunded`, `expired`.

## Money

- Internal canonical currency: **USD**.
- Display currencies on the storefront: RUB, USD, USDT, UZS.
- Conversion: snapshot at checkout into `fx_snapshots`; the order is then charged in the
  display currency at the locked rate.
- All amounts stored as `NUMERIC(20,6)` USD plus an explicit FX posting in the ledger.
