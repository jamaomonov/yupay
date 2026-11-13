-- PUBG Mobile copy promised «12 номиналов UC от 60 до 16 200»; on 2026-11-13 six
-- are on sale (60, 325, 660, 1800, 3850, 8100). Found by the storefront review.
-- The new wording names the range without a count, so the next time a rung
-- goes or comes back the text does not lie again. Exact-string replace: a
-- sentence already edited by hand is left alone (the UPDATE then changes 0
-- rows for it — check the counts).
--
-- Run: docker compose -f docker-compose.prod.yml exec -T postgres \
--        psql -U yupay_app -d yupay -v ON_ERROR_STOP=1 < scripts/seed/2026-11-13_pubg_denominations.sql

BEGIN;

UPDATE brand_translations bt
SET short_description = replace(replace(replace(short_description,
      '12 номиналов UC от 60 до 16 200', 'UC от 60 до 8100'),
      '60 dan 16 200 gacha 12 ta UC nominali', '60 dan 8100 gacha UC'),
      '12 UC denominations from 60 to 16,200', 'UC from 60 to 8,100'),
    description = replace(replace(replace(description,
      'Доступны 12 номиналов UC (от 60 до 16 200)', 'Доступны UC от 60 до 8100'),
      '12 ta UC nominali (60 dan 16 200 gacha)', '60 dan 8100 gacha UC'),
      'We offer 12 UC denominations (from 60 to 16,200)', 'We offer UC from 60 to 8,100')
FROM brands b
WHERE b.id = bt.brand_id AND b.slug = 'pubg-mobile';

UPDATE brand_faq_translations ft
SET answer = replace(replace(replace(replace(replace(replace(answer,
      ' Всего 12 номиналов — от 60 до 16 200 UC.', ' Номиналы — от 60 до 8100 UC.'),
      ' Jami 12 ta nominal — 60 dan 16 200 UC gacha.', ' Nominallar — 60 dan 8100 UC gacha.'),
      ' There are 12 denominations in total, from 60 to 16,200 UC.', ' Denominations run from 60 to 8,100 UC.'),
      'Доступно 12 номиналов UC: 60, 325, 660, 985, 1320, 1800, 2460, 3850, 5650, 8100, 11 950 и 16 200 UC.',
      'Номиналы UC: 60, 325, 660, 1800, 3850 и 8100.'),
      '12 ta UC nominali mavjud: 60, 325, 660, 985, 1320, 1800, 2460, 3850, 5650, 8100, 11 950 va 16 200 UC.',
      'UC nominallari: 60, 325, 660, 1800, 3850 va 8100.'),
      'There are 12 UC denominations: 60, 325, 660, 985, 1,320, 1,800, 2,460, 3,850, 5,650, 8,100, 11,950 and 16,200 UC.',
      'UC denominations: 60, 325, 660, 1,800, 3,850 and 8,100.')
FROM brand_faqs f JOIN brands b ON b.id = f.brand_id
WHERE f.id = ft.brand_faq_id AND b.slug = 'pubg-mobile';

-- Expect 0: nothing still claims 16 200.
SELECT count(*) AS still_claims_16200
FROM brand_translations bt JOIN brands b ON b.id = bt.brand_id
WHERE b.slug = 'pubg-mobile'
  AND (coalesce(bt.short_description, '') || coalesce(bt.description, '')) ~ '16[ ,]?200';
SELECT count(*) AS faq_still_claims_16200
FROM brand_faq_translations ft JOIN brand_faqs f ON f.id = ft.brand_faq_id
JOIN brands b ON b.id = f.brand_id
WHERE b.slug = 'pubg-mobile' AND ft.answer ~ '16[ ,]?200';

COMMIT;
