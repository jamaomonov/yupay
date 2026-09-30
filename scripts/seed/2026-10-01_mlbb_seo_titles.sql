-- Mobile Legends brand pages: search titles and descriptions (migration 0092).
--
-- Google Keyword Planner, Uzbekistan, 2026-09-30: the buying query is English —
-- «mlbb diamond» / «mobile legends diamond» at 100–1k a month, with a long tail
-- of «recharge», «ml diamond», «cheap ml diamonds»; the game itself is searched
-- as «mlbb» / «mobile legends» (1k–10k). Russian buying queries («алмазы млбб»,
-- «купить алмазы млбб», «донат млбб») are 10–100 each; Uzbek («mlbb olmos»)
-- is near zero. The template title «Mobile Legends — пополнение в Узбекистане»
-- carried none of «diamonds», «MLBB» or «алмазы».
--
-- Titles stay under ~62 characters (the page adds « | yupay»); descriptions
-- under ~170. Run after the deploy that carries 0092 — the columns do not
-- exist before it. Idempotent.

BEGIN;

UPDATE brand_translations bt SET
  seo_title = v.seo_title,
  seo_description = v.seo_description
FROM brands b, (VALUES
  ('mobile-legends', 'ru',
   'Алмазы Mobile Legends (MLBB) — купить в Узбекистане за сумы',
   'Алмазы Mobile Legends (млбб) по ID игрока и ID сервера, зачисление автоматическое. Оплата в сумах через Click, Payme или Uzum, без пароля.'),
  ('mobile-legends', 'en',
   'Mobile Legends diamonds (MLBB) — top up in Uzbekistan',
   'Buy MLBB diamonds in Uzbekistan: recharge Mobile Legends by player ID and server ID, credited automatically. Pay in soʻm with Click, Payme or Uzum. No password.'),
  ('mobile-legends', 'uz',
   'Mobile Legends olmoslari (MLBB diamonds) — soʻmda sotib olish',
   'MLBB olmoslari oʻyinchi ID va server ID orqali, avtomatik tushadi. Click, Payme yoki Uzum orqali soʻmda toʻlov, parolsiz.'),
  ('mobile-legends-ru', 'ru',
   'Алмазы Mobile Legends RU (MLBB Россия) — купить за сумы',
   'Алмазы для российского аккаунта Mobile Legends (млбб) по ID игрока и ID сервера. Оплата в сумах через Click, Payme или Uzum, без пароля.'),
  ('mobile-legends-ru', 'en',
   'Mobile Legends RU diamonds (MLBB Russia) — top up in soʻm',
   'MLBB diamonds for a Russian Mobile Legends account, by player ID and server ID. Pay in soʻm with Click, Payme or Uzum. No password.'),
  ('mobile-legends-ru', 'uz',
   'Mobile Legends RU olmoslari (MLBB Rossiya) — soʻmda',
   'Rossiya Mobile Legends akkaunti uchun MLBB olmoslari, oʻyinchi ID va server ID orqali. Click, Payme yoki Uzum orqali soʻmda toʻlov, parolsiz.')
) AS v(slug, locale, seo_title, seo_description)
WHERE b.slug = v.slug AND bt.brand_id = b.id AND bt.locale = v.locale;

COMMIT;
