# 0048. Sell Mobile Legends as two region products, and guard the choice

- **Status**: Accepted
- **Date**: 2026-08-09
- **Deciders**: @jamaomonov
- **Tags**: catalog | product | integrations

## Context and problem statement

Mobile Legends: Bang Bang is not one product at G2B. It is seven region-locked
ones, and buying the wrong one produces an order we take money for and cannot
deliver. Verified against the live `/games/{code}/fields` notes and G2B's own
eligibility matrix on 2026-08-09:

| product          | who it works for                                      | $/diamond |
| ---------------- | ----------------------------------------------------- | --------- |
| `mlbb`           | CIS + rest of world; **not** RU/SG/MY/PH/VN/Indonesia | 0.0133    |
| `mlbb_br`        | CIS + world, but non-BR accounts get **10% fewer**    | 0.0142    |
| `mlbb_global`    | everywhere except SG/MY, Russia, Turkey               | 0.0151    |
| `mlbb_special`   | everywhere except Indonesia and Russia                | 0.0169    |
| `mlbb_ru`        | Russia + CIS only                                     | 0.0178    |
| `mlbb_tr`        | Turkey only                                           | —         |
| `mlbb_exclusive` | Philippines only                                      | —         |

All seven take the same two inputs — `userid` and `serverid` — so nothing about
the form tells a customer which one they need. Worse, a player's region is fixed
when the account is created and Moonton offers no way to move it, and the game
shows no "global"/"RU" label anywhere: the profile shows only `ID (Zone ID)`.
The customer therefore has to make an unrecoverable choice from information the
game does not give them.

## Decision drivers

- The storefront serves Uzbekistan and Russia. Those need different products —
  `mlbb` excludes Russia outright, `mlbb_ru` is the only one Russia can use.
- A wrong-region order is worse than a lost sale: the money moves, the diamonds
  do not, and the refund path is manual.
- Every extra product on the page is another chance to pick the wrong one.
- Margin stays at the house 20% (ADR-0024 computes `cost × (1 + margin)`).

## Considered options

1. **One product** (`mlbb` only) — simplest page, but no Russian player can buy.
2. **Two products**, split only by region — `mlbb` and `mlbb_ru`.
3. **Four products** — region × type (diamonds, passes), mirroring how PUBG
   splits `pubg-uc` / `pubg-royal-pass` / `pubg-prime`.
4. **Add `mlbb_special`** as a third region option for its 122 denominations.

## Decision outcome

**Chosen option: 2.** `mlbb-diamonds` (global) and `mlbb-diamonds-ru`.

Option 1 drops a market the storefront explicitly targets. Options 3 and 4
multiply the one choice that can break an order — the house's type-split is
right for PUBG, where picking UC instead of Royal Pass is a recoverable mistake,
and wrong here, where region is not.

`mlbb_br` is excluded despite being cheaper than everything but `mlbb`: it
delivers non-Brazilian accounts 10% less than the label says. Selling "878
diamonds" and crediting 790 is not a discount, it is a complaint.

The passes (Weekly Diamond Pass, Twilight) sit inside the diamond products at
their price position rather than in a product of their own. A customer on this
page is comparing what a given sum buys.

### Guarding the choice

Three layers, in increasing order of reliability:

1. **The product name says it** — "Алмазы — глобальный аккаунт" /
   "— российский аккаунт", localized in all three locales. `import_game` writes
   one name into all three locale rows, so the seed corrects en/uz; without
   that, the one place the storefront states the region was Russian-only.
2. **The page explains it** — the brand FAQ leads with the region question, and
   `required_fields[*].help_text` shows where `ID (Zone ID)` lives in the
   profile.
3. **The check answers it** — `required_fields[0].check` opts the player-id
   field into the storefront verification of [ADR-0031](./0031-storefront-player-check.md),
   with `server_field: "server"`. G2B's `checkPlayerId` runs against the same
   `game_code` the product is mapped to, so a global id entered under the
   Russian product returns no nickname **before any money moves**. This is what
   turns the region from something the customer has to know into something they
   can find out.

Form keys are `player_id` and `server` because that is what the G2B fulfiller
reads out of `fulfillment_data`. Naming them after G2B's own `userid`/`serverid`
would silently drop the server and fail every order with an HTTP 400.

### Onboarding as a script, not wizard clicks

`scripts/seed/2026-08-09_mobile_legends_import.py` calls the same
`integrations.service.import_game` the admin wizard's endpoint calls. Which two
of seven products we sell, and at which denominations, is a decision worth
reading in a diff rather than reconstructing from clicks — and it is re-runnable
against prod. SEO content follows the established pattern in
`scripts/seed/mobile_legends_seo.sql`.

### Negative consequences

- Two products where competitors show one. A CIS player whose account happens to
  sit on the Russian region has to discover that; the check tells them, but only
  after they have tried the global product first.
- `mlbb` carries 105 denominations upstream and we list 13. Restocking the
  ladder is a manual edit to the script.
- A customer in Russia buying `mlbb_ru` pays ~34% more per diamond than a
  customer in Tashkent buying `mlbb`, because the wholesale cost differs that
  much. The margin is the same 20%; the gap is the supplier's.

## Validation

- The import ran against dev and was re-run to prove it is idempotent (brand
  reused, both products detected, 23 SKUs unchanged).
- Prices verified at 20% margin ±rounding across all 23 SKUs; sort_order is a
  clean price ladder.
- Brand content, FAQs and product names verified in ru/en/uz through the API's
  `Accept-Language` negotiation, and the brand page rendered in dev with both
  product groups, the ⓘ help modal and the "Проверить" button present.
- `_import_denomination` now sets `sort_order` from the request position;
  covered in `tests/integration/test_g2b_import.py`, including that a skipped
  duplicate does not shift the SKUs after it.

## References

- [ADR-0024](./0024-g2b-catalog-import.md) — the import endpoint this reuses
- [ADR-0031](./0031-storefront-player-check.md) — the player check the region guard leans on
- [ADR-0009](./0009-catalog-three-level-plus-form-schema.md) — Brand/Product/SKU + form schema
