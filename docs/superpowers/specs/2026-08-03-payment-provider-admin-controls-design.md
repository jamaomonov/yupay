# Design — Admin controls for payment providers

**Date:** 2026-08-03
**Status:** Approved (brainstorm), pending implementation plan
**Scope:** Backend (payments) + Admin SPA + Web storefront + Telegram Mini App

## Problem

Payment-provider availability today is **static**: `available_providers()` returns
the registry slugs whose gateway reports `available` (a config-derived property —
"are the keys set"). There is no way for an operator to take a provider offline
(e.g. Payme is having an outage) without a code/config change and redeploy, and
no per-provider visibility (volume, success rate, incidents) in the admin.

We want operators to, from the admin SPA:

1. See every real acquirer we have, with data + analytics on click.
2. **Disable** a provider — fully off: no new operations, hidden from the web /
   miniapp payment methods.
3. Put a provider in **Maintenance ("тех. работы")** — no new operations, but the
   method still shows on the frontend, non-clickable, with an "under maintenance"
   note.

## Decisions (from brainstorming)

- **Analytics per provider:** all four — (a) volume by currency + payment count,
  (b) success rate (successful / failed / pending + %), (c) tech state / config,
  (d) recent payments + stuck-incident counter.
- **In-flight safety:** disable/maintenance block **only new intents**
  (`create_intent`). Webhooks/callbacks for already-started payments keep
  processing — otherwise a customer who already paid would have an order that
  never settles (lost money).
- **Provider scope:** real acquirers only — Click (`click` + `click_miniapp`),
  Payme (`payme`), Uzum (`uzum`), Octo (`octo`), crypto/USDT (`crypto`). Not
  `wallet`, `mock`, or un-integrated RU stubs (`yookassa`, `tinkoff`).
- **Click grouping:** one logical "Click" control drives **both** slugs
  (`click` + `click_miniapp`) together.
- **State model:** three mutually-exclusive states `active | disabled |
maintenance`. Default (no row) = `active`.

## Architecture

### Data model

New table `payment_provider_states`, **one row per manageable slug**:

| column       | type                  | notes                                                                          |
| ------------ | --------------------- | ------------------------------------------------------------------------------ |
| `provider`   | `String(32)` PK       | the gateway slug (`click`, `click_miniapp`, `payme`, `uzum`, `octo`, `crypto`) |
| `state`      | `String(16)`          | `active` \| `disabled` \| `maintenance`                                        |
| `changed_by` | `UUID` (user id) null | who last changed it (null = never touched)                                     |
| `changed_at` | `timestamptz` null    | when                                                                           |

Absence of a row means `active` — the migration seeds nothing; a provider only
gets a row once an operator changes its state.

**Logical grouping** lives in code (not the DB), a static map in the payments
module:

```python
LOGICAL_PROVIDERS: dict[str, list[str]] = {
    "click":  ["click", "click_miniapp"],
    "payme":  ["payme"],
    "uzum":   ["uzum"],
    "octo":   ["octo"],
    "crypto": ["crypto"],
}
```

Admin actions address a **logical** key; the service expands it to slugs for DB
writes. Enforcement and the customer endpoint read **per slug** — no grouping
logic on the hot path.

### State is a separate dimension from config-availability

Admin state layers on top of the existing `gateway.available` (keys present):

| config `available` | admin `state` | customer sees                          | new intent |
| ------------------ | ------------- | -------------------------------------- | ---------- |
| false              | (any)         | not shown                              | rejected   |
| true               | `active`      | shown, clickable                       | allowed    |
| true               | `maintenance` | shown, **non-clickable**, "тех работы" | rejected   |
| true               | `disabled`    | **not shown**                          | rejected   |

Effective "shown to customer" = `gateway.available AND state != disabled`.
Effective status = `maintenance` if `state == maintenance` else `active`.

### Backend enforcement — two points, webhooks untouched

1. **`create_intent`** (`payments/service.py`): after the existing
   `gw.available` check, load the slug's state; reject with a clear error when
   `state in {disabled, maintenance}`. Blocks **new** intents only.
2. **`GET /payments/providers`**: response shape changes from
   `{"providers": ["click", ...]}` to
   `{"providers": [{"slug": "click", "status": "active"}, {"slug": "payme", "status": "maintenance"}, ...]}`.
   `disabled` slugs are omitted; `active`/`maintenance` are returned with status.
3. **Webhooks / provider callbacks** (`api/webhooks/*`, `modules/{click,payme,uzum}`):
   **no change** — in-flight payments settle regardless of admin state.

### Admin API (under `require_admin`, mounted in the admin router)

- `GET /admin/payments/providers` — list of **logical** providers:
  `{provider, display_name, slugs, config_available, state, changed_by, changed_at, quick_counts}`.
  Light query; `quick_counts` = payments today + stuck count.
- `GET /admin/payments/providers/{provider}` — detail + analytics for a window
  (`window` query: `today | 7d | 30d`, default `7d`):
  - **volume**: `sum(amount)` grouped by currency (successful payments) + total count;
  - **success_rate**: counts by bucket `succeeded | failed | pending` + success %;
  - **tech/config**: slugs, currency, `config_available` per slug, current `state`, `changed_by/at`;
  - **recent**: last N (e.g. 20) payments (id, order_id, status, amount, currency, created_at) — no PII;
  - **incidents**: stuck-pending + failed-webhook counts (reuse `admin.triage` logic scoped to this provider's slugs).
- `PUT /admin/payments/providers/{provider}/state` — body `{state}`, requires
  `Idempotency-Key`. Writes every slug in the logical group, stamps
  `changed_by/changed_at`, records an audit entry. Rejects unknown provider /
  invalid state.

Analytics queries run against `payments` (has `provider`, `status`, `amount`,
`currency`, `created_at`, `succeeded_at`, `failed_at`) filtered by the group's
slug set; incidents also use `payment_webhooks`.

### Frontend (web + miniapp)

Both surfaces already filter methods through `GET /payments/providers`
(`useAvailableProviders` / equivalent). Changes:

- Update the fetch + hook to the new `[{slug, status}]` shape.
- `disabled` slug → absent from the response → method not rendered (already the
  behaviour once omitted).
- `maintenance` slug → render the method card but **non-clickable / disabled**,
  with a localized "Технические работы" badge/label; selecting it is a no-op.
- New i18n key (`payment.maintenance` or similar) in **ru / en / uz**.

Touch points: web `PurchasePanel.tsx`; miniapp `TopUp` + `WalletTopUp` (via
`payment-methods.ts` / `useAvailableProviders`).

## Components & boundaries

- `payments/provider_state.py` (or within `service.py`): DB read/write for slug
  state + the `LOGICAL_PROVIDERS` map + effective-status resolver. Single source
  of truth consumed by `create_intent`, the customer endpoint, and the admin
  service.
- `admin/service.py` + `admin/routes.py`: the three admin endpoints + analytics
  aggregation (or a small `payments/provider_analytics.py` helper if it grows).
- Customer endpoint stays in `payments/routes.py`.
- Frontend: hook/lib update + maintenance rendering in the two panels.

## Error handling

- `create_intent` against a disabled/maintenance provider → the **same domain
  error class `create_intent` already raises** for an unavailable provider
  (currently a "payment provider not available" error), extended with a
  machine-readable `reason` (`provider_disabled` / `provider_maintenance`) in its
  `extra` so the frontend can message it. Keeping one error path avoids a new
  status code the client must learn. The frontend primarily prevents the call
  anyway (disabled not offered, maintenance non-clickable).
- `PUT state` with unknown logical provider → `404`; invalid state → `422`.
- Analytics endpoint tolerant of providers with zero payments (empty volume /
  0-count, not an error).

## Testing

- **Python (payments ≥ 95% gate):**
  - `create_intent` rejects `disabled` and `maintenance`, allows `active`.
  - A webhook/callback for an in-flight payment still settles when the provider
    is `disabled` (money-safety regression test).
  - `GET /payments/providers` shape: omits disabled, flags maintenance.
  - Admin `set state` writes all slugs of a group (Click → both), stamps
    `changed_by/at`, writes an audit entry; idempotent under repeat.
  - Analytics: volume by currency, success-rate buckets, recent list, incident
    counts — including the zero-payments case.
- **TS:** `useAvailableProviders` parses the new shape; a `maintenance` method
  renders non-clickable with the badge; a `disabled` method is absent.

## Docs

- Alembic migration for `payment_provider_states`.
- New ADR: admin-controlled provider state — the `active/disabled/maintenance`
  model, the "webhooks always pass (in-flight safety)" invariant, and the
  Click-grouping decision.
- New runbook: how to disable / put a provider into maintenance and back.
- Regenerate `docs/api/openapi.json` + `packages/api-client` (new admin
  endpoints + changed `/payments/providers` shape).
- Update `docs/architecture/module-map.md` if the payments module's public
  surface note needs it.

## Out of scope (YAGNI)

- Custom per-provider maintenance message (generic localized string only).
- Scheduled / auto-expiring maintenance windows.
- Per-surface Click control (one button = both slugs).
- Managing `wallet` / `mock` / un-integrated RU stubs.
