# Runbook: CS2 skin purchases

Code: `fulfillment/suppliers/waxpeer_skins.py` (or `csmarket_skins.py`, below), `fulfillment/skin_sweeps.py`,
`payments.service.refund_order_to_wallet`, scheduler jobs `skins_trades_reconcile` (5 s) and
`skins_protection_watch` (hourly). Spec §8.1 has the Waxpeer status model.

## Before launch

1. `scripts/seed/2026-09-29_cs2_skin_sku.py --apply` on prod (dry-run first).
2. Fund the Waxpeer balance: every purchase is paid from it at the listing's price.
3. The Waxpeer key only works from the prod VPS IP — nothing here can be exercised locally.
4. The buy panel (web and mini app) appears on an item page once the seed is applied — the
   item API then names `buy_sku_id` — and `CS2_SKINS_ENABLED` is on. Without the seed the
   pages stay browse-only and no customer can create a skin order.

## Buying through csmarket (ADR-0098)

Skins can be bought through the owner's csmarket.uz public API instead of Waxpeer. One env
switch, `CS2_SKINS_SOURCE=csmarket`, moves the five-minute catalogue job, the item page's live
offers, the trade-link check and **new** orders; a paid order keeps the supplier on its
`skin_trades.supplier` row, so switching never strands a trade. Code:
`fulfillment/suppliers/csmarket_client.py`, `csmarket_skins.py`, `skins/prices_csmarket.py`,
`skins/listings_csmarket.py`.

**Before switching on**

1. The csmarket key (`csm_…`, one bearer token, issued in the csmarket profile) is set as
   `CSMARKET_API_KEY` in `secrets/api.env` on prod (api, worker and scheduler all read it).
2. On csmarket's side the key has tariff **`cost`** and the **USD wallet** on. Check:

   ```bash
   docker exec yupay-prod-api-1 python - <<'PY'
   import asyncio
   from yupay.core.config import get_settings
   from yupay.modules.skins.listings_source import csmarket_client
   print(asyncio.run(csmarket_client().me()))
   PY
   ```

   `pricing_profile='cost'`, `usd_wallet_enabled=True`, a positive `balance_units`
   (1000 = $1). Ask csmarket to raise `read_per_min` to 600 for this key; the default 60 is
   shared by the feed (16 pages a pass), item pages and order polls.

3. Fund the csmarket **USD wallet** (an admin transfer on csmarket's side). A purchase with
   too little there refunds the buyer at once and alerts, like a Waxpeer low balance.
4. `CS2_SKINS_SOURCE=csmarket`, restart **api, worker and scheduler** with the deployed
   `IMAGE_TAG` (the worker buys; the scheduler syncs and follows trades).
   The next catalogue tick (≤ 5 min) writes `skin_items.source_item_id`; until then item
   pages show no live offers. Expect ~1 500 Waxpeer-only items to go inactive.
5. Buy one cheap skin to your own trade link and watch it reach `delivered`.

**Switching back**: `CS2_SKINS_SOURCE=waxpeer`, restart api, worker and scheduler. Open csmarket
trades keep being followed by the fast sweep until they finish.

**What csmarket does not give us**: a Steam price in the feed (the last Waxpeer value is
kept for the Steam cap), a rollback after delivery (a csmarket trade stays `delivered`; the
protection watch and the nightly audit are Waxpeer-only), and individual offers in the
feed (no snapshot fallback on the item page — the stale cache or nothing).

**A csmarket order looks stuck in `buying`**: our fast sweep re-sends the purchase under the
same id until csmarket answers, so a lost answer heals by itself. If it stays, read it on
csmarket's side by our `project_id` (their `client_order_id`); the outcome is decided only
by what csmarket reports — never refund it by hand while csmarket shows it in progress.

## Switching purchases off

- **Stop selling skins:** admin → Бренды → «CS2 скины»: switch it off, or put it in
  maintenance. New orders are refused (the SKU → product → brand chain must be buyable)
  and the item pages drop the buy panel within a minute (web pages revalidate every 60 s;
  the mini app reads live). The catalogue stays browsable; trades already paid for carry
  on and are tracked as usual.
- **Hide the whole market:** `CS2_SKINS_ENABLED=false` in the API env and an API restart
  (every `/skins/*` read answers 404; the mini app shows its «скоро» screen). The web nav
  follows `SKINS_ENABLED` in the web env.

## Admin screens

- **Скины → Обмены** (`/skins/trades`): every skin purchase, newest first — Waxpeer's status
  as our state, the dollars bought, the seller, the accept-by or protection date, the reason
  and any penalty. «В процессе» is what is not settled yet; «Требуют внимания» is what a human
  settles: a rollback after delivery (status 6 with penalties), a purchase we could not
  confirm (`buy_unconfirmed` / `ambiguous_trade`), or an in-flight buy with no Waxpeer status.
  Once settled (refund made, support answered, Waxpeer ticket filed) press **«Разобрано»**:
  the trade leaves the tab and keeps «разобрано <дата>» in «Все». A row opens the order.
  There is no «recheck» button: an in-flight trade is re-read every
  5–10 s and an accepted one hourly.
  The details drawer has **«Вернуть деньги»** — the order to the buyer's YuPay balance
  (`POST /admin/skins/trades/{id}/refund`), shown once the skin was received or failed and
  the money is still ours; the buyer gets the toast and the bot message, and the trade is
  marked «разобрано». Refused while the skin is on its way. And **«Повторить»** — the
  fulfilment retry, shown only for a failed task whose money was not refunded: before
  pressing it on `buy_unconfirmed`, look the project id up in the Waxpeer dashboard, or the
  skin may be bought twice.
- **Скины → Сводка**: sales and margin for 7 / 30 / 90 days — received, failed, in flight,
  revenue, Waxpeer cost, margin — and received skins per Tashkent day
  (`GET /admin/skins/summary?days=`). Cost is what Waxpeer charged (`bought_units`).
- **Клиент → CS2 скины**: the saved trade link's Steam account, every account their orders
  went to, and their last 20 trades (`GET /admin/skins/customers/{id}`). Accounts only: the
  link's token is a credential and is never shown.
- **Скины → Цены скинов** (`/skins/pricing`): the pricing document (saved whole, the
  catalogue reprices at once), a price preview that names the rule that won, and per-skin
  overrides (margin pp or a fixed price; «Сбросить наценку» clears both).

## Alerts

- **«Waxpeer: не хватило баланса на скин»** (`supplier_low_balance`, once per window): nothing
  was bought; the line failed `RETURNED` and the order already went back to the customer's
  balance, with «попробуйте через несколько минут» on the order page. Top up Waxpeer. **Do not
  retry** — the money is back, so a retry is refused (`order_already_refunded`); the customer
  buys again.
- **`buy_pending`** is not an alert: a lookup failed before anything was sent, and the 5 s
  sweep retries the lookup and then buys.
- **`buy_unconfirmed`** (task failed `UNKNOWN` after 10 min): a buy call's answer was lost and
  Waxpeer shows no trade under our `project_id`. Look the project id up in the Waxpeer
  dashboard; if nothing was bought, refund the order (admin → refund to balance or card).
- **«Скин: откат обмена после доставки»**: a trade was rolled back during Steam's protection.
  The task carries `skin_rollback` (reason, penalties). The customer already had the item
  delivered; decide with support whether anything is owed.
- **`ambiguous_trade`** (task failed `UNKNOWN`): Waxpeer lists several live trades under our
  `project_id` and we hold no Waxpeer id to tell ours. Check the Waxpeer dashboard; the order
  page tells the customer to contact support, not that money is coming back.
- **`skin_refund_failed`**: the automatic refund to the balance raised. Refund manually.
- **«Скин: расхождение с Waxpeer»** (`skin_history_divergence`, daily at 04:30 Tashkent, the
  last 14 days of trades we consider settled; it changes no trade state). Each divergence is
  alerted **once** — the verdict is kept on the trade (`audit_verdict`) and a new alert goes
  out only when it changes:
  - _откат после выпуска_ — a released trade Waxpeer now shows as failed: a late rollback.
    Handle as the rollback alert above.
  - _скин ушёл, а деньги вернули_ — we refunded the customer, but Waxpeer shows the offer sent
    or completed. Money lost twice over: check the Waxpeer dashboard and the customer's Steam
    before deciding; the balance refund can be reversed by an admin adjustment.
  - _Waxpeer не знает сделку_ — a trade with a Waxpeer status that its lookup no longer
    returns. Check the dashboard by project id; report to Waxpeer if it is gone.
  - _несколько живых сделок под одним ключом_ — as `ambiguous_trade`.

## Refunds

A skin task that fails with the money back (`RETURNED`) refunds the order to the customer's
YuPay balance automatically. A customer who wants the money on their card instead asks support;
the balance can then be paid out or the card refunded by an admin as for any order.

A payment refunded to the balance (`last_refund.refunded_to = "wallet"`) cannot also be
cancelled by the acquirer: Payme answers `-31007`, Uzum `10017`, Paynet `306`. If a customer
asks for the card instead, take the money off the balance first, then refund the card.

**While a skin is on its way nothing refunds** (`skins/refund_guard.py`): a skin line that is
not `delivered` and not `failed` with the money accounted for (`returned` / `spent`) — being
bought, its offer in Steam, or a failure we cannot account for (`buy_unconfirmed`,
`ambiguous_trade`, money `unknown`) — makes an acquirer
cancel read as goods shipped (the same codes as above) and an admin refund answer `409
skin_trade_in_flight`. Waxpeer cannot recall a paid offer, so a refund then would hand over the
skin and the money. Wait until it is received or fails (a failed one refunds itself).

For an `unknown` failure: look the project id up in the Waxpeer dashboard; once you know no
offer is open, press «Разобрано» on the trade — only then does «Вернуть деньги» appear and
the acquirers' cancel go through. The refund and a fulfilment retry both lock the order row
before checking, so the two can never both succeed.

A retail order already refunded cannot be retried from the fulfilment inbox
(`order_already_refunded`): the retry would buy the skin on our money.

The order page promises a refund only where one was made: `skin_trade.refunded_to` (`wallet` /
`card`) is read off the payment. A failed line with no refund yet says «напишите в поддержку».

## Still to verify on prod

- **Orphan buys** (a Waxpeer purchase with no `skin_trades` row of ours) are not detected: the
  daily audit reads trades back by our own `project_id`. Detecting them needs `my-history`,
  whose response shape was never captured (the key works only from the prod IP) — probe it
  once on prod, then extend `audit_recent_trades`.

- A **refused buy followed by a substitute under the same `project_id`** has not been exercised
  against Waxpeer (the spike bought, it never refused first). The code picks our trade by the
  id Waxpeer returned on the buy, so a refused attempt listed under the key is ignored; if
  Waxpeer rejects a reused key, substitution simply never succeeds and the order refunds.
  Try it once with a 5-unit item before relying on substitution.
