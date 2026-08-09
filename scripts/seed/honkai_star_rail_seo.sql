-- scripts/seed/honkai_star_rail_seo.sql
--
-- SEO content pack for the `honkai-star-rail` brand: highlights + short/long
-- descriptions + instructions on `brand_translations`, product names per locale,
-- and 7 FAQ entries with ru/en/uz answers.
--
-- Deliberately parallel to genshin_impact_seo.sql — same publisher, same UID +
-- server form, same currency-plus-monthly-pass shape — so a customer who has
-- bought one recognises the other. Question order matches it too.
--
-- Content-managed, NOT a fixture and NOT an Alembic data migration. Applied to
-- prod by an operator (psql / `!`), gated by the standing deploy rule. Depends
-- on scripts/seed/2026-08-09_honkai_star_rail_import.py having created the brand.
--
-- Idempotent: brand_translations and product_translations rows are UPDATEd in
-- place; FAQs are rebuilt via delete-then-insert, inside one transaction.
--
-- Strings are dollar-quoted ($c$…$c$ / $q$…$q$ / $a$…$a$) so the apostrophe-heavy
-- Uzbek copy needs no escaping.
--
-- Note there is no live id check on this brand: G2B's checkPlayerId answers any
-- miHoYo input with "No validation required", so the copy has to carry the whole
-- burden of getting UID and server right. That is why the server question is
-- third and says plainly what happens when it is wrong.
--
-- Apply on prod (operator psql):
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     psql -U yupay_app -d yupay -f - < scripts/seed/honkai_star_rail_seo.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Brand translations (highlights, short_description, description, instructions)
-- ---------------------------------------------------------------------------

UPDATE brand_translations SET
    highlights = $c$["Оплата в сумах","По UID и серверу","Автоматически","Без пароля"]$c$::json,
    short_description = $c$Пополнение Honkai: Star Rail — Oneiric Shards и Экспресс-снабжение по UID, оплата в сумах, без пароля.$c$,
    description = $c$Honkai: Star Rail — пошаговая ролевая игра от HoYoverse, создателей Genshin Impact: вы путешествуете на «Звёздном экспрессе» между мирами, собираете отряд из четырёх персонажей и сражаетесь по очереди, а не в реальном времени.

Сущность древних снов (Oneiric Shards) — валюта, которую покупают за реальные деньги. Она меняется один к одному на звёздный нефрит, а нефрит тратится на «прыжки» — розыгрыш персонажей и световых конусов. Кроме того, за Сущность берут наборы в магазине и Экспресс-снабжение.

YuPay пополняет аккаунт по публичному UID и серверу — пароль и вход в аккаунт не нужны. Оплатить можно в сумах картами Uzcard и Humo через Click, Payme или Uzum; курс виден до оплаты, а пополнение зачисляется автоматически после подтверждения платежа.$c$,
    instructions = $c$Как пополнить Honkai: Star Rail:

1. Выберите, что нужно: Oneiric Shards или Экспресс-снабжение.
2. Введите UID и выберите сервер — тот, на котором находится ваш аккаунт. Пароль не нужен.
3. Выберите способ оплаты: Click, Payme или Uzum. Курс и итог показываются до оплаты.
4. Оплатите — пополнение зачисляется автоматически после подтверждения платежа.

Где найти UID: он показан в левом нижнем углу экрана в игре, а также в меню телефона и в «Settings» → «Account» → «User ID». Сервер виден на экране входа рядом с именем аккаунта; игроки из Узбекистана и СНГ чаще всего на Europe.

Если вы играете на PlayStation, зайдите в игру на телефоне или ПК под тем же аккаунтом HoYoverse — покупка приходит на аккаунт, а не на профиль консоли.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'honkai-star-rail') AND locale = 'ru';

UPDATE brand_translations SET
    highlights = $c$["Pay in UZS","By UID and server","Automatic","No password"]$c$::json,
    short_description = $c$Top up Honkai: Star Rail — Oneiric Shards and the Express Supply Pass by UID, pay in sum, no password.$c$,
    description = $c$Honkai: Star Rail is a turn-based RPG by HoYoverse, the studio behind Genshin Impact: you travel between worlds aboard the Astral Express, build a party of four and fight in turns rather than in real time.

Oneiric Shards are the currency bought with real money. They convert one to one into Stellar Jade, and Jade is spent on warps — the draws for characters and Light Cones. Shards also buy shop bundles and the Express Supply Pass.

YuPay tops up your account by its public UID and server — no password and no account login needed. You can pay in Uzbek sum with Uzcard and Humo cards via Click, Payme or Uzum; the rate is shown before you pay, and the top-up is credited automatically once your payment is confirmed.$c$,
    instructions = $c$How to top up Honkai: Star Rail:

1. Choose what you need: Oneiric Shards or the Express Supply Pass.
2. Enter your UID and pick the server your account is on. No password required.
3. Choose a payment method: Click, Payme or Uzum. The rate and total are shown before you pay.
4. Pay — the top-up is credited automatically once your payment is confirmed.

Where to find your UID: it is shown in the bottom-left corner of the screen in game, and also in the phone menu and under Settings → Account → User ID. The server appears on the login screen next to your account name; players from Uzbekistan and the CIS are most often on Europe.

If you play on PlayStation, open the game on a phone or PC with the same HoYoverse account — the purchase lands on the account, not on the console profile.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'honkai-star-rail') AND locale = 'en';

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","UID va server orqali","Avtomatik","Parolsiz"]$c$::json,
    short_description = $c$Honkai: Star Rail toʻldirish — Oneiric Shards va Express Supply Pass UID orqali, soʻmda toʻlov, parolsiz.$c$,
    description = $c$Honkai: Star Rail — Genshin Impact ijodkorlari HoYoverse kompaniyasining navbatma-navbat jang qilinadigan rolli oʻyini: siz «Astral Express»da olamlar aro sayohat qilasiz, toʻrt nafarlik jamoa toʻplaysiz va real vaqtda emas, navbat bilan jang qilasiz.

Oneiric Shards — real pulga sotib olinadigan valyuta. U birma-bir Stellar Jade'ga almashadi, Jade esa «warp»larga — personaj va Light Cone'larni oʻynab yutishga sarflanadi. Bundan tashqari, Shards doʻkondagi toʻplamlar va Express Supply Pass uchun ham ishlatiladi.

YuPay hisobingizni ochiq UID va server orqali toʻldiradi — parol va akkauntga kirish talab qilinmaydi. Toʻlovni soʻmda Uzcard va Humo kartalari bilan Click, Payme yoki Uzum orqali amalga oshirishingiz mumkin; kurs toʻlovdan oldin koʻrinadi, toʻldirish esa toʻlov tasdiqlangach avtomatik tushadi.$c$,
    instructions = $c$Honkai: Star Rail hisobini qanday toʻldirish:

1. Nima kerakligini tanlang: Oneiric Shards yoki Express Supply Pass.
2. UID ni kiriting va akkauntingiz joylashgan serverni tanlang. Parol kerak emas.
3. Toʻlov usulini tanlang: Click, Payme yoki Uzum. Kurs va yakuniy summa toʻlovdan oldin koʻrsatiladi.
4. Toʻlang — toʻldirish toʻlov tasdiqlangach avtomatik tushadi.

UID ni qayerdan topish mumkin: u oʻyinda ekranning chap pastki burchagida, shuningdek telefon menyusida va «Settings» → «Account» → «User ID» boʻlimida koʻrsatiladi. Server kirish ekranida akkaunt nomi yonida koʻrinadi; Oʻzbekiston va MDH oʻyinchilari koʻpincha Europe serverida.

Agar PlayStation'da oʻynasangiz, xuddi shu HoYoverse akkaunti bilan telefon yoki PC'da oʻyinga kiring — xarid konsol profiliga emas, akkauntga tushadi.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'honkai-star-rail') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- 2. Product names per locale
--
-- `import_game` writes the operator's single product name into all three locale
-- rows. The English currency names stay — that is what the in-game shop shows —
-- and the Russian one leads with the official localized term, matching how
-- `genshin-crystals` is presented.
-- ---------------------------------------------------------------------------

UPDATE product_translations SET
    name = $c$Сущность древних снов$c$,
    short_description = $c$Oneiric Shards — меняются на звёздный нефрит для прыжков.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'hsr-oneiric-shards') AND locale = 'ru';
UPDATE product_translations SET
    name = $c$Oneiric Shards$c$,
    short_description = $c$Converts to Stellar Jade for warps.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'hsr-oneiric-shards') AND locale = 'en';
UPDATE product_translations SET
    name = $c$Oneiric Shards$c$,
    short_description = $c$Warp uchun Stellar Jade'ga almashadi.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'hsr-oneiric-shards') AND locale = 'uz';

UPDATE product_translations SET
    name = $c$Экспресс-снабжение$c$,
    short_description = $c$Express Supply Pass — подписка на 30 дней с ежедневным нефритом.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'hsr-express-pass') AND locale = 'ru';
UPDATE product_translations SET
    name = $c$Express Supply Pass$c$,
    short_description = $c$A 30-day pass with Stellar Jade every day.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'hsr-express-pass') AND locale = 'en';
UPDATE product_translations SET
    name = $c$Express Supply Pass$c$,
    short_description = $c$30 kunlik obuna, har kuni Stellar Jade beriladi.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'hsr-express-pass') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- 3. FAQs (rebuilt each run: delete cascades to brand_faq_translations)
-- ---------------------------------------------------------------------------

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'honkai-star-rail');

WITH hsr AS (
    SELECT id FROM brands WHERE slug = 'honkai-star-rail'
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), hsr.id, v.sort_order, true
    FROM hsr, (VALUES (1), (2), (3), (4), (5), (6), (7)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. Валюта: что покупают и во что она превращается.
        (1, 'ru', $q$Что такое Сущность древних снов (Oneiric Shards)?$q$,
            $a$Это валюта Honkai: Star Rail, которую покупают за реальные деньги. Она меняется один к одному на звёздный нефрит, а нефрит тратится на «прыжки» — розыгрыш персонажей и световых конусов (один прыжок стоит 160 нефрита). Сущность можно также тратить напрямую на наборы в магазине и на Экспресс-снабжение.$a$),
        (1, 'en', $q$What are Oneiric Shards in Honkai: Star Rail?$q$,
            $a$They are the currency of Honkai: Star Rail bought with real money. Shards convert one to one into Stellar Jade, and Jade is spent on warps — the draws for characters and Light Cones (one warp costs 160 Jade). Shards can also be spent directly on shop bundles and on the Express Supply Pass.$a$),
        (1, 'uz', $q$Oneiric Shards nima?$q$,
            $a$Bu — real pulga sotib olinadigan Honkai: Star Rail valyutasi. U birma-bir Stellar Jade'ga almashadi, Jade esa «warp»larga — personaj va Light Cone'larni oʻynab yutishga sarflanadi (bitta warp 160 Jade turadi). Shards'ni doʻkondagi toʻplamlar va Express Supply Pass uchun ham toʻgʻridan-toʻgʻri sarflash mumkin.$a$),

        -- 2. UID.
        (2, 'ru', $q$Как найти свой UID в Honkai: Star Rail?$q$,
            $a$UID показан в левом нижнем углу экрана прямо в игре — это самый быстрый способ. Его также видно в меню телефона и в «Settings» → «Account» → «User ID». Для пополнения нужен только UID и сервер, а не логин или e-mail.$a$),
        (2, 'en', $q$How do I find my UID in Honkai: Star Rail?$q$,
            $a$The UID is shown in the bottom-left corner of the screen in game — the quickest place to read it. It is also in the phone menu and under Settings → Account → User ID. A top-up needs only your UID and server, not your login or e-mail.$a$),
        (2, 'uz', $q$Honkai: Star Rail ichida UID qanday topiladi?$q$,
            $a$UID oʻyinda ekranning chap pastki burchagida koʻrsatiladi — eng tez yoʻl. Shuningdek, telefon menyusida va «Settings» → «Account» → «User ID» boʻlimida bor. Toʻldirish uchun faqat UID va server kerak, login yoki e-mail emas.$a$),

        -- 3. Сервер — единственное, что здесь можно указать неправильно.
        (3, 'ru', $q$Какой сервер выбрать при пополнении?$q$,
            $a$Выберите сервер, к которому привязан ваш аккаунт: Europe, America, Asia или TW/HK/MO. Он виден на экране входа рядом с именем аккаунта; игроки из Узбекистана и СНГ чаще всего на Europe. Сервер должен совпадать с регионом аккаунта: пополнение идёт по паре «UID + сервер», и на чужом сервере такого UID просто нет. Если не уверены — проверьте регион при входе в игру, прежде чем оплачивать.$a$),
        (3, 'en', $q$Which server should I select?$q$,
            $a$Choose the server your account is on: Europe, America, Asia or TW/HK/MO. It is shown on the login screen next to your account name; players from Uzbekistan and the CIS are most often on Europe. The server must match your account's region: the top-up goes to a UID + server pair, and on the wrong server that UID simply does not exist. If unsure, check the region on the login screen before paying.$a$),
        (3, 'uz', $q$Toʻldirishda qaysi serverni tanlashim kerak?$q$,
            $a$Akkauntingiz bogʻlangan serverni tanlang: Europe, America, Asia yoki TW/HK/MO. U kirish ekranida akkaunt nomi yonida koʻrinadi; Oʻzbekiston va MDH oʻyinchilari koʻpincha Europe serverida. Server akkaunt mintaqasiga mos boʻlishi kerak: toʻldirish «UID + server» juftligi boʻyicha boradi va begona serverda bunday UID umuman yoʻq. Ishonchingiz komil boʻlmasa, toʻlashdan oldin kirish ekranidagi mintaqani tekshiring.$a$),

        -- 4. Пароль.
        (4, 'ru', $q$Нужен ли пароль от аккаунта?$q$,
            $a$Нет. Пополнение проходит по публичному UID и серверу — пароль и вход в аккаунт не требуются, и мы их не запрашиваем.$a$),
        (4, 'en', $q$Do you need my account password?$q$,
            $a$No. Top-ups run on your public UID and server — no password and no account login are required, and we never ask for them.$a$),
        (4, 'uz', $q$Akkaunt paroli kerakmi?$q$,
            $a$Yoʻq. Toʻldirish ochiq UID va server orqali amalga oshadi — parol va akkauntga kirish talab qilinmaydi, biz ularni soʻramaymiz.$a$),

        -- 5. Оплата и скорость.
        (5, 'ru', $q$Можно ли платить в сумах и как быстро зачислится?$q$,
            $a$Да, оплата в узбекских сумах доступна картами Uzcard и Humo через Click, Payme и Uzum; курс и итоговая сумма показываются до оплаты. Пополнение зачисляется автоматически после подтверждения платежа, обычно в течение нескольких минут. Если вы играете на PlayStation, зайдите в игру на телефоне или ПК под тем же аккаунтом HoYoverse — покупка приходит на аккаунт, а не на профиль консоли.$a$),
        (5, 'en', $q$Can I pay in Uzbek sum, and how fast is it credited?$q$,
            $a$Yes — you can pay in Uzbek sum with Uzcard and Humo cards via Click, Payme and Uzum, and the rate and final total are shown before you pay. The top-up is credited automatically once your payment is confirmed, usually within a few minutes. If you play on PlayStation, open the game on a phone or PC with the same HoYoverse account — the purchase lands on the account, not on the console profile.$a$),
        (5, 'uz', $q$Soʻmda toʻlash mumkinmi va qancha vaqtda tushadi?$q$,
            $a$Ha — oʻzbek soʻmida Uzcard va Humo kartalari orqali Click, Payme va Uzum bilan toʻlash mumkin, kurs va yakuniy summa toʻlovdan oldin koʻrsatiladi. Toʻldirish toʻlov tasdiqlangach avtomatik tushadi, odatda bir necha daqiqada. Agar PlayStation'da oʻynasangiz, xuddi shu HoYoverse akkaunti bilan telefon yoki PC'da oʻyinga kiring — xarid konsol profiliga emas, akkauntga tushadi.$a$),

        -- 6. Пропуск.
        (6, 'ru', $q$Что даёт Экспресс-снабжение (Express Supply Pass)?$q$,
            $a$Это подписка на 30 дней. Сразу начисляются 300 единиц Сущности древних снов, а затем по 90 звёздного нефрита каждый день в течение 30 дней. Ежедневную часть нужно забирать самому, заходя в игру: пропущенный день не восстанавливается.$a$),
        (6, 'en', $q$What does the Express Supply Pass give?$q$,
            $a$It is a 30-day pass. You get 300 Oneiric Shards immediately, then 90 Stellar Jade every day for 30 days. The daily part is claimed by you in-game each day you log in — a missed day is not recoverable.$a$),
        (6, 'uz', $q$Express Supply Pass nima beradi?$q$,
            $a$Bu — 30 kunlik obuna. Darhol 300 Oneiric Shards beriladi, soʻngra 30 kun davomida har kuni 90 Stellar Jade beriladi. Kundalik qismini oʻzingiz oʻyinga kirib olishingiz kerak: oʻtkazib yuborilgan kun tiklanmaydi.$a$),

        -- 7. Официальность.
        (7, 'ru', $q$Это официальный сайт Honkai: Star Rail?$q$,
            $a$Нет. YuPay — независимый сервис пополнения и не связан с HoYoverse, издателем Honkai: Star Rail. Мы покупаем и перепродаём пополнения по прозрачному курсу, который виден до оплаты.$a$),
        (7, 'en', $q$Is this the official Honkai: Star Rail website?$q$,
            $a$No. YuPay is an independent top-up service and is not affiliated with HoYoverse, the publisher of Honkai: Star Rail. We buy and resell top-ups at a transparent rate that is shown before you pay.$a$),
        (7, 'uz', $q$Bu Honkai: Star Rail rasmiy saytimi?$q$,
            $a$Yoʻq. YuPay — mustaqil toʻldirish xizmati va Honkai: Star Rail noshiri HoYoverse bilan bogʻliq emas. Biz toʻldirishlarni shaffof kurs boʻyicha sotib olib, qayta sotamiz; kurs toʻlovdan oldin koʻrinadi.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
