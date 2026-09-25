-- scripts/seed/marvel_afk_minecraft_seo.sql
--
-- SEO content for three of the four brands 2026-09-24_import_four_brands.py
-- created: `marvel-rivals`, `afk-journey`, `minecraft`. Highlights, full
-- descriptions and instructions on `brand_translations` (the import wrote only
-- a one-line short description), one product name, and 4 FAQ entries per
-- brand in ru/en/uz.
--
-- Content-managed, applied by an operator. Idempotent: translations are
-- UPDATEd in place, FAQs rebuilt delete-then-insert inside one transaction.
--
-- What the copy says, and where it comes from:
--   * payment methods are the ones live on the storefront today — Click,
--     Payme, Uzum. Not Paynet: it is not live for customers yet;
--   * Minecraft's licence is the PC edition (`java_bedrock_pc` at every
--     supplier), so the copy says PC and the product name now does too —
--     a phone or console player must not buy it thinking it fits;
--   * Minecoins spend in Bedrock Edition's Marketplace only, not in Java;
--   * codes are delivered to the order's e-mail and shown on the order page,
--     as for every other voucher we sell; they redeem at minecraft.net/redeem.
--
-- What it deliberately does not say:
--   * no promise that we verify the nickname behind the ID — none of the
--     three has a player check;
--   * no exact in-game menu paths: they were not checked against the running
--     games (same caveat as the import's help text), so the copy says where
--     the ID lives in general terms;
--   * nothing about which platforms Marvel Rivals' top-up reaches — no
--     supplier states it, and a wrong answer there costs a customer money;
--   * no reversal: a top-up cannot be undone, and the FAQ says so.
--
-- Apply:
--   docker exec -i yupay-prod-postgres-1 sh -lc \
--     'psql -U $POSTGRES_USER -d $POSTGRES_DB -v ON_ERROR_STOP=1' \
--     < scripts/seed/marvel_afk_minecraft_seo.sql

BEGIN;

-- ======================================================= Marvel Rivals ======

UPDATE brand_translations SET
    highlights = $c$["Оплата в сумах","По Player ID","Без пароля","От 100 Lattice"]$c$::json,
    short_description = $c$Пополнение Marvel Rivals: Lattice от 100 до 11 680 по Player ID. Оплата в сумах через Click, Payme или Uzum, зачисление автоматическое.$c$,
    description = $c$Marvel Rivals — командный шутер от NetEase, где игроки собирают отряды из героев и злодеев вселенной Marvel. Lattice — премиальная валюта игры: за неё берут костюмы, эмоции и боевой пропуск, а также обменивают её на Units.

YuPay пополняет аккаунт по публичному Player ID — пароль и вход в аккаунт не нужны, мы их не запрашиваем. Оплата в узбекских сумах картами Uzcard и Humo через Click, Payme или Uzum; сумма видна до подтверждения, Lattice зачисляется автоматически.

Важно: валюта приходит на тот ID, который указан в заказе, и обратный перевод невозможен. Скопируйте ID из профиля, а не набирайте вручную.$c$,
    instructions = $c$Как пополнить Marvel Rivals:

1. Выберите пакет — от 100 до 11 680 Lattice.
2. Введите Player ID. Пароль не нужен.
3. Выберите способ оплаты: Click, Payme или Uzum.
4. Оплатите — Lattice зачисляется автоматически.

Где взять Player ID: откройте игру и зайдите в профиль — ID показан рядом с ником. Скопируйте его кнопкой, а не набирайте вручную.$c$
WHERE locale = 'ru' AND brand_id = (SELECT id FROM brands WHERE slug = 'marvel-rivals');

UPDATE brand_translations SET
    highlights = $c$["Pay in soʻm","By Player ID","No password","From 100 Lattice"]$c$::json,
    short_description = $c$Marvel Rivals top-ups: 100 to 11,680 Lattice by Player ID. Pay in soʻm via Click, Payme or Uzum — credited automatically.$c$,
    description = $c$Marvel Rivals is NetEase's team shooter where players build squads from Marvel heroes and villains. Lattice is the game's premium currency: it buys costumes, emotes and the battle pass, and converts into Units.

YuPay tops up the account by your public Player ID — no password and no sign-in are needed, and we never ask for them. Pay in Uzbek soʻm with Uzcard or Humo via Click, Payme or Uzum; the total is shown before you confirm and the Lattice is credited automatically.

One thing to be clear about: the currency goes to the ID given on the order, and there is no transfer back. Copy the ID from your profile rather than retyping it.$c$,
    instructions = $c$How to top up Marvel Rivals:

1. Pick a pack — 100 to 11,680 Lattice.
2. Enter your Player ID. No password needed.
3. Choose how to pay: Click, Payme or Uzum.
4. Pay — the Lattice is credited automatically.

Where to find your Player ID: open the game and go to your profile — the ID is shown next to your nickname. Copy it with the button rather than retyping it.$c$
WHERE locale = 'en' AND brand_id = (SELECT id FROM brands WHERE slug = 'marvel-rivals');

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","Player ID orqali","Parolsiz","100 Lattice dan"]$c$::json,
    short_description = $c$Marvel Rivals’ni toʻldirish: Player ID orqali 100 dan 11 680 gacha Lattice. Click, Payme yoki Uzum orqali soʻmda toʻlov, avtomatik tushadi.$c$,
    description = $c$Marvel Rivals — NetEase’ning jamoaviy shuteri, unda oʻyinchilar Marvel olamidagi qahramonlar va yovuzlardan otryad tuzadi. Lattice — oʻyinning premium valyutasi: unga kostyumlar, emotsiyalar va jangovar propusk olinadi, shuningdek u Units’ga almashtiriladi.

YuPay akkauntni ommaviy Player ID orqali toʻldiradi — parol va akkauntga kirish kerak emas, biz ularni soʻramaymiz. Uzcard va Humo kartalari bilan Click, Payme yoki Uzum orqali oʻzbek soʻmida toʻlanadi; summa tasdiqlashdan oldin koʻrinadi, Lattice avtomatik tushadi.

Muhim: valyuta buyurtmada koʻrsatilgan ID ga tushadi va uni qaytarib boʻlmaydi. ID ni qoʻlda termay, profildan nusxa oling.$c$,
    instructions = $c$Marvel Rivals’ni qanday toʻldirish:

1. Paketni tanlang — 100 dan 11 680 gacha Lattice.
2. Player ID ni kiriting. Parol kerak emas.
3. Toʻlov usulini tanlang: Click, Payme yoki Uzum.
4. Toʻlang — Lattice avtomatik tushadi.

Player ID qayerda: oʻyinni oching va profilga kiring — ID taxallusingiz yonida koʻrsatilgan. Uni qoʻlda termay, tugma orqali nusxa oling.$c$
WHERE locale = 'uz' AND brand_id = (SELECT id FROM brands WHERE slug = 'marvel-rivals');

-- ========================================================= AFK Journey ======

UPDATE brand_translations SET
    highlights = $c$["Оплата в сумах","По UID","Без пароля","Esperia Monthly"]$c$::json,
    short_description = $c$Пополнение AFK Journey: Dragon Crystals от 21 до 3150, Esperia Monthly и Growth Bundle по UID. Оплата в сумах через Click, Payme или Uzum, зачисление автоматическое.$c$,
    description = $c$AFK Journey — фэнтезийная RPG от Lilith Games про героев земли Эсперии. Dragon Crystals — премиальная валюта игры: за неё призывают героев, покупают наборы и предметы в магазине. Esperia Monthly — месячные подписки, которые выдают награды частями в течение месяца.

YuPay пополняет аккаунт по публичному UID — пароль и вход в аккаунт не нужны, мы их не запрашиваем. Товар для глобальной версии игры. Оплата в узбекских сумах картами Uzcard и Humo через Click, Payme или Uzum; сумма видна до подтверждения, покупка зачисляется автоматически.

Важно: кристаллы приходят на тот UID, который указан в заказе, и обратный перевод невозможен. Скопируйте UID из профиля, а не набирайте вручную.$c$,
    instructions = $c$Как пополнить AFK Journey:

1. Выберите пакет — от 21 до 3150 Dragon Crystals, подписку Esperia Monthly или Growth Bundle.
2. Введите UID. Пароль не нужен.
3. Выберите способ оплаты: Click, Payme или Uzum.
4. Оплатите — покупка зачисляется автоматически.

Где взять UID: откройте игру и зайдите в профиль — UID показан под именем персонажа. Скопируйте его кнопкой, а не набирайте вручную.$c$
WHERE locale = 'ru' AND brand_id = (SELECT id FROM brands WHERE slug = 'afk-journey');

UPDATE brand_translations SET
    highlights = $c$["Pay in soʻm","By UID","No password","Esperia Monthly"]$c$::json,
    short_description = $c$AFK Journey top-ups: 21 to 3,150 Dragon Crystals, Esperia Monthly and the Growth Bundle, by UID. Pay in soʻm via Click, Payme or Uzum — credited automatically.$c$,
    description = $c$AFK Journey is Lilith Games' fantasy RPG about the heroes of the land of Esperia. Dragon Crystals are the game's premium currency: they summon heroes and buy bundles and store items. Esperia Monthly is the game's monthly subscription, which pays out its rewards over the month rather than all at once.

YuPay tops up the account by your public UID — no password and no sign-in are needed, and we never ask for them. The items are for the global version of the game. Pay in Uzbek soʻm with Uzcard or Humo via Click, Payme or Uzum; the total is shown before you confirm and the purchase is credited automatically.

One thing to be clear about: the crystals go to the UID given on the order, and there is no transfer back. Copy the UID from your profile rather than retyping it.$c$,
    instructions = $c$How to top up AFK Journey:

1. Pick a pack — 21 to 3,150 Dragon Crystals, an Esperia Monthly subscription or the Growth Bundle.
2. Enter your UID. No password needed.
3. Choose how to pay: Click, Payme or Uzum.
4. Pay — the purchase is credited automatically.

Where to find your UID: open the game and go to your profile — the UID is shown under your character's name. Copy it with the button rather than retyping it.$c$
WHERE locale = 'en' AND brand_id = (SELECT id FROM brands WHERE slug = 'afk-journey');

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","UID orqali","Parolsiz","Esperia Monthly"]$c$::json,
    short_description = $c$AFK Journey’ni toʻldirish: UID orqali 21 dan 3150 gacha Dragon Crystals, Esperia Monthly va Growth Bundle. Click, Payme yoki Uzum orqali soʻmda toʻlov, avtomatik tushadi.$c$,
    description = $c$AFK Journey — Lilith Games’ning Esperiya yurti qahramonlari haqidagi fentezi RPG oʻyini. Dragon Crystals — oʻyinning premium valyutasi: unga qahramonlar chaqiriladi, toʻplamlar va doʻkondagi buyumlar olinadi. Esperia Monthly — oy davomida mukofotlarni bir yoʻla emas, qismlab beradigan oylik obuna.

YuPay akkauntni ommaviy UID orqali toʻldiradi — parol va akkauntga kirish kerak emas, biz ularni soʻramaymiz. Mahsulotlar oʻyinning global versiyasi uchun. Uzcard va Humo kartalari bilan Click, Payme yoki Uzum orqali oʻzbek soʻmida toʻlanadi; summa tasdiqlashdan oldin koʻrinadi, xarid avtomatik tushadi.

Muhim: kristallar buyurtmada koʻrsatilgan UID ga tushadi va ularni qaytarib boʻlmaydi. UID ni qoʻlda termay, profildan nusxa oling.$c$,
    instructions = $c$AFK Journey’ni qanday toʻldirish:

1. Paketni tanlang — 21 dan 3150 gacha Dragon Crystals, Esperia Monthly obunasi yoki Growth Bundle.
2. UID ni kiriting. Parol kerak emas.
3. Toʻlov usulini tanlang: Click, Payme yoki Uzum.
4. Toʻlang — xarid avtomatik tushadi.

UID qayerda: oʻyinni oching va profilga kiring — UID qahramon ismi ostida koʻrsatilgan. Uni qoʻlda termay, tugma orqali nusxa oling.$c$
WHERE locale = 'uz' AND brand_id = (SELECT id FROM brands WHERE slug = 'afk-journey');

-- =========================================================== Minecraft ======

UPDATE brand_translations SET
    highlights = $c$["Оплата в сумах","Код на почту","Global-регион","Java & Bedrock для ПК"]$c$::json,
    short_description = $c$Коды Minecraft: Minecoins от 330 до 8800 и лицензия Java & Bedrock для ПК. Глобальный регион, оплата в сумах через Click, Payme или Uzum, код приходит на почту.$c$,
    description = $c$Minecraft — песочница от Mojang и Microsoft, одна из самых популярных игр в мире. У нас два товара, оба — коды глобального региона.

Лицензия Minecraft: Java & Bedrock Edition для ПК — сама игра. Один код открывает обе версии на компьютере с Windows и привязывается к вашему аккаунту Microsoft. На телефонах и консолях эта лицензия не работает.

Minecoins — валюта Marketplace в Minecraft Bedrock Edition: за неё покупают скины, карты, текстуры и миры от создателей. В Java Edition Minecoins не используются.

После оплаты код приходит на почту, указанную в заказе, и остаётся на странице заказа. Активируете вы его сами на minecraft.net/redeem — пароль от аккаунта нам не нужен. Оплата в узбекских сумах картами Uzcard и Humo через Click, Payme или Uzum.$c$,
    instructions = $c$Как купить Minecraft:

1. Выберите товар — лицензию Java & Bedrock для ПК или Minecoins от 330 до 8800.
2. Укажите почту — на неё придёт код.
3. Выберите способ оплаты: Click, Payme или Uzum.
4. Оплатите — код придёт на почту и появится на странице заказа.

Как активировать код: откройте minecraft.net/redeem, войдите в аккаунт Microsoft и введите код. Лицензия появится в лаунчере Minecraft, а Minecoins — на балансе Marketplace в Bedrock Edition.$c$
WHERE locale = 'ru' AND brand_id = (SELECT id FROM brands WHERE slug = 'minecraft');

UPDATE brand_translations SET
    highlights = $c$["Pay in soʻm","Code by e-mail","Global region","Java & Bedrock for PC"]$c$::json,
    short_description = $c$Minecraft codes: 330 to 8,800 Minecoins and the Java & Bedrock licence for PC. Global region, pay in soʻm via Click, Payme or Uzum, the code arrives by e-mail.$c$,
    description = $c$Minecraft is the sandbox game from Mojang and Microsoft, one of the most played games in the world. We sell two things, both as global-region codes.

The Minecraft: Java & Bedrock Edition for PC licence is the game itself. One code unlocks both editions on a Windows computer and is tied to your Microsoft account. It does not work on phones or consoles.

Minecoins are the currency of the Marketplace in Minecraft Bedrock Edition: they buy skins, maps, texture packs and worlds from creators. Java Edition does not use Minecoins.

After you pay, the code is sent to the e-mail given on the order and stays on the order page. You redeem it yourself at minecraft.net/redeem — we never need your account password. Pay in Uzbek soʻm with Uzcard or Humo via Click, Payme or Uzum.$c$,
    instructions = $c$How to buy Minecraft:

1. Pick an item — the Java & Bedrock licence for PC, or 330 to 8,800 Minecoins.
2. Enter your e-mail — the code is sent there.
3. Choose how to pay: Click, Payme or Uzum.
4. Pay — the code arrives by e-mail and appears on the order page.

How to redeem the code: open minecraft.net/redeem, sign in with your Microsoft account and enter the code. The licence appears in the Minecraft Launcher; Minecoins land on your Marketplace balance in Bedrock Edition.$c$
WHERE locale = 'en' AND brand_id = (SELECT id FROM brands WHERE slug = 'minecraft');

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","Kod pochtaga","Global hudud","Java & Bedrock kompyuter uchun"]$c$::json,
    short_description = $c$Minecraft kodlari: 330 dan 8800 gacha Minecoins va kompyuter uchun Java & Bedrock litsenziyasi. Global hudud, Click, Payme yoki Uzum orqali soʻmda toʻlov, kod pochtaga keladi.$c$,
    description = $c$Minecraft — Mojang va Microsoft’ning sandbox oʻyini, dunyodagi eng mashhur oʻyinlardan biri. Bizda ikkita mahsulot bor, ikkalasi ham global hudud kodlari.

Minecraft: Java & Bedrock Edition kompyuter uchun litsenziyasi — oʻyinning oʻzi. Bitta kod Windows kompyuterida ikkala versiyani ochadi va Microsoft akkauntingizga bogʻlanadi. Telefon va konsollarda bu litsenziya ishlamaydi.

Minecoins — Minecraft Bedrock Edition’dagi Marketplace valyutasi: unga skinlar, xaritalar, teksturalar va ijodkorlar yaratgan olamlar sotib olinadi. Java Edition’da Minecoins ishlatilmaydi.

Toʻlovdan soʻng kod buyurtmada koʻrsatilgan pochtaga keladi va buyurtma sahifasida qoladi. Uni minecraft.net/redeem saytida oʻzingiz faollashtirasiz — akkaunt paroli bizga kerak emas. Uzcard va Humo kartalari bilan Click, Payme yoki Uzum orqali oʻzbek soʻmida toʻlanadi.$c$,
    instructions = $c$Minecraft’ni qanday sotib olish:

1. Mahsulotni tanlang — kompyuter uchun Java & Bedrock litsenziyasi yoki 330 dan 8800 gacha Minecoins.
2. Pochtangizni kiriting — kod oʻsha yerga keladi.
3. Toʻlov usulini tanlang: Click, Payme yoki Uzum.
4. Toʻlang — kod pochtaga keladi va buyurtma sahifasida paydo boʻladi.

Kodni qanday faollashtirish: minecraft.net/redeem saytini oching, Microsoft akkauntingizga kiring va kodni kiriting. Litsenziya Minecraft Launcher’da paydo boʻladi, Minecoins esa Bedrock Edition’dagi Marketplace balansiga tushadi.$c$
WHERE locale = 'uz' AND brand_id = (SELECT id FROM brands WHERE slug = 'minecraft');

-- ============================================== product names per locale ====

UPDATE product_translations SET name = $c$Minecraft: Java & Bedrock для ПК$c$
WHERE locale = 'ru' AND product_id = (SELECT id FROM products WHERE slug = 'minecraft-java-bedrock');
UPDATE product_translations SET name = $c$Minecraft: Java & Bedrock for PC$c$
WHERE locale = 'en' AND product_id = (SELECT id FROM products WHERE slug = 'minecraft-java-bedrock');
UPDATE product_translations SET name = $c$Minecraft: Java & Bedrock (kompyuter uchun)$c$
WHERE locale = 'uz' AND product_id = (SELECT id FROM products WHERE slug = 'minecraft-java-bedrock');

-- ================================================================== FAQ =====

DELETE FROM brand_faqs
 WHERE brand_id IN (SELECT id FROM brands WHERE slug IN ('marvel-rivals','afk-journey','minecraft'));

WITH b AS (
    SELECT id, slug FROM brands WHERE slug IN ('marvel-rivals','afk-journey','minecraft')
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), b.id, v.sort_order, true
    FROM b, (VALUES (1), (2), (3), (4)) AS v(sort_order)
    RETURNING id, brand_id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN b ON b.id = nf.brand_id
JOIN (
    VALUES
        -- ---------------------------------------------------- Marvel Rivals
        ('marvel-rivals', 1, 'ru', $q$Где найти Player ID в Marvel Rivals?$q$,
            $a$Откройте игру и зайдите в профиль — Player ID показан рядом с ником. Скопируйте его кнопкой: Lattice приходит на тот ID, который указан, и одна неверная цифра отправит покупку другому игроку без возможности вернуть.$a$),
        ('marvel-rivals', 1, 'en', $q$Where do I find my Marvel Rivals Player ID?$q$,
            $a$Open the game and go to your profile — the Player ID is shown next to your nickname. Copy it with the button: the Lattice goes to whatever ID is given, and one wrong digit sends the purchase to another player with no way back.$a$),
        ('marvel-rivals', 1, 'uz', $q$Marvel Rivals’da Player ID ni qayerdan topaman?$q$,
            $a$Oʻyinni oching va profilga kiring — Player ID taxallusingiz yonida koʻrsatilgan. Uni tugma orqali nusxa oling: Lattice koʻrsatilgan ID ga tushadi va bitta xato raqam xaridni boshqa oʻyinchiga, qaytarib boʻlmaydigan qilib yuboradi.$a$),

        ('marvel-rivals', 2, 'ru', $q$Что можно купить за Lattice?$q$,
            $a$Lattice — премиальная валюта Marvel Rivals. За неё берут костюмы героев, эмоции и боевой пропуск, а ещё её можно обменять на Units — вторую валюту игрового магазина.$a$),
        ('marvel-rivals', 2, 'en', $q$What does Lattice buy?$q$,
            $a$Lattice is Marvel Rivals' premium currency. It buys hero costumes, emotes and the battle pass, and it can be exchanged for Units, the game store's second currency.$a$),
        ('marvel-rivals', 2, 'uz', $q$Lattice’ga nima sotib olish mumkin?$q$,
            $a$Lattice — Marvel Rivals’ning premium valyutasi. Unga qahramonlar kostyumlari, emotsiyalar va jangovar propusk olinadi, shuningdek uni oʻyin doʻkonining ikkinchi valyutasi — Units’ga almashtirish mumkin.$a$),

        ('marvel-rivals', 3, 'ru', $q$Нужен ли пароль от аккаунта?$q$,
            $a$Нет. Пополнение идёт по публичному Player ID — пароль и вход в аккаунт не нужны, и мы их не запрашиваем. Если сервис просит данные для входа, это не пополнение.$a$),
        ('marvel-rivals', 3, 'en', $q$Do you need my account password?$q$,
            $a$No. The top-up goes by your public Player ID — no password and no sign-in are needed, and we never ask for them. If a service asks for sign-in details, that is not a top-up.$a$),
        ('marvel-rivals', 3, 'uz', $q$Akkaunt paroli kerakmi?$q$,
            $a$Yoʻq. Toʻldirish ommaviy Player ID orqali boʻladi — parol va akkauntga kirish kerak emas, biz ularni soʻramaymiz. Agar biror servis kirish maʼlumotlarini soʻrasa, bu toʻldirish emas.$a$),

        ('marvel-rivals', 4, 'ru', $q$Можно ли отменить пополнение?$q$,
            $a$Нет. После зачисления Lattice остаётся на аккаунте с указанным ID, вернуть или перенести её нельзя. Поэтому перед оплатой сверьте Player ID ещё раз.$a$),
        ('marvel-rivals', 4, 'en', $q$Can a top-up be reversed?$q$,
            $a$No. Once credited, the Lattice stays on the account with the ID given and cannot be returned or moved. Check the Player ID once more before you pay.$a$),
        ('marvel-rivals', 4, 'uz', $q$Toʻldirishni bekor qilish mumkinmi?$q$,
            $a$Yoʻq. Tushgandan keyin Lattice koʻrsatilgan ID dagi akkauntda qoladi, uni qaytarib yoki koʻchirib boʻlmaydi. Shuning uchun toʻlashdan oldin Player ID ni yana bir bor tekshiring.$a$),

        -- ------------------------------------------------------ AFK Journey
        ('afk-journey', 1, 'ru', $q$Где найти UID в AFK Journey?$q$,
            $a$Откройте игру и зайдите в профиль — UID показан под именем персонажа. Скопируйте его кнопкой: кристаллы приходят на тот UID, который указан, и одна неверная цифра отправит покупку другому игроку без возможности вернуть.$a$),
        ('afk-journey', 1, 'en', $q$Where do I find my AFK Journey UID?$q$,
            $a$Open the game and go to your profile — the UID is shown under your character's name. Copy it with the button: the crystals go to whatever UID is given, and one wrong digit sends the purchase to another player with no way back.$a$),
        ('afk-journey', 1, 'uz', $q$AFK Journey’da UID ni qayerdan topaman?$q$,
            $a$Oʻyinni oching va profilga kiring — UID qahramon ismi ostida koʻrsatilgan. Uni tugma orqali nusxa oling: kristallar koʻrsatilgan UID ga tushadi va bitta xato raqam xaridni boshqa oʻyinchiga, qaytarib boʻlmaydigan qilib yuboradi.$a$),

        ('afk-journey', 2, 'ru', $q$Что такое Esperia Monthly?$q$,
            $a$Это месячные подписки AFK Journey в двух вариантах — Classic и Premium. Награды по ним выдаются частями в течение месяца, а не сразу, поэтому заходить в игру за ними нужно регулярно.$a$),
        ('afk-journey', 2, 'en', $q$What is Esperia Monthly?$q$,
            $a$It is AFK Journey's monthly subscription, in two tiers — Classic and Premium. Its rewards are paid out over the month rather than all at once, so you collect them by logging in regularly.$a$),
        ('afk-journey', 2, 'uz', $q$Esperia Monthly nima?$q$,
            $a$Bu AFK Journey’ning ikki xil oylik obunasi — Classic va Premium. Mukofotlar bir yoʻla emas, oy davomida qismlab beriladi, shuning uchun ularni olish uchun oʻyinga muntazam kirib turish kerak.$a$),

        ('afk-journey', 3, 'ru', $q$Нужен ли пароль от аккаунта?$q$,
            $a$Нет. Пополнение идёт по публичному UID — пароль и вход в аккаунт не нужны, и мы их не запрашиваем. Если сервис просит данные для входа, это не пополнение.$a$),
        ('afk-journey', 3, 'en', $q$Do you need my account password?$q$,
            $a$No. The top-up goes by your public UID — no password and no sign-in are needed, and we never ask for them. If a service asks for sign-in details, that is not a top-up.$a$),
        ('afk-journey', 3, 'uz', $q$Akkaunt paroli kerakmi?$q$,
            $a$Yoʻq. Toʻldirish ommaviy UID orqali boʻladi — parol va akkauntga kirish kerak emas, biz ularni soʻramaymiz. Agar biror servis kirish maʼlumotlarini soʻrasa, bu toʻldirish emas.$a$),

        ('afk-journey', 4, 'ru', $q$Для какой версии игры подходят товары?$q$,
            $a$Для глобальной версии AFK Journey. После зачисления покупку нельзя отменить или перенести на другой аккаунт, поэтому перед оплатой сверьте UID ещё раз.$a$),
        ('afk-journey', 4, 'en', $q$Which version of the game are these for?$q$,
            $a$The global version of AFK Journey. Once credited, a purchase cannot be reversed or moved to another account, so check the UID once more before you pay.$a$),
        ('afk-journey', 4, 'uz', $q$Mahsulotlar oʻyinning qaysi versiyasi uchun?$q$,
            $a$AFK Journey’ning global versiyasi uchun. Tushgandan keyin xaridni bekor qilib yoki boshqa akkauntga koʻchirib boʻlmaydi, shuning uchun toʻlashdan oldin UID ni yana bir bor tekshiring.$a$),

        -- -------------------------------------------------------- Minecraft
        ('minecraft', 1, 'ru', $q$Как активировать код Minecraft?$q$,
            $a$Откройте minecraft.net/redeem, войдите в аккаунт Microsoft и введите код. Лицензия появится в лаунчере Minecraft, а Minecoins — на балансе Marketplace в Bedrock Edition. Пароль от аккаунта нам не нужен: код активируете вы сами.$a$),
        ('minecraft', 1, 'en', $q$How do I redeem a Minecraft code?$q$,
            $a$Open minecraft.net/redeem, sign in with your Microsoft account and enter the code. The licence appears in the Minecraft Launcher; Minecoins land on your Marketplace balance in Bedrock Edition. We never need your password: you redeem the code yourself.$a$),
        ('minecraft', 1, 'uz', $q$Minecraft kodini qanday faollashtiraman?$q$,
            $a$minecraft.net/redeem saytini oching, Microsoft akkauntingizga kiring va kodni kiriting. Litsenziya Minecraft Launcher’da paydo boʻladi, Minecoins esa Bedrock Edition’dagi Marketplace balansiga tushadi. Akkaunt paroli bizga kerak emas: kodni oʻzingiz faollashtirasiz.$a$),

        ('minecraft', 2, 'ru', $q$Подойдёт ли лицензия для телефона или консоли?$q$,
            $a$Нет. Мы продаём Minecraft: Java & Bedrock Edition для ПК — один код открывает обе версии на компьютере с Windows. На телефонах, Xbox, PlayStation и Nintendo Switch игра покупается отдельно в их магазинах.$a$),
        ('minecraft', 2, 'en', $q$Will the licence work on a phone or a console?$q$,
            $a$No. We sell Minecraft: Java & Bedrock Edition for PC — one code unlocks both editions on a Windows computer. On phones, Xbox, PlayStation and Nintendo Switch the game is bought separately in their own stores.$a$),
        ('minecraft', 2, 'uz', $q$Litsenziya telefon yoki konsolga mos keladimi?$q$,
            $a$Yoʻq. Biz kompyuter uchun Minecraft: Java & Bedrock Edition sotamiz — bitta kod Windows kompyuterida ikkala versiyani ochadi. Telefonlar, Xbox, PlayStation va Nintendo Switch’da oʻyin ularning oʻz doʻkonlarida alohida sotib olinadi.$a$),

        ('minecraft', 3, 'ru', $q$Где тратить Minecoins?$q$,
            $a$В Marketplace внутри Minecraft Bedrock Edition: там продаются скины, карты, наборы текстур и миры от создателей. В Java Edition Minecoins не используются.$a$),
        ('minecraft', 3, 'en', $q$Where are Minecoins spent?$q$,
            $a$In the Marketplace inside Minecraft Bedrock Edition, which sells skins, maps, texture packs and worlds from creators. Java Edition does not use Minecoins.$a$),
        ('minecraft', 3, 'uz', $q$Minecoins qayerda sarflanadi?$q$,
            $a$Minecraft Bedrock Edition ichidagi Marketplace’da: u yerda skinlar, xaritalar, tekstura toʻplamlari va ijodkorlar yaratgan olamlar sotiladi. Java Edition’da Minecoins ishlatilmaydi.$a$),

        ('minecraft', 4, 'ru', $q$Как быстро придёт код?$q$,
            $a$Сразу после подтверждения оплаты — на почту, указанную в заказе. Код также остаётся на странице заказа. Спешить с активацией не обязательно: код можно сохранить и ввести позже.$a$),
        ('minecraft', 4, 'en', $q$How fast does the code arrive?$q$,
            $a$Right after the payment is confirmed — to the e-mail given on the order. The code also stays on the order page. There is no rush to redeem it: you can keep the code and enter it later.$a$),
        ('minecraft', 4, 'uz', $q$Kod qanchalik tez keladi?$q$,
            $a$Toʻlov tasdiqlangandan soʻng darhol — buyurtmada koʻrsatilgan pochtaga. Kod buyurtma sahifasida ham qoladi. Faollashtirishga shoshilish shart emas: kodni saqlab, keyinroq kiritishingiz mumkin.$a$)
) AS t(brand_slug, sort_order, locale, question, answer)
  ON t.brand_slug = b.slug AND t.sort_order = nf.sort_order;

COMMIT;
