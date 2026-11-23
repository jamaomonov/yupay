# UzQR (dynamic QR payments) — runbook

ADR-0106. Payer scans a QR in any bank app; the scheduler's `uzqr_poll` books the payment.

## Go-live

1. uzqr.uz → «Управление QR»: a **dynamic** QR exists and is active. «Управление API»: an
   active key bound to that QR.
2. `secrets/api.env` (api **and** scheduler read it): `UZQR_INN` = INN, or PINFL for a sole
   trader; `UZQR_API_KEY` = the key. Restart api + scheduler with `IMAGE_TAG`.
3. Admin → Платёжные провайдеры → UzQR → active.
4. Pay a 1 000 soʻm wallet top-up by QR from a real bank app; the order goes paid within
   ~10 s. Check `uzqr.poll.done` in the scheduler log.

## Something is wrong

- **Alert `uzqr_poll_down`** — no tick in which UzQR answered every call for 10 min while
  invoices are open. Scheduler logs: `uzqr.poll.refused` (UzQR answered with an error code —
  1001 is a wrong INN/key), `uzqr_poll.failed` (our side). Payments are not lost while this
  lasts: open invoices are re-read when UzQR answers again, for up to 25 h.
- **Payer paid, order not paid.** Find the payment (`provider='uzqr'`), read
  `metadata.invoice_id`, compare with uzqr.uz «История операций». If UzQR shows it paid and
  `metadata.uzqr_closed` is not set, the poll will book it on the next good tick. If the
  payment is older than 25 h it is out of the poll's window: settle it by hand in the admin.
- **Paid after the order expired.** Booked through the late-payment path: a catalogue order is
  held for review (`paid_after_expiry` alert), a wallet top-up is credited.

## Refunds

UzQR refunds are switched off on their side. Transfer the amount back from the bank and
record the refund in the admin (the gateway refuses an automatic one).

## Fiscal receipts

Not sent (ADR-0106 debt). UzQR lists our paid invoices without a receipt under
`receipt/missing`; nothing on our side reads it yet.
