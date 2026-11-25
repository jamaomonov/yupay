-- CoD Mobile (Activision): FazerCards dropped the CA, KZ, SA and US categories
-- (price refresh 2026-11-25 01:34 UTC: «Unknown or unavailable category_id»; a
-- reseller order for CA 88 CP failed on it at 02:00). Only IN still prices.
--
-- Until another supplier covers them: those four countries go into maintenance
-- (buying is refused for retail and resellers alike — `sku_is_buyable`), and the
-- storefront card is hidden, since it opened on KZ. India stays sellable to
-- resellers. Undo: maintenance = false on the four, visible_retail = true on
-- `call-of-duty-mobile`. Idempotent.
BEGIN;

UPDATE brands SET maintenance = true, updated_at = now()
 WHERE slug IN ('call-of-duty-mobile-activision-ca', 'call-of-duty-mobile-activision-kz',
                'call-of-duty-mobile-activision-sa', 'call-of-duty-mobile-activision-us');

UPDATE brands SET visible_retail = false, updated_at = now()
 WHERE slug = 'call-of-duty-mobile';

SELECT slug, maintenance, visible_retail FROM brands
 WHERE slug LIKE 'call-of-duty-mobile%' ORDER BY slug;

COMMIT;
