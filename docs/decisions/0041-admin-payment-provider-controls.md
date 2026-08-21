# 0041. Admin-controlled payment-provider state (disable / maintenance)

- **Status**: Accepted
- **Date**: 2026-08-04
- **Deciders**: @jamaomonov
- **Tags**: backend | frontend | payments | admin

## Context and problem statement

Every acquirer YuPay has live today (Click, Payme, Uzum, Octo) can go down,
get rate-limited, or need a temporary pause for reasons that have nothing to
do with our own deploys — a supplier maintenance window,
a spike in failed webhooks, a merchant-account issue discovered via the
`admin.triage_payments` screen. Today the only lever an operator has is
removing the provider's API keys from `secrets/api.env` and redeploying,
which:

- takes a full deploy cycle (minutes, not seconds) for what is often a
  10-minute outage;
- is all-or-nothing per key, not a first-class "we chose to pause this" state
  distinguishable from "this was never configured";
- gives no visibility into _why_ an operator paused a provider, _when_, or
  _by whom_;
- offers no analytics scoped to "how is this specific provider doing right
  now" to decide whether pausing is even warranted.

Click additionally complicates any such control because it is **one merchant
relationship exposed as two `PaymentGateway` provider ids** — `click` (web,
service `108149`) and `click_miniapp` (bot, service `108150`) — per
`docs/decisions/0036-click-shop-api.md`. An operator thinking "pause Click"
should not have to remember to flip two switches.

Finally, and most importantly: whatever mechanism we build must never strand
a customer who has already started paying. A payment intent created five
seconds before an operator hits "disable" is already in flight at the
acquirer — the customer may be mid-redirect to Click's hosted page, or Payme
may be about to call our `PerformTransaction` endpoint. If "disable" also
blocked the webhook/callback that settles that payment, the customer's money
would be taken but the order would never move past `pending_payment` — a
money-safety incident, not a graceful pause.

## Decision drivers

- Operators need a same-second lever, not a redeploy, to pause a
  misbehaving/down provider (see the existing `admin.triage_payments`
  incident triage, which this feature sits next to).
- **Money safety is non-negotiable**: no in-flight, already-paid transaction
  may be stranded because an admin toggled a provider off after the customer
  paid.
- Click's one-merchant-two-slugs shape must be invisible to the operator —
  one control, one click.
- The control must compose with the existing config-availability check
  (`PaymentGateway.available`, i.e. "do we even have API keys for this
  provider") rather than replace or duplicate it.
- Auditability: who changed a provider's state and when, visible on the same
  screen as the control itself.
- Minimal blast radius: additive to `payments`, no change to the payment FSM,
  the webhook contract, or any acquirer integration module (`click`, `payme`,
  `uzum`).

## Considered options

1. **DB-backed three-state model (`active`/`disabled`/`maintenance`) consulted
   only by `create_intent`** — a new `payment_provider_states` table, one row
   per gateway slug, read at intent-creation time; webhook/callback paths
   never consult it.
2. **Config/env-only flag** — repurpose the existing "is this provider
   configured" check (env vars present/absent) as the only lever; no DB
   table, no per-state distinction.
3. **A hard block that also rejects webhooks/callbacks while disabled** —
   same DB table as Option 1, but webhook/callback handlers additionally
   check provider state and reject or no-op when disabled.

## Decision outcome

**Chosen option: 1.** A new `payment_provider_states` table (migration
`0037_payment_provider_states`) stores one row per **gateway slug** —
`provider` (primary key, e.g. `click`, `click_miniapp`, `payme`, `uzum`,
`octo`, `crypto`), `state` (`active` | `disabled` | `maintenance`, DB
`CHECK` constraint), `changed_by`, `changed_at`. **Absence of a row means
`active`** — nothing is seeded on migrate; a provider only gets a row once an
operator changes it away from the default, so the common case (every provider
active) costs zero rows.

`apps/api/src/yupay/modules/payments/provider_state.py` is the single source
of truth, consumed by three call sites:

- `payments.service.create_intent` → `_ensure_provider_accepting_intents`:
  raises `ConflictError` (`reason="provider_disabled"` or
  `"provider_maintenance"`) for a **new** intent when the provider's state is
  not `active`. An existing pending intent for the same order is still
  returned/replayed via the idempotency-key path, which runs _before_ the
  state check — a customer who already has a payment page open is unaffected.
- `GET /payments/providers` (customer-facing): returns
  `[{slug, status}]` where `status` is `active` | `maintenance`; a `disabled`
  or config-unavailable slug is **omitted entirely**, so the storefront never
  even sees it as an option, versus `maintenance` which is returned so the
  storefront can render it as a visible-but-locked method.
- The admin CRUD/analytics endpoints under `/admin/payments/providers`
  (`GET` list, `GET /{provider}?window=`, `PUT /{provider}/state`) — the
  operator-facing read/write surface.

### The in-flight safety invariant

**Enforcement is scoped exclusively to the intent-creation path.** The
webhook/callback settlement functions —
`payments.service.handle_webhook`, `settle_provider_payment`,
`reverse_provider_payment`, `cancel_pending_provider_payment`, and by
extension Payme's `PerformTransaction`/`CancelTransaction` RPC methods and
Uzum's `/confirm`/`/reverse` endpoints and Click's `/complete` endpoint —
**never call into `provider_state` at all.** This is enforced by omission
(those functions simply have no state check), and is documented at the
source: `provider_state.py`'s module docstring says webhook paths
"deliberately do NOT consult this — in-flight payments must settle
regardless of admin state," and `_ensure_provider_accepting_intents`'s
docstring lists every settlement function it must never be called from.

The reasoning: disabling a provider is an operator's statement about
**tomorrow's** traffic ("stop sending customers here"), not a statement about
money the acquirer has already collected on our behalf. A payment created
while the provider was `active` has real money moving at the acquirer
regardless of what an admin does five minutes later in our own database — the
acquirer does not know or care about our `payment_provider_states` row, and
will call our webhook/RPC endpoint to settle that transaction whether or not
we've since flagged the provider `disabled`. If we refused to process that
webhook, the money would be taken from the customer but the order would
never leave `pending_payment` — worse than doing nothing, because now support
has to manually reconcile a paid-but-stuck order. Letting it settle and
simply not _offering_ the provider to the _next_ customer is strictly safer
and requires no reconciliation step.

### Click: one control, two slugs

`LOGICAL_PROVIDERS` in `provider_state.py` maps an operator-facing "logical
provider" to the gateway slug(s) it owns:

```python
LOGICAL_PROVIDERS = {
    "click": LogicalProvider("Click", ["click", "click_miniapp"]),
    "payme": LogicalProvider("Payme", ["payme"]),
    "uzum": LogicalProvider("Uzum", ["uzum"]),
    "octo": LogicalProvider("Octo", ["octo"]),
    "crypto": LogicalProvider("USDT (crypto)", ["crypto"]),
}
```

`crypto` is listed even though its gateway (`REGISTRY["crypto"]`) is still a
`StubGateway` — always `available=False`, no real intent/webhook path yet —
so the admin screen will show it with "Нет конфига" and any state change on
it has no customer-visible effect today. It's included so the admin surface
needs no follow-up change on the day the crypto acquirer actually ships.

The admin API and admin SPA operate exclusively on the logical key.
`set_logical_state` writes every slug in the group in one transaction (one
upsert per slug, same `state`/`changed_by`/`changed_at`), so "disable Click"
atomically disables both the web and the Mini App surfaces — there is no way
to leave them in different states through the admin screen, and the read
path (`list_admin_providers`) reports one row per logical provider using the
first slug's state as canonical (the write path guarantees they're always
equal).

### State layered on config-availability

Provider state is **not** a replacement for the existing "are the API keys
even configured" check (`PaymentGateway.available`, driven by env vars). The
two compose: `provider_state.customer_status(slug, state)` returns `None`
(hide) when `REGISTRY.get(slug)` is `None`/unavailable **or** when `state ==
"disabled"` — either condition alone is enough to hide the provider from
customers. This means an operator can never accidentally make an
unconfigured provider look "active" by touching only the state table, and a
fully-configured provider still requires an explicit `active` state (the
default) to be offered. The admin summary additionally surfaces
`config_available` as its own column so an operator can distinguish "we
turned this off" from "this was never wired up" at a glance.

### Positive consequences

- Same-second provider pause/resume with no deploy, directly from
  `/payments/providers` in the admin SPA or via the raw `PUT` endpoint.
- Zero risk of stranding an already-paying customer — the money-safety
  invariant is structural (the settlement code paths have no state check to
  bypass), not a runtime toggle that could be misconfigured.
- Click's two-slug shape is fully hidden from the operator; there is no admin
  action that can put `click` and `click_miniapp` in different states.
- Full audit trail (`changed_by`, `changed_at`) and per-provider analytics
  (volume, success rate, incidents mirroring `admin.triage_payments`) live on
  the same screen as the control, so a decision to disable is informed and
  traceable.
- Additive: no change to `PaymentGateway`, the payment FSM, or any acquirer
  adapter (`click`, `payme`, `uzum`). Rollback is "drop the table + the three
  new modules + the routes," nothing else moves.

### Negative consequences

- One more state to reason about when debugging "why didn't this provider
  show up for a customer" — mitigated by `config_available` being surfaced
  alongside `state` on the same admin row, so the two causes are never
  conflated.
- `maintenance` and `disabled` are visually similar operator actions
  (adjacent buttons) with different customer-facing effects (shown-but-locked
  vs. hidden); an operator picking the wrong one is a UX risk, not a
  money-safety one — mitigated by a confirmation prompt on `disabled` only
  (`window.confirm` in `ProviderDetailDrawer.tsx`) and by both states being
  trivially reversible with the "Включить" (enable) button.
- The `payment_provider_states` table is unseeded, so a brand-new environment
  with zero rows is indistinguishable from "everyone explicitly reviewed and
  confirmed active" — acceptable because the semantics are identical
  either way (no row = `active`).

## Validation

Integration tests cover the full surface: `apps/api/tests/integration/test_payment_provider_state_model.py`
(the table round-trips and the `CHECK` constraint rejects an invalid state),
`apps/api/tests/integration/test_provider_state_service.py` (logical↔slug
mapping, default-active with no row, `state_status`/`customer_status`
composition with config-availability), `apps/api/tests/integration/test_provider_state_enforcement.py`
— most importantly `test_disabled_after_intent_created_still_settles_via_webhook`,
which is the direct regression test for this ADR's money-safety invariant: a
`create_intent` call is rejected once the provider is `disabled`/`maintenance`
(`test_create_intent_rejected_when_not_active`), but a payment created while
still `active` continues to settle via webhook after the provider is disabled.
`apps/api/tests/integration/test_admin_providers.py` and
`test_admin_provider_detail.py` cover the admin list/detail/analytics shapes
(`stuck_pending`/`failed_webhooks` parity with `admin.triage_payments`) and
the idempotent replay of `PUT .../state` (a repeated `Idempotency-Key` returns
the cached result rather than re-applying). Frontend coverage: `apps/web/src/lib/payment-providers.test.ts`
and `apps/web/src/components/store/PurchasePanel.test.tsx` (hidden vs.
maintenance rendering, fail-open when the status fetch hasn't resolved),
`apps/miniapp/src/lib/orders.test.ts`, and
`apps/admin/src/features/payments/providers/ProvidersPage.test.tsx`. Ongoing
validation: the admin screen's incident counters should track down whenever
an operator disables a struggling provider, and the `payments` module's
coverage gate (≥ 95%, per `AGENTS.md` §8) keeps the new modules
(`provider_state`, `provider_analytics`, `provider_admin`) held to the same
bar as the rest of the payments surface.

## Amendment: the locked state is an overlay, not a third line (2026-08-21)

### Context

Both storefronts rendered `maintenance` as an extra line of text stacked under
the provider name inside the method tile. The tiles sit in an equal-width grid,
so the one line of copy ("Технические работы" — two lines once it wrapped in the
web's ~110 px tile) made that tile taller than its neighbours and the whole row
went ragged. The state that is supposed to read as "nothing to do here" was the
most visually prominent thing in the block.

### Decision

The status is drawn out of the tile's flow: a strip pinned to the tile's top
edge (`absolute inset-x-0 top-0`, clipped by the tile's own `overflow-hidden`),
carrying a short label — new `web.store.paymentMaintenanceShort` /
`payment.maintenanceShort` keys ("Тех. работы") — while the full copy stays as
the `title` tooltip. The tile geometry is therefore identical in every state.
Only the mark and the name dim (`opacity-60 grayscale`), never the strip, so the
label keeps full contrast against a mark that now reads as inactive on sight.
The Mini App's separate "Скоро" corner pill (a method unavailable because of the
selected currency rather than an operator action) folds into the same strip, so
"unavailable" looks like one thing with two reasons.

For a11y the tile's accessible name stays the bare provider name; the strip is
referenced with `aria-describedby` (web) so a screen reader gets the reason
after the name instead of a name that changes when an acquirer goes down.
`WalletTopUp`'s provider list is untouched — there the status replaces the
row's subtitle, which never changed the row's height.

### Consequences

- Positive: the method row keeps its rhythm whatever the acquirers are doing,
  and the locked tile reads as locked before the label is even read.
- Negative: two copies per locale for one state (short for the strip, full for
  the tooltip/SR). Accepted — a tile that narrow cannot hold the full phrase
  without wrapping, which is the bug being fixed.

## Alternatives considered (detail)

### Option 2 — config/env-only flag

Simplest possible change (zero new table, reuse `PaymentGateway.available`
as the only signal), but rejected on every decision driver: flipping an env
var requires a redeploy (minutes, not seconds — defeats the "same-second
pause" goal entirely), gives no distinction between "never configured" and
"operator paused it," carries no `changed_by`/`changed_at` audit trail, and
provides no natural home for the per-provider analytics an operator needs to
_decide_ whether to pause something. It would also conflate "no keys" and
"keys present but paused" into the same boolean, which is precisely the
ambiguity `config_available` (Option 1) was designed to resolve.

### Option 3 — hard block including webhooks/callbacks

Same DB table and API surface as Option 1, but with the webhook/callback
handlers also checking provider state and rejecting (or silently dropping)
a settlement call while `disabled`. This was rejected as a direct violation
of the money-safety driver: an acquirer that already collected money from a
customer will still call our webhook/RPC endpoint regardless of our internal
state, and refusing to process it does not undo the charge — it only
prevents our own order from ever reflecting that the customer paid. The
customer would see a stuck `pending_payment` order, support would need to
manually cross-reference the acquirer's dashboard against our stuck payment,
and the fix would ultimately be a one-off DB repair identical in shape to
just... letting the webhook settle normally. There is no scenario where
blocking settlement is safer than allowing it; it only ever converts a clean
automatic settlement into a manual incident. Also rejected because it
would require every acquirer integration with a real settlement path
(`click`, `payme`, `uzum`, `octo`) to add a new state check to code that
already has a separate, provider-owned state machine (Payme's own
`1`/`2`/`-1`/`-2`, Uzum's
`CREATED`/`CONFIRMED`/`REVERSED`/`FAILED`, Click's
`PREPARED`/`CONFIRMED`/`CANCELLED` — see ADR-0034/0035/0036) — a second
state machine reaching into a first one, exactly the kind of coupling those
ADRs were careful to avoid ("never a second FSM path").

## References

- `apps/api/src/yupay/modules/payments/provider_state.py` — logical↔slug map,
  state read/write, customer-status resolver (module docstring states the
  webhook-exclusion invariant directly).
- `apps/api/src/yupay/modules/payments/provider_admin.py` — admin
  list/set-state service functions.
- `apps/api/src/yupay/modules/payments/provider_analytics.py` — per-provider
  volume/success-rate/incidents, mirroring `admin.service.triage_payments`.
- `apps/api/src/yupay/modules/payments/service.py` —
  `_ensure_provider_accepting_intents`, called only from `create_intent`.
- `apps/api/migrations/versions/0037_payment_provider_states.py`.
- `apps/admin/src/features/payments/providers/` — `ProvidersPage.tsx`,
  `ProviderDetailDrawer.tsx`, `ProviderAnalyticsBlocks.tsx`, `types.ts`.
- `apps/web/src/lib/payment-providers.ts`,
  `apps/miniapp/src/pages/TopUp.tsx` / `WalletTopUp.tsx` — storefront
  hidden/maintenance rendering (`methodVisibility`).
- `docs/runbooks/payment-provider-controls.md` — operator runbook for this
  feature.
- `docs/architecture/module-map.md` — `payments` row, admin-controlled
  provider state note.
- [ADR-0034](./0034-payme-merchant-api.md), [ADR-0035](./0035-uzum-merchant-api.md),
  [ADR-0036](./0036-click-shop-api.md) — the per-acquirer state machines that
  Option 3 would have coupled a second state machine into.
