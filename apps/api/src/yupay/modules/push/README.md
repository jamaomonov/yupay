# push

Pushes to the mobile app through Expo ([ADR-0102](../../../../../../docs/decisions/0102-mobile-push-through-expo.md)).

| File          | What                                                                          |
| ------------- | ----------------------------------------------------------------------------- |
| `models.py`   | `PushDevice` (one install's Expo token), `PushMessage` (one push, one device) |
| `routes.py`   | `PUT /push/devices`, `GET /push/devices`, `DELETE /push/devices/{id}`         |
| `service.py`  | Register / disable a device; `enqueue_for_order` at the order status seam     |
| `texts.py`    | Title and body per kind, in ru / en / uz                                      |
| `expo.py`     | `exp.host` `/push/send` and `/push/getReceipts`                               |
| `delivery.py` | `drain_pending_pushes` (worker, `push_queue`), `check_receipts` (scheduler)   |

## What pushes

`orders.service.on_order_status_changed` calls `enqueue_for_order` for every retail order:

| Order becomes                  | Kind              | Says                              |
| ------------------------------ | ----------------- | --------------------------------- |
| `delivered` (a sale)           | `order_delivered` | «Заказ выполнен» · brand          |
| `delivered` (a `wallet_topup`) | `wallet_credited` | «Баланс пополнен» · +amount сум   |
| `failed`                       | `order_failed`    | «Заказ не выполнен» · brand, help |
| `refunded`                     | `order_refunded`  | «Деньги возвращены» · brand       |

`data` is `{"type": "order", "order_id": …}`, so the app opens the order when the push is
tapped. Android messages carry `channelId: "orders"`, which the app must create.

## The app's side

1. Ask for permission; get the token with `getExpoPushTokenAsync({ projectId })`.
2. `PUT /api/v1/push/devices` `{token, platform, app_version}` with an `Idempotency-Key`.
   Do it at every launch with a session and after sign-in: the call is an upsert, and it
   moves the token to whoever is signed in.
3. Keep the returned `id`; on sign-out call `DELETE /api/v1/push/devices/{id}` **before**
   dropping the session.

## Operating it

Runbook: [`docs/runbooks/push-notifications.md`](../../../../../../docs/runbooks/push-notifications.md).
