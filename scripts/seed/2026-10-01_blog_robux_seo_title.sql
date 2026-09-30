-- The Robux guide (ru/en/uz): search titles with the phrases buyers type in
-- Uzbekistan (Keyword Planner, 2026-10-01): «купить робуксы» in Cyrillic, and
-- «robux sotib olish» word for word — the old Uzbek title split it as «Robux’ni
-- … sotib olish». Only seo_title changes. Idempotent.

BEGIN;

UPDATE blog_post_translations t SET seo_title = v.seo_title
FROM (VALUES
  ('robux-roblox', 'Как купить робуксы (Robux) в Узбекистане за сумы'),
  ('buy-robux-in-uzbekistan', 'How to buy Robux in Uzbekistan — Roblox gift card in soʻm'),
  ('robux-sotib-olish', 'Robux sotib olish: Oʻzbekistonda soʻmda, Roblox kartasi bilan')
) AS v(slug, seo_title)
WHERE t.slug = v.slug;

COMMIT;
