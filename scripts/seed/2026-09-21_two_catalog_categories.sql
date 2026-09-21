-- The catalogue splits two ways, not three: пополнения and подарочные карты.
--
-- Owner direction, 2026-09-21: «бренды разделить на 2 категории, топапы и
-- подарочные карты», in the interface and in the API alike. Applies
-- everywhere — `categories` is one table read by yupay.uz, the Mini App, the
-- reseller cabinet and `/merchant/v1/catalog`, so there is one taxonomy and
-- this is where it lives.
--
-- **Nothing here is a judgement call about which brand is which.** The split
-- already exists in the data: `products.kind` is `Literal["top_up",
-- "voucher"]`, and measured against production on 2026-09-21 no brand mixes
-- them —
--
--     games          16 brands   all top_up
--     subscriptions   3 brands   all top_up   (telegram-premium, telegram-stars, imo)
--     gift-cards      3 brands   all voucher  (roblox, discord, standoff-2)
--
-- so «Игры» + «Подписки и сервисы» is exactly the set of `top_up` brands and
-- «Подарочные карты» is exactly the set of `voucher` ones. The three-way split
-- was a shelf label; the two-way one is the thing itself, and it is the
-- distinction a buyer acts on — an id typed in and a balance credited, or a
-- code handed over to redeem.
--
-- ## Why the `games` row is renamed rather than replaced
--
-- Sixteen of the nineteen brands already point at it. Renaming keeps their
-- `category_id` untouched and makes this three statements instead of a move of
-- every brand in the catalogue. The slug goes with the name: «Пополнения»
-- living at `slug = 'games'` is a trap for the next reader, and the only
-- places that hardcode the string are the dev seed and one docs example, both
-- changed in this commit.
--
-- `category_slug` is published on `/merchant/v1/catalog`, where its own
-- description says it is "the same split a person sees on yupay.uz". That is
-- still true after this, which is the point: an integrator who branched on
-- `"games"` sees `"top-ups"`, and the contract never promised otherwise.
--
-- ## Why `subscriptions` is deactivated and not deleted
--
-- `Category.active` already gates every public read (`catalog.service`'s
-- `list_categories`, `list_brands` and `get_brand` all filter it), so `false`
-- removes it as completely as a DELETE would — and leaves the row, its
-- translations and its id in place if this is ever reversed.
--
-- **Order matters inside the transaction.** `list_brands` filters
-- `Brand.active AND Category.active`, so deactivating before the move would
-- take Telegram Premium, Stars and IMO off the storefront. Move first.

BEGIN;

-- 1. The `top_up` half, renamed in place.
UPDATE categories
SET slug = 'top-ups', icon = 'wallet', sort_order = 0, updated_at = now()
WHERE slug = 'games';

INSERT INTO category_translations (category_id, locale, name)
SELECT c.id, v.locale, v.name
FROM categories c
CROSS JOIN (VALUES
  ('ru', 'Пополнения'),
  ('en', 'Top-ups'),
  ('uz', 'Toʻldirishlar')
) AS v(locale, name)
WHERE c.slug = 'top-ups'
ON CONFLICT (category_id, locale) DO UPDATE SET name = EXCLUDED.name;

-- 2. The three `subscriptions` brands are `top_up` too. Before step 3.
UPDATE brands
SET category_id = (SELECT id FROM categories WHERE slug = 'top-ups'), updated_at = now()
WHERE category_id = (SELECT id FROM categories WHERE slug = 'subscriptions');

-- 3. Nothing points at it now.
UPDATE categories SET active = false, updated_at = now() WHERE slug = 'subscriptions';

-- 4. Пополнения first, подарочные карты second — the order they are sold in.
UPDATE categories SET sort_order = 10, updated_at = now() WHERE slug = 'gift-cards';

-- Two active categories, and every brand under one of them.
DO $$
DECLARE
  active_count int;
  orphans int;
BEGIN
  SELECT count(*) INTO active_count FROM categories WHERE active;
  IF active_count <> 2 THEN
    RAISE EXCEPTION 'expected exactly 2 active categories, found %', active_count;
  END IF;
  SELECT count(*) INTO orphans
  FROM brands b JOIN categories c ON c.id = b.category_id
  WHERE b.active AND NOT c.active;
  IF orphans <> 0 THEN
    RAISE EXCEPTION '% active brands sit in an inactive category', orphans;
  END IF;
END $$;

COMMIT;
