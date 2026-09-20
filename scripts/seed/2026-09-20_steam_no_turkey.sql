-- Steam top-ups: drop Turkey from every published region list.
--
-- The owner established 2026-09-20 that we cannot top up a Turkish-region
-- Steam wallet. The claim was live in fifteen places across three locales:
--
--   * `brand_translations` for `steam` — `description` and `instructions`, ru/en/uz;
--   * `brand_faq_translations` — "В каком регионе должен быть аккаунт Steam?", ru/en/uz;
--   * `blog_post_translations` for the `steam` post — one bullet, ru/en/uz;
--   * `blog_post_faqs` for that post — "Для каких регионов Steam работает
--     пополнение?", ru/en/uz.
--
-- The blog FAQ block feeds `FAQPage` JSON-LD, so an uncorrected answer is not
-- merely on the page: it is published as structured data for search engines to
-- quote back. That is the reason this is a seed and not an admin edit of the
-- brand page alone.
--
-- **`steam_seo.sql` and `2026-08-05_steam_geo_refresh.sql` are edited in the
-- same commit**, against this repo's usual habit of superseding a seed rather
-- than touching it. The habit exists so that history stays readable when copy
-- is merely *outdated*; this claim is **wrong**, and either file left as-is is
-- a loaded gun — re-running it would put Turkey back on the live brand page
-- with nothing to catch it. A reader who wants the old wording has git.
--
-- No SKU changes: Steam's SKUs are `region = 'GLOBAL'` and none names a
-- country, so nothing about routing or pricing is touched here — only claims.
--
-- The nine i18n strings that carried the same claim (`catalog.steamDesc`,
-- `catalog.cards.steam.eyebrow`, `store.brands.steam.about` in ru/en/uz) are
-- in the same commit, in `packages/i18n/locales/`. They ship with a web
-- deploy; this file ships on its own.
--
-- Idempotent: every statement is a targeted replacement that stops matching
-- once applied.
--
-- Apply:
--   docker exec -i yupay-prod-postgres-1 sh -lc \
--     'psql -U $POSTGRES_USER -d $POSTGRES_DB -v ON_ERROR_STOP=1' \
--     < scripts/seed/2026-09-20_steam_no_turkey.sql

BEGIN;

-- ------------------------------------------------------- brand description --

UPDATE brand_translations SET description = replace(
    description,
    'Поддерживаются аккаунты в регионах СНГ (РФ, Беларусь, Казахстан, Узбекистан) и Турции.',
    'Поддерживаются аккаунты в регионах СНГ (РФ, Беларусь, Казахстан, Узбекистан).')
 WHERE locale = 'ru' AND brand_id = (SELECT id FROM brands WHERE slug = 'steam');

UPDATE brand_translations SET description = replace(
    description,
    'Accounts in the CIS region (Russia, Belarus, Kazakhstan, Uzbekistan) and Turkey are supported.',
    'Accounts in the CIS region (Russia, Belarus, Kazakhstan, Uzbekistan) are supported.')
 WHERE locale = 'en' AND brand_id = (SELECT id FROM brands WHERE slug = 'steam');

UPDATE brand_translations SET description = replace(
    description,
    'MDH mintaqasidagi (Rossiya, Belarus, Qozogʻiston, Oʻzbekiston) va Turkiyadagi akkauntlar qoʻllab-quvvatlanadi.',
    'MDH mintaqasidagi (Rossiya, Belarus, Qozogʻiston, Oʻzbekiston) akkauntlar qoʻllab-quvvatlanadi.')
 WHERE locale = 'uz' AND brand_id = (SELECT id FROM brands WHERE slug = 'steam');

-- ------------------------------------------------------ brand instructions --

UPDATE brand_translations SET instructions = replace(
    instructions,
    'Поддерживаемые регионы: СНГ (РФ, Беларусь, Казахстан, Узбекистан) и Турция.',
    'Поддерживаемые регионы: СНГ (РФ, Беларусь, Казахстан, Узбекистан).')
 WHERE locale = 'ru' AND brand_id = (SELECT id FROM brands WHERE slug = 'steam');

UPDATE brand_translations SET instructions = replace(
    instructions,
    'Supported regions: CIS (Russia, Belarus, Kazakhstan, Uzbekistan) and Turkey.',
    'Supported regions: CIS (Russia, Belarus, Kazakhstan, Uzbekistan).')
 WHERE locale = 'en' AND brand_id = (SELECT id FROM brands WHERE slug = 'steam');

UPDATE brand_translations SET instructions = replace(
    instructions,
    'Qoʻllab-quvvatlanadigan mintaqalar: MDH (Rossiya, Belarus, Qozogʻiston, Oʻzbekiston) va Turkiya.',
    'Qoʻllab-quvvatlanadigan mintaqalar: MDH (Rossiya, Belarus, Qozogʻiston, Oʻzbekiston).')
 WHERE locale = 'uz' AND brand_id = (SELECT id FROM brands WHERE slug = 'steam');

-- -------------------------------------------------------------- brand FAQ --

UPDATE brand_faq_translations SET answer = replace(
    answer,
    'Пополнение работает для аккаунтов Steam в регионах СНГ (Россия, Беларусь, Казахстан, Узбекистан) и Турции.',
    'Пополнение работает для аккаунтов Steam в регионах СНГ (Россия, Беларусь, Казахстан, Узбекистан).')
 WHERE locale = 'ru'
   AND answer ~* 'турци|turkey|turkiya';

UPDATE brand_faq_translations SET answer = replace(
    answer,
    'Top-ups work for Steam accounts in the CIS region (Russia, Belarus, Kazakhstan, Uzbekistan) and Turkey.',
    'Top-ups work for Steam accounts in the CIS region (Russia, Belarus, Kazakhstan, Uzbekistan).')
 WHERE locale = 'en'
   AND answer ~* 'турци|turkey|turkiya';

-- The Uzbek locative rides on the last item, so dropping ``va Turkiyadagi``
-- would leave ``MDH (...) Steam akkauntlari`` with no case marking at all.
-- ``mintaqasidagi`` already carries it, so the clause is reordered rather than
-- truncated.
UPDATE brand_faq_translations SET answer = replace(
    answer,
    'Toʻldirish MDH mintaqasidagi (Rossiya, Belarus, Qozogʻiston, Oʻzbekiston) va Turkiyadagi Steam akkauntlari uchun ishlaydi.',
    'Toʻldirish MDH mintaqasidagi (Rossiya, Belarus, Qozogʻiston, Oʻzbekiston) Steam akkauntlari uchun ishlaydi.')
 WHERE locale = 'uz'
   AND answer ~* 'турци|turkey|turkiya';

-- -------------------------------------------------------------- blog body --

UPDATE blog_post_translations SET body_html = replace(
    body_html,
    'Пополнение работает для аккаунтов в СНГ (Россия, Беларусь, Казахстан, Узбекистан) и Турции.',
    'Пополнение работает для аккаунтов в СНГ (Россия, Беларусь, Казахстан, Узбекистан).')
 WHERE slug = 'steam' AND locale = 'ru';

UPDATE blog_post_translations SET body_html = replace(
    body_html,
    'Top-ups work for accounts in the CIS (Russia, Belarus, Kazakhstan, Uzbekistan) and Turkey.',
    'Top-ups work for accounts in the CIS (Russia, Belarus, Kazakhstan, Uzbekistan).')
 WHERE slug = 'steam' AND locale = 'en';

UPDATE blog_post_translations SET body_html = replace(
    body_html,
    'Toʻldirish MDH (Rossiya, Belarus, Qozogʻiston, Oʻzbekiston) va Turkiyadagi hisoblar uchun ishlaydi.',
    'Toʻldirish MDH mintaqasidagi (Rossiya, Belarus, Qozogʻiston, Oʻzbekiston) hisoblar uchun ishlaydi.')
 WHERE slug = 'steam' AND locale = 'uz';

-- --------------------------------------------------------------- blog FAQ --

UPDATE blog_post_faqs SET answer = replace(
    answer,
    'Для аккаунтов в СНГ — Россия, Беларусь, Казахстан, Узбекистан — и в Турции.',
    'Для аккаунтов в СНГ — Россия, Беларусь, Казахстан, Узбекистан.')
 WHERE locale = 'ru'
   AND answer ~* 'турци|turkey|turkiya';

UPDATE blog_post_faqs SET answer = replace(
    answer,
    'Accounts in the CIS — Russia, Belarus, Kazakhstan, Uzbekistan — and in Turkey.',
    'Accounts in the CIS — Russia, Belarus, Kazakhstan, Uzbekistan.')
 WHERE locale = 'en'
   AND answer ~* 'турци|turkey|turkiya';

-- Same locative problem as the brand FAQ, and the em-dash aside makes a bare
-- ``-dagi`` tail read worse still: the region phrase leads and the countries
-- follow it.
UPDATE blog_post_faqs SET answer = replace(
    answer,
    'MDH — Rossiya, Belarus, Qozogʻiston, Oʻzbekiston — va Turkiyadagi hisoblar uchun.',
    'MDH mintaqasidagi hisoblar uchun — Rossiya, Belarus, Qozogʻiston, Oʻzbekiston.')
 WHERE locale = 'uz'
   AND answer ~* 'турци|turkey|turkiya';

COMMIT;
