# Runbook — P2P deposit

Resellers top up the USD deposit by transferring an exact soʻm amount to the owner's Humo
card. A Telegram Business bot reads the **@HUMOcardbot** notification and posts it to the API,
which credits the matching reservation. Decision: ADR-0094. Module:
`apps/api/src/yupay/modules/p2p/README.md`.

## 1. Bot setup

The bot is `@depositlistenerbot`. It works only with all three settings. The third is the one
people miss.

**Before connecting the bot**, enter **your own Telegram user id** in admin → payments → P2P
cards → settings → "Your Telegram id (card owner)", and save. The API pins the Business
connection that this user enables and ignores every other one, so a connection made before the
id is saved is not pinned (disconnect and reconnect the bot). After connecting, check that the
panel shows **"connected"** with a connection id. "not connected" means nothing is credited.

1. **Business chatbot access.** Telegram → Settings → Telegram Business → Chatbots:
   `@depositlistenerbot`, access **"Only selected chats: HUMO Card"**.
2. **Messages permissions** on, in the same screen. With only "gifts and stars" no messages are
   delivered.
3. **BotFather "Bot to Bot Communication Mode" on.** In @BotFather, select the bot, enable
   Business Mode, then Bot to Bot Communication Mode. Without it, messages from another bot
   (HUMO is a bot) do not reach a business bot.

The bot token and the webhook secret are never stored in the database. They live in the API
environment: `P2P_BOT_TOKEN` (used only for the `curl` calls below) and `P2P_WEBHOOK_SECRET`
(config key `p2p_webhook_secret`), both in sops.

**The spike token was exposed in chat. Revoke it (`/revoke` in @BotFather) before production**
and use the new one.

## 2. `setWebhook`

```bash
curl -s "https://api.telegram.org/bot$P2P_BOT_TOKEN/setWebhook" \
  -d url=https://api.yupay.uz/api/v1/webhooks/telegram/p2p \
  -d secret_token=$P2P_WEBHOOK_SECRET \
  -d 'allowed_updates=["business_message","business_connection"]'
curl -s "https://api.telegram.org/bot$P2P_BOT_TOKEN/getWebhookInfo"
```

Verify `url`, `pending_update_count` near 0 and no `last_error_message`. An unset
`P2P_WEBHOOK_SECRET` makes the route answer 401 to everything.

## 3. Find the HUMO bot id

The filter accepts only messages whose sender and chat id equal the HUMO bot's numeric id, so it
must be saved before anything matches.

- Before `setWebhook`, call `getUpdates` and read `business_message.from.id` of a HUMO message
  (`from.is_bot` is `true`); or
- after `setWebhook`, read the `p2p.business_connection` log line to confirm the connection
  (`is_enabled`, rights keys, `owner` true/false; it carries no ids), then use the first
  option. `owner=false` means the saved owner id is not the account that connected.

Save it in admin → payments → P2P cards → settings → HUMO bot id.

## 4. Token rotation

1. `/revoke` in @BotFather, copy the new token.
2. Update `P2P_BOT_TOKEN` in sops. If the secret rotates too, change `P2P_WEBHOOK_SECRET`.
3. Redeploy the API with `IMAGE_TAG` set (a plain `up -d` can roll back to a stale image).
4. Run `setWebhook` again (section 2) and check `getWebhookInfo`.

Rotating the token does not drop the Business connection, but verify with a small transfer.

## 5. "A reseller says it did not credit"

1. Admin → payments → Transfers → Journal. Search by the amount.
2. `matched`: it credited; show the reseller the reservation number and the note
   `P2P · T…`.
3. `unmatched`: find who paid, using the reservation list (amount, time, merchant). Credit with
   the merchant's deposit-credit button, note `P2P · <bank time> · <amount>`.
4. No row: the notification did not arrive. Go to section 7.

Never credit a transfer twice: look for an existing credit with the same note first. Likely
causes of `unmatched`: wrong amount, amount with tiyin, a transfer after the 5 minutes, a
cancelled reservation, or two active cards sharing a last4 (`p2p_ambiguous_card`).

## 6. `p2p_chain_break` alert

Each notification prints the card balance after the operation. A break means previous balance
± amount does not equal this balance: a notification was missed, or arrived out of order.

1. Compare the card's bank statement with the journal for that window.
2. Missing credit with a reservation of that amount: credit by hand (section 5).
3. Out-of-order delivery gives a **false** break; the journal rows are all present and the
   balances are consistent once sorted by bank time. No action.

## 7. `p2p_silence` alert

Reservations are expiring while HUMO has not been heard from for over 6 hours.

1. `getWebhookInfo`: `last_error_message`, `pending_update_count`.
2. Admin P2P settings panel shows "connected". If not, reconnect the bot from the owner's
   account (section 1).
3. Telegram → Settings → Telegram Business → Chatbots: the bot is still connected and still
   has "Only selected chats: HUMO Card" and Messages permissions (a Business reconnect resets
   them).
4. BotFather Bot to Bot Communication Mode is still on.
5. Repeat section 2 if the webhook was lost.

Telegram keeps undelivered updates up to **24 hours**. After a longer gap they are gone;
reconcile with the bank statement.

## 8. Add or disable a card

Admin → payments → P2P cards. Create with label, full number (write-only, shown masked
afterwards), holder name, network, min / max and optional daily limit. Disable with the active
flag: no new reservation uses it, and only **active** cards are matched. Two active cards with
the same last4 are never auto-matched.

Settings: `off` stops new reservations (open ones live out their 5 minutes), `allowlist`
admits listed merchants, `all` admits everyone.

## Other alerts

- `p2p_unparsed`: HUMO changed the notification format. Nothing is credited. The alert carries
  the message id only; read the row in the journal and update `parsing.py`.
