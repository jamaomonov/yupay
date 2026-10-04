# p2p

Resellers top up the USD deposit by transferring an exact soʻm amount to the owner's Humo
card. A Telegram Business bot reads the @HUMOcardbot notification and posts it to the API.

Docs: ADR-0094, `docs/runbooks/p2p-deposit.md`, `docs/product/flows/p2p-deposit.md`,
`docs/architecture/sequence-diagrams/p2p-deposit.mmd`.

## Responsibilities

- **Reserve** (`reservations.py`): hold an exact amount on a card for 5 minutes, bump +1…+99
  when taken, quarantine closed amounts (expired, cancelled **and paid**) for 10 minutes, cancel,
  expire, list. Which card, and how far the bump may go: `card_choice.py`.
- **Parse** (`parsing.py`): pure reading of a HUMO notification. Anything unrecognised is
  `unparsed` as a whole.
- **Intake** (`intake.py`): journal one update and credit the reservation it pays through
  `merchants.deposit.credit_deposit`. Alerts are returned and sent by the caller after commit.
- **Routes**: `cabinet_routes.py` (`/merchant/cabinet/p2p/...`); the admin
  (`/api/v1/admin/p2p/...`) is `admin_routes.py` (the router and settings), which includes
  `admin_cards.py` (cards) and `admin_journal.py` (incoming journal and reservations), with
  shared dependencies in `admin_deps.py`; and the webhook `api/webhooks/telegram_p2p.py`
  (`POST /api/v1/webhooks/telegram/p2p`).
- **Sweep**: `apps/scheduler/.../jobs/p2p_sweep.py`, every 30 s. Correctness does not depend on
  it: the webhook and the cabinet read treat an overdue `pending` as expired.

## Tables

| Table              | Purpose                                                                                     |
| ------------------ | ------------------------------------------------------------------------------------------- |
| `p2p_cards`        | Cards. Full number sealed (`pan_ciphertext`, `pan_nonce`), `pan_last4`, limits, `active`.   |
| `p2p_reservations` | One exact amount for one merchant: status, frozen rate, `amount_usd`, `holds_amount`.       |
| `p2p_incoming`     | The journal: every notification, `kind`, `result`, `balance_after`, `chain_ok`, `raw_text`. |
| `p2p_settings`     | Single row: `mode`, allowlist, HUMO bot id, owner's Telegram id, pinned connection id.      |

Check-constraint names in `models.py` are bare suffixes (`status`, `kind`, ...):
`core.db.NAMING_CONVENTION` adds the `ck_<table>_` prefix itself.

## The uniqueness rule

`uq_p2p_reservations_open_amount` is a partial unique index on `(card_id, amount_uzs)` where
`holds_amount`. `holds_amount` is true while a reservation is `pending` or in quarantine, so two
open reservations on one card can never share an amount. A **paid** reservation keeps holding its
amount for the same 10 minutes (`quarantine_until = received_at + 10 min`): if the payer
accidentally transfers it a second time, that transfer lands `unmatched` instead of paying the
next reseller who reserved the same sum. The sweep releases `expired`, `cancelled` and `paid`
rows once `quarantine_until` has passed. The database enforces it; two racing
inserts for 50 000 give one winner and a bump to 50 001 for the other.

Other partial indexes: one `pending` per merchant, and `(merchant_id, idempotency_key)`. A
same-key replay or a concurrent race returns the same reservation or a 409
`p2p_reservation_open`. A same-key replay asking for a **different** amount is a 409
`p2p_idempotency_mismatch`; "different" means the stored amount is not the requested one plus
0…99 (a bumped amount is the same intent). The tolerance is one-sided, because a bump only goes
up: asking for more than is stored is always a mismatch, while asking for up to 99 soʻm less
(19 950 against a stored 20 000) returns the stored row. Only these two indexes and the open-amount index are
translated; any other integrity error propagates as itself.

Reservation rules:

- The card's max and the daily room bound the amount. The +1…+99 bump is capped by the remaining
  headroom.
- **Daily room** = `daily_limit_uzs` minus what the card is committed to: today's (Tashkent day)
  `paid` total **plus** its currently `pending` (unexpired) holds.
- Counting pending holds is not enough on its own: two requests could both read the same room
  before either inserts. So a card **with** a daily limit is serialised: before its room is read,
  `reserve` takes `pg_advisory_xact_lock` on a stable 64-bit key derived from the card id
  (`card_choice.card_lock_key`), held until the request's transaction commits. A concurrent
  request for that card waits, then reads the room including the first hold. Every limited
  candidate card is locked up front in key order, so two requests can never deadlock. Cards
  **without** a limit take no lock; the open-amount index is all they need.
- **Card order**: eligible cards are tried most daily room first (no limit ranks first, ties keep
  the oldest card). If every bumped amount is held on one card, the next card is tried; only when
  all are exhausted is it 502 `p2p_amount_busy`.
- A stale pending is expired by a guarded `UPDATE ... WHERE status = 'pending'`, so a
  concurrently paid row is never overwritten.
- USD = soʻm / rate, rounded **down** to cents (`ROUND_DOWN`), rate frozen on the reservation.

## Errors

| Case                         | Answer                                             |
| ---------------------------- | -------------------------------------------------- |
| P2P not enabled for merchant | 404 `p2p_disabled`                                 |
| Reservation already open     | 409 `p2p_reservation_open`                         |
| No card takes this amount    | 409 `p2p_no_card`                                  |
| Same key, different amount   | 409 `p2p_idempotency_mismatch`                     |
| Every bumped amount held     | 502 `p2p_amount_busy` (`UpstreamUnavailableError`) |
| Rate unavailable             | 502 `fx_unavailable` (`UpstreamUnavailableError`)  |

No 503 class exists in `core.errors`; the upstream-unavailable class answers 502.

## Matching rule

A `credit` pays a reservation when all of these hold:

- the card is an **active** card with that last4, and exactly one such card exists. Two or more
  active cards with the same last4: no auto-match and a `p2p_ambiguous_card` alert;
- the amount has zero tiyin and equals `amount_uzs`;
- status is `pending`, or `expired` while still in quarantine (`holds_amount`). So an on-time
  transfer delivered late matches if it arrives before `expires_at` + 10 min; after the sweep
  releases the amount it lands `unmatched` and support resolves it (runbook §5);
- bank time `<= expires_at` and `> created_at - 1 minute`. When the bank time is missing,
  `received_at` stands in.

**Bank time has minute precision** (`HH:MM`), so a transfer up to 59 s after expiry can still
match. That leniency is accepted.

The reservation is locked `FOR UPDATE`, credited with key `p2p:{reservation.id}` and note
`P2P · {number}`. The journal's unique `(business_connection_id, telegram_message_id)` makes a
Telegram retry a no-op.

## Webhook

Authenticity first: `X-Telegram-Bot-Api-Secret-Token` is compared with `compare_digest`
against `p2p_webhook_secret` (env `P2P_WEBHOOK_SECRET`) before the body is read; an unset
secret refuses everything. Only `business_message` from the HUMO bot id, in the HUMO chat, not
forwarded, and arriving through the **pinned** Business connection is processed.

The pin: an admin enters the owner's own Telegram id (`owner_telegram_user_id`). A
`business_connection` update from that user with `is_enabled` stores its `id` in
`p2p_settings.business_connection_id`; a disabled update for the stored id clears it. Updates
from anyone else change nothing. With no connection stored (or no HUMO bot id) every message
is dropped. The update is logged as `p2p.business_connection` with `is_enabled`, the names of
granted rights and `owner` (bool) — never the user id.

Changing `owner_telegram_user_id` in the admin settings (to another id or to `null`) clears the
pinned connection and logs `p2p.connection_unpinned` (no ids): the old account's connection is
no longer trusted, and the new owner reconnects the bot. Re-saving the same id keeps the pin.

A HUMO message without an integer `message_id` is dropped and logged as `p2p.malformed_update`
(field name only). Only a violation of `uq_p2p_incoming_message` counts as a duplicate; any other
integrity error surfaces.

## Alerts

| Kind                 | When                                                                |
| -------------------- | ------------------------------------------------------------------- |
| `p2p_unparsed`       | A message from HUMO the parser could not read (message id only).    |
| `p2p_chain_break`    | Previous balance ± amount differs from this balance.                |
| `p2p_ambiguous_card` | Two or more active cards share the notification's last4.            |
| `p2p_silence`        | Reservations expiring and no HUMO notification for 6 h (scheduler). |

The chain check's predecessor is the same card's row with the greatest `telegram_message_id`
below this one on the same Business connection (message ids are the chat's own order). Same-minute
bank times no longer confuse it. Caveat: a message that arrives before its predecessor is compared
with the row before _that_ one, if there is one, so out-of-order delivery can still raise a false
`p2p_chain_break` when an earlier row exists; when none exists, the verdict is unknown (`null`).

The admin card list's receive health (`last_incoming_at`, `chain_ok_last`) is keyed by **last4**,
because that is all a notification names: two cards sharing a last4 show the same health. Only
`matched_today_uzs` is per card.

## Never logged

Card numbers, holder names, raw notification text, Telegram user ids, and the webhook secret.
Log lines carry the reservation number, amount and card last4 only. The full card number is
returned only to the merchant holding the open reservation, and is write-only in the admin.
