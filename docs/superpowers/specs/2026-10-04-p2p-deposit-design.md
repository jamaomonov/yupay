# P2P deposit top-up for resellers — design

Status: design approved by the owner section by section (2026-10-04); this written
spec awaits the owner's review before `writing-plans`.

Sub-project 1 of 2. Sub-project 2 — P2P as a payment method on the storefront and the
mini app — gets its own spec later. It reuses the cards, reservations, incoming-transfer
journal and webhook defined here, and adds only the order purpose.

## 1. Problem

A reseller can only top up their USD deposit through support: they write to
`@yupay_support`, transfer money, and an admin credits the deposit by hand
(`POST /admin/merchants/{id}/deposit-credits`). That was a deliberate choice
(ADR-0080, `docs/runbooks/merchant-b2b.md` §"not self-serve"; owner rule "no top-up
mentions"). The owner now wants self-serve top-up: the reseller transfers soʻm to the
owner's Humo card, and the deposit is credited automatically within seconds.

## 2. Mechanism (owner's design)

1. The reseller enters an amount in soʻm (e.g. 50 000).
2. We **reserve that exact amount** on a card for **5 minutes**. If another live or
   quarantined reservation on the same card already holds 50 000, we give 50 001, then
   50 002, and so on. No two open reservations on one card share an amount.
3. We show the card number, the cardholder's full name and the exact amount. A
   prominent warning says the transfer must be exactly this amount, not one soʻm more
   or less.
4. The Humo card's official bot **@HUMOcardbot** notifies the owner's Telegram account
   of every credit to the card.
5. A bot connected to the owner's profile through **Telegram Business (chat
   automation)** receives that notification. We match the amount to the reservation
   and credit the deposit.
6. If nothing matches, the reseller contacts support with the receipt, and an admin
   credits by hand with the existing button.

## 3. Spike result (2026-10-04)

A throwaway long-poll listener on the bot `@depositlistenerbot` proved the channel
works.

- **It works with three settings:**
  1. In Telegram → Settings → Telegram Business → Chatbots, the bot has access to
     **"Only selected chats: HUMO Card"**. It cannot see any other chat of the owner.
  2. In the bot's permissions, the **Messages** group is on. With only "gifts and
     stars", no messages are delivered.
  3. In @BotFather, **Bot to Bot Communication Mode** is on. Without it, messages from
     another bot (HUMO is a bot) are not delivered via business accounts.
- **Delivery:** `business_message` updates arrive within seconds; `from.is_bot = true`.
- **Amounts arrive exact:** transfers of 1 003 and 1 004 soʻm from another card arrived
  as `1.003,00 UZS` and `1.004,00 UZS`, both labelled `UB P2P Uzcard2Humo>T`. An earlier
  credit of `54.728,28 UZS` from `TBC P2P S UZCARD NA` shows that amounts with tiyin
  exist. Those only fail to match and land as unmatched, which is the intended
  behaviour.
- **Notification text** (credit):

  ```
  🎉 Пополнение
  ➕ 1.004,00 UZS
  📍 UB P2P Uzcard2Humo>T
  💳 HUMOCARD *3311
  🕓 04:47 04.10.2026
  💰 1.272.764,21 UZS
  ```

  Debits use the same shape with a minus sign. Format details:
  - thousands separator `.`, decimal separator `,`, currency `UZS`;
  - the card is masked `*NNNN`;
  - time is `HH:MM DD.MM.YYYY` (Tashkent);
  - the last line is the **balance after** the operation.

- **No history.** The Bot API has no method to read past messages. Telegram keeps
  undelivered updates for up to 24 hours. A gap longer than that is lost, so it must be
  detected (§5.5).
- The spike token was exposed in chat and **must be revoked** (`/revoke` in
  @BotFather) before production. The production token lives only in sops.

## 4. Decisions (owner, 2026-10-04)

| #   | Decision                                                                                                                                                                                                                                   |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| D1  | Reservation lifetime is **strictly 5 minutes**. A transfer arriving later is never credited automatically.                                                                                                                                 |
| D2  | After a reservation expires, is cancelled or is paid, its amount stays in **quarantine for 10 minutes** on that card. It is not handed out again, so a late or repeated transfer cannot land on someone else's reservation.                |
| D3  | The reseller can **cancel** a pending reservation. Cancellation also starts the 10-minute quarantine.                                                                                                                                      |
| D4  | USD↔UZS uses **our rate at reservation time** — the same rate the storefront charges with (`pricing.fx_guard.guarded_usd_rate`; the admin `/fx` override wins). It is frozen on the reservation as an `fx_snapshots` row.                  |
| D5  | **Cards live in a table**: one card (\*3311) at launch, more can be added in the admin without a schema change. Amount uniqueness is per card.                                                                                             |
| D6  | Per-card min / max reservation amount (defaults **10 000** / **10 000 000** soʻm) and an optional daily limit (off by default) are **editable in the admin**.                                                                              |
| D7  | **One active reservation per reseller** at a time.                                                                                                                                                                                         |
| D8  | **Incoming-transfer journal** in the admin, read-only: every notification and what it was credited to. **No "not ours" button.** Owner's personal transfers and (later) storefront payments appear as unmatched or matched to their order. |
| D9  | An unmatched transfer is credited by the **existing** admin deposit-credit button, with a note citing the transfer. No new admin action.                                                                                                   |
| D10 | Notifications reach us by **Telegram webhook into the api**. There is no long-poll process and no separate service.                                                                                                                        |

## 5. Architecture

### 5.1 Module

New module `apps/api/src/yupay/modules/p2p/` with:

- `models.py`, `service.py` (reserve / cancel / expire / match);
- `parsing.py` (HUMO notification parser, pure);
- `webhook.py` (Telegram update intake);
- `cabinet_routes.py`, `admin_routes.py`, `schemas.py`, `README.md`.

The webhook route mounts at `apps/api/src/yupay/api/webhooks/telegram_p2p.py`. Crediting
goes through `merchants.deposit.credit_deposit`. Nothing in `merchants` changes beyond
the cabinet's top-up entry points.

### 5.2 Tables (one migration)

**`p2p_cards`**

- `id`, `label`;
- `pan_encrypted` — full card number, encrypted with the same primitive as the
  inventory code warehouse (`core.crypto`);
- `pan_last4` — matches the `*NNNN` in notifications;
- `holder_name`, `network` (`humo` | `uzcard`), `active`;
- `min_amount_uzs` (default 10 000), `max_amount_uzs` (default 10 000 000),
  `daily_limit_uzs` (nullable = off);
- `created_at`, `updated_at`, `updated_by`.

**`p2p_reservations`**

- `id`, `number` — `T` + 7 Crockford base32 characters, unique;
- `card_id`, `amount_uzs` — whole soʻm, the exact amount to transfer;
- `purpose` (`merchant_deposit`; later `order`), `merchant_id` (nullable for a later
  purpose);
- `fx_snapshot_id`, `amount_usd` — the deposit credit, 2 dp, at the frozen rate;
- `status` (`pending` | `paid` | `expired` | `cancelled`);
- `created_at`, `expires_at` (= created + 5 min), `closed_at`;
- `quarantine_until` — set on expiry, cancel or payment: closed + 10 min;
- `incoming_id` — the transfer that paid it;
- `idempotency_key` — the reseller's key, scoped by merchant.
- **Amount uniqueness is enforced by the database**, not by a read-then-write: a column
  `holds_amount` (bool) is true while `pending` or in quarantine. A partial unique
  index on `(card_id, amount_uzs) WHERE holds_amount` makes a racing reservation fail
  on insert. The service retries with the next amount, up to +99; past that it answers 502 `p2p_amount_busy`. A periodic job clears `holds_amount` once quarantine ends.

**`p2p_incoming`** (the journal)

- `id`, `telegram_message_id`, `business_connection_id`;
- `kind` (`credit` | `debit` | `unparsed`);
- `amount_uzs` — numeric with tiyin;
- `source_text` — e.g. `UB P2P Uzcard2Humo>T`;
- `card_last4`, `bank_time`, `balance_after`;
- `raw_text`;
- `result` (`matched` | `unmatched` | `ignored`), `reservation_id`;
- `received_at`.
- Unique key: `(business_connection_id, telegram_message_id)`.

**`p2p_settings`** (single row, the `steam_gift_settings` template)

- `mode` (`off` | `allowlist` | `all`), `allowlist_merchant_ids`;
- `humo_bot_user_id` — the numeric Telegram id of @HUMOcardbot, captured at setup;
- `updated_by`, `updated_at`.

The bot token and webhook secret are **not** stored here. They live in the environment
(sops).

### 5.3 Reservation (cabinet)

`POST /merchant/cabinet/p2p/deposits {amount_uzs}`, cabinet session plus
`Idempotency-Key`:

1. **Gate:** `p2p_settings.mode` admits this merchant, else 404.
2. **One active:** the merchant has no `pending` reservation, else 409
   `p2p_reservation_open`, with the open one's number.
3. **Card:** choose an active card where `min ≤ amount ≤ max` and today's matched total
   plus the amount stays within the daily limit. Several cards: the one with the most
   remaining daily room. None: 409 `p2p_no_card` ("try a different amount / later").
4. **Rate:** `guarded_usd_rate`, snapshot it, `amount_usd = amount_uzs / rate`, rounded **down** to cents (`ROUND_DOWN`). Rate unavailable: 502 (`UpstreamUnavailableError`; no 503 class exists), the same behaviour as checkout.
5. **Exact amount:** insert with the amount; on unique violation try +1 … +99.
6. **Response:** number, exact amount, full card number, holder name, `expires_at`,
   `amount_usd`, rate.

Other routes:

- `GET /merchant/cabinet/p2p/deposits/{number}` — status, polled every 3 s.
- `POST /merchant/cabinet/p2p/deposits/{number}/cancel` — `Idempotency-Key`; only from
  `pending`. Sets `cancelled`, `quarantine_until`.
- `GET /merchant/cabinet/p2p/deposits` — history, keyset-paged.

**Expiry:** a scheduler job every 30 s:

- `pending` past `expires_at` → `expired` (and sets `quarantine_until`);
- clears `holds_amount` on `expired`, `cancelled` and `paid` rows where `quarantine_until <= now`.

The webhook also treats a `pending` reservation past `expires_at` as expired (D1), so
correctness never depends on the job running on time.

### 5.4 Webhook intake

`POST /webhooks/telegram/p2p`:

1. **Authenticity first:** compare `X-Telegram-Bot-Api-Secret-Token` with
   `compare_digest` against the configured secret **before** reading or parsing the
   body. A mismatch answers 401 and logs nothing from the body.
2. **Filter.** Accept only `business_message` where:
   - `from.id == p2p_settings.humo_bot_user_id`;
   - it is not forwarded (no `forward_origin`);
   - the chat is that bot.

   Everything else — `edited_business_message`, other chats, connection updates — is
   answered 200 and dropped. A `business_connection` update is logged as a
   connection-health event only.

3. **Parse** (`parsing.py`, pure):
   - `Пополнение` → `credit`, with amount, source, last4, time, balance;
   - a minus line → `debit`;
   - anything else → `unparsed`, with `raw_text` kept.
4. **One transaction:**
   1. insert `p2p_incoming` in a savepoint; a unique violation means a duplicate, so
      answer 200 and stop;
   2. for a `credit` whose `card_last4` matches an active card, whose amount has zero
      tiyin, and which has a `pending` reservation with that exact amount and
      `expires_at >= bank_time` (falling back to `received_at` if the bank time is
      missing): lock the reservation `FOR UPDATE`, then
      `credit_deposit(merchant_id, amount_usd, actor="p2p", idempotency_key=f"p2p:{reservation.id}", note=f"P2P · {number}")`,
      set the reservation to `paid` with `incoming_id` (its amount stays held until
      `quarantine_until = received_at + 10 min`, D2), and mark the journal row
      `matched`;
   3. otherwise mark the row `unmatched` (`credit`) or `ignored` (`debit` / `unparsed`).
5. Answer 200. Telegram retries anything else.

The reseller's existing outbound webhook `balance.credited` fires from `credit_deposit`,
as for a manual credit.

### 5.5 Detecting gaps and format changes

- **Balance chain:** for each card, the previous journal row's `balance_after` ± this
  amount must equal this row's `balance_after` (credit +, debit −). A break raises an
  ops alert "P2P: notification missed on \*3311", once per break.
- `unparsed` raises an ops alert carrying the message id, never the raw text.
- **Silence:** no notification from HUMO for N hours while a `pending` reservation
  exists raises an ops alert. N is set at plan time.

## 6. Cabinet UI (`apps/merchant`)

- **Top-up entry:** "+" in the TopBar and the dashboard's empty-balance card open
  `/cabinet/top-up` instead of the support link, when P2P is enabled for this merchant.
  Otherwise the old support link stays.
- **Step 1, amount:** soʻm input with min/max, a live "≈ $X at rate R" line, and
  "Continue".
- **Step 2, details:**
  - the exact amount, large, with a copy button;
  - the full card number with a copy button;
  - the holder's name;
  - a 5:00 countdown;
  - a warning: "Transfer exactly 50 001 soʻm — not more, not less. Any other amount
    will not be credited automatically.";
  - buttons "Cancel" and "I've paid" (switches to "Waiting for the transfer…").

  Status is polled every 3 s.

- **Step 3, outcome:**
  - **Paid:** "Credited $4.07"; the TopBar balance refreshes.
  - **Expired:** "Time is up. If you already transferred, write to support and attach
    the receipt — number T…", with a support link.
  - **Cancelled:** back to step 1.
- **Reload:** an open reservation is restored on reload (409 points to it).
- **Transactions page:** a "Top-ups" block lists reservations (number, soʻm, USD,
  status, time). Credited ones also appear in the statement as
  `merchant_deposit_credit` with the note "P2P · T…".
- **Copy:** ru / uz / en. The hints that send the reseller to support for a top-up are
  removed while P2P is on.

## 7. Admin UI (`apps/admin`, payments group)

- **`/payments/p2p-cards`:**
  - list with label, last4, holder, network, active, min, max, daily limit, today's
    matched total;
  - create and edit; the full number is write-only and shown masked;
  - receive-health: last notification time, open balance-chain break.
- **`/payments/p2p-cards` settings panel:** `mode`, allowlist, HUMO bot id.
- **`/payments/transfers`** has two tabs:
  - **Journal:** bank time, amount, source, card, balance after, kind, result (linked
    to merchant and reservation), with filters and a search by amount;
  - **Reservations:** number, merchant, card, soʻm, USD, status, times.
- Admin role only. Card edits and settings changes are audit-logged. The full number is
  never logged.

## 8. Security and PII

- Forgery resistance comes from four checks together:
  - the webhook secret header;
  - the HUMO bot's numeric id;
  - not forwarded, not edited;
  - our card's last4.
- The full card number is encrypted at rest. It is returned only to a merchant with
  their own open reservation, and is never put in logs or URLs.
- **The holder's name and the raw notification text are PII** (they include balances
  and counterparties' bank descriptors). They are stored in the database only and
  never logged. Log lines carry reservation number, amount and card last4.
- The bot can see only the HUMO chat (Business access "only selected chats"). This is
  an operational setting, recorded in the runbook.
- Update `docs/security/threat-model.md` (forged notification, replay, race on amount,
  lost notifications) and `docs/security/pii-handling.md` (card, holder, raw text).

## 9. Edge cases

| Case                                            | Behaviour                                                                                                     |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Two transfers of the same amount close together | The first matches; the second is `unmatched`. No double credit: one key per reservation, one row per message. |
| Transfer arrives at minute 6                    | `unmatched`. Quarantine stops the amount from reaching another reservation for 10 more minutes.               |
| Wrong amount (50 000 for 50 001)                | `unmatched`; support credits by hand from the receipt.                                                        |
| Amount with tiyin                               | Never matches automatically.                                                                                  |
| Reseller cancels after transferring             | `cancelled` + quarantine; the transfer is `unmatched`; support resolves it.                                   |
| HUMO changes its format                         | `unparsed` + alert; nothing credited.                                                                         |
| Webhook down < 24 h                             | Telegram redelivers. Matching uses `bank_time`, so a transfer made inside the window still matches.           |
| Webhook down > 24 h                             | Messages are lost. The balance chain breaks and alerts; ops reconcile from the bank statement.                |
| Rate unavailable                                | 502 on reserve.                                                                                               |
| All +99 amounts taken                           | 502 "try again in a minute".                                                                                  |
| P2P switched off                                | No new reservations. Open ones live out their 5 minutes and still match.                                      |

## 10. Testing

- **Parser:** real samples (credit `1.004,00`, credit with tiyin `54.728,28`, a debit),
  plus garbage → `unparsed`. Hypothesis over formatted amounts.
- **Reservation:** amount allocation, including a concurrent race on Postgres; limits;
  one-active rule; min/max; daily limit; expiry and quarantine boundaries; cancel.
- **Webhook:**
  - wrong secret → 401 without parsing;
  - other sender, forwarded, edited, other card → dropped;
  - duplicate message id → one row, one credit;
  - match → deposit credited by exactly `amount_usd`, `balance.credited` enqueued;
  - late (`bank_time ≥ expires_at`) → unmatched.
- Balance-chain alert; silence alert.
- Cabinet API (409 / 502 / 404 when off) and admin API, with query-count assertions on
  the lists.
- **Web:** Vitest for the top-up screen states.
- **E2E:** reserve → simulated webhook → balance up.
- Coverage ≥ 95 % on the `p2p` module: it is money.

## 11. Documentation

- New ADR: "P2P deposit via a Telegram Business bot reading HUMO notifications". It
  supersedes ADR-0080's "no self-serve top-up" and records the spike and the 24-hour
  limit.
- Module `README.md`.
- `docs/runbooks/p2p-deposit.md`:
  - bot setup: the three settings from §3, `setWebhook` with secret, token rotation;
  - "not credited" procedure;
  - balance-chain break;
  - adding a card.
- `docs/product/flows/p2p-deposit.md` with a Mermaid sequence diagram.
- `docs/architecture/module-map.md`; `cache-keys.md` if the settings row is cached;
  OpenAPI regenerated.
- Update `docs/runbooks/merchant-b2b.md`, which says top-up is "not self-serve".

## 12. Rollout

1. Revoke the spike token. Put the new token and webhook secret in sops.
2. Deploy with `mode = off`. Run `setWebhook(url, secret_token,
allowed_updates=["business_message","business_connection"])`. Record the HUMO bot id
   in settings.
3. Add card \*3311 in the admin. Set `mode = allowlist` with the owner's own merchant
   account, then do a real 10 000 soʻm top-up.
4. Set `mode = all`.

## 13. Out of scope

- P2P as a storefront / mini-app payment method (sub-project 2).
- Uzcard notification bots and other banks.
- Automatic resolution of unmatched transfers.
- Refunding a P2P transfer back to the card.
- Withdrawals.
