-- The Steam top-up guide (`steam`, ru/en/uz): search titles that carry the
-- words buyers type. Keyword Planner, Uzbekistan: «пополнить стим» is the
-- Steam buying query (100–1k/month), written in Cyrillic; «без комиссии» is a
-- large query across the CIS (Wordstat, 22.5k) and is what we offer. The old
-- titles («… — от $1, картами Uzcard и Humo») had neither. Only seo_title
-- changes; the visible title stays. Idempotent.

BEGIN;

UPDATE blog_post_translations t SET seo_title = v.seo_title
FROM (VALUES
  ('ru', 'Как пополнить Steam (стим) в Узбекистане без комиссии — за сумы'),
  ('en', 'How to top up Steam in Uzbekistan with no fee — pay in soʻm'),
  ('uz', 'Oʻzbekistonda Steam’ni komissiyasiz toʻldirish — soʻmda')
) AS v(locale, seo_title)
WHERE t.slug = 'steam' AND t.locale = v.locale;

COMMIT;
