-- scripts/seed/imo_seo.sql
--
-- SEO content pack for the `imo` brand: highlights + short/long descriptions +
-- instructions on `brand_translations`, the product name per locale, and 6 FAQ
-- entries with ru/en/uz answers.
--
-- Content-managed, NOT a fixture and NOT an Alembic data migration. Applied to
-- prod by an operator (psql / `!`), gated by the standing deploy rule. Depends
-- on scripts/seed/2026-09-20_imo_import.py having created the brand.
--
-- Idempotent: brand_translations and product_translations rows are UPDATEd in
-- place; FAQs are rebuilt via delete-then-insert, inside one transaction.
--
-- Strings are dollar-quoted ($c$…$c$ / $q$…$q$ / $a$…$a$) so the apostrophe-heavy
-- Uzbek copy needs no escaping.
--
-- Two things this copy must NOT say, and both are the point:
--
--   * **It does not promise nickname verification.** Neither supplier gives us
--     a validator for IMO we have tested (see the import script), so the page
--     leans on "copy the ID, do not retype it" instead. Promising a check we
--     do not run is the one claim that would make a mistyped ID our fault.
--   * **It does not say diamonds can be refunded or moved.** They cannot.
--
-- Apply on prod (operator psql):
--   docker exec -i yupay-prod-postgres-1 sh -lc \
--     'psql -U $POSTGRES_USER -d $POSTGRES_DB -v ON_ERROR_STOP=1' \
--     < scripts/seed/imo_seo.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Brand translations
-- ---------------------------------------------------------------------------

UPDATE brand_translations SET
    highlights = $c$["Оплата в сумах","По IMO ID","Без пароля","От 10 алмазов"]$c$::json,
    short_description = $c$Пополнение imo — алмазы по IMO ID, оплата в сумах картой Uzcard или Humo, без пароля.$c$,
    description = $c$imo — мессенджер с видеозвонками и прямыми эфирами. Алмазы это внутренняя валюта приложения: за них дарят подарки стримерам во время эфиров, открывают премиальные стикеры и оформление профиля. Заработать алмазы в самом приложении нельзя, их покупают.

YuPay пополняет баланс по публичному IMO ID — пароль от аккаунта и код из SMS не нужны, и мы их не запрашиваем. Номиналы идут от 10 алмазов до 21 000, так что можно взять и небольшую сумму на один подарок, и крупный пакет сразу. Оплата в узбекских сумах картами Uzcard и Humo через Click, Payme, Uzum или Paynet; сумма к оплате видна до подтверждения, алмазы зачисляются автоматически.

Важно: IMO зачисляет алмазы на тот ID, который получил, и обратный перевод не предусмотрен. Скопируйте свой ID из профиля вместо того, чтобы набирать его вручную.$c$,
    instructions = $c$Как пополнить imo:

1. Выберите пакет алмазов — от 10 до 21 000.
2. Введите IMO ID. Пароль и код из SMS не нужны.
3. Выберите способ оплаты: Click, Payme, Uzum или Paynet.
4. Оплатите — алмазы зачисляются на аккаунт автоматически.

Где взять IMO ID: откройте imo, перейдите в «Профиль» — ID показан под вашим именем. Нажмите на номер, чтобы скопировать его. Набирать вручную не стоит: ID состоит только из цифр, а одна ошибка отправит алмазы другому человеку, и вернуть их будет нельзя.$c$
WHERE locale = 'ru' AND brand_id = (SELECT id FROM brands WHERE slug = 'imo');

UPDATE brand_translations SET
    highlights = $c$["Pay in som","By IMO ID","No password","From 10 diamonds"]$c$::json,
    short_description = $c$Top up imo — diamonds by IMO ID, paid in som with an Uzcard or Humo card, no password.$c$,
    description = $c$imo is a messenger with video calls and live streams. Diamonds are the app's own currency: they buy gifts for streamers during a broadcast, premium stickers and profile decorations. There is no way to earn diamonds inside the app — they are bought.

YuPay tops up the balance by your public IMO ID — no account password and no SMS code are needed, and we never ask for them. Denominations run from 10 diamonds to 21 000, so a single gift and a large pack are both one purchase. Pay in Uzbek sum with Uzcard and Humo cards via Click, Payme, Uzum or Paynet; the total is shown before you confirm, and the diamonds are credited automatically.

One thing to be clear about: IMO credits the ID it receives, and there is no transfer back. Copy your ID from your profile rather than retyping it.$c$,
    instructions = $c$How to top up imo:

1. Pick a diamond pack — anywhere from 10 to 21 000.
2. Enter your IMO ID. No password and no SMS code needed.
3. Choose a payment method: Click, Payme, Uzum or Paynet.
4. Pay — the diamonds are credited to the account automatically.

Where to find your IMO ID: open imo and go to Profile — the ID is shown under your name. Tap the number to copy it. Do not retype it: the ID is digits only, and one wrong digit sends the diamonds to somebody else, with no way to get them back.$c$
WHERE locale = 'en' AND brand_id = (SELECT id FROM brands WHERE slug = 'imo');

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","IMO ID boʻyicha","Parolsiz","10 olmosdan"]$c$::json,
    short_description = $c$imo ni toʻldirish — IMO ID boʻyicha olmoslar, Uzcard yoki Humo karta bilan soʻmda toʻlov, parolsiz.$c$,
    description = $c$imo — video qoʻngʻiroqlar va jonli efirlar bilan messenjer. Olmoslar ilovaning ichki valyutasi: ular bilan efir vaqtida strimerlarga sovgʻa qilinadi, premium stikerlar va profil bezaklari ochiladi. Olmoslarni ilovaning oʻzida ishlab topib boʻlmaydi, ular sotib olinadi.

YuPay balansni ommaviy IMO ID boʻyicha toʻldiradi — akkaunt paroli va SMS kod kerak emas, biz ularni soʻramaymiz. Nominallar 10 olmosdan 21 000 gacha, shuning uchun bitta sovgʻaga kichik summani ham, yirik paketni ham olish mumkin. Toʻlov oʻzbek soʻmida Uzcard va Humo kartalari orqali Click, Payme, Uzum yoki Paynet bilan; toʻlanadigan summa tasdiqlashdan oldin koʻrinadi, olmoslar avtomatik tushadi.

Muhim: IMO olmoslarni qaysi ID ni olgan boʻlsa, oʻshanga hisoblaydi va orqaga oʻtkazish koʻzda tutilmagan. ID ni qoʻlda termay, profilingizdan nusxa oling.$c$,
    instructions = $c$imo ni qanday toʻldirish:

1. Olmoslar paketini tanlang — 10 dan 21 000 gacha.
2. IMO ID ni kiriting. Parol va SMS kod kerak emas.
3. Toʻlov usulini tanlang: Click, Payme, Uzum yoki Paynet.
4. Toʻlang — olmoslar hisobga avtomatik tushadi.

IMO ID ni qayerdan olish: imo ni oching, «Profil» boʻlimiga oʻting — ID ismingiz ostida koʻrsatilgan. Nusxa olish uchun raqamni bosing. Qoʻlda termang: ID faqat raqamlardan iborat va bitta xato olmoslarni boshqa odamga yuboradi, ularni qaytarib boʻlmaydi.$c$
WHERE locale = 'uz' AND brand_id = (SELECT id FROM brands WHERE slug = 'imo');

-- ---------------------------------------------------------------------------
-- 2. Product name per locale
-- ---------------------------------------------------------------------------

UPDATE product_translations SET name = $c$Алмазы$c$
WHERE locale = 'ru' AND product_id = (SELECT id FROM products WHERE slug = 'imo-diamonds');

UPDATE product_translations SET name = $c$Diamonds$c$
WHERE locale = 'en' AND product_id = (SELECT id FROM products WHERE slug = 'imo-diamonds');

UPDATE product_translations SET name = $c$Olmoslar$c$
WHERE locale = 'uz' AND product_id = (SELECT id FROM products WHERE slug = 'imo-diamonds');

-- ---------------------------------------------------------------------------
-- 3. FAQ
-- ---------------------------------------------------------------------------

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'imo');

WITH b AS (
    SELECT id FROM brands WHERE slug = 'imo'
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), b.id, v.sort_order, true
    FROM b, (VALUES (1), (2), (3), (4), (5), (6)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. The ID — the one irreversible mistake on this page.
        (1, 'ru', $q$Где найти свой IMO ID?$q$,
            $a$Откройте imo и перейдите в «Профиль» — ID показан под вашим именем. Нажмите на номер, чтобы скопировать его. Не набирайте ID вручную: он состоит только из цифр, IMO зачисляет алмазы на тот ID, который получил, и одна неверная цифра отправит их другому человеку без возможности вернуть.$a$),
        (1, 'en', $q$Where do I find my IMO ID?$q$,
            $a$Open imo and go to Profile — the ID is shown under your name. Tap the number to copy it. Do not retype the ID: it is digits only, IMO credits whatever ID it receives, and one wrong digit sends the diamonds to somebody else with no way back.$a$),
        (1, 'uz', $q$IMO ID ni qayerdan topaman?$q$,
            $a$imo ni oching va «Profil» boʻlimiga oʻting — ID ismingiz ostida koʻrsatiladi. Nusxa olish uchun raqamni bosing. ID ni qoʻlda termang: u faqat raqamlardan iborat, IMO qaysi ID ni olgan boʻlsa oʻshanga hisoblaydi va bitta xato raqam olmoslarni boshqa odamga, qaytarib boʻlmaydigan qilib yuboradi.$a$),

        -- 2. No password. The question every by-ID top-up gets asked.
        (2, 'ru', $q$Нужен ли пароль от аккаунта imo?$q$,
            $a$Нет. Пополнение идёт по публичному IMO ID — пароль и код из SMS не нужны, и мы их не запрашиваем. Если сервис просит у вас данные для входа в imo, это не пополнение.$a$),
        (2, 'en', $q$Do you need my imo account password?$q$,
            $a$No. The top-up goes by your public IMO ID — no password and no SMS code are needed, and we never ask for them. If a service asks for your imo sign-in details, that is not a top-up.$a$),
        (2, 'uz', $q$imo akkaunti paroli kerakmi?$q$,
            $a$Yoʻq. Toʻldirish ommaviy IMO ID boʻyicha amalga oshiriladi — parol va SMS kod kerak emas, biz ularni soʻramaymiz. Agar xizmat sizdan imo ga kirish maʼlumotlarini soʻrasa, bu toʻldirish emas.$a$),

        -- 3. Speed.
        (3, 'ru', $q$Как быстро приходят алмазы?$q$,
            $a$Обычно в течение нескольких минут после подтверждения оплаты. Зачисление автоматическое, оператор в нём не участвует. Если алмазы не пришли, напишите в поддержку с номером заказа.$a$),
        (3, 'en', $q$How fast do the diamonds arrive?$q$,
            $a$Usually within a few minutes of the payment being confirmed. Delivery is automatic, with no operator involved. If the diamonds have not arrived, contact support with your order number.$a$),
        (3, 'uz', $q$Olmoslar qancha tez keladi?$q$,
            $a$Odatda toʻlov tasdiqlangach bir necha daqiqa ichida. Hisobga oʻtkazish avtomatik, operator ishtirok etmaydi. Agar olmoslar kelmagan boʻlsa, buyurtma raqami bilan qoʻllab-quvvatlashga yozing.$a$),

        -- 4. What diamonds are for.
        (4, 'ru', $q$Для чего нужны алмазы в imo?$q$,
            $a$Алмазы это внутренняя валюта приложения. За них дарят подарки во время прямых эфиров, покупают премиальные стикеры и оформление профиля. Заработать их в самом imo нельзя.$a$),
        (4, 'en', $q$What are diamonds for in imo?$q$,
            $a$Diamonds are the app's own currency. They buy gifts during live streams, premium stickers and profile decorations. There is no way to earn them inside imo itself.$a$),
        (4, 'uz', $q$imo da olmoslar nima uchun kerak?$q$,
            $a$Olmoslar ilovaning ichki valyutasi. Ular bilan jonli efirlarda sovgʻa qilinadi, premium stikerlar va profil bezaklari sotib olinadi. Ularni imo ning oʻzida ishlab topib boʻlmaydi.$a$),

        -- 5. Payment methods — the live list, not a guess.
        (5, 'ru', $q$Как оплатить пополнение?$q$,
            $a$В узбекских сумах картой Uzcard или Humo через Click, Payme, Uzum или Paynet. Сумма к оплате в сумах показывается до подтверждения, дополнительной комиссии сверху нет.$a$),
        (5, 'en', $q$How do I pay?$q$,
            $a$In Uzbek sum with an Uzcard or Humo card via Click, Payme, Uzum or Paynet. The total in sum is shown before you confirm, with no extra fee on top.$a$),
        (5, 'uz', $q$Toʻldirishni qanday toʻlash mumkin?$q$,
            $a$Oʻzbek soʻmida Uzcard yoki Humo kartasi bilan Click, Payme, Uzum yoki Paynet orqali. Soʻmdagi summa tasdiqlashdan oldin koʻrsatiladi, ustiga qoʻshimcha komissiya yoʻq.$a$),

        -- 6. The wrong-ID question, answered honestly rather than reassuringly.
        (6, 'ru', $q$Что будет, если я ошибусь в IMO ID?$q$,
            $a$Алмазы уйдут на тот аккаунт, чей ID был указан, и вернуть их нельзя — так устроено зачисление на стороне imo. Поэтому копируйте ID из профиля, а не набирайте его вручную, и проверьте номер перед оплатой.$a$),
        (6, 'en', $q$What happens if I get the IMO ID wrong?$q$,
            $a$The diamonds go to whichever account that ID belongs to, and they cannot be recovered — that is how crediting works on imo's side. So copy the ID from your profile instead of retyping it, and check the number before you pay.$a$),
        (6, 'uz', $q$IMO ID da xato qilsam nima boʻladi?$q$,
            $a$Olmoslar oʻsha ID tegishli boʻlgan akkauntga tushadi va ularni qaytarib boʻlmaydi — imo tomonida hisobga oʻtkazish shunday ishlaydi. Shuning uchun ID ni qoʻlda termay, profilingizdan nusxa oling va toʻlovdan oldin raqamni tekshiring.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
