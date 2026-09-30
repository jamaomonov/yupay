-- Steam brand page: search title and description (migration 0092).
--
-- Google Keyword Planner, Uzbekistan, 2026-10-01: unlike the games, Steam top-up
-- is searched in Russian — «пополнить стим» / «пополнения стима» at 100–1k a
-- month, «стим» 1k–10k; English «steam top up», «steam wallet», «steam balance»
-- and «пополнить стим без комиссии» / «пополнить стим в узбекистане» are 10–100;
-- Uzbek («steam toldirish») is near zero. Wordstat shows «без комиссии» as a
-- large query across the CIS (22.5k), and 0% commission is what we offer.
--
-- The description gives no maximum amount (the limit is $500 since 2026-10-01;
-- the copy said $300 until 2026-10-01_steam_limit_500.sql) — it can change again.
--
-- Run after the deploy that carries 0092. Idempotent.

BEGIN;

UPDATE brand_translations bt SET
  seo_title = v.seo_title,
  seo_description = v.seo_description
FROM brands b, (VALUES
  ('steam', 'ru',
   'Пополнить Steam (стим) без комиссии — в Узбекистане за сумы',
   'Пополнение баланса Steam по логину, без пароля: любая сумма от $1, 0 % комиссии. Оплата в сумах через Click, Payme или Uzum. Для аккаунтов Узбекистана и СНГ.'),
  ('steam', 'en',
   'Steam top up in Uzbekistan — no fee, pay in soʻm',
   'Top up your Steam wallet by login, no password: any amount from $1, 0% commission. Pay in soʻm with Click, Payme or Uzum. For Uzbekistan and CIS accounts.'),
  ('steam', 'uz',
   'Steam hisobini toʻldirish — komissiyasiz, soʻmda',
   'Steam balansini login orqali, parolsiz toʻldirish: $1 dan istalgan summa, 0 % komissiya. Click, Payme yoki Uzum orqali soʻmda toʻlov. Oʻzbekiston va MDH akkauntlari uchun.')
) AS v(slug, locale, seo_title, seo_description)
WHERE b.slug = v.slug AND bt.brand_id = b.id AND bt.locale = v.locale;

COMMIT;
