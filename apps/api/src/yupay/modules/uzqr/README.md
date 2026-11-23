# uzqr

Pay by scanning a dynamic QR in any Uzbek bank app — the Central Bank's UzQR, driven
through its POS API v1.2 (ADR-0106).

- `client.py` — `invoice/create`, `invoice/status`, `invoice/cancel`, the `Auth` digest
  (`INN:sha1(timestamp + key):timestamp`). Transport failures and 5xx are
  `UzqrUnavailableError` ("ask again"); an error envelope is `UzqrError` with its code.
  The payer's phone and card are dropped on read.
- `poll.py` — one pass over open invoices, run by the scheduler's `uzqr_poll` every 5 s.
  Books paid invoices through `payments.service.settle_provider_payment`, cancels invoices
  whose order's window is over, and keeps watching payments the expiry sweep cancelled until
  UzQR confirms the invoice closed (`payments.metadata.uzqr_closed`).

The gateway itself is `payments/gateways/uzqr.py`; the QR reaches the storefront as
`PaymentOut.uzqr` (`payments/p2p_details.py`). Sequence: `docs/architecture/sequence-diagrams/uzqr-payment.mmd`.
Operations: `docs/runbooks/uzqr.md`. No fiscal receipts yet — see the ADR.
