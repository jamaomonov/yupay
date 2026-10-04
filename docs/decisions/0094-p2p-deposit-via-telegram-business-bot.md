# 0094. P2P deposit via a Telegram Business bot reading HUMO notifications

- **Status**: Accepted
- **Date**: 2026-10-04
- **Deciders**: @jamaomonov
- **Tags**: backend | payments | security

## Context and problem statement

A reseller can top up the USD deposit only through support: they transfer money, write to
`@yupay_support`, and an admin credits the deposit by hand. ADR-0080 and the merchant runbook
made that a deliberate choice ("no self-serve top-up"). The owner now wants self-serve: the
reseller transfers an exact soʻm amount to the owner's Humo card and the deposit is credited
within seconds.

No acquirer is involved, so nothing tells us a transfer arrived except the card's own bank
notification. Humo's official bot **@HUMOcardbot** sends every credit to the owner's Telegram
account. The question is how to read it reliably and match it to one reseller.

## Decision drivers

- No new third-party acquirer, no per-transaction fee.
- A credit must never land on the wrong reseller, and never twice.
- Missed notifications must be detectable, because Telegram offers no history.
- Operable on the existing single VPS: no new long-running process.

## Considered options

1. **Telegram Business bot, webhook into the API, exact-amount reservations** — chosen.
2. **Userbot (MTProto session of the owner's account)** — reads any chat, but is a logged-in
   personal session, against Telegram's terms, and one flood-wait from a banned account.
3. **Bank statement polling / bank API** — Humo exposes none to a personal card.
4. **Keep manual credit via support** — status quo; the cost is the owner's time and the
   reseller's wait.

## Decision outcome

**Chosen option:** 1.

- **Channel.** A bot connected through Telegram Business (chat automation) receives the
  HUMO chat as `business_message` updates. The Bot API delivers them by webhook to
  `POST /api/v1/webhooks/telegram/p2p`. There is no long-poll process.
- **Matching.** The reseller enters an amount; we reserve that exact whole-soʻm amount on a
  card for 5 minutes (+1…+99 if taken). The amount is the only key that ties a notification
  to a reseller. A partial unique index makes "one open amount per card" a database rule. An
  expired or cancelled amount stays in quarantine for 10 minutes.
- **Spike (2026-10-04).** It works only with three settings; the third is the one people miss:
  1. Business chatbot access is "Only selected chats: HUMO Card". The bot cannot see any other
     chat of the owner.
  2. The bot's Messages permissions are on.
  3. BotFather "Bot to Bot Communication Mode" is on. Without it, messages from another bot
     (HUMO is a bot) are not delivered through business accounts.
- **Forgery resistance** is three checks together: the webhook secret header, the sender and
  chat id both equal to the HUMO bot's numeric id, and no `forward_origin`. Edited messages
  never arrive: `allowed_updates` has no edited type and the intake ignores
  `edited_business_message`. Our card's last4 is a matching condition, not an authentication
  control.
- **Rate.** USD = soʻm / rate rounded **down** to cents, at the storefront's own guarded rate,
  frozen on the reservation.
- **Fallback.** A transfer nothing matches is `unmatched` in the journal; an admin credits it
  with the existing deposit-credit button and a note.

This **supersedes ADR-0080's "no self-serve top-up"** for the cabinet. The reseller marketing
site's "no top-up mentions" rule is unchanged: it concerns the public site, not the cabinet.

### Positive consequences

- Top-up in seconds, no fee, no new infrastructure beyond one webhook route and a 30 s job.
- Every notification is journaled, including ones that match nothing.
- The balance printed in each notification lets us detect a missed one.

### Negative consequences

- **24-hour redelivery limit.** Telegram keeps undelivered updates for up to 24 hours, and
  the Bot API cannot read history. A longer outage loses notifications for good. Matching uses
  the bank time, so a redelivered on-time transfer still matches inside the window.
- **Balance chain as the gap detector.** For each card, previous `balance_after` ± amount must
  equal this row's `balance_after`; a break raises `p2p_chain_break`. It can raise a false
  break on out-of-order delivery. Reconcile against the bank statement before acting.
- **Personal-card P2P risk.** Receiving many transfers on a personal card can make the bank
  restrict it (compare the Click incident). The owner accepts this risk; more cards can be
  added without a schema change.
- **Dependence on an unofficial channel.** HUMO can change the notification format
  (`p2p_unparsed` alert, nothing credited) or Telegram can change Business rules.
- **Minute-precision bank time.** The notification carries `HH:MM`, so the expiry edge has up
  to 59 s of leniency.
- Amounts with tiyin never match automatically.

## Validation

- Coverage on `yupay.modules.p2p` is at least 95 % (money path).
- Rollout (spec §12): `mode = off`, then `allowlist` with the owner's own merchant and a real
  10 000 soʻm top-up, then `all`.
- Review after the first month: count of `unmatched` credits, `p2p_chain_break` and
  `p2p_unparsed` alerts.

## Alternatives considered (detail)

### Userbot

Sees the same notification with no Business setup, but it is a full personal session in our
infrastructure, and a ban would also cost the owner their account.

### Manual credit only

Zero risk, and the current state. It scales with the owner's attention, not with orders.

## References

- Spec: `docs/superpowers/specs/2026-10-04-p2p-deposit-design.md`
- [ADR-0080](./0080-reseller-site-for-non-technical-resellers.md) — the "no self-serve
  top-up" rule this ADR supersedes for the cabinet
- Runbook: `docs/runbooks/p2p-deposit.md`
- Module: `apps/api/src/yupay/modules/p2p/README.md`
