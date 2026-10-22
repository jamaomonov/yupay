# 0102. Push notifications to the mobile app through Expo

- **Status**: Accepted
- **Date**: 2026-10-22
- **Deciders**: @jamaomonov
- **Tags**: backend | mobile | notifications

## Context and problem statement

The app (ADR-0100) is where a buyer waits for an order, and a browser tab cannot tell them it
landed. A push says it on the lock screen: the order was delivered, failed or refunded, or a
wallet top-up was credited. iOS pushes go through APNs and Android pushes through FCM, each
with its own credentials and payload format.

Today's customer notifications (Telegram, email) are fire-and-forget after commit: nothing
retries them and a crash loses them. A push that never arrives is the same failure, so it
should not copy that shape.

## Considered options

1. **Expo's push service.** One HTTP API in front of APNs and FCM. The app gets an
   `ExponentPushToken[…]` from `expo-notifications`; the APNs key and FCM credentials live
   in the Expo project (EAS) rather than in our secrets.
2. **APNs and FCM directly.** The backend holds a `.p8` key and a Firebase service account,
   signs JWTs for APNs and OAuth for FCM, and speaks two payload formats.
3. **A third party (OneSignal and the like).** Another account, an SDK in the app, and a
   dashboard that owns the audience.

## Decision outcome

**Option 1.** The app is already Expo; `expo-notifications` hands it a token in one call, and
one request to `exp.host` serves both platforms. The cost is a dependency on Expo's relay
being up. That is the same trust EAS builds already require, and switching later to option 2
changes the sender in `push/expo.py`, not the queue or the app.

### Shape

- **Devices.** `push_devices` holds one row per install token (`UNIQUE token`). `PUT
/push/devices` registers or refreshes it and moves it to the account signing in, so a phone
  that changes accounts stops pushing to the previous one. `DELETE /push/devices/{id}` is the
  app's sign-out. Both take `Idempotency-Key`.
- **Queue.** `push_messages` holds one row per message per device.
  `orders.service.on_order_status_changed`, the seam every status write passes through,
  calls `push.enqueue_for_order` in the same transaction, followed by `pg_notify
push_queue`. An order that rolls back pushes nothing. `UNIQUE (device_id, dedupe_key)`
  with `dedupe_key = <kind>:<order id>` means an order that passes through `delivered` twice
  still pushes once. Merchant and guest orders queue nothing.
- **Sending.** The worker drains `push_queue` (concurrency 1) with one batched `POST
/push/send` of up to 100 messages. Each message ends one of three ways:
  - **Retry with backoff** (30 s doubling, capped at 1 h, at most 6 attempts) on network
    errors, 429, 5xx or `MessageRateExceeded`. A `Retry-After` from Expo sets the delay.
  - **`DeviceNotRegistered`**: the message fails and the device is disabled.
  - **Any other error**: the message fails.

  Outside `ENVIRONMENT=prod` messages are `skipped`, so dev and staging never push real
  phones.

- **Receipts.** The scheduler job `push.check_receipts` runs every 15 minutes. It reads
  receipts for messages sent at least 15 minutes earlier, disables a device whose receipt
  says `DeviceNotRegistered`, and gives up on a receipt after 24 hours.
- **Text.** `push/texts.py` renders the text in the account's `users.locale` (ru, en, uz):
  the brand name, or the credited amount for a top-up. No codes, and nothing about the
  recipient.
- **`EXPO_ACCESS_TOKEN`** is optional. When set it goes out as a bearer token, and with
  Expo's «enhanced push security» turned on, nobody else can push to our tokens.

### Positive consequences

- Durable: a crash or an Expo outage delays a push but does not lose it.
- One seam: a new status that deserves a push is one line in `push.service._kind_for`.

### Negative consequences

- Pushes depend on Expo's relay as well as on APNs and FCM.
- Telegram and email are still fire-and-forget. Moving them onto a queue is not part of this
  change.

### The app's side (2026-10-22)

`apps/mobile/src/lib/push.ts` and `components/PushBridge.tsx`: permission asked once after
sign-in, the Android channel `orders`, the token registered with `PUT /push/devices` against
the EAS project `0ccca536-c3c8-4bdf-b5ea-1868b084c444`, `DELETE` before sign-out, and a tap
opening the order. Expo Go on Android cannot receive remote pushes (SDK 53+), so testing
there needs a development build.

## Validation

`apps/api/tests/integration/test_push.py` covers:

- the token moving between accounts;
- one message per active device and per outcome;
- merchant, guest and no-device orders queueing nothing;
- a sent message, a gone device at send time, a retry after a 503, skipping outside prod;
- a receipt disabling a device;
- the HTTP routes requiring `Idempotency-Key` and never echoing the token.
