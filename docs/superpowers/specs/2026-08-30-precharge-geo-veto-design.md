# Pre-charge geo veto and timed auto-refund

**Date:** 2026-08-30
**Status:** Accepted, not implemented
**Scope:** Country capture on order evidence (+migration 0060) · a pre-charge veto in the three acquirer check/prepare stages · an early refusal at order creation with a human-readable message · a scheduler job that auto-refunds held orders after a deadline · settings + runbook/ADR updates
**Touches:** `evidence` (new column), `orders` (risk module + create route), `payme`/`click`/`uzum` services (one call each), `payments` (refund reuse), `apps/scheduler` (new job), `core.config`
**Builds on:** ADR-0062 (identity windows) and the spec `2026-08-30-antifraud-velocity-design.md`

## Problem

The identity-window rules stop the _goods_, not the _charge_. A stolen card
is still debited; the hold only parks the order for review. The cardholder —
the actual victim — sees `YUPAY` on their statement with nothing to show for
it, and every such line item is a complaint, a chargeback, or worse aimed at
the merchant. Two gaps produce it:

1. **Nothing refuses a charge before it happens**, even when the order is
   fraudulent beyond reasonable doubt at creation time. Yet all three
   acquirers give us a pre-charge stage that exists for exactly this: Payme
   `CheckPerformTransaction`, Click `Prepare`, Uzum `Check` all ask the
   merchant "may this be paid?" before money moves, and our services already
   answer "no" there for non-payable orders (`payme/service.py:117`
   `_check_perform`, `click/service.py:217` `prepare`,
   `uzum/service.py:249` `check`).
2. **A held order keeps the victim's money indefinitely.** The hold waits
   for an operator with no deadline; until someone acts, the merchant is
   holding stolen funds — which is precisely the position that turns a
   fraud victim's complaint into the merchant's problem.

Measured grounding (production, delivered orders, 14 days): all 15 Roblox
orders from foreign browser timezones were the carding run; 11 orders with
`Europe/Moscow` look at least partly legitimate (Uzbek diaspora paying with
Uzbek instruments) and are spread across brands. Any geo rule must refuse
the former without amputating the latter.

## Design

### 1. Country capture — `order_evidence.ip_country`

All production traffic transits Cloudflare, which stamps `CF-IPCountry`
(ISO-3166-1 alpha-2) on every proxied request once the free **IP
Geolocation** toggle is on. The edge Caddy passes request headers upstream
untouched (it overrides only `X-Forwarded-For`), so the header reaches the
app with no proxy change.

- New column `order_evidence.ip_country VARCHAR(2) NULL` (migration 0060,
  additive; no backfill — historic rows keep `NULL` and every consumer
  treats `NULL` as "unknown").
- `evidence.capture_for_order` reads `request.headers.get("cf-ipcountry")`,
  uppercases, and stores it only when it is two ASCII letters. Cloudflare's
  sentinels `XX` (unknown) and `T1` (Tor) are stored as-is — `T1`
  is a signal in its own right, and neither is in any home list.
- The evidence admin pack (`OrderEvidenceOut`) gains `ip_country`; it is a
  country code, not an address — no PII change.

Timezone (already captured in `client_hints`) remains the **fallback and
cross-check**, not the primary: it is a browser self-report, spoofable with
one OS setting, and it survives as a signal only until it becomes a reason
for refusal. The country comes from the network path and costs the attacker
a scarce Uzbek proxy instead.

### 2. The veto decision — one function, three enforcement points

A new pure-ish helper in `orders/risk.py`:

```python
async def precharge_veto(db: AsyncSession, order: Order, *, settings: Settings | None = None) -> str | None
```

Returns a reason string (`VETO_FOREIGN_COUNTRY` / `VETO_FOREIGN_TIMEZONE`)
or `None`. Logic, in order:

1. `purpose != "catalog"` → `None` (wallet top-ups are reversible; the
   post-payment gate already skips them).
2. Kill switch `risk_precharge_veto` off → `None`.
3. **Trusted-buyer exemption:** the order's `user_id` is set AND that user
   has ≥ 1 prior `delivered` order → `None`. The diaspora customer with a
   history sails through; the window rules still hold their orders
   post-payment if something else is off. A _fresh_ account is treated as a
   guest — registration takes a carder thirty seconds, so an account with
   zero delivered orders earns nothing.
4. Evidence row loaded (by `order_id`). Then:
   - `ip_country` present and not in `risk_home_countries` →
     `VETO_FOREIGN_COUNTRY`.
   - `ip_country` absent (header missing / pre-toggle orders) and the
     evidence timezone is present and not in `risk_home_timezones` →
     `VETO_FOREIGN_TIMEZONE`.
   - Otherwise `None`. **No evidence row, no claim** — the veto never fires
     blind, and a capture failure degrades to "charge allowed, post-payment
     rules apply", consistent with the gate's never-block-blind philosophy.
5. The whole body wrapped like `_gather`: any exception (inside a
   savepoint) logs and returns `None`. A broken veto must fail open — the
   post-payment hold is the net beneath it.

Deliberately **brand-agnostic**, unlike the post-payment geo _hold_ (which
stays liquid-brands-only): a veto scoped to Roblox would just move the
carding to the next brand, and the trusted-buyer exemption already protects
the honest foreign segment. The two rules coexist: veto refuses
guests/fresh accounts abroad before the charge; the hold still catches a
trusted-buyer-turned-mule and the country-spoofed leftovers after it.

**Enforcement point A — the three acquirer pre-charge stages.** Each
service calls `precharge_veto` where it already validates payability and
maps a veto to its protocol's own "order not payable" answer:

- Payme: alongside the `_check_perform` calls (`service.py:235,277`) →
  error `-31051`. The transaction is never created; nothing is charged.
- Click: inside `prepare(db, ...)` before allocating the transaction row →
  the Click error code already used for unpayable orders.
- Uzum: inside `check(db, ...)` → its equivalent refusal.

Each records one `order_events` row (`kind="order.precharge_vetoed"`,
payload: reason + country/timezone value — a country code is not PII) the
FIRST time only (idempotent per order), so repeated acquirer retries do not
spam the timeline, and ops can see refusals happening without an alert per
attempt. A daily count in the existing alert digest is enough; a per-veto
Telegram ping would be noise.

**Enforcement point B — order creation, with words.** The acquirer's own
decline screen is generic and unbrandable; an honest buyer refused there
just sees a broken shop. So the same _decision_ runs in
`orders/routes.py`'s create flow — but fed from the live request (the
`cf-ipcountry` header and the submitted client hints) plus the same
trusted-buyer query, NOT from a stored evidence row: refusing creation
rolls the request transaction back, so there is no row to read, and the
request itself is the fresher source anyway. The decision core is split
pure (`_veto_decision(is_trusted, country, timezone, cfg)`) so points A
and B share it verbatim and diverge only in where the inputs come from.
When it fires, the API returns **422** with a new error code
`payment_unavailable_abroad` and a message the storefront and Mini App
render verbatim near the pay button:

> «Оплата из-за границы доступна после входа в аккаунт с историей заказов.
> Напишите в поддержку, если это ошибка.»

plus the support link. New i18n keys in all three locales. The order is
NOT created (nothing to pay for beats a pre-made order that can never be
paid). Point A stays as the backstop for orders created before the rule,
race conditions, and spoofed-then-changed context.

### 3. Timed auto-refund of held orders

New scheduler job `apps/scheduler/.../jobs/held_order_refund.py`
(pattern: `click_timeout.py`), every 15 minutes:

- Select orders with `status = "paid"`, `purpose = "catalog"`, and a
  `order.held_for_review` event older than `risk_hold_auto_refund_hours`
  (default **24**, `0` disables), that have no later fulfilment start —
  i.e. still parked.
- For each: full refund through the existing
  `payments.service.refund_admin` (`actor`/`admin_id` = the system actor
  the codebase already uses for jobs; `reason="auto_refund_hold_expired"`;
  idempotency key derived from order id so the job surviving a crash cannot
  double-refund), then an `order_events` row and ONE admin alert naming the
  order and the deadline that expired.
- Batch-limited per tick; any single failure logs and moves on (an acquirer
  refund API being down must not wedge the sweep — the next tick retries by
  construction).

Consequences to state honestly: an operator who wanted to _release_ a held
order now has a deadline. The alert text for every hold already tells them
so («выдай или верни»); the runbook gains the deadline explicitly, and the
kill switch (`RISK_HOLD_AUTO_REFUND_HOURS=0`) exists for a fire-drill week.
`REASON_PAID_AFTER_EXPIRY` holds are included — same logic: if no human
decided within a day, returning the money is the safe default for both
fraud and confusion.

### 4. Settings

| Setting                       | Default | Off                                 |
| ----------------------------- | ------- | ----------------------------------- |
| `risk_precharge_veto`         | `true`  | `false`                             |
| `risk_home_countries`         | `"UZ"`  | empty = veto never fires on country |
| `risk_hold_auto_refund_hours` | `24`    | `0`                                 |

(`risk_home_timezones` is reused from ADR-0062.) `risk_home_countries` is
CSV like its siblings — the RU launch becomes `RISK_HOME_COUNTRIES=UZ,RU`
in an env file, not a deploy.

## Privacy & money rules

- A country code and a timezone are not PII; the IP they derive from never
  leaves `order_evidence`. Event payloads carry the code, never the
  address.
- The veto refuses **before** any money moves; the auto-refund only ever
  runs the existing admin refund path with its idempotency; no new money
  primitives.
- Webhook signature checks, raw-body middleware, idempotency: untouched.

## Testing

- Unit: veto decision table — every branch (purpose, kill switch, trusted
  buyer, fresh account = guest, country hit, country miss, tz fallback, XX
  and T1, no evidence row, exception → fail-open).
- Integration: Payme CheckPerform / Click Prepare / Uzum Check each refuse a
  vetoed order with their protocol's own error and create no transaction
  row; a trusted buyer's order passes the same stage. One `order_events`
  row across repeated attempts.
- Integration: order creation returns 422 + `payment_unavailable_abroad`
  for a guest with foreign country; creates normally for the trusted buyer.
- Integration: the sweep refunds a held order past the deadline (mock
  gateway), skips a fresh hold and a released order, and is idempotent
  across two ticks.
- The three acquirer suites' existing success paths must stay green with
  UZ-country/UZ-tz fixtures (the fixtures may need the evidence row added —
  that is part of the task, not a test relaxation).

## Rollout

1. Deploy with the veto ON but `CF-IPCountry` not yet flowing → country is
   `NULL` everywhere → the veto works on the timezone fallback only (same
   signal as the proven hold rule). No cliff.
2. Operator flips **IP Geolocation** in the Cloudflare dashboard (one
   toggle, free). Verify with one order that `ip_country` lands. From then
   on the primary signal is the network, not the self-report.
3. Watch the `order.precharge_vetoed` counts and the auto-refund alerts for
   a week; tune `risk_hold_auto_refund_hours` to ops reality.
4. Rollback: each mechanism has its own env switch; migration 0060 is
   additive.

## Open questions (defaults chosen, none blocking)

- **Should Moscow-timezone guests be vetoed pre-charge?** Under this
  design: yes (tz fallback, foreign) — but only until CF country flows,
  and only for guests/fresh accounts. The measured Moscow segment that
  matters (repeat buyers) is exempted by history. Revisit with the RU
  launch (`RISK_HOME_COUNTRIES=UZ,RU` and add `Europe/Moscow` etc. to the
  tz list).
- **24h auto-refund vs operator working hours:** a hold landing Friday
  night refunds Saturday night. If ops wants business-hours-only reviews,
  raise the default to 48 — one env var, their call after a week of data.
