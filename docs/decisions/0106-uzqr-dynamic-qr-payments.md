# 0106. UzQR: pay by dynamic QR through the CBU's POS API, settled by polling

- **Status**: Accepted
- **Date**: 2026-11-23
- **Deciders**: @jamaomonov
- **Tags**: backend | payments | scheduler

## Context and problem statement

UzQR is the Central Bank's single QR: any Uzbek banking app scans it, and the money lands on
the merchant's account with no acquirer fee on our side. A competitor already takes deposits
this way. The merchant registers a **dynamic** QR in uzqr.uz and gets an API key; the
documented integration is the «UzQR API POS» v1.2 for cash registers: create an invoice per
payment (`invoice/create` → `invoice_id` + `qr_text`), poll its status, cancel it, send the
fiscal receipt link. There is no callback.

## Considered options

1. **Our server is the POS; the scheduler polls every open invoice** — chosen.
2. **A static QR and statement matching** through KapitalAPI (`GetDoc1C` on the QR account).
   Matching would be by amount, the statement lags, and the API needs a whitelisted IP or an
   SMS code — not something money can rest on.
3. **Poll from the customer's browser through our API.** Fewer calls while nobody looks, but a
   closed tab would leave a paid invoice unbooked, and AGENTS.md §10 keeps supplier/provider
   calls out of request handlers on the money path.

## Decision outcome

**Chosen option:** 1.

- **Intent.** `payments/gateways/uzqr.py` calls `invoice/create` inside `create_intent`, like
  every hosted-checkout gateway calls its acquirer there; the payer needs the QR in the
  response. `external_id` is a random 20-character token, not the order id — a retried order
  must get a new invoice, and UzQR replays an `external_id` until the invoice is final.
  `qr_text` and `invoice_id` live on `payments.metadata`; the order page draws the QR
  (`PaymentOut.uzqr`, shown only while the payment and order are pending and unexpired).
- **Settlement.** `modules/uzqr/poll.py`, every 5 s from the scheduler. Paid →
  `settle_provider_payment` (the Payme chokepoint). Rejected or 3001 → closed. Still pending
  past the order's window → `invoice/cancel` at UzQR first; 3002 means the payer won and the
  payment is booked.
- **Open is UzQR's word, not our status.** The expiry sweep cancels an order's pending
  payments while the invoice stays payable at UzQR for 24 h. The poll therefore watches
  `uzqr` payments that are `pending` **or** `cancelled` until `metadata.uzqr_closed` is set,
  which only UzQR's answer sets. A scan after the sweep is booked through the late-payment
  path instead of being lost.
- **No HTTP inside a transaction.** Each UzQR call is made with no session open; writes
  re-read the payment under its row lock.
- **Seeded `disabled`** (migration 0112): available once `UZQR_INN` and `UZQR_API_KEY` are
  set, on checkout only after the owner switches it on.
- **Refunds are manual.** UzQR has them switched off; `refund` refuses with the runbook.

### Consequences

- Good: no acquirer fee, any bank app pays, the integration is three HTTP calls.
- Bad: up to one status call per open invoice every 5 s. Fine at our volume; revisit past a
  few hundred open invoices (the batch is capped at 200, oldest first).
- Bad: a phone cannot scan its own screen. The card offers a PNG to save and open from the
  gallery in the bank app; Telegram's webview may not save it.
- **Debt: no fiscal receipt.** The spec expects a GNK receipt link after each payment
  (`receipt/send`, `receipt/missing`). We have no virtual till; UzQR accepts a paid invoice
  without one. The owner accepted this on 2026-11-23 to launch; a fiscal module is the
  follow-up.

## Links

- UzQR API POS v1.2 (owner's copy); KapitalAPI OpenAPI v3 (considered, option 2)
- ADR-0078 (Paynet), ADR-0097 (P2P on the storefront) — the shapes this follows
