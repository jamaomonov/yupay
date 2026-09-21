# 0090. A voucher is not flat: gift-card catalogues get their own denomination kind

- **Status**: Accepted
- **Date**: 2026-09-21
- **Deciders**: @jamaomonov
- **Tags**: backend | data | frontend

## Context and problem statement

`supplier_catalog_cache` has carried three kinds since it was built around G2B:
`voucher` (a flat, directly-mappable product), `game` (a category) and
`game_denom` (one rung of a game's ladder). That shape encodes an assumption —
a voucher is one product at one price, only a game has a ladder — which was
true of G2B and is false of both other suppliers we buy codes from.

The consequences were reported from the outside, as three separate complaints
that turned out to be one:

- «я только что сделал синхронизацию новы, там синхронизировались только игры,
  ваучеры нет» — `sync_nova_catalog` swept only `/api/v2/topups`. NOVA's second
  catalogue (`/api/v2/giftcards`, 576 categories, each holding cards with their
  own `card_id`, `price_usd` and `stock`) was never read. Its own module
  docstring asserted "NOVA has no voucher concept".
- «у g engine постоянно каталог не синхронизирован» — `catalog_sync_gengine`
  deliberately skipped the shop catalogue (`/shop/products`,
  `/shop/denominations/{id}`) and said so in its docstring, on the grounds that
  it would need a fourth cache kind nothing had asked for.
- «в соурсинге в "Сравнить поставщиков по бренду" я всегда вижу что у g engine
  нету синхронизации цен и не показывает» — G-Engine was not in
  `PRICE_COLLECTION_SUPPORTED_SUPPLIERS`, so `brand_overview` reported
  `cost_source=None` for every SKU mapped to it. It had no `cost_lookup` at
  all, because there was nowhere to look a price up from.

Measured on production before the change: 1192 `g2b` voucher rows, zero for
`nova` and `gengine`; zero `supplier_price_history` rows for either supplier on
any Roblox SKU, including the four we had just started selling at NOVA's price.

A fourth failure was found while fixing these and is the one with money on it:
the admin mapping wizard had no denomination step for a voucher and saved
`external_variant_id: null` unconditionally. Every NOVA and G-Engine gift-card
mapping in production had to be written by a seed script, and opening one in
the wizard and pressing save would have erased the card id — leaving a mapping
that names a category and no card.

## Decision drivers

- The cache is what the mapping picker reads and what the cost refresh reads.
  A catalogue that never lands in it is invisible to both.
- Shop and recharge ids collide at G-Engine: shop product `9` is Roblox
  Global, recharge service `9` is Delta Force. Whatever distinguishes them has
  to be structural, not a convention.
- Adding a supplier's price source must not make two suppliers fight over
  `Sku.cost_usdt` — ADR-0083's routed-supplier rule already settles that and
  must keep holding with a third contender.

## Considered options

1. **Reuse `game_denom` for gift-card ladders** — no migration, and the
   picker filters the cache by kind, so a gift card's rungs would surface
   under "Игра у поставщика" while the voucher step stayed empty. It also
   loses the G-Engine id collision: shop 9 and recharge 9 would be the same
   `(kind, parent)`.
2. **Add a `voucher_denom` kind** — one CHECK swap; the key already carries
   `parent_external_id` (0084) and the parent index already covers it.
3. **Keep vouchers flat and put the card id in `extra`** — no schema change,
   and no picker, no price, no stock: exactly the state being complained
   about, with a JSON blob added.

## Decision outcome

**Chosen option: 2.** `voucher_denom` joins the kind CHECK (migration 0086),
and both suppliers' second catalogue is swept with the same restraint the
first one already had: the top level whole, the ladder **only** for products
an active mapping points at.

Prices for both G-Engine catalogues and for NOVA gift cards are read **from
the cache**, not live. G-Engine's `/recharge/services` already returns every
service's denominations inline, so the sync holds the number and asking again
per mapping would be ~120 redundant calls an hour; NOVA answers a whole
gift-card category in one call, so nine Roblox rungs would otherwise be nine
identical requests. This makes «Синхронизировать каталог» the button that
moves G-Engine prices, which is the honest coupling — the alternative is a
price that silently is not one.

`gengine` therefore joins `PRICE_COLLECTION_SUPPORTED_SUPPLIERS`, which is
what makes the brand-comparison screen report a G-Engine cost at all.
ADR-0083's rule is untouched: only the routed supplier writes
`Sku.cost_usdt`, everyone else writes history.

The wizard gains a denomination step for a voucher whose supplier sells a
ladder, backed by `POST /{supplier}/vouchers/{product_id}/sync-denominations`
— the voucher twin of the existing per-game pull, and the same deviation-free
shape under AGENTS.md §10 (a POST, operator-triggered, off the order path).
G2B is not accepted there, and for its own reason: its vouchers genuinely are
flat, so there is no ladder to pull.

### Positive consequences

- Both NOVA catalogues and both G-Engine catalogues are now visible in the
  mapping picker, with price and stock on the row.
- A NOVA gift card and a G-Engine shop denomination have a cost basis for the
  first time, so the hourly refresh moves them and the brand-comparison screen
  can be read.
- A gift-card mapping can be made in the admin instead of by a seed script,
  and editing one no longer erases its card id.

### Negative consequences

- G-Engine and NOVA gift-card prices are as fresh as the last catalogue sync,
  not as fresh as the last price refresh. Both are hourly, so the ceiling is
  about an hour; an operator wanting it now presses the button. A sync that
  fails silently reuses the cached number — the same exposure G2B's voucher
  path has always had.
- Two more upstream calls per sync tick for NOVA (the category cursor walk)
  and one per mapped shop product for G-Engine. Measured today: 6 calls, from
  two mapped shop products and one mapped gift-card category.
- A fourth kind is a fourth thing to get right in every place that filters by
  kind. The picker, the cost lookup and the sync all take it as a parameter
  rather than branching on the supplier, which is what keeps that bounded.

## Validation

- `tests/integration/test_integrations_catalog_sync_nova.py` and its G-Engine
  twin assert that each supplier's second catalogue is swept, that a ladder is
  read **only** for a mapped product (the unmapped one's endpoint is never
  registered with respx, so calling it fails on the network), and that one
  catalogue failing does not lose the other.
- `tests/integration/test_cost_from_voucher_denominations.py` seeds the same
  denomination id under two parents and under two kinds, so a lookup that
  drops either would return the wrong price rather than nothing.
- `MappingEditPage.test.tsx` asserts a gift-card mapping saves its card id,
  refuses to save without one, and that a G2B voucher still has no
  denomination step at all.
