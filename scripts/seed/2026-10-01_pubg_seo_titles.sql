-- PUBG Mobile brand page: search title and description (migration 0092).
--
-- Google Keyword Planner, Uzbekistan, 2026-10-01: the buying query is English —
-- «pubg uc» / «uc pubg» / «pubg mobile uc» at 1k–10k a month, «pubg uc top uz»
-- 100–1k; the game is «pubg» / «pubg mobile» (10k–100k), «пабг» / «пабг
-- мобайл» 100–1k. Russian buying queries («купить uc», «донат пабг», «юси
-- пабг») are 10–100 in Uzbekistan (unlike Russia, where «юси» is common);
-- Uzbek «pubg uc sotib olish» 10–100. «midasbuy» is 100k–1M — a guide, not a
-- title. The template «PUBG Mobile — пополнение в Узбекистане» carried no «UC».
--
-- Run after the deploy that carries 0092. Idempotent.

BEGIN;

UPDATE brand_translations bt SET
  seo_title = v.seo_title,
  seo_description = v.seo_description
FROM brands b, (VALUES
  ('pubg-mobile', 'ru',
   'UC PUBG Mobile (пабг) — купить в Узбекистане за сумы',
   'UC для PUBG Mobile по ID игрока, зачисление автоматическое. Royale Pass и Prime. Оплата в сумах через Click, Payme или Uzum, без пароля.'),
  ('pubg-mobile', 'en',
   'PUBG Mobile UC — top up in Uzbekistan for soʻm',
   'Buy PUBG Mobile UC in Uzbekistan by player ID, credited automatically. Royale Pass and Prime too. Pay in soʻm with Click, Payme or Uzum. No password.'),
  ('pubg-mobile', 'uz',
   'PUBG Mobile UC — Oʻzbekistonda soʻmga sotib olish',
   'PUBG Mobile uchun UC oʻyinchi ID orqali, avtomatik tushadi. Royale Pass va Prime ham bor. Click, Payme yoki Uzum orqali soʻmda toʻlov, parolsiz.')
) AS v(slug, locale, seo_title, seo_description)
WHERE b.slug = v.slug AND bt.brand_id = b.id AND bt.locale = v.locale;

COMMIT;
