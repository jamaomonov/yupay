-- Steam Wallet codes on the storefront: one card, the countries on its region
-- switcher (ADR-0099), with search and activation copy.
--
-- `steam-wallet` (global USD codes) and its 28 country brands came from the bulk
-- import, priced and B2B-only. The main brand keeps its own global codes; its
-- region code is 'usd' («Глобальная (USD)»), not the default 'global', whose
-- chip reads «Глобальный (Узбекистан)» — whether a USD code redeems on a
-- CIS-USD account is not something we can promise (Steam locks codes to the
-- account's store currency, and community reports disagree about USD).
-- The FAQ steers Uzbek accounts to the login top-up (`steam`) instead.
--
-- Run AFTER the release with the cl/pe/uy/cr/usd region labels.
-- Rollback: UPDATE brands SET visible_retail = false WHERE slug = 'steam-wallet';
--
-- Idempotent. Apply with operator psql:
--   docker exec -i yupay-prod-postgres-1 psql -U yupay_app -d yupay -v ON_ERROR_STOP=1 \
--     < scripts/seed/2026-11-24_steam_wallet_regions.sql

BEGIN;

CREATE TEMP TABLE country (code text, ru text, en text, uz text) ON COMMIT DROP;
INSERT INTO country VALUES
    ('ae', 'ОАЭ', 'UAE', 'BAA'),
    ('ar', 'Аргентина', 'Argentina', 'Argentina'),
    ('br', 'Бразилия', 'Brazil', 'Braziliya'),
    ('cl', 'Чили', 'Chile', 'Chili'),
    ('cn', 'Китай', 'China', 'Xitoy'),
    ('co', 'Колумбия', 'Colombia', 'Kolumbiya'),
    ('cr', 'Коста-Рика', 'Costa Rica', 'Kosta-Rika'),
    ('eu', 'Европа', 'Europe', 'Yevropa'),
    ('hk', 'Гонконг', 'Hong Kong', 'Gonkong'),
    ('id', 'Индонезия', 'Indonesia', 'Indoneziya'),
    ('in', 'Индия', 'India', 'Hindiston'),
    ('kr', 'Южная Корея', 'South Korea', 'Janubiy Koreya'),
    ('kw', 'Кувейт', 'Kuwait', 'Quvayt'),
    ('mx', 'Мексика', 'Mexico', 'Meksika'),
    ('my', 'Малайзия', 'Malaysia', 'Malayziya'),
    ('pe', 'Перу', 'Peru', 'Peru'),
    ('ph', 'Филиппины', 'Philippines', 'Filippin'),
    ('pl', 'Польша', 'Poland', 'Polsha'),
    ('qa', 'Катар', 'Qatar', 'Qatar'),
    ('sa', 'Саудовская Аравия', 'Saudi Arabia', 'Saudiya Arabistoni'),
    ('sg', 'Сингапур', 'Singapore', 'Singapur'),
    ('th', 'Таиланд', 'Thailand', 'Tailand'),
    ('tr', 'Турция', 'Turkey', 'Turkiya'),
    ('tw', 'Тайвань', 'Taiwan', 'Tayvan'),
    ('us', 'США', 'USA', 'AQSH'),
    ('uy', 'Уругвай', 'Uruguay', 'Urugvay'),
    ('vn', 'Вьетнам', 'Vietnam', 'Vyetnam'),
    ('za', 'ЮАР', 'South Africa', 'Janubiy Afrika');

UPDATE brands
   SET visible_retail = true, region_code = 'usd', sort_order = 24, updated_at = now()
 WHERE slug = 'steam-wallet' AND region_parent_id IS NULL;

UPDATE brands c
   SET region_parent_id = m.id, region_code = k.code, visible_retail = true, updated_at = now()
  FROM brands m, country k
 WHERE m.slug = 'steam-wallet' AND c.slug = 'steam-wallet-' || k.code AND c.active;

-- "Steam Wallet (TR)" → "Steam Wallet · Турция", brand and product alike.
UPDATE brand_translations t
   SET name = 'Steam Wallet · ' || CASE t.locale WHEN 'ru' THEN k.ru WHEN 'en' THEN k.en ELSE k.uz END
  FROM brands c JOIN country k ON c.slug = 'steam-wallet-' || k.code
 WHERE t.brand_id = c.id;


UPDATE brand_translations SET
    name = 'Steam Wallet',
    seo_title = $c$Коды Steam Wallet — купить карту пополнения Steam в Узбекистане$c$,
    seo_description = $c$Коды пополнения Steam в долларах и в валютах других стран: Турция, Бразилия, Индия, Европа и ещё два десятка. Код на почту сразу после оплаты. Оплата в сумах через Click, Payme или Uzum.$c$,
    short_description = $c$Коды пополнения кошелька Steam в валюте нужной страны. Код на почту, оплата в сумах.$c$,
    description = $c$Код Steam Wallet пополняет кошелёк Steam. На эти деньги покупают игры, дополнения и предметы на Торговой площадке.

Код работает на аккаунте с той же валютой магазина, что и у кода. Выберите в переключателе выше страну или валюту своего аккаунта.$c$,
    instructions = $c$Как активировать код Steam Wallet:

1. Откройте store.steampowered.com/account/redeemwalletcode и войдите в свой аккаунт Steam.
2. Введите код из письма и нажмите «Продолжить».
3. Сумма сразу зачислится на кошелёк Steam.

Код приходит на почту, указанную при заказе, сразу после оплаты. Если письма нет — проверьте «Спам» и «Промоакции».$c$,
    highlights = $c$["Оплата в сумах", "Код на почту", "Валюта на выбор", "Без пароля"]$c$::json
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'steam-wallet') AND locale = 'ru';
UPDATE brand_translations SET
    name = 'Steam Wallet',
    seo_title = $c$Steam Wallet codes — buy a Steam gift card in Uzbekistan$c$,
    seo_description = $c$Steam Wallet codes in US dollars and other currencies: Turkey, Brazil, India, Europe and two dozen more. Code by email right after payment. Pay in soʻm with Click, Payme or Uzum.$c$,
    short_description = $c$Steam Wallet codes in your account’s currency. Code by email, pay in soʻm.$c$,
    description = $c$A Steam Wallet code tops up your Steam wallet. The balance buys games, DLC and Community Market items.

A code works on an account whose store currency matches it. Pick your account’s country or currency in the switcher above.$c$,
    instructions = $c$How to redeem your Steam Wallet code:

1. Open store.steampowered.com/account/redeemwalletcode and sign in to your Steam account.
2. Enter the code from the email and click Continue.
3. The amount lands in your Steam wallet at once.

The code is emailed to the address on the order right after payment. If it has not arrived, check Spam and Promotions.$c$,
    highlights = $c$["Pay in UZS", "Code by email", "Pick your currency", "No password"]$c$::json
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'steam-wallet') AND locale = 'en';
UPDATE brand_translations SET
    name = 'Steam Wallet',
    seo_title = $c$Steam Wallet kodlari — Oʻzbekistonda Steam kartasini sotib olish$c$,
    seo_description = $c$Dollarda va boshqa valyutalarda Steam toʻldirish kodlari: Turkiya, Braziliya, Hindiston, Yevropa va yana yigirmadan ortiq. Kod toʻlovdan soʻng pochtaga. Click, Payme yoki Uzum orqali soʻmda toʻlov.$c$,
    short_description = $c$Kerakli davlat valyutasida Steam hamyonini toʻldirish kodlari. Kod pochtaga, soʻmda toʻlov.$c$,
    description = $c$Steam Wallet kodi Steam hamyonini toʻldiradi. Bu pulga oʻyinlar, qoʻshimchalar va Savdo maydonchasidagi buyumlar olinadi.

Kod doʻkon valyutasi bir xil boʻlgan akkauntda ishlaydi. Yuqoridagi tanlagichda akkauntingiz davlati yoki valyutasini tanlang.$c$,
    instructions = $c$Steam Wallet kodini qanday faollashtirish:

1. store.steampowered.com/account/redeemwalletcode ni oching va Steam akkauntingizga kiring.
2. Xatdagi kodni kiriting va «Continue» ni bosing.
3. Summa darhol Steam hamyoniga tushadi.

Kod toʻlovdan soʻng darhol buyurtmadagi pochtaga keladi. Xat kelmasa — «Spam» va «Promotions» papkalarini tekshiring.$c$,
    highlights = $c$["Soʻmda toʻlov", "Kod pochtaga", "Valyutani tanlang", "Parolsiz"]$c$::json
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'steam-wallet') AND locale = 'uz';

-- Products read like their brands (after the main brand's name above).
UPDATE product_translations pt
   SET name = bt.name
  FROM products p
  JOIN brands c ON c.id = p.brand_id
  JOIN brand_translations bt ON bt.brand_id = c.id
 WHERE pt.product_id = p.id AND bt.locale = pt.locale
   AND c.slug LIKE 'steam-wallet%' AND p.slug = c.slug || '-cards';

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'steam-wallet');
WITH nf AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), b.id, v.so, true
      FROM brands b, (VALUES (1), (2), (3), (4)) AS v(so)
     WHERE b.slug = 'steam-wallet'
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
  FROM nf JOIN (VALUES
    (1, 'ru', $q$Код какой страны выбрать?$q$, $a$Код в валюте магазина вашего аккаунта: код в другой валюте Steam может не принять. Валюту видно по цене игр в магазине Steam и по балансу кошелька.$a$),
    (1, 'en', $q$Which country’s code do I need?$q$, $a$One in your account’s store currency: Steam may refuse a code in another currency. The currency shows in game prices in the Steam store and in your wallet balance.$a$),
    (1, 'uz', $q$Qaysi davlat kodini tanlash kerak?$q$, $a$Akkauntingiz doʻkoni valyutasidagi kodni: boshqa valyutadagi kodni Steam qabul qilmasligi mumkin. Valyuta Steam doʻkonidagi oʻyin narxlarida va hamyon balansida koʻrinadi.$a$),
    (2, 'ru', $q$Подойдёт ли код для аккаунта из Узбекистана?$q$, $a$Для аккаунта из Узбекистана надёжнее пополнение Steam по логину: деньги приходят на баланс без кода. Коды здесь — для аккаунтов других стран.$a$),
    (2, 'en', $q$Will a code work on an account from Uzbekistan?$q$, $a$For an account from Uzbekistan, topping up Steam by login is the safer choice: the money lands on the balance with no code. The codes here are for accounts from other countries.$a$),
    (2, 'uz', $q$Kod Oʻzbekiston akkauntiga mos keladimi?$q$, $a$Oʻzbekiston akkaunti uchun Steam ni login orqali toʻldirish ishonchliroq: pul kodsiz balansga tushadi. Bu yerdagi kodlar boshqa davlatlar akkauntlari uchun.$a$),
    (3, 'ru', $q$Когда придёт код?$q$, $a$Сразу после оплаты на почту, указанную при заказе. Если письма нет — проверьте «Спам» и «Промоакции».$a$),
    (3, 'en', $q$When will I get the code?$q$, $a$Right after payment, to the email on the order. If it has not arrived, check Spam and Promotions.$a$),
    (3, 'uz', $q$Kod qachon keladi?$q$, $a$Toʻlovdan soʻng darhol buyurtmadagi pochtaga. Xat kelmasa — «Spam» va «Promotions» papkalarini tekshiring.$a$),
    (4, 'ru', $q$Как оплатить код Steam?$q$, $a$Оплата в сумах через Click, Payme или Uzum. Итог в сумах виден до подтверждения, комиссии сверху нет.$a$),
    (4, 'en', $q$How do I pay for a Steam code?$q$, $a$Pay in soʻm with Click, Payme or Uzum. The total in soʻm is shown before you confirm, with no extra fee.$a$),
    (4, 'uz', $q$Steam kodini qanday toʻlash mumkin?$q$, $a$Click, Payme yoki Uzum orqali soʻmda toʻlov. Yakuniy summa soʻmda tasdiqlashdan oldin koʻrinadi, ustiga komissiya yoʻq.$a$)
) AS t(so, locale, question, answer) ON t.so = nf.sort_order;

SELECT c.region_code, c.slug,
       (SELECT name FROM brand_translations WHERE brand_id = c.id AND locale = 'ru') AS ru_name
  FROM brands c JOIN brands m ON m.id = c.region_parent_id
 WHERE m.slug = 'steam-wallet'
 ORDER BY 1;

COMMIT;
