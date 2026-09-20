-- scripts/seed/hok_bigo_likee_seo.sql
--
-- SEO content for the three brands 2026-09-21_hok_bigo_likee_import.py creates:
-- `honor-of-kings`, `bigo-live`, `likee`. Highlights, short/long descriptions
-- and instructions on `brand_translations`, product names per locale, and
-- 4 FAQ entries per brand in ru/en/uz.
--
-- Content-managed, applied by an operator. Depends on the import having run.
-- Idempotent: translations are UPDATEd in place, FAQs rebuilt delete-then-insert
-- inside one transaction.
--
-- Two claims this copy deliberately does NOT make, for the same reason the IMO
-- pack does not:
--   * no promise that we verify the nickname behind the ID — no supplier gives
--     us a validator for these three that we have tested;
--   * no promise that a top-up can be reversed. It cannot.
--
-- Bigo Live and Likee are streaming apps, not games, and the copy says so —
-- they sit in `games` only because that is where the storefront's top-up
-- category lives today.
--
-- Apply:
--   docker exec -i yupay-prod-postgres-1 sh -lc \
--     'psql -U $POSTGRES_USER -d $POSTGRES_DB -v ON_ERROR_STOP=1' \
--     < scripts/seed/hok_bigo_likee_seo.sql

BEGIN;

-- ====================================================== Honor of Kings ======

UPDATE brand_translations SET
    highlights = $c$["Оплата в сумах","По Player ID","Без пароля","От 16 токенов"]$c$::json,
    short_description = $c$Пополнение Honor of Kings: токены от 16 до 8360 и Weekly Card по Player ID. Оплата в сумах через Click, Payme, Uzum и Paynet, зачисление автоматическое.$c$,
    description = $c$Honor of Kings — мобильная MOBA от Tencent, самая массовая в мире по числу игроков. Токены это внутриигровая валюта: за них берут героев, скины, сезонные пропуска Weekly Card и предметы из магазина.

YuPay пополняет аккаунт по публичному Player ID — пароль и вход в аккаунт не нужны, мы их не запрашиваем. Оплата в узбекских сумах картами Uzcard и Humo через Click, Payme, Uzum или Paynet; сумма видна до подтверждения, токены зачисляются автоматически.

Важно: токены приходят на тот ID, который указан при заказе, и обратный перевод не предусмотрен. Скопируйте ID из профиля, а не набирайте вручную.$c$,
    instructions = $c$Как пополнить Honor of Kings:

1. Выберите номинал — от 16 до 8360 токенов, либо Weekly Card.
2. Введите Player ID. Пароль не нужен.
3. Выберите способ оплаты: Click, Payme, Uzum или Paynet.
4. Оплатите — токены зачисляются автоматически.

Где взять Player ID: откройте игру, нажмите на аватар в левом верхнем углу — ID показан в профиле под именем. Нажмите на номер, чтобы скопировать.$c$
WHERE locale = 'ru' AND brand_id = (SELECT id FROM brands WHERE slug = 'honor-of-kings');

UPDATE brand_translations SET
    highlights = $c$["Pay in som","By Player ID","No password","From 16 tokens"]$c$::json,
    short_description = $c$Honor of Kings top-ups: 16 to 8360 tokens and the Weekly Card, by Player ID. Pay in som via Click, Payme, Uzum or Paynet — credited automatically.$c$,
    description = $c$Honor of Kings is Tencent's mobile MOBA and the most played in the world by headcount. Tokens are the in-game currency: heroes, skins, the Weekly Card season pass and store items.

YuPay tops up the account by your public Player ID — no account password is needed and we never ask for one. Pay in Uzbek sum with Uzcard and Humo via Click, Payme, Uzum or Paynet; the total is shown before you confirm and the tokens are credited automatically.

One thing to be clear about: tokens go to the ID given on the order, and there is no transfer back. Copy the ID from your profile rather than retyping it.$c$,
    instructions = $c$How to top up Honor of Kings:

1. Pick a denomination — 16 to 8360 tokens, or the Weekly Card.
2. Enter your Player ID. No password needed.
3. Choose a payment method: Click, Payme, Uzum or Paynet.
4. Pay — the tokens are credited automatically.

Where to find your Player ID: open the game, tap your avatar in the top-left corner — the ID is shown on the profile under your name. Tap the number to copy it.$c$
WHERE locale = 'en' AND brand_id = (SELECT id FROM brands WHERE slug = 'honor-of-kings');

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","Player ID boʻyicha","Parolsiz","16 tokendan"]$c$::json,
    short_description = $c$Honor of Kings toʻldirish: Player ID boʻyicha 16 dan 8360 gacha token va Weekly Card. Click, Payme, Uzum, Paynet orqali soʻmda toʻlov, avtomatik.$c$,
    description = $c$Honor of Kings — Tencent'ning mobil MOBA oʻyini, oʻyinchilar soni boʻyicha dunyoda eng yiriklaridan. Tokenlar oʻyin ichidagi valyuta: ular bilan qahramonlar, skinlar, Weekly Card mavsumiy propuski va doʻkondagi buyumlar olinadi.

YuPay hisobni ommaviy Player ID boʻyicha toʻldiradi — parol kerak emas, biz uni soʻramaymiz. Toʻlov oʻzbek soʻmida Uzcard va Humo kartalari orqali Click, Payme, Uzum yoki Paynet bilan; summa tasdiqlashdan oldin koʻrinadi, tokenlar avtomatik tushadi.

Muhim: tokenlar buyurtmada koʻrsatilgan ID ga tushadi, orqaga oʻtkazish koʻzda tutilmagan. ID ni qoʻlda termay, profilingizdan nusxa oling.$c$,
    instructions = $c$Honor of Kings ni qanday toʻldirish:

1. Nominalni tanlang — 16 dan 8360 tokengacha yoki Weekly Card.
2. Player ID ni kiriting. Parol kerak emas.
3. Toʻlov usulini tanlang: Click, Payme, Uzum yoki Paynet.
4. Toʻlang — tokenlar avtomatik tushadi.

Player ID ni qayerdan olish: oʻyinni oching, chap yuqori burchakdagi avatarni bosing — ID profilda ism ostida koʻrsatilgan. Nusxa olish uchun raqamni bosing.$c$
WHERE locale = 'uz' AND brand_id = (SELECT id FROM brands WHERE slug = 'honor-of-kings');

-- ============================================================= Bigo Live ====

UPDATE brand_translations SET
    highlights = $c$["Оплата в сумах","По Bigo ID","Без пароля","От 10 алмазов"]$c$::json,
    short_description = $c$Пополнение Bigo Live: алмазы от 10 до 10 000 по Bigo ID для подарков в эфирах. Оплата в сумах через Click, Payme, Uzum и Paynet, без пароля.$c$,
    description = $c$Bigo Live — приложение для прямых эфиров. Алмазы это внутренняя валюта: ими дарят подарки стримерам во время трансляций, открывают уровни и оформление профиля. Заработать их в приложении нельзя, их покупают.

YuPay пополняет баланс по публичному Bigo ID — пароль и код из SMS не нужны. Оплата в сумах картами Uzcard и Humo через Click, Payme, Uzum или Paynet, зачисление автоматическое.

Алмазы приходят на тот ID, который указан при заказе, и вернуть их нельзя. Скопируйте ID из профиля.$c$,
    instructions = $c$Как пополнить Bigo Live:

1. Выберите пакет алмазов — от 10 до 10 000.
2. Введите Bigo ID. Пароль и код из SMS не нужны.
3. Выберите способ оплаты: Click, Payme, Uzum или Paynet.
4. Оплатите — алмазы зачисляются автоматически.

Где взять Bigo ID: откройте приложение, перейдите в «Me» → профиль. ID показан под вашим именем. Нажмите на него, чтобы скопировать.$c$
WHERE locale = 'ru' AND brand_id = (SELECT id FROM brands WHERE slug = 'bigo-live');

UPDATE brand_translations SET
    highlights = $c$["Pay in som","By Bigo ID","No password","From 10 diamonds"]$c$::json,
    short_description = $c$Bigo Live top-ups: 10 to 10,000 diamonds by Bigo ID for gifts during live broadcasts. Pay in som via Click, Payme, Uzum or Paynet, no password.$c$,
    description = $c$Bigo Live is a live-streaming app. Diamonds are its own currency: they buy gifts for streamers during a broadcast, levels and profile decorations. There is no way to earn them in the app — they are bought.

YuPay tops up the balance by your public Bigo ID — no password and no SMS code are needed. Pay in som with Uzcard and Humo via Click, Payme, Uzum or Paynet; delivery is automatic.

Diamonds go to the ID given on the order and cannot be recovered. Copy the ID from your profile.$c$,
    instructions = $c$How to top up Bigo Live:

1. Pick a diamond pack — 10 to 10,000.
2. Enter your Bigo ID. No password and no SMS code needed.
3. Choose a payment method: Click, Payme, Uzum or Paynet.
4. Pay — the diamonds are credited automatically.

Where to find your Bigo ID: open the app and go to Me → profile. The ID is shown under your name. Tap it to copy.$c$
WHERE locale = 'en' AND brand_id = (SELECT id FROM brands WHERE slug = 'bigo-live');

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","Bigo ID boʻyicha","Parolsiz","10 olmosdan"]$c$::json,
    short_description = $c$Bigo Live toʻldirish: efirlarda sovgʻa uchun Bigo ID boʻyicha 10 dan 10 000 gacha olmos. Click, Payme, Uzum, Paynet orqali soʻmda toʻlov, parolsiz.$c$,
    description = $c$Bigo Live — jonli efirlar ilovasi. Olmoslar uning ichki valyutasi: ular bilan efir vaqtida strimerlarga sovgʻa qilinadi, darajalar va profil bezaklari ochiladi. Ilovada ularni ishlab topib boʻlmaydi, sotib olinadi.

YuPay balansni ommaviy Bigo ID boʻyicha toʻldiradi — parol va SMS kod kerak emas. Toʻlov soʻmda Uzcard va Humo kartalari bilan Click, Payme, Uzum yoki Paynet orqali, hisobga oʻtkazish avtomatik.

Olmoslar buyurtmada koʻrsatilgan ID ga tushadi va ularni qaytarib boʻlmaydi. ID ni profilingizdan nusxa oling.$c$,
    instructions = $c$Bigo Live ni qanday toʻldirish:

1. Olmoslar paketini tanlang — 10 dan 10 000 gacha.
2. Bigo ID ni kiriting. Parol va SMS kod kerak emas.
3. Toʻlov usulini tanlang: Click, Payme, Uzum yoki Paynet.
4. Toʻlang — olmoslar avtomatik tushadi.

Bigo ID ni qayerdan olish: ilovani oching, «Me» → profilga oʻting. ID ismingiz ostida koʻrsatilgan. Nusxa olish uchun bosing.$c$
WHERE locale = 'uz' AND brand_id = (SELECT id FROM brands WHERE slug = 'bigo-live');

-- ================================================================= Likee ====

UPDATE brand_translations SET
    highlights = $c$["Оплата в сумах","По Likee ID","Без пароля","От 100 алмазов"]$c$::json,
    short_description = $c$Пополнение Likee: алмазы от 100 до 20 000 по Likee ID для подарков авторам в эфирах. Оплата в сумах через Click, Payme, Uzum и Paynet, без пароля.$c$,
    description = $c$Likee — приложение коротких видео и прямых эфиров. Алмазы нужны, чтобы отправлять подарки авторам во время трансляций и покупать эффекты. В приложении их не заработать.

YuPay пополняет баланс по публичному Likee ID — пароль не нужен. Оплата в сумах картами Uzcard и Humo через Click, Payme, Uzum или Paynet, зачисление автоматическое.

Алмазы уходят на указанный ID безвозвратно — скопируйте его из профиля, а не набирайте.$c$,
    instructions = $c$Как пополнить Likee:

1. Выберите пакет алмазов — от 100 до 20 000.
2. Введите Likee ID. Пароль не нужен.
3. Выберите способ оплаты: Click, Payme, Uzum или Paynet.
4. Оплатите — алмазы зачисляются автоматически.

Где взять Likee ID: откройте приложение, перейдите в «Профиль» — ID показан под именем пользователя. Нажмите, чтобы скопировать.$c$
WHERE locale = 'ru' AND brand_id = (SELECT id FROM brands WHERE slug = 'likee');

UPDATE brand_translations SET
    highlights = $c$["Pay in som","By Likee ID","No password","From 100 diamonds"]$c$::json,
    short_description = $c$Likee top-ups: 100 to 20,000 diamonds by Likee ID for gifting creators on live streams. Pay in som via Click, Payme, Uzum or Paynet, no password.$c$,
    description = $c$Likee is a short-video and live-streaming app. Diamonds are what you send creators as gifts during a broadcast, and what buys effects. They cannot be earned in the app.

YuPay tops up the balance by your public Likee ID — no password needed. Pay in som with Uzcard and Humo via Click, Payme, Uzum or Paynet; delivery is automatic.

Diamonds go to the ID you give and cannot come back — copy it from your profile rather than retyping.$c$,
    instructions = $c$How to top up Likee:

1. Pick a diamond pack — 100 to 20,000.
2. Enter your Likee ID. No password needed.
3. Choose a payment method: Click, Payme, Uzum or Paynet.
4. Pay — the diamonds are credited automatically.

Where to find your Likee ID: open the app and go to Profile — the ID is shown under your username. Tap it to copy.$c$
WHERE locale = 'en' AND brand_id = (SELECT id FROM brands WHERE slug = 'likee');

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","Likee ID boʻyicha","Parolsiz","100 olmosdan"]$c$::json,
    short_description = $c$Likee toʻldirish: efirlarda mualliflarga sovgʻa uchun Likee ID boʻyicha 100 dan 20 000 gacha olmos. Click, Payme, Uzum, Paynet orqali soʻmda toʻlov.$c$,
    description = $c$Likee — qisqa videolar va jonli efirlar ilovasi. Olmoslar efir vaqtida mualliflarga sovgʻa yuborish va effektlar sotib olish uchun kerak. Ilovada ularni ishlab topib boʻlmaydi.

YuPay balansni ommaviy Likee ID boʻyicha toʻldiradi — parol kerak emas. Toʻlov soʻmda Uzcard va Humo kartalari bilan Click, Payme, Uzum yoki Paynet orqali, hisobga oʻtkazish avtomatik.

Olmoslar koʻrsatilgan ID ga qaytarib boʻlmaydigan tarzda tushadi — ID ni qoʻlda termay, profilingizdan nusxa oling.$c$,
    instructions = $c$Likee ni qanday toʻldirish:

1. Olmoslar paketini tanlang — 100 dan 20 000 gacha.
2. Likee ID ni kiriting. Parol kerak emas.
3. Toʻlov usulini tanlang: Click, Payme, Uzum yoki Paynet.
4. Toʻlang — olmoslar avtomatik tushadi.

Likee ID ni qayerdan olish: ilovani oching, «Profil» boʻlimiga oʻting — ID foydalanuvchi nomi ostida koʻrsatilgan. Nusxa olish uchun bosing.$c$
WHERE locale = 'uz' AND brand_id = (SELECT id FROM brands WHERE slug = 'likee');

-- ============================================== product names per locale ====

UPDATE product_translations SET name = $c$Токены$c$
WHERE locale = 'ru' AND product_id = (SELECT id FROM products WHERE slug = 'hok-tokens');
UPDATE product_translations SET name = $c$Tokens$c$
WHERE locale = 'en' AND product_id = (SELECT id FROM products WHERE slug = 'hok-tokens');
UPDATE product_translations SET name = $c$Tokenlar$c$
WHERE locale = 'uz' AND product_id = (SELECT id FROM products WHERE slug = 'hok-tokens');

UPDATE product_translations SET name = $c$Алмазы$c$
WHERE locale = 'ru' AND product_id IN (SELECT id FROM products WHERE slug IN ('bigo-diamonds','likee-diamonds'));
UPDATE product_translations SET name = $c$Diamonds$c$
WHERE locale = 'en' AND product_id IN (SELECT id FROM products WHERE slug IN ('bigo-diamonds','likee-diamonds'));
UPDATE product_translations SET name = $c$Olmoslar$c$
WHERE locale = 'uz' AND product_id IN (SELECT id FROM products WHERE slug IN ('bigo-diamonds','likee-diamonds'));

-- ================================================================== FAQ =====

DELETE FROM brand_faqs
 WHERE brand_id IN (SELECT id FROM brands WHERE slug IN ('honor-of-kings','bigo-live','likee'));

WITH b AS (
    SELECT id, slug FROM brands WHERE slug IN ('honor-of-kings','bigo-live','likee')
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
        -- 1. Where the ID lives. The one irreversible mistake on every page.
        ('honor-of-kings', 1, 'ru', $q$Где найти Player ID в Honor of Kings?$q$,
            $a$Откройте игру и нажмите на аватар в левом верхнем углу — ID показан в профиле под именем. Скопируйте номер, а не набирайте: токены приходят на тот ID, который указан, и одна неверная цифра отправит их другому игроку без возможности вернуть.$a$),
        ('honor-of-kings', 1, 'en', $q$Where do I find my Honor of Kings Player ID?$q$,
            $a$Open the game and tap your avatar in the top-left corner — the ID is on the profile under your name. Copy it rather than retyping: the tokens go to whatever ID is given, and one wrong digit sends them to another player with no way back.$a$),
        ('honor-of-kings', 1, 'uz', $q$Honor of Kings'da Player ID ni qayerdan topaman?$q$,
            $a$Oʻyinni oching va chap yuqori burchakdagi avatarni bosing — ID profilda ism ostida koʻrsatilgan. Raqamni qoʻlda termay, nusxa oling: tokenlar koʻrsatilgan ID ga tushadi va bitta xato raqam ularni boshqa oʻyinchiga, qaytarib boʻlmaydigan qilib yuboradi.$a$),

        ('bigo-live', 1, 'ru', $q$Где найти Bigo ID?$q$,
            $a$Откройте приложение, перейдите в «Me» → профиль. ID показан под вашим именем. Нажмите на него, чтобы скопировать: алмазы приходят на указанный ID, и вернуть их нельзя.$a$),
        ('bigo-live', 1, 'en', $q$Where do I find my Bigo ID?$q$,
            $a$Open the app and go to Me → profile. The ID is shown under your name. Tap it to copy: diamonds go to the ID given and cannot be recovered.$a$),
        ('bigo-live', 1, 'uz', $q$Bigo ID ni qayerdan topaman?$q$,
            $a$Ilovani oching, «Me» → profilga oʻting. ID ismingiz ostida koʻrsatilgan. Nusxa olish uchun bosing: olmoslar koʻrsatilgan ID ga tushadi va ularni qaytarib boʻlmaydi.$a$),

        ('likee', 1, 'ru', $q$Где найти Likee ID?$q$,
            $a$Откройте приложение и перейдите в «Профиль» — ID показан под именем пользователя. Нажмите, чтобы скопировать: алмазы уходят на указанный ID безвозвратно.$a$),
        ('likee', 1, 'en', $q$Where do I find my Likee ID?$q$,
            $a$Open the app and go to Profile — the ID is shown under your username. Tap it to copy: diamonds go to the ID given and cannot come back.$a$),
        ('likee', 1, 'uz', $q$Likee ID ni qayerdan topaman?$q$,
            $a$Ilovani oching va «Profil» boʻlimiga oʻting — ID foydalanuvchi nomi ostida koʻrsatilgan. Nusxa olish uchun bosing: olmoslar koʻrsatilgan ID ga qaytarib boʻlmaydigan tarzda tushadi.$a$),

        -- 2. No password. Asked of every by-ID top-up.
        ('honor-of-kings', 2, 'ru', $q$Нужен ли пароль от аккаунта?$q$,
            $a$Нет. Пополнение идёт по публичному Player ID — пароль и вход в аккаунт не нужны, и мы их не запрашиваем. Если сервис просит данные для входа, это не пополнение.$a$),
        ('honor-of-kings', 2, 'en', $q$Do you need my account password?$q$,
            $a$No. The top-up goes by your public Player ID — no password and no sign-in are needed, and we never ask for them. If a service asks for sign-in details, that is not a top-up.$a$),
        ('honor-of-kings', 2, 'uz', $q$Akkaunt paroli kerakmi?$q$,
            $a$Yoʻq. Toʻldirish ommaviy Player ID boʻyicha amalga oshiriladi — parol va akkauntga kirish kerak emas, biz ularni soʻramaymiz. Agar xizmat kirish maʼlumotlarini soʻrasa, bu toʻldirish emas.$a$),

        ('bigo-live', 2, 'ru', $q$Нужен ли пароль или код из SMS?$q$,
            $a$Нет. Пополнение идёт по публичному Bigo ID. Пароль и код подтверждения не нужны, и мы их не запрашиваем.$a$),
        ('bigo-live', 2, 'en', $q$Do you need my password or SMS code?$q$,
            $a$No. The top-up goes by your public Bigo ID. No password and no confirmation code are needed, and we never ask for them.$a$),
        ('bigo-live', 2, 'uz', $q$Parol yoki SMS kod kerakmi?$q$,
            $a$Yoʻq. Toʻldirish ommaviy Bigo ID boʻyicha amalga oshiriladi. Parol va tasdiqlash kodi kerak emas, biz ularni soʻramaymiz.$a$),

        ('likee', 2, 'ru', $q$Нужен ли пароль от аккаунта Likee?$q$,
            $a$Нет. Пополнение идёт по публичному Likee ID — пароль не нужен, и мы его не запрашиваем.$a$),
        ('likee', 2, 'en', $q$Do you need my Likee password?$q$,
            $a$No. The top-up goes by your public Likee ID — no password is needed and we never ask for one.$a$),
        ('likee', 2, 'uz', $q$Likee paroli kerakmi?$q$,
            $a$Yoʻq. Toʻldirish ommaviy Likee ID boʻyicha amalga oshiriladi — parol kerak emas, biz uni soʻramaymiz.$a$),

        -- 3. Speed.
        ('honor-of-kings', 3, 'ru', $q$Как быстро приходит пополнение?$q$,
            $a$Обычно в течение нескольких минут после подтверждения оплаты. Зачисление автоматическое. Если ничего не пришло, напишите в поддержку с номером заказа.$a$),
        ('honor-of-kings', 3, 'en', $q$How fast does it arrive?$q$,
            $a$Usually within a few minutes of the payment being confirmed. Delivery is automatic. If nothing arrived, contact support with your order number.$a$),
        ('honor-of-kings', 3, 'uz', $q$Toʻldirish qancha tez keladi?$q$,
            $a$Odatda toʻlov tasdiqlangach bir necha daqiqa ichida. Hisobga oʻtkazish avtomatik. Agar hech narsa kelmagan boʻlsa, buyurtma raqami bilan qoʻllab-quvvatlashga yozing.$a$),

        ('bigo-live', 3, 'ru', $q$Как быстро приходят алмазы?$q$,
            $a$Обычно в течение нескольких минут после подтверждения оплаты. Зачисление автоматическое. Если алмазы не пришли, напишите в поддержку с номером заказа.$a$),
        ('bigo-live', 3, 'en', $q$How fast do the diamonds arrive?$q$,
            $a$Usually within a few minutes of the payment being confirmed. Delivery is automatic. If they have not arrived, contact support with your order number.$a$),
        ('bigo-live', 3, 'uz', $q$Olmoslar qancha tez keladi?$q$,
            $a$Odatda toʻlov tasdiqlangach bir necha daqiqa ichida. Hisobga oʻtkazish avtomatik. Agar olmoslar kelmagan boʻlsa, buyurtma raqami bilan qoʻllab-quvvatlashga yozing.$a$),

        ('likee', 3, 'ru', $q$Как быстро приходят алмазы?$q$,
            $a$Обычно в течение нескольких минут после подтверждения оплаты. Зачисление автоматическое. Если алмазы не пришли, напишите в поддержку с номером заказа.$a$),
        ('likee', 3, 'en', $q$How fast do the diamonds arrive?$q$,
            $a$Usually within a few minutes of the payment being confirmed. Delivery is automatic. If they have not arrived, contact support with your order number.$a$),
        ('likee', 3, 'uz', $q$Olmoslar qancha tez keladi?$q$,
            $a$Odatda toʻlov tasdiqlangach bir necha daqiqa ichida. Hisobga oʻtkazish avtomatik. Agar olmoslar kelmagan boʻlsa, buyurtma raqami bilan qoʻllab-quvvatlashga yozing.$a$),

        -- 4. What the currency is for.
        ('honor-of-kings', 4, 'ru', $q$На что тратятся токены?$q$,
            $a$На героев, скины, сезонный пропуск Weekly Card и предметы из внутриигрового магазина. Боевого преимущества они не дают — это внешний вид и удобство.$a$),
        ('honor-of-kings', 4, 'en', $q$What are tokens for?$q$,
            $a$Heroes, skins, the Weekly Card season pass and items from the in-game store. They buy no combat advantage — it is looks and convenience.$a$),
        ('honor-of-kings', 4, 'uz', $q$Tokenlar nimaga sarflanadi?$q$,
            $a$Qahramonlar, skinlar, Weekly Card mavsumiy propuski va oʻyin ichidagi doʻkon buyumlariga. Ular jangovar ustunlik bermaydi — bu tashqi koʻrinish va qulaylik.$a$),

        ('bigo-live', 4, 'ru', $q$Для чего нужны алмазы?$q$,
            $a$Ими дарят подарки стримерам во время прямых эфиров, открывают уровни и оформление профиля. Заработать их в самом приложении нельзя.$a$),
        ('bigo-live', 4, 'en', $q$What are diamonds for?$q$,
            $a$They buy gifts for streamers during live broadcasts, levels and profile decorations. There is no way to earn them in the app itself.$a$),
        ('bigo-live', 4, 'uz', $q$Olmoslar nima uchun kerak?$q$,
            $a$Ular bilan jonli efirlarda strimerlarga sovgʻa qilinadi, darajalar va profil bezaklari ochiladi. Ilovaning oʻzida ularni ishlab topib boʻlmaydi.$a$),

        ('likee', 4, 'ru', $q$Для чего нужны алмазы?$q$,
            $a$Ими отправляют подарки авторам во время прямых эфиров и покупают эффекты. В самом приложении их не заработать.$a$),
        ('likee', 4, 'en', $q$What are diamonds for?$q$,
            $a$They send gifts to creators during live broadcasts and buy effects. There is no way to earn them in the app itself.$a$),
        ('likee', 4, 'uz', $q$Olmoslar nima uchun kerak?$q$,
            $a$Ular bilan jonli efirlarda mualliflarga sovgʻa yuboriladi va effektlar sotib olinadi. Ilovaning oʻzida ularni ishlab topib boʻlmaydi.$a$)
) AS t(brand_slug, sort_order, locale, question, answer)
  ON t.brand_slug = b.slug AND t.sort_order = nf.sort_order;

COMMIT;
