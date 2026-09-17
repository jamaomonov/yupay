# Design: NOVA for Steam (reserve) and for Free Fire CIS, and a cost basis that is not the face value

**Date:** 2026-09-17
**Status:** Approved in chat — three decisions taken by the owner, recorded in §2
**Branch:** `feat/nova-steam-and-free-fire`
**Builds on:** ADR-0081 / `docs/superpowers/specs/2026-09-17-nova-supplier-design.md`
**Surface:** API (`fulfillment.suppliers.nova*`, `orders.revenue`, `fulfillment.service`), catalogue data on prod, docs
**New ADR:** 0082

---

## 1. Problem

Three things, found by looking at NOVA's live prices the day after the integration merged.

**Free Fire CIS is cheaper at NOVA, on every SKU we sell.** Measured 2026-09-17 against our live
`cost_usdt`:

| SKU                | ours (G2B) | NOVA      | cheaper by |
| ------------------ | ---------- | --------- | ---------- |
| 110 Diamonds       | 0.820000   | 0.790602  | 3.6 %      |
| 341 Diamonds       | 2.470000   | 2.407608  | 2.5 %      |
| 572 Diamonds       | 4.020000   | 3.914964  | 2.6 %      |
| 1166 Diamonds      | 8.070000   | 7.850940  | 2.7 %      |
| 2398 Diamonds      | 16.140000  | 15.701778 | 2.7 %      |
| 6160 Diamonds      | 40.900000  | 39.777858 | 2.7 %      |
| Weekly Lite        | 0.380000   | 0.376890  | 0.8 %      |
| Weekly Membership  | 1.610000   | 1.570188  | 2.5 %      |
| Monthly Membership | 5.810000   | 5.652636  | 2.7 %      |

**NOVA sells ten Free Fire items we do not.** `Level Up Package 6/10/15/20/25/30`,
`Evo Access 3d/7d/30d`, `Newbie Bundle` — all in the same `free_fire_cis` category, none of them in
G2B's catalogue for that game.

**Steam at NOVA costs less than the wallet is worth.** Their Steam top-up is charged against our
balance "according to your plan": $10 of wallet costs us $9.80, $100 costs $98. Waxpeer and
G-Engine both charge face value. Our margin reporting cannot see that difference, because for a
variable-amount SKU it assumes the cost basis **is** the face value — `margin_usd_expr` computes
`qty × unit_price_usd × (multiplier − 1)`, and that `1` is the assumption. Left alone, every
NOVA-filled Steam order would understate margin by 2 % of the face value: $2 invisible on a $100
top-up.

## 2. Decisions taken by the owner

1. **Free Fire: map and switch now.** All nine SKUs get a NOVA mapping and a
   `force_supplier = nova` rule in the same change. Switching back is one admin action per SKU.
2. **Steam: reserve, like G-Engine.** Build the path and the mapping; the sourcing rule stays on
   Waxpeer. Nothing routes to NOVA's Steam until an operator says so.
3. **New SKUs: 10 % markup**, matching the 9–11 % the rest of the brand already carries.

## 3. Steam through NOVA

**A different endpoint from the games one.** `POST /api/v2/steam-topup/order` takes
`{steamLogin, currency, amount}` — no category, no offer — and answers **201**, not 200. Their
`GET /api/v2/steam-topup/rates` is FX only (USD/RUB/UAH/KZT); we send USD, where `amount` may carry
at most two decimals.

**How the adapter tells the two apart.** The SKU's mapping. A Steam mapping is
`supplier_slug='nova'`, `kind='game'`, `external_product_id='steam-topup'`, no variant — a
**sentinel**, and it is a sentinel rather than a new `kind` for the reason ADR-0081 already gives
for the validate namespace: `ck_sku_supplier_mapping_kind` allows only `voucher|game|gift`, and the
admin wizard coerces anything it loads to `voucher|game` on save. A sentinel in a column the wizard
round-trips untouched survives an operator opening the page; a fourth `kind` does not.

**The amount is the face value.** A variable Steam line carries `qty=1` and
`unit_price_usd = the dollars the customer bought` (verified on prod: 1, 6 and 10 dollar lines, all
`qty=1`). The customer receives that many dollars of wallet, so that is what we send. We are charged
less than we send, and §4 is about making that visible rather than about changing what we send.

**Status and money** follow the games path unchanged: their order object, its allow-list
(`created → processing → completed`), the `409`-means-a-reused-key grading, and the refusal grading
by status. `check_status` reads the same `GET /api/v2/orders/{id}`.

**Steam-specific refusals.** Their 400 for this endpoint can carry `availablePlans` and
`balanceUsd` — the shape of "your plan does not allow this" and "you cannot afford the upgrade".
Both are refusals before a charge, so they grade `RETURNED` like every other 400, and the message
(`_message_of`) is what tells an operator which it was.

## 4. A cost basis that is not the face value

**Today.** `orders.revenue.margin_usd_expr` has one branch for variable-amount SKUs:
`qty × unit_price_usd × (multiplier − 1)`. Rearranged, that is `gross − qty × unit_price_usd`: the
cost is the face value, hard-coded as the `1`. It is right for Waxpeer (`waxpeer_fee_rate` is 0) and
for G-Engine, and wrong for NOVA.

**The change.** Record what the supplier actually charged, on the line, and prefer it:

```
variable AND OrderItem.cost_usdt IS NOT NULL
    -> qty × unit_price_usd × multiplier − qty × cost_usdt − discount
variable, no recorded cost (every row written before this change)
    -> unchanged
```

`gross − margin == cost` still holds, which is the property `charged_usd_expr` and this function are
written to keep.

**Why `OrderItem.cost_usdt` and not a new column.** It exists, it means exactly this for fixed SKUs
("what this line cost us, frozen at checkout", ADR-0053), and **no variable line has ever carried
one** — 0 of 316 on prod. So the meaning is not being overloaded on any existing row, and every
historical Steam order keeps reporting exactly as it does today.

**Who writes it.** The fulfiller, when the supplier states the charge. NOVA states it twice: the
create response carries `novaDebit.amountUsd` (observed on the first live order) and the order
carries `chargedUsd`. A supplier that does not state it writes nothing and the old branch applies.
This is a write from `fulfillment` into an `orders` row, which the saga already holds for update —
it goes beside the existing `_apply_*` writes rather than into the adapter, so an adapter stays a
thing that talks to a supplier.

**What it is not.** Not a "NOVA discount rate" constant. Their discount depends on a plan
(`bronze|silver|gold`) that can change without telling us, and a number in our code that silently
disagrees with what we were charged is worse than no number — it would report a margin nobody
received.

## 5. Free Fire CIS

**The nine.** Map `free-fire` → `free_fire_cis` in the seed, then `force_supplier = nova` on each.
Six pair on number-and-unit as the matcher already does ("110 Diamonds" ↔ "110 Diamonds"); the three
memberships carry no number, so the seed gets a small **explicit** override table
(`freefire_cis-weekly-lite → weekly_lite`, `-weekly-membership → weekly_membership`,
`-monthly-membership → monthly_membership`). Explicit rather than by-name fuzzy matching: a name is
exactly the thing that must not be guessed when the guess routes money.

**The ten new ones**, priced at cost × 1.10 rounded up to the cent:

| NOVA offer            | cost     | price |
| --------------------- | -------- | ----- |
| `newbie_bundle`       | 0.224400 | 0.25  |
| `level_up_package_6`  | 0.293148 | 0.33  |
| `weekly_lite`\*       | —        | —     |
| `evo_access_3d`       | 0.418710 | 0.47  |
| `level_up_package_10` | 0.523362 | 0.58  |
| `level_up_package_15` | 0.523362 | 0.58  |
| `level_up_package_20` | 0.523362 | 0.58  |
| `level_up_package_25` | 0.523362 | 0.58  |
| `evo_access_7d`       | 0.711858 | 0.79  |
| `level_up_package_30` | 0.753678 | 0.83  |
| `evo_access_30d`      | 2.093550 | 2.31  |

\* already ours; listed only to show where it sits in the ladder.

**Where they live.** `Evo Access` joins `free-fire-membership` — it is time-limited access, which is
what that product already means. The six Level Up Packages and the Newbie Bundle need a product that
does not exist yet: `free-fire-packs` ("Наборы" / "Packs" / "Toʻplamlar").

**The trap that product must not spring.** `brand_check_field` (ADR-0079) returns a check only when
**every active product of the brand agrees** on it; a new product with a different or absent
`check` config silently disables the player check for the whole Free Fire brand. So
`free-fire-packs` copies `required_fields` from `free-fire-diamonds` **verbatim**, and a test
asserts the brand still resolves a check afterwards.

**They are NOVA-only, so they need a rule.** Auto sourcing skips reserve suppliers (ADR-0081), which
means a SKU whose only mapping is NOVA routes to the manual queue. Each of the ten therefore gets
`force_supplier = nova` in the same seed that creates it — without it they would be ten SKUs that
look sellable and land in a human's inbox on every order.

## 6. Out of scope

Their Steam **gifts**, game keys, gift cards and the Fragment API; the other Free Fire regions
(`free_fire_br/eu/id/…`); any change to what the customer sees; and any change to Waxpeer's or
G-Engine's own cost reporting beyond the branch in §4 that they simply do not reach.

## 7. Validation

- Contract tests for the Steam order (201, the `availablePlans` 400 shape, the amount's two-decimal
  rule).
- Unit tests for the adapter's Steam branch, including that a games mapping never reaches it and a
  Steam mapping never reaches the games path.
- A money test per new margin branch, and the invariant `gross − margin == cost` asserted on a
  variable line with and without a recorded cost.
- An integration test that the Free Fire brand still resolves a player check after `free-fire-packs`
  exists — the §5 trap.
- No live Steam order is placed by this branch: it is a reserve, nothing routes to it, and the first
  one is an operator's deliberate step (runbook).
