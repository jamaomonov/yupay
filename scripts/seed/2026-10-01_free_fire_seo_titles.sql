-- Free Fire brand page: search title and description (migration 0092).
--
-- Google Keyword Planner, Uzbekistan, 2026-10-01: the game is searched as
-- «ff» / «free fire» (10k–100k) and «free fire max» (1k–10k); the buying query
-- is English — «free fire diamond», «ff diamond(s)», «free fire diamond id /
-- uid» at 100–1k. «фри фаер» is 100–1k; Russian buying phrasings («алмазы фри
-- фаер», «донат фри фаер») and Uzbek «free fire olmos» are 10–100. The same
-- account plays Free Fire MAX, so the description says so.
--
-- Run after the deploy that carries 0092. Idempotent.

BEGIN;

UPDATE brand_translations bt SET
  seo_title = v.seo_title,
  seo_description = v.seo_description
FROM brands b, (VALUES
  ('free-fire', 'ru',
   'Алмазы Free Fire (фри фаер) — купить в Узбекистане за сумы',
   'Алмазы Free Fire и Free Fire MAX по ID игрока, зачисление автоматическое. Подписка и наборы. Оплата в сумах через Click, Payme или Uzum, без пароля.'),
  ('free-fire', 'en',
   'Free Fire diamonds (FF) — top up in Uzbekistan for soʻm',
   'Buy Free Fire and Free Fire MAX diamonds by player ID, credited automatically. Membership and bundles too. Pay in soʻm with Click, Payme or Uzum. No password.'),
  ('free-fire', 'uz',
   'Free Fire olmoslari (FF diamonds) — soʻmda sotib olish',
   'Free Fire va Free Fire MAX olmoslari oʻyinchi ID orqali, avtomatik tushadi. Obuna va toʻplamlar ham bor. Click, Payme yoki Uzum orqali soʻmda toʻlov, parolsiz.')
) AS v(slug, locale, seo_title, seo_description)
WHERE b.slug = v.slug AND bt.brand_id = b.id AND bt.locale = v.locale;

COMMIT;
