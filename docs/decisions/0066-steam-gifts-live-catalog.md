# 0066. Steam Gifts: live catalog proxy, dynamic checkout, adopt-don't-rebuy

- **Status**: Accepted
- **Date**: 2026-09-03
- **Deciders**: @jamaomonov
- **Tags**: backend | frontend | data | payments

## Context and problem statement

G-Engine exposes ~4 241 Steam games/DLC that can be gifted straight to a
buyer's Steam account: `GET /gifts/apps` (paginated catalog, server-side
search), `GET /gifts/apps/{id}` (full card — packages, each with ~41
per-region wholesale prices, and DLC), and `POST /gifts/orders
{invite_url, package_id, region}` (create-is-buy, no reservation step,
walking `accepted → prepared → delivering → shipped → delivered`). Every
other product line in the catalog is an imported SKU with a price that
moves on an hourly refresh; this one has ~4 200 positions whose prices move
with Steam sales throughout the day, and a purchase call that both creates
and spends money in a single, non-idempotent step. Both properties break
assumptions the rest of the catalog and fulfilment stack are built on.

## Decision drivers

- 4 241 daily-moving prices cannot be kept fresh as imported SKU rows
  without either staleness (a customer buying a discount that has already
  ended) or an import job running near-continuously against a catalog nine
  times the size of everything else combined.
- `/gifts/orders` takes no client-chosen idempotency token (unlike
  `/shop/orders`' `uuid` or a recharge order's own `pending` id), so a
  network failure between our request and G-Engine's response is genuinely
  ambiguous — the money may or may not have moved — and the design has to
  treat that as a first-class case, not an edge case.
- `delivered` only fires once the recipient manually accepts the gift in
  Steam, which is entirely their action and can take days; a task that
  waited for it would hold an already-successful sale open indefinitely.
- The margin on this brand has to be admin-tunable without a deploy: the
  gift market is price-transparent (buyers can see G-Engine's own panel or
  a competitor's), so 10% is a starting point that will need adjusting
  without shipping code.

## Considered options

1. **Import the catalog as SKUs**, refreshed on a tight schedule — the
   existing pattern for every other supplier.
2. **Live catalog proxy + dynamic checkout** — one service SKU
   (`steam-gift`), Redis-cached reads of the live G-Engine catalog, and a
   server-side re-price at order creation, on the precedent
   `tg-stars-any` already set for a variable-priced single SKU
   (ADR-0054).
3. **A parallel `gift_orders` table** distinct from `sku_supplier_mapping`,
   with its own routing logic in `fulfillment`.
4. **`gift` as a third `sku_supplier_mapping.kind`**, alongside
   `voucher`/`game`, routed by the existing G-Engine fulfiller.

## Decision outcome

**Chosen: 2 for catalog/checkout shape, 4 for storage.** The catalog is
proxied live (`gifts.service`, Redis cache with a `stale-while-error`
twin per key — fresh 15 min–1 h depending on the read, a 24 h stale
fallback behind it) instead of imported: nothing this size, moving this
often, is worth a second source of truth. Checkout follows the
`tg-stars-any` shape (ADR-0054) — one product-line SKU, `steam-gift`, with
a required-fields form (`app_id`, `package_id`, `region`, `invite_url`)
and a `fulfillment_data` snapshot. `orders.service` re-fetches the app via
the same 15-min-cached `gifts.service.get_app` the catalog browses,
recomputes the sell price from the live supplier price and the current
margin, and refuses the line (422, `extra.expected_amount_usd`) if the
client's quoted price has drifted more than ±2% — a Steam sale ending
between "customer opens the page" and "customer clicks pay" cannot corrupt
a paid order in either direction. The mapping lives as `kind='gift'` on
the existing `sku_supplier_mapping` table (migration `0064_steam_gifts`,
widening its CHECK) rather than a parallel table: the fulfiller already
dispatches on `mapping.kind`, and a gift line needs nothing a voucher/game
mapping's columns don't already have room for — `external_product_id` is
carried but purely informational, since routing is `mapping.kind=="gift"`
alone.

**Success is `shipped`, not `delivered`.** Verified live 2026-09-02:
`delivered` only flips once the recipient clicks "Принять подарок" in
Steam, which can take days and is entirely their action, not ours or
G-Engine's. Counting that as our fulfilment SLA would hold a task open for
a sale that already happened. `shipped`/`delivered` are both terminal
success; `canceled`/`refunded` are terminal failure; a decline _after_
`shipped` comes back as `refunded` on an already-succeeded task — handled
by the existing stuck/refund manual path (`docs/runbooks/wallet-refunds.md`),
not by this state machine, since `check_status` never runs again once a
task is `succeeded`.

**Adopt, don't rebuy.** Because the create call carries no idempotency
token, a lost response after a successful create is genuinely
indistinguishable from a lost response after a failed one. `fulfill_gift`
probes for an existing order first (`GET /gifts/orders?search=&date_from=`
narrowed to the invite-url tail plus `package_id`, bounded to since the
parent order was created) before ever calling create; an ambiguous create
failure (`GEngineUnavailableError` — ambiguous, unlike a clean
`GEngineError` refusal, which is a real failure) parks the task
`in_progress` with search metadata instead of declaring it failed (which
would invite a human to retry and buy a second gift) or blindly retrying.
An id-less task that stays unresolved past `GIFT_ADOPT_WINDOW_MINUTES`
(30) is parked `failed` for manual review — by then a landed create is
findable, so its absence means the create never happened, and a human
confirms that before any second spend. This mirrors the existing
`_recover(uuid)` pattern for recharge orders, adapted to a supplier that
gives us no id of our own to recover by.

**Margin is a DB-backed runtime setting, not an env var.** `gifts.settings`
mirrors `fx.quote_settings`'s shape exactly: Redis (`gifts:margin`, 1 h
TTL) → Postgres (`steam_gift_settings` row 1, singleton via a `CHECK id=1`)
→ the env-seeded default, read on a cold cache/first boot only. An admin
`PATCH /admin/gifts/settings` writes Postgres first, commits, and only
then publishes to Redis (`publish_margin`) — publishing before commit
would make an uncommitted margin briefly live if the commit then failed.
`STEAM_GIFTS_MARGIN_PERCENT` seeds the table on first read; it is not
consulted again once the row exists.

### Positive consequences

- No second source of truth for 4 241 daily-moving prices; the storefront
  and the order re-price both read the same cache, so there is exactly one
  pricing path.
- The two-second-spend risk of a no-idempotency-token create is bounded to
  a 30-minute manual-review window instead of an indefinite one, without
  ever risking a double purchase automatically.
- The margin knob ships without a deploy story from day one — the gift
  market being price-transparent makes this more likely to need tuning
  than most brands' margins.
- Reuses every existing mechanism instead of adding new ones: the
  `sku_supplier_mapping.kind` dispatch, the Stars-pattern dynamic SKU, the
  fulfilment queue's `in_progress` polling, the 60 s `gengine_reconcile`
  sweep (unmodified — it reconciles any `in_progress` gengine task,
  gift or not).

### Negative consequences

- **`/gifts/orders` takes no client uuid**, so two near-simultaneous
  identical gift purchases (same `invite_url` + `package_id`, placed
  within the same short window) can in rare cases be cross-adopted by the
  wrong task if the probe races the create under queue lag — the search
  probe matches on `invite_url` + `package_id` alone, not on which of our
  tasks actually triggered the order. This is an accepted, documented
  limitation (see the runbook), not a bug to fix here: G-Engine's API
  gives us no stronger key to disambiguate on, and the failure mode is
  "wrong task shows the receipt for the right purchase," not lost money or
  a double charge.
- The dev G-Engine API key 401s on `/gifts/apps` (an entitlement the prod
  key already has) — a go-live blocker, not a build blocker; see the
  runbook's launch checklist.
- Catalog SEO is deliberately thin in v1: only the hot-offers ItemList is
  indexable (spec §5) — the section itself, not per-game pages, since live
  prices for 4 000 items would churn the crawl. Per-game SEO pages are an
  explicit Phase 2, out of scope here.
- Phase 2 SKU/product pages for top-selling titles (spec §3) are
  deliberately not built now — this ADR covers only the live-proxy phase.

## Validation

`apps/api/tests/unit/test_gifts_service.py` and
`test_gifts_settings.py` cover the pricing math and the
Redis→DB→env-default precedence in isolation; `test_gifts_catalog_routes.py`
and `test_gifts_admin_settings.py` cover the same over real HTTP
(`respx`-mocked G-Engine). Checkout's re-price and ±2% refusal, and the
`risk_liquid_brands` hold applying to the `steam-gifts` brand, are covered
in the `orders` test suite that exercises `is_gift_sku`/`price_gift_line`.
The fulfiller's adopt-before-create, ambiguous-create parking, the
30-minute adopt-window failure, and the refunded-after-shipped ordering
are covered in `apps/api/tests/*` against `gengine_gifts.py` (contract
tests stub `GEngineClient`, per AGENTS.md §8's respx/VCR convention for
supplier adapters). The cross-adopt race under queue lag is not covered
by an automated test — it requires two genuinely concurrent tasks racing
a real supplier's non-atomic search — and is instead a documented,
accepted operational risk (see the runbook).

## Alternatives considered (detail)

### Option 1 — import as SKUs

Rejected outright: a nightly or even hourly refresh across 4 241 rows
still leaves discount windows and price moves stale for most of the
gap, and the write volume (every package × every zone, ~41 region rows
each) dwarfs anything else in the catalog for a section that may not
even prove out demand (spec's own Phase 2 gate). The live proxy costs
nothing extra beyond the cache the storefront already relies on for its
own catalog.

### Option 3 — a parallel `gift_orders` table

Rejected: it would have needed its own routing branch in `sourcing` and
its own admin surface parallel to `sku_supplier_mapping`, duplicating
machinery the existing table and fulfiller dispatch already provide. The
`kind` CHECK widen (Option 4) is a one-line migration against the same
table every other supplier mapping already uses.

## References

- `docs/superpowers/specs/2026-09-02-steam-gifts-design.md` — full design
- [ADR-0054](./0054-telegram-stars-unit-sku.md) — the dynamic-SKU/
  server-side-repricing pattern this checkout follows
- [ADR-0064](./0064-postgres-fulfilment-queue.md) — the fulfilment queue
  the gift fulfiller's `in_progress` polling rides
- `docs/architecture/module-map.md` — the new `gifts` module and its edges
- `docs/architecture/cache-keys.md` — every `gifts:*` Redis key
- `docs/runbooks/steam-gifts.md` — flag flip, parked-task triage,
  post-shipped refunds, margin changes, the launch checklist
- `docs/product/flows/steam-gifts.md` — the buyer-facing flow
