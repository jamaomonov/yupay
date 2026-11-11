# usdt

Resellers top up the USD deposit by sending an exact USDT amount on TRON (TRC20) to the
owner's address. A scheduler job reads confirmed transfers from TronGrid and credits the
reservation each one pays. 1 USDT = 1 USD.

Docs: ADR-0104, `docs/runbooks/usdt-deposit.md`,
`docs/architecture/sequence-diagrams/usdt-deposit.mmd`.

## Responsibilities

- **Reserve** (`reservations.py`): hold an exact amount for 60 minutes, bumping
  +0.01…+0.99 when the amount is taken. A closed amount (expired, cancelled **or paid**) stays
  held for another 60 minutes. Also cancel, read, list and sweep.
- **Read the chain** (`tron.py`): TronGrid `GET /v1/accounts/{address}/transactions/trc20`
  with `only_to`, `only_confirmed` and the USDT contract. Every row is checked again: the
  contract, the recipient, the type `Transfer` and 6 decimals.
- **Intake** (`intake.py`): journal one transfer by `tx_id` and credit the reservation it
  pays. Alerts are returned and sent by the caller after commit.
- **Poll** (`poll.py`): fetch from the cursor minus 10 minutes, ingest each transfer in its
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
- the block time lies in `[created_at − 1 min, closed_at or expires_at]`.

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
- Setting a new address resets the cursor to now, so that address's earlier history is
  never journaled.
- The poller does nothing while `mode = off`.

## Errors

| Case                       | Answer                                              |
| -------------------------- | --------------------------------------------------- |
| Not enabled for merchant   | 404 `usdt_disabled`                                 |
| Reservation already open   | 409 `usdt_reservation_open` (`number`)              |
| Same key, different amount | 409 `usdt_idempotency_mismatch`                     |
| Amount outside min/max     | 422 `usdt_amount_out_of_bounds`                     |
| More than two decimals     | 422 `usdt_amount_precision`                         |
| Every bumped amount held   | 502 `usdt_amount_busy` (`UpstreamUnavailableError`) |
| Admin: bad address         | 422 `usdt_bad_address`                              |
| Admin: row resolved        | 409 `usdt_incoming_resolved`                        |

## Alerts

| Kind             | When                                                         |
| ---------------- | ------------------------------------------------------------ |
| `usdt_unmatched` | A transfer of 1 USDT or more matched nothing.                |
| `usdt_poll_down` | TronGrid failing for 15 min while a reservation waits (1/h). |
