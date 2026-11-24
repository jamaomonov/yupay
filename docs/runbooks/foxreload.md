# FoxReload (Steam top-ups) — runbook

ADR-0107. Whole-dollar Steam lines go to FoxReload, the rest to `FOXRELOAD_OVERFLOW_SUPPLIER`.

## Go-live

1. foxreload.com → «API ключи»: create a key, bind it to the VPS IP `152.228.137.175`. Fund
   the **USD** balance (orders are created and paid in USD).
2. `secrets/api.env` (api, worker, scheduler): `FOXRELOAD_API_KEY=<key>`. Restart with
   `IMAGE_TAG`.
3. Mapping for the Steam SKU (`steam-wallet-usd`, `019f83f5-f4ab-7152-98cd-f0329806b66f`):
   `supplier_slug='foxreload'`, `kind='game'`, `external_product_id` =
   `product_01kjp6vtmjf8rbbxw88719wz3b` («Steam Wallet 1 USD (Global)», 2026-11-24), active.
4. Webhook (optional, speeds delivery from ≤10 s polling to seconds): foxreload.com →
   «Вебхуки» → URL `https://api.yupay.uz/api/v1/webhooks/foxreload`, event «Завершённые
   заказы» (`order.completed`). Put the secret shown once into `FOXRELOAD_WEBHOOK_SECRET`
   and restart api with `IMAGE_TAG`. Without the secret the receiver answers 401 to
   everything; the sweep still delivers.
5. Admin → Integrations → FoxReload → health shows the balance.
6. Sourcing → Steam SKU → `force_supplier = foxreload`. A $5 order goes to FoxReload,
   a $5.50 one to Waxpeer (`fulfillment.foxreload_overflow` in the api log).

## Switch everything to one supplier

Sourcing → Steam SKU → `force_supplier = waxpeer` (everything to Waxpeer), and back to
`foxreload` to split again. No deploy, no env change.

## Something is wrong

- **Low balance** — the task stalls as `supplier_low_balance` with the alert; fund USD and
  retry from the inbox. An unpaid FoxReload order expires on its own.
- **Task stuck in progress** — `fulfillment.foxreload_reconcile` checks new orders every 10 s, older ones on the shared backoff. Webhook refusals log `foxreload.webhook.bad_signature` (wrong/missing secret). Look the
  order up in their dashboard by `external_order_id`. `action_required` should not happen for
  Steam (`direct_topup`); if it does, the order needs a confirmation code — resolve with them.
- **Failed with a reason** — `items[].error` is written for the customer (e.g. wrong login);
  their refund lands on our balance and the order is refunded automatically (`RETURNED`).
- **Product id changed** — their catalogue (`GET /api/products/?categoryId=gaming-services-steam-wallet-top-up`,
  no key needed) lists it; update the mapping's `external_product_id`.
