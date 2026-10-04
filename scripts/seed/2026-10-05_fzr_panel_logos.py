"""Logos for the brands FazerCards sells, from the FazerCards reseller panel's covers.

    docker exec -i yupay-prod-api-1 python - < scripts/seed/2026-10-05_fzr_panel_logos.py
    docker exec -i -e APPLY=1 yupay-prod-api-1 python - < scripts/seed/2026-10-05_fzr_panel_logos.py

The FazerCards API publishes no pictures, but its reseller panel does: every
gift-card category and top-up game carries an ``icon_url`` on a public media
host. The panel's own catalogue endpoint was read once from a logged-in browser
(2026-10-05) and the result is the table below — the panel's category id (our
``sku_supplier_mapping.external_product_id`` for ``fzr``) per cover file. Same
software as NovaGifts' panel; same approach as ``2026-10-05_nova_panel_logos.py``.

Two passes, both idempotent (a brand with a logo is left alone):

1. **Own cover.** A brand with no ``logo_url`` whose active fzr mapping (gift
   card or top-up) has a cover gets it. One cover file serves many categories
   (every PlayStation region shares one), so each file is downloaded and
   uploaded to our media bucket once and the public URL is reused.
2. **Sibling.** A brand still without a logo borrows the logo of a brand with
   the same title once region, variant and the « (Voucher)» suffix are
   stripped — «PlayStation (IN)» from any other PlayStation, «Delta Force
   (Voucher)» from the Delta Force top-up. The URL is copied, not the object.

Never hot-linked: the cover sits in our bucket under ``brand_logo/`` so a panel
rename cannot blank our shelf.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections import defaultdict
from typing import Any

import httpx
import yupay.main  # noqa: F401 -- registers every model
from sqlalchemy import text
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Brand
from yupay.modules.storage.client import get_s3_client
from yupay.modules.storage.service import _build_key, public_url_for

APPLY = os.environ.get("APPLY") == "1"
IMAGE_MIME = {"image/png", "image/jpeg", "image/webp"}
MEDIA = "https://reseller.fazercards.com/api/v2/media/game-key-covers/"

# cover file -> FazerCards category ids (gift cards and top-ups) that show it
COVERS = {
    "002069ad-c220-433c-bcf1-0a16bb7fd263.webp": "ea_sports_fctm_24_ea_points",
    "00ee088a-fdd4-4f9e-8120-2b903ad03ad9.png": "starmaker",
    "011ca39b-9aec-4baa-abc8-19c9a210eb86.png": "modern_strike_online",
    "021d181f-8c8f-4ceb-b9f5-d6a3f77ef1c7.jpg": "mico_live_global",
    "024093b6-34e0-433f-86a1-570c4cddb99d.jpg": "where_winds_meet",
    "02dd494f-82c9-4d25-be0f-33378432052b.webp": "eafc_mobile_id",
    "05147ab8-2084-4f88-bc9f-9dab82ed9ecd.jpg": "age_of_empire_mobile",
    "06681f94-e87f-4d86-b701-286ad11a7e61.webp": "pubg_mobile_reserve",
    "07629932-d41a-44b9-abd2-7225aa2d062b.jpg": "ensemble_stars_music",
    "080a24ed-8c89-4463-b138-83065249f493.jpg": "hyper_front",
    "0918a64f-8a5c-4c87-be8e-909b0c80233b.jpg": "sea_of_thieves_xbox_coins",
    "0943f75d-90d8-4356-bbe7-a473b301a09d.png": "capcut",
    "098d216b-11b0-42d1-87c4-1757a397242d.png": "gearup_booster_pc_global",
    "09a747bd-ca2e-4a4c-8b35-7062f1aad84d.png": "free_fire_th",
    "09b4326c-793a-4671-ac69-552aeb0c635c.png": "r6_mobile_sg",
    "09f6aa0e-29b3-4d6e-9a44-3d77aaa8e870.jpg": "cherry_credits",
    "0a80ff23-896c-4167-a17c-2c4f6763a361.jpg": "google_play_ae google_play_at google_play_be google_play_br google_play_de google_play_es google_play_fr google_play_id google_play_in google_play_it google_play_jp google_play_kr google_play_nl google_play_pl google_play_sa google_play_tr google_play_uk google_play_us",
    "0ac77b20-fe6c-4427-bebd-6468255a3e37.webp": "heaven_burns_red",
    "0bda948b-ed35-4169-9ae7-4950726f7655.png": "farlight_84",
    "0c1a9ce3-e9fe-4749-8155-79154e48a6d1.png": "crossfire_legend",
    "0ce7db4c-27a8-469f-aa92-e080f8f5952c.jpg": "honkai_star_rail_global honkai_star_rail_us",
    "0d9e1a64-4ff2-45d1-a38a-d5003d56a60c.webp": "ragnarok_idle_adventure_plus",
    "0e07b98c-f85d-4428-8cc7-690e19b3ba8b.png": "twitch_at twitch_au twitch_be twitch_ca twitch_es twitch_nl twitch_usd",
    "0f71c0f6-2108-4e5c-913e-bf9cec15f29d.jpg": "genshin_impact_global genshin_impact_login",
    "0ff43f66-51d4-4cc4-856b-84a37bbb4b2a.webp": "apex_legends_mobile_id apex_legends_mobile_ph apex_legends_mobile_sg apex_legends_mobile_th apex_legendstm_ea",
    "1055eced-4b7d-45a2-a4b3-30960eb6b238.jpg": "wild_rift_ae wild_rift_bh wild_rift_br wild_rift_by wild_rift_eu wild_rift_kw wild_rift_my wild_rift_ph wild_rift_ru wild_rift_sa wild_rift_sg wild_rift_tr wild_rift_ua wild_rift_uk wild_rift_us",
    "105cc742-7f7b-4eb1-98df-b4c47babcd9e.webp": "karma_koin_us",
    "107dd253-ba22-46b3-9f3e-a115b9286dfd.png": "undawn_garena_id",
    "110e2305-279f-4fc2-a384-e46375e3b3ed.png": "marvel_rivals",
    "11711361-4dc9-4ea3-89b5-3dfcbcfc2397.webp": "silver_and_blood",
    "12603283-75a3-409d-b838-c86ee8165120.webp": "ragnarok_the_lost_memories",
    "128f142f-91cd-44d3-b2c2-fbb61b54d746.png": "ghost_story_love_destiny",
    "12919928-b4ec-43fd-bde2-2a6fb2f928b5.webp": "kul_vn",
    "12cb4491-5d87-4f73-ac62-85350880f3d2.png": "r6_mobile_id",
    "12f39a7a-21e4-476b-8da5-8821b6900eeb.png": "weyyak",
    "14a07cb4-74c8-418b-bd24-901c0fc80189.png": "honor_of_kings_token_global",
    "14b998ae-9fc8-4b55-bee4-4f055f1b35e1.jpg": "lol_ph",
    "14bfaf50-34b6-4e52-8cb9-21f541018ba6.png": "free_fire_sg",
    "15e9eb6b-a2de-4111-a146-1e14b730105e.jpg": "ragnarok_tactics",
    "163a9fb3-8558-4b98-a64f-bbdd8b159fa6.webp": "bleach_soul_resonance_americas",
    "167aeda4-cef8-4d48-95a0-85ddbbb26fcb.png": "free_fire_bd",
    "16899739-3679-4a53-b4b9-b804682a2968.webp": "apex_legendstm_xbox",
    "16c58452-659c-4d35-9a20-95ac68230e5d.jpg": "legends_of_runeterra_indonesia",
    "173b21af-0aa1-4fd0-93ed-690d928f06b3.webp": "valorant_th",
    "18bdc1a0-53e7-4117-860e-48cef0b740ad.jpg": "razer_gold_au razer_gold_br razer_gold_ca razer_gold_cl razer_gold_co razer_gold_cz razer_gold_dk razer_gold_eu razer_gold_global razer_gold_hk razer_gold_id razer_gold_in razer_gold_mx razer_gold_my razer_gold_no razer_gold_ph razer_gold_pl razer_gold_ro razer_gold_se razer_gold_sg razer_gold_th razer_gold_tr razer_gold_tw razer_gold_us razer_gold_vn",
    "18d44cb6-b6c2-4a71-8d66-ee5597784a5b.webp": "gamestop_us",
    "197af879-a699-49eb-992c-b1f64fc80cb6.jpg": "crossout_mobile",
    "19dd6df1-ecdf-463d-8150-e4fce2c0fb1b.png": "r6_mobile_th",
    "1a8350de-a235-4dbe-aef1-8a0ac0a258fe.jpg": "imo",
    "1af9beee-11bf-4bae-9fc0-46290d8449d5.webp": "astral_guardians_cyber_fantasy",
    "1b26ca92-db76-4c08-a876-5afd1d6ebe76.png": "be_the_king",
    "1c3b7fb4-b3d3-4917-99e5-fc06dfa8988c.webp": "codm_garena_indonesia",
    "1cf4be09-b594-45b2-951f-90247411bf7f.webp": "ea_sports_fctm_26_ea_points",
    "1d2add01-cab0-421b-8466-ceffdd220d28.png": "t3_arena",
    "1d7c1661-d40f-48a8-9d3a-c7ec11d0a2e5.png": "eneba_ars eneba_aud eneba_brl eneba_cad eneba_eur eneba_gbp eneba_pln eneba_usd",
    "1db4f43f-9cfc-40e5-a815-e1eeec0f42ff.png": "mycard_tw",
    "1dcc88e3-fefa-466d-92c3-4af4049b8121.jpg": "nida_al_harb",
    "1efe3877-e8bf-4c35-a716-163047c7a460.jpg": "new_state_mobile_global",
    "1f06189e-05ed-47f6-936b-648703ccdafe.jpg": "idol_party",
    "1f2429dd-e2eb-4f3d-84e7-ba391a2244c4.png": "free_fire_mena",
    "1f54d1b9-56a7-4d9d-a9cb-e878c8cb5435.jpg": "legend_of_neverland",
    "202a4b8b-b1b0-43c0-8741-f2ce9d71f598.jpg": "bigo_live",
    "210b66a2-8205-48b3-8ea0-7ab64b9459dc.webp": "imvu_us",
    "213559e4-ebd0-45ba-b8dc-9be841998280.webp": "netflix_ae netflix_br netflix_ch netflix_co netflix_eu netflix_mx netflix_pl netflix_sa netflix_uk netflix_us",
    "238b8354-c290-4a68-9434-fe57c6423a17.jpg": "minecraft_java_bedrock_global minecraft_minecoins",
    "25164347-345b-4f73-ba37-8cbceeda6a51.webp": "mangatoon_read_comics_novel",
    "2663dd10-baba-487d-afa1-ea494fb94250.webp": "octopath_traveler_cotc",
    "26b9d12b-7e36-4867-b990-23a429356156.jpg": "marvel_duel",
    "27f488b6-549d-4f1c-b746-d44ab7bb09ef.webp": "mobile_legends_ru",
    "293f98d6-1663-47b5-928a-2cb0dfd06256.webp": "soho_101_okey",
    "29538829-7ec1-4740-9bb7-3a64d8aaf5d6.jpg": "etheria_restart",
    "2b232ebf-5c78-4548-a80d-b214884bef12.webp": "tom_and_jerry_chase",
    "2b5dcbcd-cfed-4efd-a814-26e04609a11b.webp": "tq_point_cards",
    "2c8acda2-c140-41f5-ab95-355ad707ac85.jpg": "dragon_nest_m_tw_hk_mo",
    "2cae6743-c948-4219-b503-104d3d139680.webp": "sword_of_justice_sea",
    "2d208e4b-180c-4408-b32b-2b1975b572f9.png": "undawn_eu",
    "2d9a5822-d6d3-422c-a93b-41dd565e6f82.webp": "yalla_ludo",
    "2f035ce1-7fd9-48a1-9de9-1b0ad37867c3.jpg": "legend_of_neverland_naeu",
    "2f25dc0c-329e-4aef-9ab4-f9b096e1776f.jpg": "azur_lane",
    "2f733b59-6811-4a22-8a9b-5b8f09a0815d.jpg": "omega_legends",
    "2f8037ff-cfda-4489-8e28-4acea1795296.jpg": "arena_of_valor_id",
    "2f8aa0dc-422d-4888-98e2-12a51e1ecea1.jpg": "shining_nikki",
    "3041b770-484a-44d0-b286-8ea40a4e4798.webp": "codm_activision_in",
    "31498f0b-360e-472b-b1cc-b0e3920fb228.jpg": "battle_net_br battle_net_eu battle_net_id battle_net_my battle_net_pl battle_net_sg battle_net_th battle_net_us",
    "31988792-9f93-48d6-ab9f-339076b75cdc.png": "bigo_live",
    "31b44613-e2de-468c-a7ac-ff2c3e601ad6.jpg": "the_ants_underground_kingdom",
    "321fc074-dc57-4046-80c5-670bfd73a603.png": "blacknut",
    "322f9cb8-c1c2-4caf-ad46-6c8f04b22ba2.png": "garena_free_fire_br garena_free_fire_global",
    "3244ee39-0fc6-4fe3-b124-746ca40a6952.png": "mobile_legends_adventure",
    "32e3f5db-d3b2-4482-883a-6685f0ad0dee.jpg": "telegram_premium",
    "32f5cfbf-d352-4335-bdb1-fb34ed27cb8c.jpg": "arena_of_valor_th",
    "332e860f-c5c5-4af4-8ac4-059eb6e9dd18.jpg": "maplestory_m",
    "356bd541-a445-4148-8fe4-70816355b78f.png": "fashion_dream",
    "356e2acf-67d9-4046-af32-dc4f90801ccf.webp": "eafc_mobile_my",
    "3679e4a9-2438-4d4c-9446-c4166ba98fe8.png": "zepeto",
    "36cd5e0c-fb3b-472e-904c-895c003e067f.jpg": "frag_pro_shooter",
    "37c9972e-24a3-4709-8dff-d30405a78984.png": "undawn_garena_sg",
    "383518c7-554e-448b-8063-350ac697ca12.png": "point_blank_id",
    "39ebae87-5444-4add-a276-8c98788594e2.jpg": "neverness_to_everness_login",
    "3ac2d92f-d3d4-457e-963f-5167208d8e9f.png": "tower_of_fantasy_login",
    "3bdf3e2d-d7b3-43a6-9674-ef118580b1f9.jpg": "acecraft",
    "3cad1fdf-5eac-40c7-b185-33ff5913fc2e.webp": "realms_of_pixel",
    "3cca4935-7f9d-4276-97f3-2c25ba7a9c58.jpg": "blade_x_odyssey_of_heroes",
    "3cf0add2-d640-4e42-a72c-9e519e4874fa.webp": "goddess_of_victory_nikke",
    "3d437fb4-e9c9-49c9-bc4e-5e140116924c.jpg": "captain_tsubasa_ace",
    "3e1020e9-e4ee-44c1-8687-89f314a80a8c.png": "rewarble_eur",
    "3e5428dc-fb4f-49f7-afee-760ac2703b76.jpg": "sky_children_of_light",
    "3f5e444e-ffb2-4176-8549-49d0dfc588e6.webp": "amazon_ae amazon_au amazon_be amazon_ca amazon_de amazon_eg amazon_es amazon_fr amazon_in amazon_it amazon_jp amazon_nl amazon_sa amazon_sg amazon_tr amazon_uk amazon_us",
    "3fb337ee-e8b1-46a8-b3fe-62ca43119afd.webp": "eafc_mobile_sg",
    "3fb625a7-7e8f-45d1-82b4-cc461f3c0fb9.jpg": "racing_master_sea",
    "3fc7f073-c34f-4ccf-94c6-63c4f75dc835.jpg": "airalo_voucher",
    "405e866c-d7b3-41d7-8c43-b77a123dc8bf.jpg": "lol_kh",
    "415164e4-c588-45c0-9831-1f0a0729f092.webp": "hello_yo",
    "43e5ba79-7179-43bc-b636-fc1301092bde.png": "binance_btc binance_usdc binance_usdt",
    "44a69afc-e1b5-4bf6-96c6-a97bc074c26f.png": "riot_access_code_ae riot_access_code_au riot_access_code_bh riot_access_code_br riot_access_code_ca riot_access_code_ch riot_access_code_dk riot_access_code_eu riot_access_code_hk riot_access_code_kw riot_access_code_my riot_access_code_no riot_access_code_nz riot_access_code_ph riot_access_code_pl riot_access_code_sa riot_access_code_se riot_access_code_sg riot_access_code_th riot_access_code_tr riot_access_code_uk riot_access_code_us",
    "44c98e6e-9a68-4473-9f24-2f2548861a4c.jpg": "firefly_live",
    "44fb5be1-b667-4a5a-9fd5-e9e88dead084.jpg": "football_master_2",
    "46d86a10-73c9-46da-81f6-4e3ffd0b193b.webp": "wild_rift_th",
    "472ccc99-c55b-4b94-826f-01fcebaa42c0.webp": "pubg_mobile_fast",
    "47342fa6-14c0-4498-860f-4d22213eb541.webp": "puzzles_and_survival",
    "4892263a-0424-48c1-a950-f0a618e1c120.webp": "soulchill",
    "49afbf29-3709-44d9-a289-72a86d5eb2c0.jpg": "garena_shells_id garena_shells_my garena_shells_us garena_shells_vn",
    "49c9918e-6aae-4739-afdc-8af4ad923a99.png": "state_of_survival",
    "49f599e5-6a42-4a91-94c9-bb2d6565935d.jpg": "crystalfall",
    "4a03a1a4-d5ef-4e83-8847-52abb80bd435.jpg": "lol_vn",
    "4a0b1d7a-047e-4456-aa94-33b8ca37f12f.webp": "bleach_soul_resonance_europe",
    "4a9f7f28-5c9c-4faa-a890-3b2c67b1205e.webp": "roblox_robux_us",
    "4c74d9f3-a80c-492d-82e5-2da457589cc9.webp": "codm_activision_kz",
    "4c8a6467-60fc-4ec4-9a81-b13d3486398c.png": "snowbreak_containment_zone",
    "4d326368-9076-4d81-9708-9d19c3ff27cc.png": "r6_mobile_ph",
    "4de463d8-1853-4c3e-bb42-2a899cb0e29d.png": "undawn_global",
    "4eefc59e-5e27-4237-ba3c-adfbbc5cf840.png": "devil_may_cry_peak_of_combat",
    "4f41fade-044f-4169-bdfe-20f32837d3b9.jpg": "lineage2m",
    "512b2549-3a5a-4fb6-99ae-2dd8a8d25454.jpg": "candy_crush_us",
    "518ba83e-78fa-4e18-b8bd-db2fa6288f86.png": "super_sus",
    "523410ea-262c-411b-8b02-08a1bd62e6ff.jpg": "mongil_star_dive",
    "52d114f2-a357-496f-8ffc-fd346657360b.webp": "bleach_soul_resonance_sea",
    "54883ba9-8bcb-463c-bee5-3d7b267105d9.webp": "valorant_ae valorant_bh valorant_br valorant_by valorant_eu valorant_hk valorant_id valorant_kw valorant_my valorant_ph valorant_ru valorant_sg valorant_th valorant_ua valorant_uk valorant_us",
    "552a890f-6b13-4770-b734-3e1bce72e255.png": "garena_speed_drifters",
    "55d56217-4dad-4e75-b6a7-bb82fcc563df.jpg": "sugo_online_chat_party",
    "55f613d9-dedc-4aa5-ac5c-6cfddf8b01dc.png": "free_fire_latam",
    "59900c1d-77e0-4550-b010-8aca5185c7dd.webp": "wild_rift_kh",
    "5a236d32-65da-4234-96ae-02a190faa313.jpg": "extraordinary_ones",
    "5a348f4b-b811-4f2e-93a5-dba3230eeffe.png": "path_to_nowhere",
    "5a64f178-2b1a-4fe0-bb25-a471e5dc25e4.jpg": "garena_delta_force_indonesia garena_delta_force_my",
    "5daf26db-9454-41f0-b77b-8d49fe94b6ef.webp": "dream_and_lethe_record",
    "5db8303c-113e-410c-9ff9-588f47ec86fe.webp": "xbox_ae xbox_au xbox_br xbox_ca xbox_co xbox_cz xbox_de xbox_dk xbox_es xbox_eu xbox_game_pass_au xbox_game_pass_br xbox_game_pass_eu xbox_game_pass_hk xbox_game_pass_in xbox_game_pass_jp xbox_game_pass_mena xbox_game_pass_mx xbox_game_pass_sg xbox_game_pass_us xbox_hk xbox_hu xbox_jp xbox_mx xbox_no xbox_pl xbox_sa xbox_tr xbox_uk xbox_us xbox_za",
    "5dbe30d1-8cc9-4fff-8357-8add0c804ff0.jpg": "world_of_warcraft",
    "5efabde3-5b58-446c-9365-2dba4155d498.png": "kings_choice_sea",
    "5f316da1-f586-4f99-a33c-2d3cedaca20d.webp": "ragnarok_origin",
    "5f4f17b8-a295-4e33-bc4c-d559fd128e4d.webp": "legend_of_the_phoenix",
    "5f6173f9-d06d-4524-9fb9-b48e4cf5663f.webp": "codm_activision_us",
    "5fcce3fe-13d6-4932-8629-7ca05ddbe918.jpg": "delta_force_steam_global",
    "5ffd01bd-db30-4705-a167-f9362a95f4cf.webp": "exitlag_gift_card_tier_3_global",
    "600a6ef9-c2d1-417d-8a65-ae66faf33511.png": "arena_breakout",
    "6188289a-e1a3-4e13-afc6-6fe53928f883.jpg": "stormshot",
    "64253648-6424-4509-93a7-74d375e6098c.png": "jetoncash_eu",
    "65015577-bd8e-4a5d-ac00-16c87c12d5b6.webp": "dynasty_heroes_legend_samkok",
    "655a7fe4-ce10-49ee-9300-db0412afc285.png": "heroes_evolved",
    "663e76a5-8c89-4eb7-a199-c0068c641858.jpg": "ragnarok_x",
    "6a16f8a9-8fd0-4e6b-aa75-67bdc35ab7dd.jpg": "haikyu_fly_high_sea",
    "6a9d1a47-7bb5-4574-826a-fa71692b6b29.jpg": "yoho_group_voice_chat_room",
    "6b82fa27-e2b7-4710-82cf-ac4da7e25233.jpg": "merge_kingdom_warlords",
    "6c79e7bf-b0aa-4db7-86c6-0f2f6eaa4f92.jpg": "pokemon_unite_ph",
    "6ce06f19-7d79-4aef-8e23-811ae8b5cd3e.png": "pixel_gun_3d",
    "6e6e80db-6587-4954-abeb-e29a1127a479.webp": "valorant_sg",
    "7061d229-616c-46d2-8034-4d0a2cd9382a.png": "ncsoft_ncoin_global",
    "71823adf-8f84-4d97-b14f-0951b3547ca8.jpg": "undawn",
    "71f3256f-57dd-45f5-81e3-52a6da9e04cd.jpg": "blood_strike",
    "7235d33f-2dad-4389-bb90-71c5fd257f2d.png": "onmyoji_arena",
    "73c3ff63-d207-4d4d-bfd2-508a70731df6.png": "r6_mobile_my",
    "747165f1-b51b-4dde-ae1a-01bb3b1b6cb9.webp": "pubg_mobile_manual",
    "7474b9c6-ab5c-42b8-b18c-b9d3366f282d.webp": "battlefieldtm_6_bfc",
    "7738cb93-cfb8-4e35-9cf0-658ed4ca1dc5.webp": "zing_card_vn",
    "77930b73-8dce-4bd5-a310-c2aecdc93aa2.jpg": "uni_in",
    "77d027a8-1e6e-4679-ab9e-b15137864ab8.webp": "wild_rift_sg",
    "77d54150-b208-404c-ac4f-b7e143dc627f.png": "free_fire_id",
    "78056467-80c0-4faf-851d-c9734cda9c9c.png": "arknight_endfield_login",
    "78b38712-5684-4647-ac3c-35653973580d.webp": "tomb_busters",
    "78bed9bc-c2a8-4840-a67d-b331f3e0286f.png": "civilization_eras_and_allies",
    "78fd25a7-d103-44d9-81ae-8206fe815b47.png": "free_fire_cis",
    "7960d420-7519-47a0-aa92-6ff707172e0b.png": "mirage_perfect_skyline",
    "79d3c563-cc01-48d8-b6e0-c0608712d25c.png": "oxide_survival_island",
    "79da1eb4-10c1-4075-bc1a-4015e3690661.jpg": "dunk_city_dynasty",
    "79db17f1-e6e8-49cd-832a-ad17198453ef.jpg": "slam_dunk",
    "7ab676df-9c32-4945-97b4-158de8e95660.jpg": "tft_mobile_th",
    "7bd04f7f-0ec4-4af3-a4a6-74115c35a739.jpg": "tinder_ad tinder_ae tinder_at tinder_az tinder_be tinder_bg tinder_bh tinder_br tinder_ca tinder_ch tinder_cl tinder_co tinder_cy tinder_cz tinder_dk tinder_dz tinder_ee tinder_eg tinder_es tinder_fi tinder_fr tinder_gr tinder_hk tinder_hr tinder_hu tinder_id tinder_ie tinder_in tinder_iq tinder_it tinder_jo tinder_kr tinder_kw tinder_kz tinder_lb tinder_lu tinder_lv tinder_ma tinder_mv tinder_mx tinder_my tinder_ng tinder_nl tinder_no tinder_nz tinder_om tinder_pe tinder_ph tinder_pl tinder_pt tinder_qa tinder_ro tinder_sa tinder_sg tinder_sk tinder_th tinder_tn tinder_uy tinder_uz tinder_vn tinder_za",
    "7ced4f08-4353-4d52-bbab-c62633898c10.webp": "codm_activision_ca",
    "7d41979d-47e7-4aaa-8ca9-38fd73614b9d.png": "carrom_gold",
    "7e3b28ab-e2e0-49a9-b78e-f725f6ecb94f.webp": "wild_rift_vn",
    "7e795078-c37e-4866-9828-8b5afb88c60a.jpg": "heesay",
    "7e844879-72c8-40ad-9415-1cc6ca6753bb.webp": "pubg_mobile",
    "80ed8299-6d40-4a04-8546-39b2531506ae.png": "likee",
    "816e40a9-dc05-458d-aaf4-1b354833818b.jpg": "afk_journey",
    "81e95f23-e454-4adc-ac45-82d57582c1f1.webp": "app_store_itunes_ae app_store_itunes_at app_store_itunes_au app_store_itunes_be app_store_itunes_br app_store_itunes_ch app_store_itunes_cn app_store_itunes_de app_store_itunes_es app_store_itunes_fi app_store_itunes_fr app_store_itunes_hk app_store_itunes_id app_store_itunes_ie app_store_itunes_in app_store_itunes_it app_store_itunes_jp app_store_itunes_lu app_store_itunes_mx app_store_itunes_nl app_store_itunes_no app_store_itunes_nz app_store_itunes_pl app_store_itunes_pt app_store_itunes_ru app_store_itunes_sa app_store_itunes_se app_store_itunes_tr app_store_itunes_uk app_store_itunes_us",
    "826f0c5a-a284-453e-8841-256dfe981981.png": "vision_plus_id",
    "838a76e0-512f-4f7e-aeba-57eb8d304c92.webp": "lita",
    "83a9c376-0c7e-4ffa-9747-bfc844ae4060.webp": "pubg_mobile_auto",
    "83faaaf9-4560-4370-a5ed-1dd6e7643493.jpg": "lifeafter",
    "83fd6aff-f1cd-45af-bbad-17dba0fa76af.jpg": "whiteout_survival",
    "845ccc8d-bd5f-41e5-937b-35479b38378b.jpg": "domino_cafe",
    "84b3d50e-5ca4-4446-a170-691c44153909.webp": "the_lord_of_the_rings_rise_to_war",
    "84e30b97-afef-447c-908e-13542a3014ef.png": "eve_echoes",
    "852f3039-a068-441a-8f12-6b64a4f797e6.webp": "teen_patti_gold",
    "8691382c-5f1f-4aa2-9f1a-455190aa18e4.webp": "magic_chess_gogo_ru",
    "87de24f3-69fd-493c-8293-3cfeaeb1660a.webp": "valorant_my",
    "88a57299-277e-4b8e-85cf-14f948d8723f.jpg": "meta_quest",
    "88a8526d-aa3a-4942-915b-e8001b682664.jpg": "adobe_digital_code",
    "89674c7d-0f52-4f5f-b059-731cee9d1206.jpg": "journey_renewed_fate_fantasy",
    "8a398e56-b096-4ab0-a1d3-8fc5701c2a21.jpg": "blood_strike_mena",
    "8abc7de5-0305-40aa-a082-47291ff791bb.jpg": "growtopia",
    "8be19f14-2f3a-4b74-8221-21ebab95ee28.webp": "wild_rift_ph",
    "8dfba14a-7c9e-4771-b771-a15e23d9143c.jpg": "harry_potter_magic_awakened",
    "8e02f40f-0101-490b-846a-385eeb7e1738.png": "free_fire_my_sg",
    "8f09a795-1b5a-4e76-b708-4005b32a55dc.png": "chamet",
    "8f3e967c-d135-414e-8b9e-8ac706db2f08.png": "podu",
    "8ff5894f-e635-4d1f-9e37-f8413908ec26.png": "modern_warships_naval_battles",
    "90a01770-d570-40e8-a8fa-344004d2fc3f.png": "free_fire_vn",
    "90d70b0a-6cd1-4640-9791-235576975f91.jpg": "tng_reload_pin_my",
    "90e4f2f8-3e61-46a2-b306-658445018861.webp": "ragnarok_crush",
    "91e91768-1cc6-4266-aef3-646e7472945f.webp": "the_division_resurgence",
    "92546385-99b4-4595-8aee-510e47dc7fc8.jpg": "crystal_of_atlan",
    "92dede20-1031-411d-891c-0d9b44141c0b.png": "ea_gift_cards_eu",
    "937bf50c-4ba4-4aca-adad-03cf002b7771.webp": "asphalt_9_legends",
    "93c3bbdc-50cf-4ccb-ba4f-8e502784e950.jpg": "tft_mobile_my",
    "94cf3342-5ed6-47f8-91b6-6e054f38cceb.jpg": "fashion_queen",
    "95538766-ac96-467d-9675-3d9e0baa7b1e.webp": "roblox_ae roblox_at roblox_au roblox_br roblox_ca roblox_ch roblox_dk roblox_eu roblox_fr roblox_global roblox_hk roblox_id roblox_jp roblox_mx roblox_my roblox_no roblox_nz roblox_pl roblox_sa roblox_se roblox_sg roblox_th roblox_uk roblox_us roblox_za",
    "95a49ef5-30cf-482a-a87a-dad160e66a62.png": "nexon_game_card",
    "988ed541-c0d7-4ad9-bc09-8f9a66b8e405.png": "free_fire",
    "98a70a8e-959e-4a5a-90b6-e92da4bfdb17.webp": "sword_of_justice_eu",
    "99124507-fcd9-476e-bea2-e10a65e86671.png": "mycard_my",
    "99b59be7-fb87-4e49-bdde-374b050f82a4.webp": "star_resonance",
    "99bdf100-0fc3-438c-9f9f-f288d4d35be1.webp": "magic_chess_gogo_global",
    "9aac875e-15b0-4e49-bb00-8a73c7ae93f7.png": "tik_tok_china tiktok_ae tiktok_cn tiktok_de tiktok_id tiktok_it tiktok_jp",
    "9abd8bce-9919-438e-a2ab-b251c7bdb964.webp": "free_fire_diamond_pins_eu_tr",
    "9afd27df-c036-4dc7-967b-88e3899b8b20.png": "sohacoin_vn",
    "9b130de5-901d-42a8-8e50-47616305e8ce.png": "guns_of_glory",
    "9be25633-eb14-46ee-b7ea-845ab36babc8.webp": "wild_rift_id",
    "9c503ca6-1027-4df2-a547-622aea08e5d7.jpg": "pubg_battlegrounds_global",
    "9cb26acf-6cdc-4b92-b0fa-5abd84acec4e.webp": "qq_coin_qb_direct",
    "9ce67235-9214-493f-bb5a-b2596952ab7e.jpg": "starfall_fantasy_neverland",
    "9d8e2d04-1cc6-4f5c-abaf-8195bac6f260.webp": "eafc_mobile_kh",
    "9e77520f-cdc1-4b86-9adc-4ea8f3e5a717.png": "arena_breakout",
    "9e8fb7de-d9ea-4752-acba-acd2034a2825.png": "ozon_ru",
    "9efc29a9-94e1-4983-9435-fadbba0553b6.webp": "mobile_legends_brazil mobile_legends_exclusive mobile_legends_global mobile_legends_indonesia mobile_legends_malaysia mobile_legends_philippines mobile_legends_singapore mobile_legends_special mobile_legends_turkey mobile_legends_united_states",
    "9f3d3ac5-0150-4217-bdae-a06da1a46e37.png": "seagm_global",
    "9f434ee0-c81f-48f6-a4fb-b105f627806a.png": "surfshark",
    "9f9d120b-b8ad-4036-b0e0-2774cd6949b7.png": "project_entropy",
    "9fb2cc9c-f30c-4a3a-9245-c2779ab7c25e.png": "free_fire_ph",
    "a037873d-fc84-442b-8d5c-bb6725c70524.png": "kuroko_street_rivals",
    "a0df8b6c-ccc3-4aeb-81fe-c6148a862bde.jpg": "hero_clash",
    "a0ecb655-e490-4196-8288-489f8bc33064.jpg": "love_and_deepspace love_and_deepspace_login",
    "a16c834d-583e-4226-9caf-c493dc2000f8.webp": "valorant_kh",
    "a17b6665-e1f8-4d3a-8041-8a7a4977e39b.webp": "acash_my",
    "a1c62f77-82f3-4b37-95a4-7e126b231598.jpg": "mu_ascension",
    "a255fbf4-2b9c-42b8-b808-0fc7981250b6.png": "sausage_man",
    "a25dad68-6f6b-4d07-aeaf-b09f54b04895.jpg": "legends_of_runeterra_thailand",
    "a3e784c9-df8b-41d8-b15e-c1cbfddbb4b5.webp": "nimo_tv",
    "a6541b9f-70af-476a-a6ce-2c7c5b6f92d8.png": "my_singing_monsters",
    "a7b8a92a-0139-4f2f-b1f4-2bab98eb584f.jpg": "lol_id",
    "a8447840-5c56-4fba-9f2c-69e185da1c7d.webp": "honkai_impact_3rd_asia honkai_impact_3rd_id honkai_impact_3rd_kh honkai_impact_3rd_my honkai_impact_3rd_ph honkai_impact_3rd_sg honkai_impact_3rd_th",
    "a8934d52-282f-4c3f-86bb-7a0e5d79e795.jpg": "overmortal_idle_sea",
    "a972465d-e230-4810-a779-3c2f06f198ac.jpg": "unipin_in",
    "a9ce40db-c583-46e2-b7bc-098af5fa8fc3.jpg": "legends_of_runeterra_malaysia",
    "a9cf4de5-b424-4c43-896a-dc4d9b773dd6.jpg": "life_makeover_global",
    "a9e2f8e0-fb13-461f-8978-c0ee38f4db69.png": "ea_gift_cards_us",
    "aa1383d2-cc9d-48ec-8514-9198f9a66177.webp": "sword_of_justice_na",
    "aad5562d-56eb-4a86-bb4e-3bba6bdcc761.png": "legacy_of_discord_furiouswings",
    "ab1d1fb6-f65b-4543-98df-7353604ac4a9.jpg": "ace_racer",
    "ac1dda33-49a5-4a16-bb19-05e05d764130.jpg": "steam_wallet_ae steam_wallet_ar steam_wallet_br steam_wallet_cl steam_wallet_co steam_wallet_cr steam_wallet_eu steam_wallet_global steam_wallet_hk steam_wallet_id steam_wallet_in steam_wallet_kr steam_wallet_kw steam_wallet_mx steam_wallet_my steam_wallet_pe steam_wallet_ph steam_wallet_pl steam_wallet_qa steam_wallet_sa steam_wallet_sg steam_wallet_th steam_wallet_tr steam_wallet_tw steam_wallet_us steam_wallet_uy steam_wallet_vn steam_wallet_za",
    "acf086c5-7a70-4e32-954d-26b08d0a834c.jpg": "once_human",
    "adfdcf27-0713-4649-849a-7b86db01807a.png": "astropay_bd astropay_br astropay_cn astropay_eg astropay_id astropay_in astropay_jp astropay_my astropay_ph astropay_pk astropay_sg astropay_th astropay_us",
    "afb7bfbf-edc5-405a-a9e1-b566f80bf040.jpg": "bilibili_id bilibili_my bilibili_ph bilibili_th",
    "afdb0922-e2a5-45d6-b1b0-9c65a9af6ad5.png": "twitch_uk",
    "afffd937-d61b-46c3-a788-72df8aa260a2.jpg": "black_clover_m",
    "b016912a-d8c7-43fc-9c36-70a5695da370.png": "delta_force",
    "b0bda483-923d-43e0-a580-48b92ffb2adf.jpg": "yalla_live",
    "b1262eb4-609e-4fd8-83a2-c3d2d0f8a34e.webp": "bullet_echo",
    "b2bdd5fc-26c1-4434-a9d9-27080d56f5e3.png": "free_fire_br",
    "b2cd3fee-b683-4ade-bdd8-e541384ca3a0.png": "kinguin_pl",
    "b3390178-abd9-46e3-81b7-f295e29486fb.jpg": "hakuna",
    "b57c223e-a206-45da-aba4-fe414abd5090.jpg": "sword_of_fire_and_ice",
    "b5a7922b-1b28-45e6-8fde-e46a7007ad5c.webp": "funcard_vn",
    "b5b166e3-7232-462f-a48e-dc983a87ba9e.png": "nintendo_br nintendo_ca nintendo_de nintendo_eu nintendo_hk nintendo_jp nintendo_pl nintendo_switch_br nintendo_switch_ch nintendo_switch_eu nintendo_switch_mx nintendo_switch_pl nintendo_switch_us nintendo_uk nintendo_us",
    "b698ff4a-a420-44a7-86e9-4a9a096c5ed1.jpg": "legends_of_runeterra_singapore",
    "b6e3e6b5-dddf-4e93-aa96-363dedbe63f2.webp": "exitlag_gift_card_tier_2_global",
    "b6f49c82-0932-49d3-95db-de7717b08cb0.png": "ballistic_hero_vng",
    "b7685d04-e221-4a9b-80e5-e65ed0090884.webp": "metal_slug_awakening_sea",
    "b76ee6af-a1fe-4a47-a126-80baeccda625.png": "identity_v",
    "b7bbd614-5eeb-42f9-97f2-07b165dba611.webp": "watcher_of_realms",
    "b827b32b-6d74-4948-bab8-3b93933c4581.png": "free_fire_tw",
    "b8e9cbe2-31eb-421a-be52-5702a649f704.png": "jade_dynasty_new_fantasy",
    "b982ac77-4f3b-41a3-bca9-68b2353988c8.png": "free_fire_eu",
    "ba4efd7a-2e4d-441b-891a-a9d6195b1e2e.png": "microsoft_windows",
    "ba9bf649-7295-41e3-9957-d8b8a22db40d.jpg": "hatsune_miku_colorful_stage",
    "bada4167-15ee-46ba-a7f3-6bc4e6278bc4.webp": "jawaker",
    "bb5e6027-f7cb-47ee-abce-a56f27afa1d7.png": "parchis_club",
    "bb66e029-20a0-4600-9d97-bc157f4fb5cf.webp": "roblox_ru",
    "be043124-a4b1-406a-9a7a-e937b3a5fd20.jpg": "playstation_ae playstation_ar playstation_at playstation_au playstation_be playstation_bh playstation_br playstation_ca playstation_ch playstation_cz playstation_de playstation_dk playstation_es playstation_fi playstation_fr playstation_hk playstation_hr playstation_hu playstation_id playstation_ie playstation_it playstation_jp playstation_kw playstation_lb playstation_lu playstation_my playstation_nl playstation_no playstation_nz playstation_om playstation_pl playstation_pt playstation_qa playstation_ro playstation_sa playstation_sg playstation_sk playstation_th playstation_tr playstation_uk playstation_us playstation_za",
    "beaef350-2c25-4b22-9853-f1ecb19dfc06.webp": "valorant_ph",
    "bef91073-5133-4108-8d9c-2ce786fdc83f.webp": "age_of_magic",
    "bfd32302-5757-4324-a4e9-b934961a3d04.jpg": "legends_of_runeterra_philippines",
    "c091ada5-b5b2-41f1-a72f-432cf39057ae.webp": "mobile_legends_voucher_global",
    "c09edeff-0c49-4d48-a120-46125f010baf.png": "8_ball_pool",
    "c1091e6d-a8fc-45a5-8317-6f8fc42a3061.webp": "zenless_zone_zero_global zenless_zone_zero_ru zenless_zone_zero_us",
    "c1c65196-bf12-4fdf-82d3-3d2dfe1a09d7.webp": "yalla_ludo_gold",
    "c27e0c7c-6c87-4b9c-94bd-0149fce8ac85.jpg": "league_of_legends_ae league_of_legends_bh league_of_legends_br league_of_legends_by league_of_legends_eu league_of_legends_kw league_of_legends_my league_of_legends_ph league_of_legends_sg league_of_legends_tr league_of_legends_ua league_of_legends_uk league_of_legends_us",
    "c2dd7b1f-1228-4a14-8408-a996d2b0944b.webp": "lineage_w",
    "c47974c5-6669-4cd4-83a3-f0f98905692d.png": "kinguin_eu",
    "c4f98182-fdce-4c91-9a05-57af2843a6a7.jpg": "racing_master_latam",
    "c4fe0f93-6d1a-4ecb-89cd-9aaba5f1434b.webp": "valorant_id",
    "c4fed241-443c-4d67-8bc8-08a1b7832ce9.webp": "moonlight_blade_m",
    "c53d5928-28e5-4c6c-b14c-bfa34e76bae9.webp": "arena_breakout_infinite",
    "c63d4d95-ccc3-42f8-98f3-26b2cddd6842.png": "soul_land_new_world",
    "c6de429a-a10a-4ea7-b754-9a5b6ee34e8e.png": "destiny_rising",
    "c7499830-a25b-40e7-9adc-3bb47dcbe0d9.webp": "honor_of_kings",
    "c7a25fb5-5240-43e6-a3ea-c396af9efb46.webp": "division_resurgence",
    "c7bcad91-5222-47da-90bf-ed81ca9ecddd.jpg": "badlanders",
    "c7fb73ab-b3b1-4154-a9c2-f1c8ce7b91ce.webp": "exitlag_gift_card_tier_1_global exitlag_ru",
    "c856647f-7224-4a6a-9735-df796568368e.jpg": "wuthering_waves",
    "c8fd33c8-7c0f-4d2c-a27b-840a971b3eb3.png": "ea_gift_cards_uk",
    "c9d3e64a-2fc8-4f59-9c50-cb1c8f1ef2af.jpg": "valorant_au valorant_ca valorant_in valorant_nz valorant_tr",
    "cbcb9d39-9dc0-415f-bc1a-ca9546f681fb.png": "knives_out",
    "cc2dfb0f-fb4d-4773-adb4-9f6ae74c3589.webp": "black_clover_m",
    "cc91d3ea-ece7-44fe-bb93-0e6b4ac4bc8c.png": "rewarble_usd",
    "ccff4bc7-871d-4576-b885-1de5f225295c.jpg": "warborne_above_ashes",
    "cd0750ed-6e04-40d9-8a8d-5fa5e042e9e5.webp": "dragon_raja_sea",
    "ce094f9f-2343-4223-a809-dd56ca266a26.png": "twitch_eu",
    "cf012d90-eb43-491d-bf18-f1caccbcf678.webp": "heartopia",
    "d0c6baa5-109e-4be2-bd36-c8395b020872.png": "kinguin_us",
    "d0ebe9ff-a56d-42ea-9c7d-163c433ee491.webp": "codm_activision_sa",
    "d1733d47-091d-4dc3-9725-65a4c7757d2d.jpg": "lol_my",
    "d1a8aca0-95b0-4462-a6b9-0885278b3daa.webp": "codm_garena_sgmy",
    "d217c4f7-94c0-4a82-bb87-41f84fa8e242.png": "lords_mobile",
    "d24aac12-93a9-463e-ac2c-8e2128f2db7f.png": "cats_crash_arena_turbo_stars",
    "d2842985-be7d-4f87-adad-2e45b226f76c.jpg": "revelation_infinite_journey",
    "d2cd5bdd-a82a-4cdb-b13b-19ee5d50fb96.jpg": "tom_clancy_s_rainbow_six_extraction_xbox_react_credits",
    "d440607b-e69f-4359-827c-ecb4b2a26d89.png": "punishing_gray_raven",
    "d59f3110-9d32-40e2-b396-a521d07e22bf.jpg": "standoff_2_global",
    "d79c04b6-2cfc-4b1c-93a2-f07d6632779b.webp": "ludus_strategy_pvp",
    "d83a6390-68ba-489c-aa2f-3354aa8ab09c.jpg": "appota_vn",
    "d9af45ec-db59-479a-8c48-80ceaa271da7.webp": "karma_koin_ca",
    "dbc6197b-aea6-4a00-b9e7-63734627ee7b.jpg": "legends_of_runeterra_united_states",
    "dc8e5cb7-7c39-410a-a309-41b6d7b5423f.webp": "clash_of_plants",
    "dd5c9e7b-7b02-4641-9e08-7b8b7773d3db.png": "airbnb_at airbnb_au airbnb_be airbnb_br airbnb_ca airbnb_de airbnb_es airbnb_fr airbnb_ie airbnb_it airbnb_mx airbnb_nz airbnb_pt airbnb_se airbnb_uk airbnb_us",
    "dd60dfd6-d09b-43f4-87b7-4b6597ba416f.jpg": "dragonheir_silent_gods",
    "ddae376a-2af7-480b-9f49-d13e938a0439.webp": "ragnarok_m_eternal_love_sea",
    "ddf3a946-561f-46f1-a0a5-41d41d05aba5.webp": "valorant_vn",
    "de00f298-0c02-4e20-8fd8-4e05214f2b66.jpg": "tft_mobile_sg",
    "de3b0126-925a-42c7-a39a-680b7390892d.jpg": "overmortal_idle_global",
    "de8997dc-80b6-40e4-8e21-70c9f070a84e.jpg": "echocalypse_scarlet_covenant",
    "e1ed3ac5-290e-4e33-9f56-4bf44a69065c.jpg": "ulala_idle_adventure",
    "e20187f4-f253-41a6-8406-1f29cf890dd4.png": "eggy_party",
    "e3084b9f-40bb-424d-b455-e91fd5c9cdf0.png": "undawn_garena_global",
    "e4cef1ef-a5c3-4974-bf1a-ab12e32cbbae.jpg": "tft_mobile_ph",
    "e5c967af-b2ff-40b2-84b1-506f17ec5a0f.webp": "duet_night_abyss",
    "e5fb4e18-1946-44c0-a321-7e081d3b7c56.jpg": "lol_th",
    "e64a1969-9cf8-4675-add7-bf43e37057c3.png": "uber_us",
    "ea60b266-e749-45fd-b4f8-57f6362ecdab.png": "discord_global",
    "ea7d0df4-0d3e-480f-b158-90db42bf5693.webp": "exitlag_mobile_gift_card_tier_3_global",
    "eb1baa2c-d63d-49c6-9180-da422955f21e.png": "conquer_online",
    "eb2a7fbb-e290-45a8-a137-48893f40b626.jpg": "solo_leveling_arise_login",
    "eb751b0c-43bd-4879-8f92-b5252070abc6.webp": "scoin_vn",
    "ec391f75-bc66-48bb-a38f-ed9556c92e17.webp": "spring_valley_farm_adventures",
    "ece60fce-2fd6-401e-9243-d512973e792a.webp": "wesing",
    "ee4f71b8-f659-446b-9130-3b8c7f71b9dd.png": "r6_mobile_us",
    "ee7d7151-1617-45cb-8dc1-047b665ee964.webp": "netease_pay_aed netease_pay_bdt netease_pay_brl netease_pay_cad netease_pay_clp netease_pay_cop netease_pay_eur netease_pay_idr netease_pay_krw netease_pay_mmk netease_pay_mxn netease_pay_myr netease_pay_ngn netease_pay_rub netease_pay_sar netease_pay_sgd netease_pay_thb netease_pay_try netease_pay_usd netease_pay_vnd",
    "ef68d0c6-ed68-4f1f-afa4-ae4633129bc6.jpg": "rememento_white_shadows",
    "f0dd115d-de8c-424d-8b74-28c55a427908.webp": "infinite_lagrange",
    "f1586cbd-72e8-4247-9cb6-f8dae36720c1.jpg": "stumble_guys",
    "f1e8e26e-fa1a-4a73-8387-b57c62694518.jpg": "imo",
    "f22271ce-433e-4e05-8304-16a0aa882de8.jpg": "tft_mobile_id",
    "f2a5b476-5334-42ec-a15f-115b7397c164.jpg": "dragon_nest_m_sea",
    "f3566580-87ce-4463-8072-efc1d88c8e07.png": "mu_origin_3_asia",
    "f3572681-c1b4-4791-8d62-5c209b33d545.webp": "tango",
    "f47f3ea8-cbc9-4413-a1f4-80d6f80d4390.webp": "fortnite_ae fortnite_ch fortnite_de fortnite_eu fortnite_fr fortnite_ie fortnite_no fortnite_sa fortnite_se fortnite_uk fortnite_us",
    "f4d18639-cdfc-4fa7-a33c-d644c2e0987f.jpg": "love_nikki",
    "f5054832-c3f5-4bdb-8140-6c27014ec7a0.jpg": "lol_sg",
    "f51b5205-3459-419b-a8d1-7b75e207697e.jpg": "kingshot",
    "f5fe666e-29e7-4a47-8d52-543de862c226.png": "poppo_live",
    "f715e271-1358-43f8-9a8e-abd014bb8185.png": "golden_spatula",
    "f8113dad-cebc-437b-aec9-66e559396242.webp": "wild_rift_my",
    "f88e7baf-3895-4b15-8a97-e45f2e13c022.jpg": "isekai_feast_tales_of_recipes",
    "fa020ab7-4736-44aa-a639-b31be8a2e2d7.webp": "pubg_new_state",
    "fa0b0d84-aacb-4287-b49d-9c53c4d48e94.jpg": "marvel_mystic_mayhem",
    "faa2f8dd-9c3a-4c3d-8cd6-c09506867d05.png": "r6_mobile_global",
    "fb0dfb6f-85d2-402a-8c49-a2747d264cbe.jpg": "vip_jalsat",
    "fbe82c7e-8411-4699-bb9c-34060754ed7f.jpg": "telegram_stars",
    "fcc14de5-421b-4f84-8d45-98704fde82c6.jpg": "arena_of_valor_eu",
    "fcd84ae3-439d-4015-ad01-48d07b4de679.jpg": "enhypen_world",
    "fcdad8dc-0d0c-418c-94b1-c955b7086baa.jpg": "stella_sora",
    "fd07512d-6090-42f1-967f-b295cd3ce12a.webp": "yalla_ludo_diamond",
    "fda1925b-3291-4c23-9c1f-49816613f68b.png": "mecha_break",
    "ff454ca0-4472-410b-a1fc-27fb1d4e7508.jpg": "starmaker_global",
    "ffece318-b3d3-49fb-a80e-49d355985d07.webp": "ragnarok_m_classic_sea",
}

ICON_OF = {cid: f for f, ids in COVERS.items() for cid in ids.split()}

# Titles that are one brand under two spellings.
SIBLING_ALIASES = {
    "mobile legends bang bang": "mobile legends",
    "tango live": "tango",
    "garena free fire": "free fire",
}


def title_key(name: str) -> str:
    """«PlayStation (IN)» → «playstation»; «Delta Force (Voucher)» → «delta force»."""
    t = re.sub(r"\(.*?\)", " ", name).lower()
    t = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", t)).strip()
    return SIBLING_ALIASES.get(t, t)


async def brands() -> list[dict[str, Any]]:
    """Every brand with its title, logo and active fzr category ids."""
    async with get_session_factory()() as db:
        rows = await db.execute(text("""
            select b.id, b.slug, t.name, b.logo_url,
                   coalesce(array_agg(distinct m.external_product_id)
                            filter (where m.supplier_slug = 'fzr' and m.is_active), '{}') fzr
              from brands b
              join brand_translations t on t.brand_id = b.id and t.locale = 'ru'
              left join products p on p.brand_id = b.id
              left join skus s on s.product_id = p.id
              left join sku_supplier_mapping m on m.sku_id = s.id
             group by b.id, b.slug, t.name, b.logo_url
             order by b.slug
        """))  # fmt: skip
        return [dict(r) for r in rows.mappings().all()]


async def fetch_image(client: httpx.AsyncClient, url: str) -> tuple[bytes, str] | None:
    """(bytes, content_type), or ``None`` when it is not an image we store."""
    resp = await client.get(url)
    if resp.status_code != 200:
        return None
    content_type = resp.headers.get("content-type", "").split(";")[0].strip()
    if content_type not in IMAGE_MIME or len(resp.content) > get_settings().media_max_upload_bytes:
        return None
    return resp.content, content_type


async def store(body: bytes, content_type: str) -> str:
    """Upload to the media bucket; returns the public URL."""
    key = _build_key("brand_logo", content_type)
    settings = get_settings()
    await asyncio.to_thread(
        get_s3_client().put_object,
        Bucket=settings.r2_bucket_media,
        Key=key,
        Body=body,
        ContentType=content_type,
        CacheControl="public, max-age=31536000, immutable",
    )
    return public_url_for(key)


async def set_logo(brand_id: str, url: str) -> bool:
    async with get_session_factory()() as db, db.begin():
        brand = await db.get(Brand, brand_id)
        if brand is None or brand.logo_url is not None:
            return False
        brand.logo_url = url
        return True


PENDING = "(будет)"  # dry-run marker: this brand gets a cover when APPLY runs


async def own_covers(rows: list[dict[str, Any]]) -> int:
    """Pass 1: a brand's own fzr cover. Returns how many logos were written."""
    own: dict[str, list[dict[str, Any]]] = defaultdict(list)  # cover file -> brands
    for b in rows:
        if b["logo_url"]:
            continue
        cover = next((ICON_OF[c] for c in b["fzr"] if c in ICON_OF), None)
        if cover:
            own[cover].append(b)
    print(f"Своя обложка у fzr: {sum(len(v) for v in own.values())} брендов, {len(own)} файлов")
    if not APPLY:
        for bs in own.values():
            for b in bs:
                b["logo_url"] = PENDING
        return 0
    written = 0
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for cover, bs in own.items():
            try:
                got = await fetch_image(client, MEDIA + cover)
            except httpx.HTTPError as exc:
                print(f"  ! {cover}: {exc!s:.80}")
                continue
            if got is None:
                print(f"  - {cover}: не картинка или слишком большая")
                continue
            public = await store(*got)
            for b in bs:
                if await set_logo(b["id"], public):
                    b["logo_url"] = public
                    written += 1
            await asyncio.sleep(0.2)
    return written


async def siblings(rows: list[dict[str, Any]]) -> tuple[int, list[str]]:
    """Pass 2: borrow the logo of a brand with the same title. Returns (copied, left)."""
    by_title: dict[str, str] = {}
    for b in rows:
        if b["logo_url"]:
            by_title.setdefault(title_key(b["name"]), b["logo_url"])
    copied, left = 0, []
    for b in rows:
        if b["logo_url"]:
            continue
        url = by_title.get(title_key(b["name"]))
        if url is None:
            left.append(b["slug"])
        elif not APPLY or (url != PENDING and await set_logo(b["id"], url)):
            copied += 1
    return copied, left


async def main() -> None:
    rows = await brands()
    print(f"Брендов без логотипа: {sum(1 for b in rows if not b['logo_url'])}")
    written = await own_covers(rows)
    copied, left = await siblings(rows)
    print(f"Скопировано от соседа: {copied}")
    print(f"Остаются без логотипа ({len(left)}): {', '.join(left)}")
    print(f"Загружено: {written}" if APPLY else "APPLY не задан — ничего не записано.")


if __name__ == "__main__":
    asyncio.run(main())
