# usdt

Resellers top up the USD deposit by sending an exact USDT amount on TRON (TRC20) to the
owner's address. A scheduler job reads confirmed transfers from TronGrid and credits the
reservation each one pays. 1 USDT = 1 USD.

Docs: ADR-0104, `docs/runbooks/usdt-deposit.md`,
`docs/architecture/sequence-diagrams/usdt-deposit.mmd`.

## Responsibilities

- **Reserve** (`reservations.py`): hold exactly the asked amount for 30 minutes. When it is
  held, answer `409 usdt_amount_taken` with a free `suggested` amount (plus random cents)
  and hold nothing. At most 10 reservations per merchant an hour. A closed amount
  (expired, cancelled **or paid**) stays
  held for another 60 minutes. Also cancel, read, list and sweep.
- **Read the chain** (`tron.py`): TronGrid `GET /v1/accounts/{address}/transactions/trc20`
  with `only_to`, `only_confirmed` and the USDT contract. Every row is checked again: the
  contract, the recipient, the type `Transfer` and 6 decimals.
- **Intake** (`intake.py`): journal one transfer event — `(tx_id, sender, amount)` — and credit the reservation it
  pays. Alerts are returned and sent by the caller after commit.
- **Poll** (`poll.py`): fetch from the cursor minus 10 minutes (exactly the cursor after a page-capped read or an address change), skip dust and known events, ingest each transfer in its
  own transaction, then advance the cursor. The scheduler job
  `apps/scheduler/.../jobs/usdt_poll.py` runs sweep + poll every 20 s.
- **Routes**:
  - `cabinet_routes.py` (`/merchant/cabinet/usdt/...`): `status`, `deposits` create, read,
    cancel and list.
  - `admin_routes.py` (`/api/v1/admin/usdt/...`): `settings`, `incoming` (the journal, plus
    `credit` and `dismiss` for unmatched rows) and `reservations`.

## Tables

| Table               | Purpose                                                                                    |
| ------------------- | ------------------------------------------------------------------------------------------ |
| `usdt_settings`     | Single row: `mode`, allowlist, `address`, min/max amount, poll cursor (`cursor_block_ms`). |
| `usdt_reservations` | One exact amount for one merchant: status, `holds_amount`, window, `incoming_id`.          |
| `usdt_incoming`     | The journal: every confirmed transfer to us, `result`, who it was credited to.             |

## Matching rule

A transfer pays a reservation when:

- the amount has no more than two decimals and equals `amount_usdt`;
- the reservation is not `paid`;
- the block time lies in `[created_at − 5 s, closed_at or expires_at]`, and the transfer's recipient is the reservation's address.

The window is checked whatever the status:

- a transfer sent in time but read after expiry still pays;
- a transfer sent and then cancelled still pays;
- a transfer sent after a cancel does not.

The amount stays held 60 minutes after a reservation closes, so two windows for one amount
never overlap and at most one reservation can match.

**Results:**

| `result`    | Meaning                                               |
| ----------- | ----------------------------------------------------- |
| `matched`   | Credited a reservation (key `usdt:{reservation.id}`). |
| `unmatched` | Nothing fits; alert `usdt_unmatched`.                 |
| `ignored`   | Under 1 USDT (dust, address poisoning); no alert.     |
| `manual`    | An admin credited it (key `usdt:incoming:{id}`).      |
| `dismissed` | An admin closed it without crediting, with a note.    |

A manual credit books the amount rounded down to cents.

## Settings

- `admits` requires an address. With no address nobody is admitted, whatever the mode.
- Setting a new address closes every pending reservation (they show the old one) and restarts the cursor at now, with no overlap, so that address's earlier history is
  never journaled.
- With `mode = off` the poller keeps reading while any reservation still holds an amount, then stops.

## Errors

| Case                       | Answer                                 |
| -------------------------- | -------------------------------------- |
| Not enabled for merchant   | 404 `usdt_disabled`                    |
| Reservation already open   | 409 `usdt_reservation_open` (`number`) |
| Same key, different amount | 409 `usdt_idempotency_mismatch`        |
| Amount outside min/max     | 422 `usdt_amount_out_of_bounds`        |
| More than two decimals     | 422 `usdt_amount_precision`            |
| Amount held by another     | 409 `usdt_amount_taken` (`suggested`)  |
| It and all nearby held     | 409 `usdt_amount_busy`                 |
| Over 10 reservations / h   | 429 `usdt_too_many`                    |
| Admin: bad address         | 422 `usdt_bad_address`                 |
| Admin: row resolved        | 409 `usdt_incoming_resolved`           |

## Alerts

| Kind                 | When                                                           |
| -------------------- | -------------------------------------------------------------- |
| `usdt_unmatched`     | A transfer of 1 USDT or more matched nothing.                  |
| `usdt_poll_down`     | No successful poll for 15 min while a reservation waits (1/h). |
| `usdt_ingest_failed` | A transfer failed to ingest; the cursor waits on it (1/h).     |
| `usdt_poll_flood`    | A read hit the page cap — spam flood (1/h).                    |
