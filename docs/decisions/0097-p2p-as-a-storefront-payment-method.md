# 0097 — P2P card transfer as a storefront payment method

- Status: accepted
- Date: 2026-10-05
- Deciders: owner, Claude
- Supersedes / extends: ADR-0094 (P2P deposit via Telegram Business bot), sub-project 2 of
  `docs/superpowers/specs/2026-10-04-p2p-deposit-design.md`

## Context and problem statement

ADR-0094 lets a reseller top up their deposit by transferring an exact soʻm amount to the
owner's Humo card; a Telegram Business bot reads the @HUMOcardbot notification and the API
credits the matching reservation. The owner wants the same channel on the public storefront as
one more way to pay for an order, beside Click, Payme and Uzum — and wants it governed by the
same admin switch as every other provider (active / maintenance / disabled).

What already exists: the reservation table with a `purpose` column and a nullable
`merchant_id`, the exact-amount hold with per-card bump and daily limit, the intake with its
four forgery checks, the sweep and the quarantine. What does not: a way to tie a hold to an
order, a `PaymentGateway` for it, a place on the storefront to show the card and the amount.

## Decision drivers

- One settlement path. An order must become `paid` through
  `payments.service._mark_payment_succeeded`, the chokepoint every acquirer uses, never a
  second P2P-only transition.
- One switch. The storefront must obey `payment_provider_state` like every provider; the P2P
  settings `mode` (`off` / `allowlist` / `all`) stays the cabinet's gate.
- No new secrets on the payment row. The card number stays sealed in `p2p_cards`.
- Nothing bought twice. A retried intent is the same hold; a late transfer takes the
  late-payment path that already exists.

## Considered options

1. **A `p2p` gateway over the existing reservation**, `purpose='order'` + `order_id` on the
   reservation, intent = hold, settlement = intake → `settle_provider_payment`.
2. A separate `p2p_order_payments` table and its own matcher beside the deposit one.
3. Wallet-first: the customer tops up a YuPay balance by P2P and pays with the balance.

## Decision outcome

**Option 1.**

- **Reservation.** `p2p_reservations.order_id` (migration 0097), `purpose IN
('merchant_deposit','order')`, one pending reservation per order
  (`uq_p2p_reservations_one_pending_order`). `reservations.reserve_for_order` holds the order's
  whole-soʻm total until **the order's own `expires_at`** — the ten-minute payment window —
  rather than the cabinet's five minutes, so the clock the payer sees is the order's clock.
  No admission mode is consulted. The amount may be **bumped** by up to the card's cap when the
  exact total is held by someone else; the payer is told the bumped figure, and whatever they
  transfer that matches pays the order. The extra soʻm are the price of amount-matching, the
  same trade the reseller top-up makes.
- **Gateway.** `payments/gateways/p2p.py`, provider `p2p`. `available` = the Telegram webhook
  secret is set. `create_intent` refuses a non-UZS or fractional total, an order with under 90
  seconds left, and an unpinned Business connection, then holds the amount and returns
  `intent_url=None` with the reservation number as `external_id` (`p2p:<number>`) and
  `amount_uzs` / `card_last4` / `expires_at` in the metadata. `verify_webhook` is never
  reached; `refund` refuses — a refund is a manual transfer, recorded in the admin.
- **Instructions.** `payments.p2p_details.payment_out` fills `PaymentOut.p2p` — card number
  grouped in fours, holder, network, exact amount, deadline — on the three customer payment
  routes, only while the reservation is pending and unexpired. The number is opened from the
  sealed card on read, the way the cabinet does; it is never stored on the payment.
- **Settlement.** The intake's `_credit` branches on `purpose`: an order reservation finds the
  `p2p` payment by `external_id` and calls `settle_provider_payment`, so the order flips to
  `paid`, fulfilment starts, and an order that already expired takes `_settle_late_payment`
  (ADR on paid-after-expiry). A reservation with no payment behind it is reported as
  `unmatched` with an alert rather than guessed around.
- **Switch.** `LOGICAL_PROVIDERS["p2p"]` — the admin provider list, the customer
  `GET /payments/providers` list and `create_intent`'s state check all come for free.
- **Storefront (web first).** «Перевод на карту» beside the acquirers; after the intent the
  buyer lands on the order page, where the pay-now block shows the card, the holder, the exact
  amount with copy buttons and a countdown, and the order polls itself to `paid`. The mini app
  is a later step.

### Positive consequences

- One more rail with no acquiring fee, no new infrastructure, one migration.
- Every transfer is journaled and every order payment goes through the one chokepoint.
- The admin switch, the quarantine, the daily limit and the forgery checks are inherited.

### Negative consequences

- The owner's card number is shown to anyone who reaches the payment step, guests included.
  Accepted by the owner: a transfer cannot be made without it, and the cabinet already shows it.
- The payer may be asked for a few soʻm more than the price when the exact total is held.
- No automatic refund. The runbook names the manual steps.
- A transfer that arrives after the order expired pays it late, like a late acquirer callback:
  the existing late-payment handling applies, and the operator sees it in the journal.

## Validation

- `tests/integration/test_payments_p2p_gateway.py`: hold for the order's window with the card
  on the payment; retried intent is the same payment; disabled provider and unpinned bot refuse
  before holding; a held amount is bumped and the payer sees the bumped figure; the matching
  HUMO notification pays the order and the instructions disappear.
- The existing P2P and payments suites stay green.

## References

- ADR-0094, `docs/superpowers/specs/2026-10-04-p2p-deposit-design.md`
- `docs/runbooks/p2p-deposit.md` §storefront
- `apps/api/src/yupay/modules/payments/README.md`, `apps/api/src/yupay/modules/p2p/README.md`
