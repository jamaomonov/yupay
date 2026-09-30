-- Roblox brand page: search title and description (migration 0092).
--
-- Google Keyword Planner, Uzbekistan, 2026-10-01: «robux» 1k–10k; «roblox gift
-- card», «buy robux», «roblox robux», «купить робуксы», «робуксы» and — the first
-- Uzbek buying query with real volume in this research — «robux sotib olish»
-- are 100–1k each; «roblox com redeem» is 1k–10k (buyers redeeming a card, which
-- is what ours are). The voucher template «Roblox — купить в Узбекистане» named
-- neither Robux nor a gift card. Denominations 50–24,000 Robux (2026-10-01).
--
-- Run after the deploy that carries 0092. Idempotent.

BEGIN;

UPDATE brand_translations bt SET
  seo_title = v.seo_title,
  seo_description = v.seo_description
FROM brands b, (VALUES
  ('roblox', 'ru',
   'Робуксы (Robux) — купить подарочную карту Roblox в Узбекистане',
   'Подарочные карты Roblox на 50–24 000 Robux: код приходит на почту после оплаты, активация на roblox.com/redeem. Оплата в сумах через Click, Payme или Uzum, без пароля.'),
  ('roblox', 'en',
   'Buy Robux in Uzbekistan — Roblox gift card for soʻm',
   'Roblox gift cards for 50 to 24,000 Robux: the code arrives by email after payment; redeem it at roblox.com/redeem. Pay in soʻm with Click, Payme or Uzum. No password.'),
  ('roblox', 'uz',
   'Robux sotib olish — Roblox sovgʻa kartasi soʻmda',
   '50 dan 24 000 Robux gacha Roblox sovgʻa kartalari: kod toʻlovdan keyin pochtaga keladi, roblox.com/redeem da faollashtiriladi. Click, Payme yoki Uzum orqali soʻmda toʻlov, parolsiz.')
) AS v(slug, locale, seo_title, seo_description)
WHERE b.slug = v.slug AND bt.brand_id = b.id AND bt.locale = v.locale;

COMMIT;
