# Runbook: CS2 skin purchases

Code: `fulfillment/suppliers/waxpeer_skins.py`, `fulfillment/skin_sweeps.py`,
`payments.service.refund_order_to_wallet`, scheduler jobs `skins_trades_reconcile` (5 s) and
`skins_protection_watch` (hourly). Spec §8.1 has the Waxpeer status model.

## Before launch

1. `scripts/seed/2026-09-29_cs2_skin_sku.py --apply` on prod (dry-run first).
2. Fund the Waxpeer balance: every purchase is paid from it at the listing's price.
3. The Waxpeer key only works from the prod VPS IP — nothing here can be exercised locally.
4. Plan 3b ships the storefront buttons; until then no customer can create a skin order.

## Alerts

- **Low balance** (`supplier_low_balance`): the order stays «в обработке». Top up Waxpeer, then
  retry the task from the admin fulfilment inbox.
- **`buy_unconfirmed`** (task failed `UNKNOWN` after 10 min): a buy call's answer was lost and
  Waxpeer shows no trade under our `project_id`. Look the project id up in the Waxpeer
  dashboard; if nothing was bought, refund the order (admin → refund to balance or card).
- **«Скин: откат обмена после доставки»**: a trade was rolled back during Steam's protection.
  The task carries `skin_rollback` (reason, penalties). The customer already had the item
  delivered; decide with support whether anything is owed.
- **`skin_refund_failed`**: the automatic refund to the balance raised. Refund manually.

## Refunds

A skin task that fails with the money back (`RETURNED`) refunds the order to the customer's
YuPay balance automatically. A customer who wants the money on their card instead asks support;
the balance can then be paid out or the card refunded by an admin as for any order.
