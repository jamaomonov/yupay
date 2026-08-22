# Runbook — Admin payment-provider controls

Operator-facing procedure for pausing, marking under maintenance, and
re-enabling a payment provider (Click, Payme, Uzum, Octo, **Кошелёк**, or
`crypto`) without a deploy — plus how to read the per-provider analytics
that inform that decision. Background:
[ADR-0041](../decisions/0041-admin-payment-provider-controls.md),
[ADR-0056](../decisions/0056-fx-drop-tripwire.md).

**Before touching anything, read the caution below** — disabling a provider
does not cancel money already in flight.

## The three states

| State         | Storefront (web + miniapp)                                                                                   | New payment intents (`POST /payments/intents`)               | Already-created intents / in-flight payments                             |
| ------------- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------ | ------------------------------------------------------------------------ |
| `active`      | Shown, selectable, exactly as today. This is the default — a provider with no row in the DB is `active`.     | Allowed.                                                     | Unaffected.                                                              |
| `maintenance` | **Shown but greyed out / non-clickable**, labelled "Технические работы" (web) / "Тех. работы" badge (admin). | Rejected — `409 Conflict`, `reason: "provider_maintenance"`. | **Continue to settle normally via webhook/callback.** See caution below. |
| `disabled`    | **Hidden entirely** — omitted from `GET /payments/providers`, so the storefront never renders it.            | Rejected — `409 Conflict`, `reason: "provider_disabled"`.    | **Continue to settle normally via webhook/callback.** See caution below. |

`maintenance` vs `disabled` is purely a UX choice for the operator: use
`maintenance` when you want customers to see the method exists but can't use
it right now (e.g. a known, temporary supplier issue); use `disabled` when
you want it to look like the method never existed (e.g. we've decided to
drop a provider). Both behave identically for new-intent enforcement — the
only difference is what the storefront renders.

Provider state also composes with **config availability** (does `api.env`
even have API keys for this provider). A provider missing its keys is hidden
from customers regardless of its admin state — the admin list screen shows
this separately as the "Конфиг" / "Настроен" / "Нет конфига" column, so you
can tell "we turned this off" apart from "this was never wired up."

**Click is one control for two surfaces.** Click is exposed to acquirers as
two gateway slugs (`click` for web, `click_miniapp` for the bot), but the
admin screen and API only ever expose the single logical provider `click` —
setting its state writes both slugs atomically. You cannot disable Click on
web only.

## Caution: disabling does NOT cancel in-flight payments

**A customer who already started paying before you changed the state will
still be charged, and their payment will still settle.** Provider state is
only consulted when a **new** intent is created — the webhook/callback paths
that settle a payment (Click `/complete`, Payme `PerformTransaction`, Uzum
`/confirm`, Octo's webhook) never check provider state at all, by design.
This is intentional: the acquirer has already collected the money and will
call our endpoint regardless of what we do on our side; refusing that call
would not undo the charge, it would only strand the order at
`pending_payment` while the customer has already paid — a worse outcome
than letting it settle. See ADR-0041's "in-flight safety invariant" section
for the full reasoning.

**What this means in practice:**

- Disabling/maintenance-ing a provider stops it from being **offered to new
  customers**. It does not touch any payment that already has a pending
  intent.
- If you need to know whether any in-flight payments exist for a provider
  you're about to pause, check the **Инциденты** ("Висящие платежи" /
  stuck-pending count) and the **Последние платежи** (recent payments) block
  in the provider detail drawer before or right after you disable it — see
  "Reading the analytics" below.
- There is no separate "cancel all pending payments for this provider"
  action. If a specific payment needs to be stopped, use the existing
  payment-level admin tools (`/admin/payments/{id}`), not the provider
  toggle.

## How to change a provider's state

### Via the admin screen (preferred)

1. Open the admin SPA → **Провайдеры оплаты** (`/payments/providers`).
2. The table lists one row per logical provider: display name, current
   state badge, config status, gateway slugs, and who last changed it and
   when.
3. Click a row to open the detail drawer. It shows the per-provider
   analytics (see below) plus three actions in the footer:
   - **Отключить** ("Disable") — asks for confirmation first (this is the
     "hide entirely" state); then sets `disabled`.
   - **Технические работы** ("Maintenance") — no confirmation prompt; sets
     `maintenance`.
   - **Включить** ("Enable") — only shown when the provider isn't already
     `active`; sets it back to `active`.
4. Each action fires immediately (a fresh `Idempotency-Key` is generated
   client-side per click) and shows a toast confirming the new state. Both
   the provider list and the open drawer refresh automatically — no manual
   reload needed.

### Via the API directly (fallback — e.g. scripting, or the admin UI is down)

```bash
curl -X PUT "https://api.yupay.uz/api/v1/admin/payments/providers/<provider>/state" \
  -H "Authorization: Bearer <admin JWT>" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"state": "disabled"}'
```

- `<provider>` is the **logical** key: `click`, `payme`, `uzum`, `octo`, or
  `crypto` — never a raw gateway slug like `click_miniapp`.
- `state` is one of `"active"`, `"disabled"`, `"maintenance"`.
- **Always send a fresh, unique `Idempotency-Key`** (a UUID is fine) per
  logical change. The endpoint is idempotent: replaying the same key returns
  the cached response from the first call rather than re-applying — useful
  if a request times out and you're unsure whether it landed, but it means
  reusing a key will **not** let you "retry" a state change with a different
  `state` value; generate a new key for that.
- A 404 means the `provider` path segment isn't a recognised logical
  provider (check spelling — it's the logical key, not a gateway slug).
- The response is an `AdminProviderSummary` — check `state` in the response
  body to confirm the change took effect.

To list current states without the UI:

```bash
curl "https://api.yupay.uz/api/v1/admin/payments/providers" \
  -H "Authorization: Bearer <admin JWT>"
```

## Reading the analytics / incidents blocks

The detail drawer (`GET /admin/payments/providers/{provider}?window=today|7d|30d`)
shows, for the selected time window:

- **Объём (Volume)** — total payment amount and count per currency, for
  payments that reached `succeeded`/`refunded`/`partially_refunded` in the
  window (a later refund does not remove volume — it's tracked separately).
  Empty means no completed payments through this provider in the window.
- **Успешность (Success rate)** — succeeded / failed / pending counts and a
  success percentage. `failed` here means terminal failure (`failed` or
  `cancelled` status) — not "still processing."
- **Инциденты (Incidents)** — two counters, computed the same way as the
  existing payments triage screen (`admin.triage_payments`), so the numbers
  agree between the two:
  - **Висящие платежи (stuck pending)** — payments still `pending` after 30
    minutes. A non-zero count here, especially rising, is a signal the
    provider may be having trouble and is worth investigating before (or
    right after) you disable it.
  - **Сбои webhook (failed webhooks)** — webhook deliveries that failed
    signature verification or were never marked processed. A spike here
    often precedes a stuck-pending spike and is an early warning sign.
- **Последние платежи (Recent payments)** — the last 20 payments through
  this provider's slug(s), newest first, with status/amount/currency/time.
  No PII (email, phone, Telegram id) is shown, per `AGENTS.md` §9 — only
  payment id, order id, status, amount, currency, timestamp.

Use the window switcher (Сегодня / 7 дней / 30 дней) to distinguish a
short-lived blip from a sustained problem before deciding whether to
disable, mark maintenance, or leave the provider alone.

## FX drop tripwire (automatic maintenance)

Every 5 minutes (and on admin «Обновить курс FX») the scheduler compares the
new market rate to the last `fx_rates` row for UZS and RUB. If either
**falls** more than 6%:

1. Every **active** provider — including **Кошелёк** — is set to
   `maintenance`. Already-`disabled` rows are left alone.
2. After that commit, the ops Telegram group gets an alert (`kind=fx_drop`).
   The alert is not sent if the transaction rolls back.

**Recovery:** look at Курсы, then on **Провайдеры оплаты** click **Включить**
on each row you want back. The tripwire will not turn them back on by
itself. If the market is still >6% below the last stored tick, the next
refresh will put the ones you just enabled back into maintenance and page
again — wait until the rate is stable.

Wallet (оплата с баланса) is the same three buttons as Click. `disabled`
hides it from the miniapp; `maintenance` greys it out with «Технические
работы».

## Related

- [ADR-0041](../decisions/0041-admin-payment-provider-controls.md) — full
  design rationale, including why webhook/callback settlement never checks
  provider state.
- `docs/runbooks/payment-provider-outage.md` — broader outage triage
  (provider status pages, dashboards, alerts); use this runbook for the
  actual disable/maintenance/enable mechanics once you've decided to act.
- `docs/runbooks/click-troubleshooting.md`, `payme-troubleshooting.md`,
  `uzum-troubleshooting.md`, `octo-troubleshooting.md` — per-provider
  incident diagnosis.
- `docs/architecture/module-map.md` — `payments` module row.
