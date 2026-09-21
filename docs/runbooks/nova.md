# Runbook — NOVA (nova-gifts.com)

NOVA is a **reserve** supplier for game top-ups and a **fallback** for the
player-id check. It never receives an order or a check on its own — an
operator switches a SKU to it, or the primary check has already failed.
Design: [ADR-0081](../decisions/0081-nova-reserve-supplier.md) (the reserve
pattern) and [ADR-0082](../decisions/0082-nova-steam-and-real-cost-basis.md)
(the Steam wallet reserve, the real cost basis for margin, and switching
Free Fire CIS). Code:
`apps/api/src/yupay/modules/fulfillment/suppliers/nova.py` (fulfiller),
`nova_grading.py` (pure order-reading + money grading, split out of `nova.py`),
`nova_client.py` (transport), `apps/api/src/yupay/modules/integrations/player_check_nova.py`
(check fallback), `apps/scheduler/src/yupay_scheduler/jobs/nova_reconcile.py`
(reconcile job).

## What NOVA is for

A second place to buy essentially the whole game top-up catalogue (306
categories, matched against our brands) when G2B is out of stock, short on
balance, or down, **and** a second opinion for the storefront/reseller
player-id check when the primary (G2B for a game, Waxpeer for Steam)
answers `error`. Nothing routes to NOVA automatically in either role — see
"Switching a SKU" and "The check fallback" below.

## Funding

NOVA quotes its balance in USD (`GET /api/v2/balance` →
`{"ok":true,"balance":"…","currency":"USD"}`); how the owner actually funds
it (bank, card, USDT) is between them and NOVA, not something this repo
does. **The balance was `$0.0000` and no order had ever been placed on this
key as of the morning of 2026-09-17** — the adapter was wired but could not
fulfil anything until the wallet was funded. It has since been topped up to
$10 and the first live order (a PUBG Mobile top-up, same day) took the
balance to `$9.0985` — see "The first live order" below. Steam's own first
live order is still outstanding; see the Steam section further down.

**Where to look:** Admin → Интеграции → NOVA. The card probes
`GET /api/v1/admin/integrations/nova/health`, which calls
`NovaFulfiller.health()` and reports three things in one line — whether the
key is set, whether NOVA accepted it, and the balance behind it. That probe
exists because NOVA is a reserve: nothing routes to it on an ordinary day, so
a dead key or an empty balance would otherwise be discovered at the moment
somebody needs to switch a SKU to it.

The same answer from a shell, when the admin is not to hand:

```bash
curl -s https://nova-gifts.com/api/v2/balance -H "X-API-Key: $NOVA_API_KEY"
```

**Turning the key on/off.** `NOVA_API_KEY` lives in `secrets/api.env`
alongside every other supplier key. Settings are cached per-process
(`get_settings()`, `functools.lru_cache`), so editing the file is not
enough — a plain `restart` does not re-read `env_file` either:

```bash
docker compose -f docker-compose.prod.yml up -d --force-recreate api worker scheduler
```

`worker` needs the key because it is what actually calls `fulfill()` when
`FULFILMENT_ASYNC` is on; `scheduler` needs it because `nova_reconcile`
polls NOVA directly. Clearing `NOVA_API_KEY` (empty string) and
recreating those three turns NOVA off completely — no top-ups, no check
fallback — without touching code. See "The check fallback" below to turn
off only the check while keeping top-ups live.

A **zero or exhausted balance is not a code problem**: NOVA refuses the
create, the adapter recognises a refusal whose text contains "not enough
balance" / "insufficient balance" / "insufficient funds" (they document no
error code for this, so the match is on the message — see
`_LOW_BALANCE_HINTS` in `nova.py`), and turns it into the saga's existing
`supplier_low_balance` stall rather than a hard failure: the task lands in
the admin inbox (Fulfilment → "Failed" tab) with an ops alert
(`kind="supplier_low_balance"`), and the **order item stays `in_progress`**
so the storefront keeps saying "обработка" instead of erroring out.

### Gift cards — a second endpoint, and a second artifact

NOVA sells 576 gift-card categories beside its top-ups, and they do **not**
go through `/api/v2/topups/order`. A card has no player to credit, so that
endpoint's required `fields` cannot be built and a voucher mapping refused
every order with "no nova fields could be built". Since 2026-09-21 the
adapter dispatches on `SkuSupplierMapping.kind == "voucher"` to
`_fulfill_giftcard`, which calls `POST /api/v2/giftcards/order` with
`{category_id, card_id, quantity}` and no fields at all.

Three things worth knowing on call:

- **The create never carries the codes.** It answers `status: "created"`,
  `cards: []`, and the money is already gone. The codes appear on
  `GET /api/v2/orders/{id}` — about a second later on the first live order,
  but it is `check_status` that finishes the task, not the create.
- **`completed` with an empty `cards` is graded a FAILURE**, not a success,
  with `MoneyOutcome.UNKNOWN`. We were charged and have nothing to hand over;
  a success there would close the order with an empty code and the customer
  would be the one to find out. It lands in the Fulfilment inbox.
- **Quantity is real here.** Their endpoint takes 1–100 and stock caps it
  lower, so the "one call buys one offer" guard that protects top-ups is
  deliberately skipped for cards — see the dispatch order in `fulfill`.

Denominations come from `GET /api/v2/giftcards/cards?category_id=…`, which is
also where `card_id` and the live `stock` live. The endpoint is not
`/giftcards/offers` — that 404s, and guessing it cost a probe.

### The pre-emptive warning, before any order is refused

Since 2026-09-21 the hourly price refresh also probes NOVA's wallet through
the same `health()` the integrations page reads, and pings ops when it falls
below `SUPPLIER_LOW_BALANCE_THRESHOLD` (default **$50**). G2B has had this
since it was the only supplier we funded; G-Engine, NOVA and Waxpeer hold our
prepaid money the same way and had nothing, so an empty wallet was discovered
from failed orders.

Two things worth knowing when it does not fire:

- **A supplier that is down is not an empty wallet.** A failed probe is
  skipped — reachability has its own alerts — so a silent NOVA can mean
  unreachable rather than funded.
- **A currency the threshold does not describe is skipped and logged**, not
  compared: `integrations.lowbal.unknown_currency`. NOVA passes its own
  `currency` through from `GET /api/v2/balance`, so if that ever stops being
  USD-like this warning goes quiet by design. Grep that event before trusting
  silence.

One dedupe key per supplier (`alert:low_balance_warn:nova`, 6 h), so a quiet
G2B cannot mask a draining NOVA.

### Which balance is short — read the alert, not the label

NOVA has **two** refusals that both say a balance is insufficient, and they
mean opposite things to whoever is on call:

| Their sentence                                           | Whose money                      | What to do                                           |
| -------------------------------------------------------- | -------------------------------- | ---------------------------------------------------- |
| `Insufficient internal balance`                          | **ours** — our NOVA wallet       | Top up, then Retry.                                  |
| `Service balance is insufficient to complete this order` | **theirs** — NOVA's own upstream | Nothing to top up. Ask NOVA, retry when they answer. |

The second was observed 2026-09-20 in NOVA's own dashboard, which refused a
$19 Steam top-up while displaying a $112.75 wallet — so it cannot be read as
"top up". Until then both graded as `supplier_low_balance` and the alert said
"Пополни счёт", which sent an operator to check a balance that was already
fine. The alert now names the side, quotes NOVA's own sentence and prints our
real balance beside it; `shortfall` (`ours` / `supplier`) and
`supplier_message` are on the task's metadata if you need them after the fact.

### Telegram (Fragment) — a second API on the same key

Stars and Premium do not go through `/api/v2/topups`. NOVA runs a separate
**Fragment** namespace, and it disagrees with the v2 API on three things that
matter when something breaks (ADR-0084):

- **no `ok` envelope** — a Fragment 200 is the payload itself;
- **a reused `Idempotency-Key` returns the original order** rather than being
  refused with `409`, which is the opposite of every other NOVA endpoint;
- **`DRY_RUN`** is a real status. It means their sandbox answered and nothing
  was bought. We grade it a failure that cost nothing; if you see it in the
  inbox, ask NOVA whether the account is in test mode before retrying.

Both halves of a Fragment order live in that namespace, **including the
status poll**. `/api/v2/orders/{id}` does not know a Fragment order, and
asking it anyway does not 404 — the answer comes back without the `ok`
envelope, which surfaces as `nova HTTP 200`. That exact alert fired on
2026-09-20 for a delivered Stars order: the customer had their Stars, the
task sat in processing, and the only clue was a status step failing with a 200. `check_status` picks the endpoint from the SKU's mapping.

Mappings carry a sentinel in `external_product_id`:

| Product | `external_product_id` | variant               | `quantity`                                   |
| ------- | --------------------- | --------------------- | -------------------------------------------- |
| Stars   | `fragment-stars`      | none                  | the pack size; **1** on the free-amount line |
| Premium | `fragment-premium`    | months (`3`/`6`/`12`) | 1                                            |

Get `quantity` wrong on a Stars mapping and the order buys the wrong number of
Stars — it is the multiplier, not a formality.

**There is no username validation at NOVA.** Their quote endpoints take one and
ignore it: `premium/quote` priced a username that does not exist and echoed it
back. So a typo reaches the supplier. G2B's `checkPlayerId` does answer for
Telegram, and wiring it up is separate work.

### Retrying a NOVA task

NOVA burns an `Idempotency-Key` the moment it sees one and answers a reuse
with `409 "This Idempotency-Key was already used for a purchase"`. The
fulfilment key used to be `task.id` for the life of the task, so **a NOVA task
that failed once could not be retried at all** — and the 409 graded `UNKNOWN`,
which the confidence ladder never releases, so one Retry turned "we know we
spent nothing" into "we cannot tell" permanently.

`arm_retry_key` now mints a fresh key on Retry, but only for suppliers in
`KEY_BURNED_ON_USE` and only while no attempt may have spent. A task already
standing at `UNKNOWN` or `SPENT` keeps the burned key on purpose: a key NOVA
has not seen is a new purchase, and paying twice is worse than a stuck task.
Those need a human to reconcile against NOVA's order list before anything is
re-sent.

Waxpeer and G-Engine are deliberately _not_ in that set — they replay the
original order for a repeated key, so for them the reuse is the protection.

## Switching a SKU to NOVA and back

The exact mirror of the Steam (Waxpeer) / G-Engine procedure — nothing NOVA-
specific about the mechanism, only about what has to exist first.

**Prerequisite: an active mapping.** NOVA is in `MAPPING_REQUIRED_SUPPLIERS`,
so forcing a SKU onto it without one is refused immediately with

> `no active nova mapping for this SKU — create it under Integrations →
Mappings before routing orders there`

Create it at **Admin → Integrations → Mappings** — `category_id` (e.g.
`mobile_legends_ru`) into `external_product_id`, `offer_id` into
`external_variant_id` — or run the seed for a whole brand at once:

```bash
docker compose -f docker-compose.prod.yml exec -T api \
  python - < scripts/seed/2026-09-17_nova_mappings.py
```

It pairs our `denomination` with a NOVA offer name on both the number and the
unit ("1800 UC" is not "1800 WOW Coins", and NOVA sells both under one PUBG
category), writes an ACTIVE mapping only where exactly one offer matches and
exactly one of our SKUs claims it, then prints two tables: `matched` (`sku_code`, NOVA's offer
name, our `cost_usdt` beside their `price_usd` — compare before trusting a
margin) and `unmatched` (`sku_code`, `denomination`, why) for an operator to
finish by hand in the admin. Writing mappings active is safe on its own —
auto sourcing skips reserve suppliers entirely (`RESERVE_SUPPLIERS`), so
nothing routes to NOVA until `force_supplier` says so, whatever else changes
about the SKU's other mappings.

**PUBG Mobile is a guess, check it before trusting it.** NOVA sells PUBG
under four speed tiers (`pubg_mobile_auto`/`_fast`/`_manual`/`_reserve`,
same game, different fulfilment speed and price); the seed picks `_auto`
on a hunch. Confirm that's the right tier against the `matched` table's
price column, and edit the mapping by hand if not.

**Switch it on:** Admin → **Sourcing** (`/sourcing`) → pick the SKU → mode
**"Только поставщик"** (`force_supplier`) → choose **NOVA** → Save. Every
new order for that SKU now routes to NOVA; nothing already in flight moves.

**Switch it back:** same page — either pick **"Авто"** (deletes the rule;
the SKU falls back to `sourcing._resolve_auto`, which skips NOVA as a reserve
and picks the **oldest** of its remaining active mappings, i.e. the original
incumbent, per ADR-0081 — nothing to double-check), or force it onto a
specific supplier again. A SKU whose only active mapping was NOVA lands in
the manual queue rather than back on NOVA, which is the intended answer: a
reserve is never the automatic route.

**A task that already failed elsewhere** (G2B out of stock, low balance,
etc.) does not need a sourcing-rule change — that only affects orders that
don't exist yet. Reassign the one stuck task instead: Fulfilment
(`/fulfillment`) → **"Failed"** tab → open the task → **«Сменить
поставщика»** → NOVA. This calls `POST /tasks/{id}/reassign {"supplier":
"nova"}`, which is refused the same way (no mapping, unknown slug, same
supplier) and otherwise runs the order on NOVA immediately.

## The first live order — done, 2026-09-17

**It has been placed.** One 60 UC top-up for PUBG Mobile, on the owner's own
test account, against `pubg_mobile_auto`. It completed in **8 seconds**. What
follows is not a form to fill in any more; it is what their API actually does,
and it corrected two things this integration had guessed.

```
Order id:      "ord-1372576"       (key: `id`, a prefixed string, not a number)
Charged:       $0.901476 on create — balance 10.0000 -> 9.0985
Statuses:      created -> processing -> completed      (8s end to end)
```

The order object, in full, is the shape `nova.py` reads:

- `id`, `status`, `kind`, `title` — plus `category_id`, `offer_id`,
  `offer_name`, `category_name`, `fields` (our submitted `player_id`),
  `price_usd`, `total_usd`, `created_at`, `completed_at`.
- **`fail_reason`** — `null` on a healthy order. On a failure this is the only
  thing that says _why_, which is why `nova.py` copies it into `task.last_error`
  and into `nova_fail_reason` on the task's metadata.
- **`status_history`** — `[{status, at}, …]`, the whole path. Useful when an
  order sat somewhere: it timestamps each step.
- The `GET` adds money fields (`amountUsd`, `chargedUsd`, `charged_usd`,
  `customerAmountUsd`, `novaAmountUsd`, `totalUsd`), all equal to the price for
  a game. **`chargedUsd` and `charged_usd` are read** — they are what
  `nova_grading._charged_usd` freezes onto the order line as the real cost, and
  for an order whose create came back without a `novaDebit` block they are the
  only place that figure ever appears. The create reports the same number under
  `novaDebit.amountUsd`, which the client folds in so one key answers on both
  paths. For Steam these are **not** the price: that is the whole point.

**All three observed statuses were already in the allow-list** (`created` and
`processing` in-flight, `completed` success), so no correction was needed
there.

### What it corrected

**1. A reused `Idempotency-Key` is refused, not replayed.** Their endpoint
description says a repeat "returns the original order instead of
charging/fulfilling again"; their parameter description says it "is rejected".
The parameter description is the true one:

```
409  {"message":"This Idempotency-Key was already used for a purchase. Create a
      new key for a new purchase.","error":"Conflict","statusCode":409}
```

So **a create is never safely retried under the same key** — which is what
`nova.py` already assumed by grading a 409 `UNKNOWN`. It also means a create
whose response we lost cannot be recovered by replaying it: find the order in
`GET /api/v2/orders` instead, matching `fields.player_id`, `offer_id` and
`created_at`, and settle the task by hand.

The header is genuinely **required** — without it, `400 Idempotency-Key header
is required for purchase requests`.

**2. Their real error envelope is not the documented one.** Their OpenAPI
describes `{"ok": false, "error": "…", "code": "…"}`. A live 400/409/502
returns `{"message": "…", "error": "<status name>", "statusCode": N}` — no
`ok`, and `error` holding the word "Conflict" rather than the reason. The
client reads `message` first for exactly this reason (`_message_of`);
otherwise `task.last_error` would have said "Conflict" and nothing more.

**3. A bad `offer_id` answers `502`, not `404`.**
`{"message":"Unable to determine the current product price","error":"Bad
Gateway","statusCode":502}` — and the balance does **not** move. `nova.py`
grades a 502 `UNKNOWN`, so a mistyped mapping produces one task asking a human
to chase money that was never spent. That is the safe direction and it is
deliberate: no status alone can tell "they refused before charging" from "they
broke while charging". If you see that sentence in the inbox, the fix is the
mapping, not the money.

### While you are there: the PUBG tier

NOVA sells PUBG under four tiers. Measured 60 UC, same day:

| tier                  | 60 UC     |
| --------------------- | --------- |
| `pubg_mobile_auto`    | $0.901476 |
| `pubg_mobile_reserve` | $0.901476 |
| `pubg_mobile_manual`  | $0.915552 |
| `pubg_mobile_fast`    | $0.924222 |

`_auto` is the cheapest and it delivered in 8 seconds, so the seed's default
is confirmed rather than guessed. `_fast` costs 2.5% more for no observed
benefit at this denomination.

### Repeating this for another game

Place it the same way — through a switched SKU and a real checkout, not by
hand — and add a line here if the game behaves differently. A game whose
fulfilment is slower is the case most likely to show a status we have not
seen; `nova.unknown_order_status` in the logs names it and says which of the
four sets to add it to.

## Steam wallet top-ups (a reserve — never gone live)

Design: [ADR-0082](../decisions/0082-nova-steam-and-real-cost-basis.md). Code:
`NovaFulfiller._fulfill_steam` and `STEAM_SENTINEL` in `nova.py`,
`NovaClient.create_steam_order` in `nova_client.py`.

There is exactly one Steam SKU: brand `steam`, product `steam-wallet`,
`sku_code = "steam-wallet-usd"` — `variable_amount`, so `unit_price_usd` is
whatever dollar amount the customer typed at checkout, not a denomination
picked from a list. It routes to **Waxpeer** today, forced there by an
explicit `SkuSourcingRule` (`force_supplier = waxpeer`) rather than a
mapping — Waxpeer sells one thing and needs no `sku_supplier_mapping` row at
all (`docs/runbooks/waxpeer-troubleshooting.md`). NOVA is a second option,
wired since 2026-09-17, and like every reserve it is inert until an operator
switches this one SKU.

**No live order has ever gone through NOVA's Steam endpoint.** Everything
below the money-shape facts is a documented guess, exactly like the games
path was before its first live order (above) — see "The first live order"
subsection here for what to do about that before trusting it with volume.

### A different endpoint, and it costs less than what it sends

`POST /api/v2/steam-topup/order` takes `{steamLogin, currency, amount}` — no
category, no offer — and answers **201**, not the games endpoint's 200.
`amount_usd` is quantized to at most two decimals, rounded half-up, before it
is sent.

**The amount we send is the face value the customer bought — what NOVA
charges us for it is less.** NOVA states "according to your plan"
(`bronze|silver|gold`); observed nowhere yet on this endpoint specifically,
but the design's working number from their account page is a $10 top-up
costing us $9.80 — a 2% plan discount. We still send the full face value:
the customer receives that many dollars of wallet, full stop. What changes
is what we record ourselves as having paid for it.

### Where the discount shows up

NOVA folds what it actually charged into the order object — `novaDebit.amountUsd`
on the create response, `chargedUsd`/`charged_usd` on a later `GET` — and
`nova_grading._meta` copies it onto the fulfilment task as
`extra_metadata["supplier_charged_usd"]`. `fulfillment.service._record_supplier_charge`
reads that key once (never on a later poll if the create already wrote it)
and, only when it is a positive finite number, freezes it onto
`OrderItem.cost_usdt` for that line. A `0` or `NaN` is logged
(`fulfillment.supplier_charge_not_a_cost`) and dropped instead of written —
the order still delivers; see ADR-0082 §2 for why.

From there, `orders.revenue.margin_usd_expr` reads `cost_usdt` when it is
present instead of assuming a dollar of wallet costs a dollar. Nothing
displays "the NOVA discount" as its own figure anywhere; it is the gap
between `charged_usd_expr` (what the customer paid, from `unit_price_usd ×
rate_multiplier`) and `cost_usdt` (what NOVA took), both queryable per line
once a real order exists to look at.

### Switching Steam to NOVA and back

Same mechanism as "Switching a SKU to NOVA and back" above, with two
Steam-specific catches an operator following that section by rote would
trip on.

**1. Creating the mapping.** The Steam sentinel mapping is
`external_product_id = "steam-topup"`, `kind = "game"`, and **no номинал** —
their Steam endpoint takes a login and an amount, so there is no denomination
to name. `upsert_mapping` allows an empty variant for exactly this one row
(`_is_amount_priced`, `integrations/service.py`), the same way it already does
for G-Engine's amount-priced services. A NOVA **game** mapping still requires
its offer id, and still refuses to save without one.

- Admin → Интеграции → Маппинги → Создать
- Шаг 1 (SKU): `steam-wallet-usd`
- Шаг 2 (Тип): «Игровой топ-ап»
- Шаг 3 (Поставщик + продукт): NOVA; «ID сервиса у поставщика» (typed by
  hand — NOVA has no catalogue cache) = `steam-topup`
- Шаг 4 (Номинал): leave it empty.
- Шаг 5: quantity `1`, Активен, Сохранить. The save toast will say
  `cost_usdt не обновлён (cost sync supported only for g2b today)` — that is
  expected for every non-G2B supplier, not a failure.

**2. Switching _back_ is not "Авто".** For a game SKU with a real G2B
mapping, «Авто» correctly falls back to the incumbent. For
`steam-wallet-usd` it would not: Waxpeer has **no mapping row at all** (by
design — see above), so with the NOVA rule removed, `_resolve_auto` would
find no non-reserve mapping and route the SKU to the **manual queue**, not
back to Waxpeer. Switch back explicitly instead:

- Admin → **Sourcing** (`/sourcing`) → `steam-wallet-usd` → «Только
  поставщик» → **Waxpeer** → Save.

Switching _to_ NOVA is ordinary: same page, «Только поставщик» → **NOVA** →
Save, once the mapping above exists. Every new Steam order routes to NOVA
from that point; nothing already in flight moves.

### The first live order — not yet done

Nobody has bought Steam wallet credit through NOVA. Before trusting this
path with real volume, place one small top-up through a switched
`steam-wallet-usd` and a real checkout — the same way the games path's first
order was placed — and record here, in this shape:

```
Order id:
Sent (face value, what the customer received):
Charged (novaDebit.amountUsd / chargedUsd — what NOVA actually took):
Statuses walked:
Time end to end:
```

Specifically check and correct this section if any of these differ from
what is written above or in ADR-0082:

- Whether `chargedUsd` is genuinely lower than the sent amount, and by how
  much — the 2% figure above is the design's working number, not a
  measurement.
- Whether a refusal on this endpoint really does carry `availablePlans` and
  `balanceUsd` the way the design doc describes, and what `_message_of`
  surfaces for it.
- Whether any status appears outside `nova.py`'s allow-list —
  `nova.unknown_order_status` in the logs is the signal, same as for games.
- Whether `_record_supplier_charge` actually froze a figure onto
  `OrderItem.cost_usdt` — check the order's `order_items` row after the
  order settles.

## Free Fire CIS (switched to NOVA)

Design: [ADR-0082](../decisions/0082-nova-steam-and-real-cost-basis.md) §3–4.
Two seeds decide what is actually live here, and until both have been run
with `APPLY=1` against a deployed copy of this branch, nothing about Free
Fire's sourcing or catalogue has changed — the seeds are the switch, landing
the code is not.

> **Fund the wallet before you run them.** Switching a brand to NOVA is a
> promise their balance has to keep, and the top Free Fire SKU alone costs
> **$39.78** (6160 Diamonds). The balance was **$9.10** when this was written.
> A SKU priced above the balance does not fail at the seed — it fails at a
> customer's checkout, which is a worse place to find out. Both seeds print
> `nova balance: $…` as their first line for this reason.
>
> What a short wallet looks like when it happens: NOVA answers
> `400 "Insufficient internal balance"`, the adapter recognises it as a
> low-balance refusal and **stalls** the order (`supplier_low_balance`) rather
> than failing it — the customer stays on "в обработке", ops is alerted, and
> topping up and retrying completes the order. That sentence is theirs,
> observed on 2026-09-18 by asking for a $39.78 top-up against the $9.10
> wallet; the refusal costs nothing, which is why it could be checked at all.

### The nine existing SKUs

`scripts/seed/2026-09-17_nova_mappings.py` maps `free-fire` (NOVA category
`free_fire_cis`) alongside Mobile Legends and PUBG, but `free-fire` is the
**only** brand in the script's `SWITCH_TO_NOVA` set — so it is the only one
this run actually moves live orders for. Mobile Legends and PUBG get a
mapping and stay on their incumbent, exactly as before.

```bash
# dry run — prints the tables, writes nothing
docker compose -f docker-compose.prod.yml exec -T api \
  python - < scripts/seed/2026-09-17_nova_mappings.py

# read the tables, then commit
docker compose -f docker-compose.prod.yml exec -T -e APPLY=1 api \
  python - < scripts/seed/2026-09-17_nova_mappings.py
```

It prints **three** tables, and they answer three different questions —
reading only the first is reading half the story:

- **matched** — `sku_code`, NOVA's offer name, our `cost_usdt`, NOVA's
  `price_usd`. A mapping, not yet a switch: compare the last two columns
  before trusting it.
- **switched to nova** — the subset of `matched` whose brand is in
  `SWITCH_TO_NOVA` (`free-fire` only) and therefore also got a
  `force_supplier = nova` rule in the same transaction. This is the table
  that says whose live orders actually moved — everything else in `matched`
  is a mapping sitting in reserve, same as Mobile Legends and PUBG.
- **unmatched** — `sku_code`, `denomination`, and why. Finish these by hand
  in Admin → Интеграции → Маппинги.

The three memberships (Weekly Lite, Weekly Membership, Monthly Membership)
carry no denomination number, so the usual number-and-unit matcher can't
place them; they are paired instead through an explicit `SKU_OFFER_OVERRIDES`
table in the script (`freefire_cis-weekly-lite → weekly_lite`, etc.), read
once by a human rather than fuzzy-matched by name.

### What the operator sees once the switch is live

Design: [ADR-0083](../decisions/0083-routed-supplier-cost-and-price-ratchet.md). This is what
changes for these nine SKUs from the moment `APPLY=1` commits the `force_supplier = nova` rule —
distinct from the mapping/routing mechanics above, which exist the instant the mapping is written.

**Cost now syncs from NOVA, not G2B.** `sourcing.resolve_for_sku` says these nine SKUs route to
NOVA, so per ADR-0083 NOVA is the only supplier whose hourly (or on-demand) refresh is allowed to
write `Sku.cost_usdt` for them. The G2B mapping is still active and still refreshed every hour —
switching never deletes or deactivates it, which is exactly what makes the rollback in the next
section a one-click change — but its refresh now only records a `supplier_price_history` row. It
can no longer move these SKUs' cost or price.

**The retail price does not move.** Syncing cost down to NOVA's number is a drop, and the
automatic refresh path may raise a margin-derived price but never lower one (ADR-0083 Decision 2).
So `price_usd` holds exactly where it was, and the whole gap between what G2B was charging and
what NOVA charges lands as margin instead of as a markdown nobody decided on.

**The nine diamond SKUs are still on G2B, and the gain has not started.** Verified on production
after this branch deployed: `freefire_cis-110`, `-341`, `-572`, `-1166`, `-2398`, `-6160`,
`weekly-lite`, `weekly-membership` and `monthly-membership` carry **no sourcing rule at all**. They
hold both a G2B and a NOVA mapping, and because NOVA is a reserve (ADR-0081) auto routing never
picks it — so G2B wins as the oldest non-reserve mapping and stays the cost writer. Only the ten
NOVA-only SKUs carry `force_supplier = nova`, which is what the seed wrote them for.

So switching the nine is still a **decision someone has to take**, not something the deploy did. It
is now a job for the brand screen: open Free Fire, compare G2B against NOVA per SKU, tick the nine
and switch them — as `force_supplier`, because a reserve cannot be reached any other way.

**What it is worth, measured against production on 2026-09-18.** Take 110 Diamonds: the price holds
at $0.90, the cost would move from G2B's $0.820000 to NOVA's $0.790602, and margin from 9.76 % to
13.84 %. Across all nine the average moves from **10.7 % to 13.6 %** — about 2.9 points per SKU,
tracking each one's own 0.8–3.6 % NOVA discount. Weekly Lite gains least (0.93 points, on a 0.8 %
discount) and 110 Diamonds most (4.08 points, on 3.6 %).

**Order of operations, and it matters.** The cost only moves on the first hourly `catalog_watch`
tick _after_ the rules are written. The B2B markup correction comes after that, never before — the
merchant price list is cost-plus and computed live, so raising a markup while the cost is still
G2B's raises the reseller price instead of holding it.

Margin here is measured the way the rest of the system measures it — against **cost**, not against
price, which is what `Sku.margin_percent` means and what `price_usd = cost_usdt * (1 +
margin_percent / 100)` encodes. Measuring against price instead would report the same nine SKUs as
9.6 % → 11.9 % and quietly disagree with every other screen.

### The reseller price does not hold by itself

Retail and B2B price from the same `cost_usdt` but by opposite rules. Retail
`price_usd` is a stored column ADR-0083 refuses to lower, so the saving stays
with us automatically. The merchant price list is **cost-plus, computed live** —
`merchants.pricing.merchant_unit_price` reads `cost_usdt` on every request — so
the same cost drop cuts the reseller price by the same 0.8–3.6 % unless somebody
raises the markup.

The owner's decision (2026-09-18) is to keep the saving on both channels. The
lever is `b2b_markup_pct` on the nine SKUs, and the script is
`scripts/seed/2026-09-18_free_fire_b2b_hold.py`.

**Run it after the cost has moved**, not before: it computes each markup from the
SKU's current cost against the B2B price recorded on 2026-09-18, so run early —
while `cost_usdt` is still G2B's — and it correctly writes nothing and says so.
Dry run first, `APPLY=1` to commit, like the other seeds here. It refuses any
markup outside 5–13 %, because a cost that moved for some other reason would
otherwise have its markup bent to hold a price that no longer means anything.

All nine sit at the platform-wide 6 % today and land between 6.87 % and 9.94 %:
the smaller the NOVA discount, the smaller the correction. Skipping this step is
not neutral — it is a price cut to resellers that nobody decided.

### The ten NOVA-only SKUs

`scripts/seed/2026-09-18_free_fire_nova_only.py` creates six Level Up
Packages plus a Newbie Bundle under a new `free-fire-packs` product, and
three Evo Access durations joining the existing `free-fire-membership` — all
priced at cost × 1.10 ceiled to the cent, all NOVA-only (there is no G2B
equivalent), each with its own `force_supplier = nova` rule written in the
same transaction as its mapping.

```bash
docker compose -f docker-compose.prod.yml exec -T api \
  python - < scripts/seed/2026-09-18_free_fire_nova_only.py

docker compose -f docker-compose.prod.yml exec -T -e APPLY=1 api \
  python - < scripts/seed/2026-09-18_free_fire_nova_only.py
```

It refuses to write **anything** — even in the dry run, it just exits with a
non-zero status — if NOVA's live price has drifted more than 10% from the
table frozen in the script, or if a smaller move still crosses a cent
boundary the table didn't predict. Either is read as a catalogue change for
a human to look at, not a number to seed past. Its one printed table is
`sku_code`, `denomination`, `offer_id`, `cost_usdt`, `price_usd` — all ten
rows or none, since the whole run is one transaction.

### If NOVA's Free Fire price moves above G2B's

**The nine existing SKUs** have a real fallback: Admin → **Sourcing** → the
SKU → «Авто» removes the `force_supplier` rule, and `_resolve_auto`
(ADR-0081 Decision 4) falls back to the oldest remaining active mapping —
the G2B incumbent, since the switch never deleted or deactivated it. Do this
per SKU, or for all nine if the whole category's price moved. No re-seeding
needed either way.

**The ten NOVA-only SKUs have no fallback supplier** — NOVA is the only
mapping that exists for them. Each carries `margin_percent = 10`, so the
hourly supplier-price job keeps re-deriving `price_usd` as NOVA's cost
moves — a price _rise_ alone does not erode margin. If NOVA's cost rises
enough that the retail price stops being worth selling at all, the fix is
Admin → Catalog → the SKU → turn off «Активен» until a cheaper supplier
turns up; there is no supplier to fail over to in the meantime.

## The check fallback

Fires **only** when the primary check (G2B for a game, Waxpeer for Steam)
answers `error` — never instead of `valid`/`invalid`, and it can only turn
that `error` into `valid`, never into `invalid` (ADR-0081 Decision 2 — see
`docs/product/flows/player-check.md` for the sequence diagram). It covers
five brands through a code table (`NOVA_VALIDATE` in `player_check_nova.py`):
`mobile-legends-ru`, `pubg-mobile`, `free-fire`, `magic-chess-gogo`,
`magic-chess-gogo-ru`, plus a separate Steam-login branch. **Global Mobile
Legends is deliberately absent** — NOVA's single validate category has only
ever been observed answering for a Russian account, and a brand that can't
be told apart gets no fallback rather than a guess (open question, design
doc §10).

**Turn off only the check**, keep top-ups working:

```
NOVA_PLAYER_CHECK_ENABLED=false
```

in `secrets/api.env`, then `docker compose -f docker-compose.prod.yml up -d
--force-recreate api` — the check only runs inside API request handlers
(`/catalog/brands/{slug}/check-player`, `/merchant/v1/validate/player`), so
`worker` and `scheduler` never read this flag and don't need recreating.

**Turn off everything** (top-ups and the check): clear `NOVA_API_KEY` — see
"Funding" above.

Its own circuit (`nova:player_check`, Redis keys `breaker:nova:player_check:open`
/ `:fails`, same shape as `docs/runbooks/g2b-troubleshooting.md`'s breaker
section) opens after 3 consecutive failures for 30 s, its own cache
namespace (`playercheck:nova:*`, TTL 300 s, positive verdicts only — see
`docs/architecture/cache-keys.md`), and its own tighter timeout
(`nova_check_timeout_seconds`, default 4 s — the primary check measures
830 ms – 4.9 s in production, and the fallback must not double that wait).
Only 422/404/400/409 on the _check_ call count as "about what we sent" and
do **not** open the breaker (a customer's mistyped id must not silence the
fallback for everyone); a transport failure, a 5xx, 401, 403, or 429 does.

## What the logs say

| Event                                       | Level | Meaning                                                                                              |
| ------------------------------------------- | ----- | ---------------------------------------------------------------------------------------------------- |
| `nova.request`                              | info  | One HTTP call to NOVA — `method`, `path`, `status`. Every call, including failed ones.               |
| `player_check`                              | info  | One fallback attempt completed — `provider=nova`, `category_id`, `player_id_hash`, `status`.         |
| `player_check_failed`                       | warn  | The fallback's call to NOVA raised — `provider=nova`, redacted `error`. Never contains the raw id.   |
| `player_check_fallback_region_mismatch`     | warn  | NOVA validated the id, but for a different region than the brand expects — downgraded to `error`.    |
| `player_check_fallback_short_circuited`     | info  | The breaker (`nova:player_check`) was open — no call made.                                           |
| `nova.unknown_order_status`                 | warn  | An order status outside the allow-list — still `in_progress`. The first-live-order signal.           |
| `nova.order_without_status` / `_without_id` | warn  | Their order object had no recognisable `status`/`state` or `id`/`order_id`/`public_id`/`uuid` field. |
| `nova_reconcile.tick`                       | info  | One 60 s sweep finished — `checked`, `reconciled`, `failed`.                                         |
| `nova_reconcile.task_failed`                | warn  | One task's reconciliation raised — the sweep continues past it.                                      |

`nova.request` at `info` is verbose by design — it is the only line that
shows every call, including the ones nothing else logs. For a specific
order, grep the task id or the api container's recent `nova.request` lines
by timestamp.

## Rate limits

NOVA documents exactly **one** rate limit, and it is on
`GET /steam-gifts/games` (1 request / 3 min) — an endpoint this integration
never calls. Nothing is documented for `validate-id`, `topups/order`, or
`topups/offers`.

If a 429 ever appears anyway: on the **check** path it counts against the
breaker (`_counts_against_supplier` treats 429 as "about NOVA's health", not
about our input — backing off is the point of a rate limit, and this whole
module exists because the _primary_ hit one), so the breaker absorbs it and
the fallback goes quiet for 30 s rather than retrying into the limit. On the
**order** path there is no retry budget by design — `create_topup_order` is
sent once, like every other supplier's money-spending call — so a 429 there
is graded `UNKNOWN` (not `RETURNED`: it isn't one of their 400/403/404
request refusals) and parks the task for a human, same as any other
unexplained create failure.

## Related

- [ADR-0081](../decisions/0081-nova-reserve-supplier.md) — design and the
  four decisions this runbook assumes.
- [ADR-0082](../decisions/0082-nova-steam-and-real-cost-basis.md) — the
  Steam sentinel mapping, the real-cost-basis margin branch
  (`OrderItem.cost_usdt` / `orders.revenue.margin_usd_expr`), and the Free
  Fire CIS switch this runbook's Steam and Free Fire sections describe.
- [ADR-0031](../decisions/0031-storefront-player-check.md),
  [ADR-0052](../decisions/0052-g-engine-as-a-second-source.md),
  [ADR-0079](../decisions/0079-region-brands-and-brand-level-player-check.md)
  — the check, the second-source precedent, and the brand-scoped check this
  fallback plugs into.
- `docs/product/flows/player-check.md` — the check sequence diagram,
  including the NOVA branch.
- `docs/runbooks/merchant-b2b.md` § `POST /merchant/v1/validate/player keeps
answering error` — the reseller-facing side of the same fallback.
- `docs/runbooks/g2b-troubleshooting.md` — the primary this fallback stands
  behind; its breaker section is the template this one follows.
- `docs/runbooks/waxpeer-troubleshooting.md` — Steam's incumbent supplier;
  `steam-wallet-usd`'s own sourcing rule and inbox live there today.
- `apps/api/src/yupay/modules/fulfillment/README.md` § Поставщики,
  `apps/api/src/yupay/modules/sourcing/README.md` — the sourcing/fulfilment
  mechanics this runbook operates, in more detail.
- `apps/api/src/yupay/modules/orders/revenue.py` — `margin_usd_expr` and
  `charged_usd_expr`, the module this runbook's Steam section describes the
  new branch of.
