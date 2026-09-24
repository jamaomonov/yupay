"""Map our catalogue onto FazerCards.

Run inside the api container. Preview first, then apply:

    docker exec -i -e APPLY=0 yupay-prod-api-1 python - < scripts/seed/2026-09-24_fzr_mappings.py
    docker exec -i -e APPLY=1 yupay-prod-api-1 python - < scripts/seed/2026-09-24_fzr_mappings.py

## Where these ids come from

**216 of the 225 were not matched at all — they were copied.** FazerCards and
NOVA publish the same catalogue under the same ids, so for every SKU that
already holds a NOVA mapping the category and offer ids transfer verbatim.
That is not an assumption: each one was checked against FazerCards' live
ladders on 2026-09-24, and **215 of 215 existed**, zero misses. (The 216th is
the Steam wallet sentinel, which names a mapping shape rather than a
category.) Copying beats matching here because it cannot be subtly wrong —
a fuzzy match on "565 Diamonds" can land on a first-top-up rung, an id cannot.

The remaining nine had no NOVA mapping and were matched by hand:

- **four by number and unit** — `mcgg-165`, `mcgg-275`, `mcgg-565`,
  `mcgg-1060`, all in `magic_chess_gogo_global`;
- **five by name**, owner-confirmed 2026-09-24: `mcgg-weekly-card` ->
  `weekly_card`, `mlbb-weekly` ("Weekly Diamond Pass") -> `weekly_pass`, and
  the three Discord subscriptions, where their "Discord Basic: 1 Month" is
  what we sell as "Nitro Basic — 1 month".

## Regions are pinned, never guessed

Each brand is bound to one category. It matters twice over: Mobile Legends and
Magic Chess each publish a global and an RU catalogue and we sell both as
separate brands, and Free Fire publishes twelve regional catalogues of which
only `free_fire_cis` is ours. Taking the cheapest across regions is how an
earlier pass invented a saving that came from LATAM prices.

## What is deliberately NOT mapped, and why

Fifty-one active SKUs get nothing here. None of it is an oversight:

- **MLBB Global 55 / 165 / 275 / 565.** FazerCards carries these *only* as
  "First Top-Up Bonus" rungs (50+5, 150+15, 250+25, 500+65). The bonus lands
  on a player's first top-up and nowhere else, so a repeat customer would
  receive 50 where we sold 55. Owner ruled on this directly. Note the NOVA
  mappings skip exactly these four and map every ordinary base+bonus rung —
  the same decision, already made once.
- **A different ladder.** PUBG (985, 1320, 2460, 5650, 11950, 16200), Roblox
  (200, 1500, 4000, 5250, 11000, 24000), IMO (200, 500, 1000, 2000, 5000),
  MLBB Global's G2B rungs, Arena Breakout 13640/20460, Standoff 100/1000/3000.
  These exist on G2B and simply are not products on this platform.
- **A different product.** Delta Force "Pass Upgrade Level N" (they sell
  Season Passes), MLBB RU "Limited-Time Value Pack", MCGG Global 55 (they have
  56 and 59, not 55).
- **Telegram.** Stars and Premium are dearer here than NOVA — $0.0152625 per
  star against $0.015225, and all three Premium terms — and the adapter has no
  Telegram branch for exactly that reason (ADR-0092).
- **Steam Gifts.** Their gift endpoints are not wired up.

## Nothing is rerouted

Every mapping lands as a second (or third) source. `fzr` is in
`RESERVE_SUPPLIERS`, so `sourcing._pick_auto_mapping_slug` will never choose it
on its own — an operator picks it with `force_supplier` after reading the
comparison screen, which is the whole point of creating these rows. No
sourcing rule is written here, no cost is touched, no price moves.

Idempotent: `upsert_mapping` converges, so re-running changes nothing.
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import select
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Sku
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping

ADMIN_ID = "00000000-0000-7000-8000-000000000001"
SUPPLIER = "fzr"
APPLY = os.environ.get("APPLY") == "1"

#: ``(sku_code, mapping kind, their category_id, their offer/card id[, quantity])``.
#: Grouped by brand with the category named once, so a wrong region is visible
#: by reading rather than by cross-referencing.
MAPPINGS: list[tuple[str, ...]] = [
    # arena-breakout -> arena_breakout
    ("arena_breakout-1690", "game", "arena_breakout", "1690_bonds"),
    ("arena_breakout-335", "game", "arena_breakout", "335_bonds"),
    ("arena_breakout-3400", "game", "arena_breakout", "3400_bonds"),
    ("arena_breakout-66", "game", "arena_breakout", "66_bonds"),
    ("arena_breakout-675", "game", "arena_breakout", "675_bonds"),
    ("arena_breakout-6820", "game", "arena_breakout", "6820_bonds"),
    ("arena_breakout-beginner-select", "game", "arena_breakout", "beginner_select"),
    ("arena_breakout-bulletproof-case-30d", "game", "arena_breakout", "bulletproof_case_30d"),
    ("arena_breakout-composition-case-30d", "game", "arena_breakout", "composition_case_30d"),
    (
        "arena_breakout-monthly-advanced-battle-pass-activation-pass",
        "game",
        "arena_breakout",
        "monthly_advanced_battle_pass_activation_pass",
    ),
    (
        "arena_breakout-monthly-premium-battle-pass-activation-pass",
        "game",
        "arena_breakout",
        "monthly_premium_battle_pass_activation_pass",
    ),
    (
        "arena_breakout-quarterly-premium-battle-pass-bundle-act-ec2be00c",
        "game",
        "arena_breakout",
        "quarterly_premium_battle_pass_bundle_activation_pass_bundle",
    ),
    # arena-breakout-infinite -> arena_breakout_infinite
    ("arena_breakout_infinite-100", "game", "arena_breakout_infinite", "100_bonds"),
    ("arena_breakout_infinite-1000", "game", "arena_breakout_infinite", "1000_bonds"),
    ("arena_breakout_infinite-10000", "game", "arena_breakout_infinite", "10000_bonds"),
    ("arena_breakout_infinite-2500", "game", "arena_breakout_infinite", "2500_bonds"),
    ("arena_breakout_infinite-500", "game", "arena_breakout_infinite", "500_bonds"),
    ("arena_breakout_infinite-5000", "game", "arena_breakout_infinite", "5000_bonds"),
    (
        "arena_breakout_infinite-advanced-battle-pass-activation-card",
        "game",
        "arena_breakout_infinite",
        "advanced_battle_pass_activation_card",
    ),
    (
        "arena_breakout_infinite-premium-battle-pass-activation-card",
        "game",
        "arena_breakout_infinite",
        "premium_battle_pass_activation_card",
    ),
    # bigo-live -> bigo_live
    ("bigo-10", "game", "bigo_live", "10_diamonds"),
    ("bigo-100", "game", "bigo_live", "100_diamonds"),
    ("bigo-1000", "game", "bigo_live", "1000_diamonds"),
    ("bigo-10000", "game", "bigo_live", "10000_diamonds"),
    ("bigo-200", "game", "bigo_live", "200_diamonds"),
    ("bigo-2000", "game", "bigo_live", "2000_diamonds"),
    ("bigo-25", "game", "bigo_live", "25_diamonds"),
    ("bigo-50", "game", "bigo_live", "50_diamonds"),
    ("bigo-500", "game", "bigo_live", "500_diamonds"),
    ("bigo-5000", "game", "bigo_live", "5000_diamonds"),
    # blood-strike -> blood_strike
    ("bs-105", "game", "blood_strike", "105_bc"),
    ("bs-1100", "game", "blood_strike", "1100_bc"),
    ("bs-2260", "game", "blood_strike", "2260_bc"),
    ("bs-320", "game", "blood_strike", "320_bc"),
    ("bs-51", "game", "blood_strike", "51_bc"),
    ("bs-540", "game", "blood_strike", "540_bc"),
    ("bs-5800", "game", "blood_strike", "5800_bc"),
    ("bs-level-up-pass", "game", "blood_strike", "level_up_pass"),
    ("bs-strike-pass-elite", "game", "blood_strike", "strike_pass_elite"),
    ("bs-strike-pass-premium", "game", "blood_strike", "strike_pass_premium"),
    # delta-force -> delta_force
    ("deltaforce-1480", "game", "delta_force", "1480_delta_coins"),
    ("deltaforce-16200", "game", "delta_force", "16200_delta_coins"),
    ("deltaforce-18", "game", "delta_force", "18_delta_coins"),
    ("deltaforce-1980", "game", "delta_force", "1980_delta_coins"),
    ("deltaforce-24300", "game", "delta_force", "24300_delta_coins"),
    ("deltaforce-30", "game", "delta_force", "30_delta_coins"),
    ("deltaforce-320", "game", "delta_force", "320_delta_coins"),
    ("deltaforce-3950", "game", "delta_force", "3950_delta_coins"),
    ("deltaforce-460", "game", "delta_force", "460_delta_coins"),
    ("deltaforce-60", "game", "delta_force", "60_delta_coins"),
    ("deltaforce-750", "game", "delta_force", "750_delta_coins"),
    ("deltaforce-8100", "game", "delta_force", "8100_delta_coins"),
    (
        "deltaforce-season-pass-delta-force-deluxe",
        "game",
        "delta_force",
        "season_pass_delta_force_deluxe",
    ),
    (
        "deltaforce-season-pass-operations-special",
        "game",
        "delta_force",
        "season_pass_operations_special",
    ),
    (
        "deltaforce-season-pass-warfare-special",
        "game",
        "delta_force",
        "season_pass_warfare_special",
    ),
    # discord -> discord_global
    ("discord-nitro-1m", "voucher", "discord_global", "discord_nitro_1_month_subscription"),
    ("discord-nitro-1y", "voucher", "discord_global", "discord_nitro_12_months_subscription"),
    ("discord-nitro-basic-1m", "voucher", "discord_global", "discord_basic_1_month_subscription"),
    # free-fire -> free_fire_cis
    ("freefire_cis-110", "game", "free_fire_cis", "110_diamonds"),
    ("freefire_cis-1166", "game", "free_fire_cis", "1166_diamonds"),
    ("freefire_cis-2398", "game", "free_fire_cis", "2398_diamonds"),
    ("freefire_cis-341", "game", "free_fire_cis", "341_diamonds"),
    ("freefire_cis-572", "game", "free_fire_cis", "572_diamonds"),
    ("freefire_cis-6160", "game", "free_fire_cis", "6160_diamonds"),
    ("freefire_cis-evo-access-30d", "game", "free_fire_cis", "evo_access_30d"),
    ("freefire_cis-evo-access-3d", "game", "free_fire_cis", "evo_access_3d"),
    ("freefire_cis-evo-access-7d", "game", "free_fire_cis", "evo_access_7d"),
    ("freefire_cis-level-up-10", "game", "free_fire_cis", "level_up_package_10"),
    ("freefire_cis-level-up-15", "game", "free_fire_cis", "level_up_package_15"),
    ("freefire_cis-level-up-20", "game", "free_fire_cis", "level_up_package_20"),
    ("freefire_cis-level-up-25", "game", "free_fire_cis", "level_up_package_25"),
    ("freefire_cis-level-up-30", "game", "free_fire_cis", "level_up_package_30"),
    ("freefire_cis-level-up-6", "game", "free_fire_cis", "level_up_package_6"),
    ("freefire_cis-monthly-membership", "game", "free_fire_cis", "monthly_membership"),
    ("freefire_cis-newbie-bundle", "game", "free_fire_cis", "newbie_bundle"),
    ("freefire_cis-weekly-lite", "game", "free_fire_cis", "weekly_lite"),
    ("freefire_cis-weekly-membership", "game", "free_fire_cis", "weekly_membership"),
    # genshin-impact -> genshin_impact_global
    ("genshin-1090", "game", "genshin_impact_global", "980_110_genesis_crystals"),
    ("genshin-2240", "game", "genshin_impact_global", "1980_260_genesis_crystals"),
    ("genshin-330", "game", "genshin_impact_global", "300_30_genesis_crystals"),
    ("genshin-3880", "game", "genshin_impact_global", "3280_600_genesis_crystals"),
    ("genshin-60", "game", "genshin_impact_global", "60_genesis_crystals"),
    ("genshin-8080", "game", "genshin_impact_global", "6480_1600_genesis_crystals"),
    ("genshin-blessing", "game", "genshin_impact_global", "blessing_of_the_welkin_moon"),
    # honkai-star-rail -> honkai_star_rail_global
    ("hsr-1090", "game", "honkai_star_rail_global", "980_110_oneiric_shard"),
    ("hsr-2240", "game", "honkai_star_rail_global", "1980_260_oneiric_shard"),
    ("hsr-330", "game", "honkai_star_rail_global", "300_30_oneiric_shard"),
    ("hsr-3880", "game", "honkai_star_rail_global", "3280_600_oneiric_shard"),
    ("hsr-60", "game", "honkai_star_rail_global", "60_oneiric_shard"),
    ("hsr-8080", "game", "honkai_star_rail_global", "6480_1600_oneiric_shard"),
    ("hsr-express", "game", "honkai_star_rail_global", "express_supply_pass"),
    # honor-of-kings -> honor_of_kings
    ("hok-1245", "game", "honor_of_kings", "1245_tokens"),
    ("hok-16", "game", "honor_of_kings", "16_tokens"),
    ("hok-240", "game", "honor_of_kings", "240_tokens"),
    ("hok-2508", "game", "honor_of_kings", "2508_tokens"),
    ("hok-400", "game", "honor_of_kings", "400_tokens"),
    ("hok-4180", "game", "honor_of_kings", "4180_tokens"),
    ("hok-560", "game", "honor_of_kings", "560_tokens"),
    ("hok-80", "game", "honor_of_kings", "80_tokens"),
    ("hok-830", "game", "honor_of_kings", "830_tokens"),
    ("hok-8360", "game", "honor_of_kings", "8360_tokens"),
    ("hok-weekly", "game", "honor_of_kings", "weekly_card"),
    ("hok-weekly-plus", "game", "honor_of_kings", "weekly_card_plus"),
    # imo -> imo
    ("imo-10", "game", "imo", "10_diamonds"),
    ("imo-100", "game", "imo", "100_diamonds"),
    ("imo-1680", "game", "imo", "1680_diamonds"),
    ("imo-16800", "game", "imo", "16800_diamonds"),
    ("imo-2100", "game", "imo", "2100_diamonds"),
    ("imo-21000", "game", "imo", "21000_diamonds"),
    ("imo-420", "game", "imo", "420_diamonds"),
    ("imo-4200", "game", "imo", "4200_diamonds"),
    ("imo-840", "game", "imo", "840_diamonds"),
    ("imo-8400", "game", "imo", "8400_diamonds"),
    # likee -> likee
    ("likee-100", "game", "likee", "100_diamonds"),
    ("likee-1000", "game", "likee", "1000_diamonds"),
    ("likee-10000", "game", "likee", "10000_diamonds"),
    ("likee-200", "game", "likee", "200_diamonds"),
    ("likee-2000", "game", "likee", "2000_diamonds"),
    ("likee-20000", "game", "likee", "20000_diamonds"),
    ("likee-3000", "game", "likee", "3000_diamonds"),
    ("likee-500", "game", "likee", "500_diamonds"),
    ("likee-5000", "game", "likee", "5000_diamonds"),
    # magic-chess-gogo -> magic_chess_gogo_global
    ("mcgg-1060", "game", "magic_chess_gogo_global", "1060_diamonds"),
    ("mcgg-1346", "game", "magic_chess_gogo_global", "1346_diamonds"),
    ("mcgg-165", "game", "magic_chess_gogo_global", "165_diamonds"),
    ("mcgg-2195", "game", "magic_chess_gogo_global", "2195_diamonds"),
    ("mcgg-275", "game", "magic_chess_gogo_global", "275_diamonds"),
    ("mcgg-3688", "game", "magic_chess_gogo_global", "3688_diamonds"),
    ("mcgg-5532", "game", "magic_chess_gogo_global", "5532_diamonds"),
    ("mcgg-565", "game", "magic_chess_gogo_global", "565_diamonds"),
    ("mcgg-706", "game", "magic_chess_gogo_global", "706_diamonds"),
    ("mcgg-86", "game", "magic_chess_gogo_global", "86_diamonds"),
    ("mcgg-9288", "game", "magic_chess_gogo_global", "9288_diamonds"),
    ("mcgg-weekly-card", "game", "magic_chess_gogo_global", "weekly_card"),
    # magic-chess-gogo-ru -> magic_chess_gogo_ru
    ("mcgg_ru-1060", "game", "magic_chess_gogo_ru", "1060_diamonds"),
    ("mcgg_ru-1155", "game", "magic_chess_gogo_ru", "1155_diamonds"),
    ("mcgg_ru-165", "game", "magic_chess_gogo_ru", "165_diamonds"),
    ("mcgg_ru-1765", "game", "magic_chess_gogo_ru", "1765_diamonds"),
    ("mcgg_ru-275", "game", "magic_chess_gogo_ru", "275_diamonds"),
    ("mcgg_ru-2975", "game", "magic_chess_gogo_ru", "2975_diamonds"),
    ("mcgg_ru-55", "game", "magic_chess_gogo_ru", "55_diamonds"),
    ("mcgg_ru-565", "game", "magic_chess_gogo_ru", "565_diamonds"),
    ("mcgg_ru-6000", "game", "magic_chess_gogo_ru", "6000_diamonds"),
    ("mcgg_ru-battle-for-discounts", "game", "magic_chess_gogo_ru", "battle_for_discounts"),
    ("mcgg_ru-lukas-battle-bounty", "game", "magic_chess_gogo_ru", "lukas_s_battle_bounty"),
    ("mcgg_ru-weekly-card", "game", "magic_chess_gogo_ru", "weekly_card"),
    ("mcgg_ru-weekly-diamond-pass", "game", "magic_chess_gogo_ru", "weekly_diamond_pass"),
    # mobile-legends -> mobile_legends_global
    ("mlbb-172", "game", "mobile_legends_global", "156_16_diamonds"),
    ("mlbb-2195", "game", "mobile_legends_global", "1860_335_diamonds"),
    ("mlbb-257", "game", "mobile_legends_global", "234_23_diamonds"),
    ("mlbb-3688", "game", "mobile_legends_global", "3099_589_diamonds"),
    ("mlbb-429", "game", "mobile_legends_global", "429_diamonds"),
    ("mlbb-706", "game", "mobile_legends_global", "625_81_diamonds"),
    ("mlbb-86", "game", "mobile_legends_global", "78_8_diamonds"),
    ("mlbb-monthly-elite-pack", "game", "mobile_legends_global", "monthly_elite_pack"),
    ("mlbb-twilight", "game", "mobile_legends_global", "twilight_pass"),
    ("mlbb-weekly", "game", "mobile_legends_global", "weekly_pass"),
    ("mlbb-weekly-elite-pack", "game", "mobile_legends_global", "weekly_elite_pack"),
    # mobile-legends-ru -> mobile_legends_ru
    ("mlbb_ru-1155", "game", "mobile_legends_ru", "1155_diamonds"),
    ("mlbb_ru-165", "game", "mobile_legends_ru", "165_diamonds"),
    ("mlbb_ru-1765", "game", "mobile_legends_ru", "1765_diamonds"),
    ("mlbb_ru-275", "game", "mobile_legends_ru", "275_diamonds"),
    ("mlbb_ru-2975", "game", "mobile_legends_ru", "2975_diamonds"),
    ("mlbb_ru-35", "game", "mobile_legends_ru", "35_diamonds"),
    ("mlbb_ru-55", "game", "mobile_legends_ru", "55_diamonds"),
    ("mlbb_ru-565", "game", "mobile_legends_ru", "565_diamonds"),
    ("mlbb_ru-6000", "game", "mobile_legends_ru", "6000_diamonds"),
    ("mlbb_ru-weekly", "game", "mobile_legends_ru", "weekly_pass"),
    # oxide-survival-island -> oxide_survival_island
    ("oxide-125-20", "game", "oxide_survival_island", "125_20_web_bonus"),
    ("oxide-1250-500", "game", "oxide_survival_island", "1250_500_web_bonus"),
    ("oxide-250-65", "game", "oxide_survival_island", "250_65_web_bonus"),
    ("oxide-2500-1250", "game", "oxide_survival_island", "2500_1250_web_bonus"),
    ("oxide-50-5", "game", "oxide_survival_island", "50_5_web_bonus"),
    ("oxide-500-175", "game", "oxide_survival_island", "500_175_web_bonus"),
    ("oxide-7500-3750", "game", "oxide_survival_island", "7500_3750_web_bonus"),
    # pubg-mobile -> pubg_mobile_auto
    ("pubgm-1800", "game", "pubg_mobile_auto", "1800_uc"),
    ("pubgm-325", "game", "pubg_mobile_auto", "325_uc"),
    ("pubgm-3850", "game", "pubg_mobile_auto", "3850_uc"),
    ("pubgm-60", "game", "pubg_mobile_auto", "60_uc"),
    ("pubgm-660", "game", "pubg_mobile_auto", "660_uc"),
    ("pubgm-8100", "game", "pubg_mobile_auto", "8100_uc"),
    ("pubgm-elite-pass-lv1-100", "game", "pubg_mobile_auto", "elite_pass_lv1_100"),
    ("pubgm-elite-pass-lv1-50", "game", "pubg_mobile_auto", "elite_pass_lv1_50"),
    ("pubgm-elite-pass-plus-lv1-100", "game", "pubg_mobile_auto", "elite_pass_plus_lv1_100"),
    (
        "pubgm-firearm-materials-pack",
        "game",
        "pubg_mobile_auto",
        "upgradable_firearm_materials_pack",
    ),
    ("pubgm-first-purchase-pack", "game", "pubg_mobile_auto", "first_purchase_pack"),
    ("pubgm-mythic-emblem-pack", "game", "pubg_mobile_auto", "mythic_emblem_pack"),
    ("pubgm-prime-1-month", "game", "pubg_mobile_auto", "prime_1_month"),
    ("pubgm-prime-12-months", "game", "pubg_mobile_auto", "prime_12_months"),
    ("pubgm-prime-3-months", "game", "pubg_mobile_auto", "prime_3_months"),
    ("pubgm-prime-6-months", "game", "pubg_mobile_auto", "prime_6_months"),
    ("pubgm-prime-plus-1-month", "game", "pubg_mobile_auto", "prime_plus_1_month"),
    ("pubgm-prime-plus-12-months", "game", "pubg_mobile_auto", "prime_plus_12_months"),
    ("pubgm-prime-plus-3-months", "game", "pubg_mobile_auto", "prime_plus_3_months"),
    ("pubgm-prime-plus-6-months", "game", "pubg_mobile_auto", "prime_plus_6_months"),
    ("pubgm-weekly-deal-pack-1", "game", "pubg_mobile_auto", "weekly_deal_pack_1"),
    ("pubgm-weekly-deal-pack-2", "game", "pubg_mobile_auto", "weekly_deal_pack_2"),
    (
        "pubgm-weekly-mythic-emblem-value-pack",
        "game",
        "pubg_mobile_auto",
        "weekly_mythic_emblem_value_pack",
    ),
    ("pubgm-wow-1800", "game", "pubg_mobile_auto", "1800_wow_coins"),
    ("pubgm-wow-325", "game", "pubg_mobile_auto", "325_wow_coins"),
    ("pubgm-wow-3850", "game", "pubg_mobile_auto", "3850_wow_coins"),
    ("pubgm-wow-60", "game", "pubg_mobile_auto", "60_wow_coins"),
    ("pubgm-wow-660", "game", "pubg_mobile_auto", "660_wow_coins"),
    ("pubgm-wow-8100", "game", "pubg_mobile_auto", "8100_wow_coins"),
    # roblox -> roblox_global
    ("roblox-100", "voucher", "roblox_global", "100_robux"),
    ("roblox-1000", "voucher", "roblox_global", "1000_robux"),
    ("roblox-10000", "voucher", "roblox_global", "10000_robux"),
    ("roblox-2000", "voucher", "roblox_global", "2000_robux"),
    ("roblox-2500", "voucher", "roblox_global", "2500_robux"),
    ("roblox-3000", "voucher", "roblox_global", "3000_robux"),
    ("roblox-4500", "voucher", "roblox_global", "4500_robux"),
    ("roblox-50", "voucher", "roblox_global", "50_robux"),
    ("roblox-800", "voucher", "roblox_global", "800_robux"),
    # standoff-2 -> standoff_2_global
    ("so2-gold-500", "voucher", "standoff_2_global", "500_gold"),
    # steam -> steam-topup
    ("steam-wallet-usd", "game", "steam-topup", ""),
    # whiteout-survival -> whiteout_survival
    ("wos-18495", "game", "whiteout_survival", "18495_frost_stars"),
    ("wos-1999", "game", "whiteout_survival", "1999_frost_stars"),
    ("wos-299", "game", "whiteout_survival", "299_frost_stars"),
    ("wos-29999", "game", "whiteout_survival", "29999_frost_stars"),
    ("wos-499", "game", "whiteout_survival", "499_frost_stars"),
    ("wos-4999", "game", "whiteout_survival", "4999_frost_stars"),
    ("wos-7499", "game", "whiteout_survival", "7499_frost_stars"),
    ("wos-99", "game", "whiteout_survival", "99_frost_stars"),
    ("wos-999", "game", "whiteout_survival", "999_frost_stars"),
    ("wos-9999", "game", "whiteout_survival", "9999_frost_stars"),
]


async def main() -> None:
    """Upsert every mapping, reporting what changed and what was missing."""
    factory = get_session_factory()
    async with factory() as session:
        codes = [row[0] for row in MAPPINGS]
        found = {
            sku.sku_code: sku
            for sku in (await session.execute(select(Sku).where(Sku.sku_code.in_(codes)))).scalars()
        }
        missing = [c for c in codes if c not in found]
        written = 0
        for row in MAPPINGS:
            sku_code, kind, product_id, variant_id = row[0], row[1], row[2], row[3]
            quantity = int(row[4]) if len(row) > 4 else 1
            sku = found.get(sku_code)
            if sku is None:
                continue
            print(f"  {sku_code:44s} {kind:8s} {product_id}/{variant_id}  x{quantity}")
            if APPLY:
                await upsert_mapping(
                    session,
                    MappingUpsert(
                        sku_id=sku.id,
                        supplier_slug=SUPPLIER,
                        kind=kind,
                        external_product_id=product_id,
                        external_variant_id=variant_id,
                        quantity=quantity,
                        extra={},
                        is_active=True,
                        updated_by=ADMIN_ID,
                    ),
                )
            written += 1
        if APPLY:
            await session.commit()

        print(f"\n{'ЗАПИСАНО' if APPLY else 'СУХОЙ ПРОГОН'}: {written} маппингов")
        if missing:
            # A sku_code that no longer exists is a real signal, not noise:
            # it means this table and the catalogue have drifted apart.
            print(f"НЕ НАЙДЕНО SKU ({len(missing)}): {', '.join(missing)}")
        if not APPLY:
            print("APPLY=1 чтобы записать")


asyncio.run(main())
