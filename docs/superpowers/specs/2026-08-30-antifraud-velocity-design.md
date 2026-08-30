# Antifraud: identity windows on the order risk gate

**Date:** 2026-08-30
**Status:** Accepted, not implemented
**Scope:** Four new rules in `orders/risk.py` + one migration (`order_evidence.device_hash` + two indexes) + settings + tests
**Touches:** `payments.service` (the one call site becomes async-aware), `evidence` (new derived column), `core.config`

## Problem

Carders pay with stolen cards and resell the goods. The existing risk gate
(ADR-0047) holds any single order at or above `manual_review_threshold_usd`
for a human to look at — and it worked, so the attackers adapted: they found
the edge of the threshold and split their volume into many orders priced
under it, aimed at the most liquid goods (Roblox vouchers, Telegram Stars).

Measured on production, last 14 days, delivered orders only:

- One buyer identity placed **10 Roblox orders averaging $18** — $180 through
  a $40 gate that never fired.
- One IP produced **16 orders under 2 buyer identities**, 11 of them
  delivered. Four more IPs produced 8–9 orders each.
- One Telegram username received **Stars from 7 orders across different
  buyer identities** — cards vary, the destination does not.
- Browser timezone separates the fraud almost perfectly on liquid brands:
  **roblox 15 of 19** delivered orders came from non-Uzbek timezones,
  **telegram-stars 11 of 21** — against **free-fire 3 of 108** and
  **mobile-legends 1 of 46**. The legitimate audience is overwhelmingly in
  Asia/Tashkent and Asia/Samarkand; the carders ran under Europe/Kiev and
  similar, and did not bother to fake it.

The per-order threshold cannot see any of this: every signal above is a
property of a _group_ of orders sharing an identity, not of one order.

Chargebacks land weeks later; by then the codes are redeemed and resold.
Prevention has to happen between payment and fulfilment — which is exactly
where the risk gate already sits.

### What exists and is reused as-is

- **`orders/risk.py`** — `review_reason(order)` decides, `hold_for_review`
  records an `order_events` row, pre-arms the stuck-order watchdog and pages
  ops. The order stays `paid`; releasing the hold is the same
  `fulfillment.start_for_order` call that would have run. Its module
  docstring explicitly reserved space for "velocity, repeat cards" rules.
- **`evidence` module (ADR-0044)** — `order_evidence`, one immutable row per
  order: `ip INET`, `user_agent`, `accept_language`, `client_hints` JSONB
  (timezone, locale, screen), `purge_after`. Coverage measured at **93%** of
  orders over 30 days.
- **The interim mitigation** — `MANUAL_REVIEW_THRESHOLD_USD=12` is already
  set on production (2026-08-30) to blunt the attack while this ships. The
  operator decides whether to raise it back afterwards.

### Non-goals

- **Card identity.** The UZ acquirers in use (Click, Payme, Uzum) do not
  reliably hand us a card fingerprint, and Octo — which does send a masked
  PAN — is disabled with no plan to enable it. When a card-carrying acquirer
  goes live, the card mask becomes a fifth identity key in the same
  mechanism; nothing else changes. Not in this iteration.
- **External IP intelligence.** No geo-IP or ASN databases, no third-party
  fraud scoring. The browser-reported timezone already separates the current
  attack, costs nothing and has no licence, update cadence or false-positive
  profile to manage. Revisit only if the attackers start faking timezones —
  which the cross-identity and window rules still catch.
- **Blocking payments.** Same philosophy as ADR-0047: money is already
  taken; the only question is whether a human looks before irreversible
  goods leave. Every rule below holds, none rejects.
- **Machine learning.** Four legible rules with thresholds an operator can
  read, tune and disable beat a score nobody can explain to a customer whose
  order was held.

## Design

### Identity keys

Each order carries up to four identities. Every window rule is evaluated
per key, independently — a carder must randomise _all_ of them at once to
slip through, and randomising the payment card does not randomise any:

| Key      | Source                                                      | Normalisation                                               |
| -------- | ----------------------------------------------------------- | ----------------------------------------------------------- |
| `buyer`  | `orders.user_id`, else `orders.guest_email`                 | email lowercased (CITEXT already does)                      |
| `ip`     | `order_evidence.ip`                                         | as stored                                                   |
| `device` | `order_evidence.device_hash` (new)                          | sha256 of `user_agent \| timezone \| locale \| screen`, hex |
| `target` | `order_items.fulfillment_data` values (e.g. Stars username) | values lowercased, `@` stripped, empty dicts skipped        |

`device_hash` is computed in `evidence.service` when the row is written and
backfilled for existing rows by the migration. Vouchers (Roblox, Discord)
have empty `fulfillment_data`, so they simply have no `target` key — the
other three still apply.

### Rules

Evaluated in order; the first hit wins and its reason is recorded. All
windows look at orders with `paid_at` in the window (an unpaid checkout is
not evidence of anything), excluding the order under review itself from
counts but including it in sums.

1. **`REASON_LARGE_AMOUNT`** _(existing, now jittered — see below)_: this
   order's `total_usd` ≥ effective threshold.
2. **`REASON_ROLLING_SUM`**: Σ `total_usd` over paid orders sharing any
   identity key within 24h ≥ `risk_sum_24h_usd` (default **$25**), or within
   7 days ≥ `risk_sum_7d_usd` (default **$60**). This is the direct counter
   to the split: ten $18 orders are $180 whichever way they are sliced.
3. **`REASON_VELOCITY`**: ≥ `risk_velocity_24h` paid orders (default **5**)
   sharing any identity key within 24h. The honest tail measured on prod is
   a free-fire regular at 12 orders over 14 days — under one a day; five in
   a day is nobody's normal.
4. **`REASON_SHARED_IDENTITY`**: this order's `ip` or `device` was used by
   ≥ `risk_distinct_buyers_7d` distinct `buyer` keys (default **3**) within
   7 days. Catches the 16-orders-one-IP pattern even when every order is
   cheap and slow.
5. **`REASON_GEO_MISMATCH`**: the order is a guest order (`user_id IS
NULL`), **at least one** item belongs to a brand in `risk_liquid_brands`
   (default `roblox, telegram-stars, steam`), and the evidence timezone is present
   but not in `risk_home_timezones` (default `Asia/Tashkent,
Asia/Samarkand`). Signed-in buyers are exempt: an account with history is
   an identity the window rules already cover, and RU/CIS expansion should
   not fight this rule — the operator widens the allowlist by env var, not
   by redeploy. "At least one" rather than "all": requiring the whole
   cart to be liquid would let a carder unlock a Stars order by tossing a
   $0.50 non-liquid SKU into it, and a held mixed cart still costs a
   legitimate buyer only one operator click.

Orders with `purpose = "wallet_topup"` keep bypassing the gate at the call
site exactly as today (the gate guards irreversible goods; a wallet credit
is reversible), and orders with no evidence row are checked by rules 1–3 on
the `buyer` key alone — 7% of orders today, shrinking, and never a reason
to fail open entirely.

### Threshold jitter

The attackers learned $40 by probing. The effective per-order threshold
becomes:

```
effective = manual_review_threshold_usd × (0.6 + 0.4 × u)
u = int.from_bytes(sha256(order.id)[:8]) / 2^64      # [0, 1)
```

Deterministic per order — the same order always gets the same answer, so
retries and tests are stable — but unguessable from outside: probing now
maps out a fuzzy band, not an edge, and the band's floor (0.6 × base) is
what a prober must actually stay under. Applied only to rule 1; the window
rules have no edge worth probing because the prober cannot see their
counters. Jitter is disabled by setting `risk_jitter = false` (tests set
this to pin exact values; the default stays on in every environment).

### Call-site change

`review_reason(order)` is synchronous and takes no session; rules 2–5 need
the database. It becomes:

```python
async def review_reason(db: AsyncSession, order: Order, *, settings: Settings | None = None) -> str | None
```

One call site exists (`payments.service`, payment-success path, already
async). The old sync signature has no other consumers — verified by grep —
so no compatibility shim.

Latency budget: the rules are four indexed queries over a 7-day slice of a
table growing at ~50 rows/day (≤ ~400 rows in the widest window). This adds
single-digit milliseconds to the payment-success path, which is a webhook
handler, not an interactive request.

### Data changes — migration 0059

- `order_evidence.device_hash VARCHAR(64) NULL` + backfill from existing
  `user_agent`/`client_hints` in the same migration (613 rows today —
  trivially in-transaction).
- Index `order_evidence (ip)`, index `order_evidence (device_hash)`.
- `orders (paid_at)` — check first; add only if missing.

No new tables. The `target` key is matched by scanning `order_items` of the
already-selected window orders in Python — a few hundred rows, not worth an
expression index over JSONB.

### Settings (all env-overridable, defaults in code)

| Setting                   | Default                        | Off-switch   |
| ------------------------- | ------------------------------ | ------------ |
| `risk_sum_24h_usd`        | `25`                           | `0` disables |
| `risk_sum_7d_usd`         | `60`                           | `0` disables |
| `risk_velocity_24h`       | `5`                            | `0` disables |
| `risk_distinct_buyers_7d` | `3`                            | `0` disables |
| `risk_liquid_brands`      | `roblox,telegram-stars,steam`  | empty        |
| `risk_home_timezones`     | `Asia/Tashkent,Asia/Samarkand` | empty        |
| `risk_jitter`             | `true`                         | `false`      |

Every rule ships with its own kill switch because a false-positive storm at
3 a.m. must be stoppable by env var and restart, not by revert and deploy.

### Alerts

Each new reason gets its own entry in `HOLD_ALERT_TEXT`, following the
existing pattern (title + what the operator should do), e.g. for
`REASON_ROLLING_SUM`: «🔍 Серия заказов — на проверке» / «Сумма заказов
этого покупателя за окно превысила лимит. Проверь всю серию, не только этот
заказ: выдай или верни деньги по каждому.» The alert for
`REASON_SHARED_IDENTITY` explicitly tells the operator to search the admin
orders list by the shared attribute, since releasing one order of a linked
group without looking at the rest defeats the rule.

### Privacy (§9)

IP and device data already live in `order_evidence` under ADR-0044's
retention. The new code must not copy them anywhere with a longer life:
`order_events` payloads and alert texts carry the _reason and counts_ («3
покупателя с этого IP за 7 дней»), never the raw IP, user agent or target
username. `device_hash` is a derived pseudonym and stays in the evidence
table under the same `purge_after`.

## Testing

TDD, unit-first, one test per rule boundary:

- each rule fires exactly at its threshold and not below (jitter off);
- jitter: effective threshold stays within [0.6, 1.0) × base and is stable
  for a fixed order id;
- identity normalisation: same email in different case, `@user` vs `user`;
- a missing evidence row degrades to buyer-key rules, never to an error and
  never to an unconditional pass of rules 2–3;
- wallet top-ups bypass;
- integration: two paid orders from one IP under two guest emails → third
  order held with `REASON_SHARED_IDENTITY`, released via the existing
  `fulfillment.start_for_order` path;
- integration: the guest + liquid brand + foreign tz combination holds, the
  same order signed-in does not.

`orders` is not in the 95% coverage list (§8) but the module gates money
against goods; target ≥ 95% for `risk.py` anyway.

## Rollout & rollback

1. Ship with defaults; keep `MANUAL_REVIEW_THRESHOLD_USD=12` for the first
   week.
2. Watch the held-order alert volume; tune windows by env.
3. Once the window rules prove out, raising the base threshold back toward
   $40 is an operator decision — rule 2 now covers the ground it guarded.
4. Rollback of any single rule: its env kill switch. Rollback of the whole
   feature: previous image; migration 0059 is additive and safe to leave.

## Open questions (blocking nothing; defaults chosen)

- **Europe/Moscow in the home list?** 11 delivered orders in 14 days carry
  it, and RU is a declared market. Default excludes it — the rule only
  holds guests on liquid brands, and a held legit RU buyer costs one click.
  Widen by env when RU marketing starts.
- **Raise the base threshold back to $40 after shipping?** Operator call,
  revisit after a week of alert volume.
