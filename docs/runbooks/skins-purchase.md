# Runbook: CS2 skin purchases

Code: `fulfillment/suppliers/waxpeer_skins.py`, `fulfillment/skin_sweeps.py`,
`payments.service.refund_order_to_wallet`, scheduler jobs `skins_trades_reconcile` (5 s) and
`skins_protection_watch` (hourly). Spec §8.1 has the Waxpeer status model.

## Before launch

1. `scripts/seed/2026-09-29_cs2_skin_sku.py --apply` on prod (dry-run first).
2. Fund the Waxpeer balance: every purchase is paid from it at the listing's price.
3. The Waxpeer key only works from the prod VPS IP — nothing here can be exercised locally.
4. The buy panel (web and mini app) appears on an item page once the seed is applied — the
   item API then names `buy_sku_id` — and `CS2_SKINS_ENABLED` is on. Without the seed the
   pages stay browse-only and no customer can create a skin order.

## Admin screens

- **Скины → Обмены** (`/skins/trades`): every skin purchase, newest first — Waxpeer's status
  as our state, the dollars bought, the seller, the accept-by or protection date, the reason
  and any penalty. «В процессе» is what is not settled yet; «Требуют внимания» is what a human
  settles: a rollback after delivery (status 6 with penalties), a purchase we could not
  confirm (`buy_unconfirmed` / `ambiguous_trade`), or an in-flight buy with no Waxpeer status.
  A row opens the order. There is no «recheck» button: an in-flight trade is re-read every
  5–10 s and an accepted one hourly.
- **Скины → Цены скинов** (`/skins/pricing`): the pricing document (saved whole, the
  catalogue reprices at once), a price preview that names the rule that won, and per-skin
  overrides (margin pp or a fixed price; «Сбросить наценку» clears both).

## Alerts

- **Low balance** (`supplier_low_balance`): the order stays «в обработке». Top up Waxpeer, then
  retry the task from the admin fulfilment inbox.
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
  last 14 days of trades we consider settled; read-only):
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
