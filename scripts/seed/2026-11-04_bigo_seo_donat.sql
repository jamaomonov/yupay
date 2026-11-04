-- Bigo Live: «донат» in the search title, description and short description.
--
-- 2026-11-04: for «bigo донат» / «bigo danat» Google shows multishop.uz
-- («Bigo Live — купить донат…») and not us; our page never said «донат».
-- Uzbek speakers write it «danat»/«donat». A NULL short description keeps the current one. Idempotent.

BEGIN;

UPDATE brand_translations bt SET
  seo_title = v.seo_title,
  seo_description = v.seo_description,
  short_description = coalesce(v.short_description, bt.short_description)
FROM brands b, (VALUES
  ('ru',
   $t$Bigo Live донат — купить алмазы Биго Лайв за сумы$t$,
   $t$Донат в Bigo Live по Bigo ID, без пароля: алмазы Биго Лайв за сумы через Click, Payme, Uzum или Paynet. Зачисление автоматическое.$t$,
   $t$Донат в Bigo Live: алмазы от 10 до 10 000 по Bigo ID для подарков в эфирах. Оплата в сумах через Click, Payme, Uzum и Paynet, без пароля.$t$),
  ('en',
   $t$Bigo Live top up — buy Bigo diamonds for soʻm in Uzbekistan$t$,
   $t$Bigo Live diamonds by Bigo ID, no password. Pay in soʻm with Click, Payme, Uzum or Paynet; credited automatically.$t$,
   NULL),
  ('uz',
   $t$Bigo Live donat — olmoslarni soʻmga sotib olish$t$,
   $t$Bigo Live donat: olmoslar Bigo ID orqali, parolsiz. Click, Payme, Uzum yoki Paynet orqali soʻmda toʻlov, avtomatik tushadi.$t$,
   NULL::text)
) AS v(locale, seo_title, seo_description, short_description)
WHERE b.slug = 'bigo-live' AND bt.brand_id = b.id AND bt.locale = v.locale;

COMMIT;
