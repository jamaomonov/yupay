-- scripts/seed/whiteout_survival_seo.sql
--
-- SEO content pack for the `whiteout-survival` brand: highlights + short/long
-- descriptions + instructions on `brand_translations`, product names per locale,
-- and 7 FAQ entries with ru/en/uz answers.
--
-- Content-managed, NOT a fixture and NOT an Alembic data migration. Applied to
-- prod by an operator (psql / `!`), gated by the standing deploy rule. Depends
-- on scripts/seed/2026-08-09_whiteout_survival_import.py having created the brand.
--
-- Idempotent: brand_translations and product_translations rows are UPDATEd in
-- place; FAQs are rebuilt via delete-then-insert, inside one transaction.
--
-- Strings are dollar-quoted ($c$…$c$ / $q$…$q$ / $a$…$a$) so the apostrophe-heavy
-- Uzbek copy needs no escaping.
--
-- No region trap on this brand and no confusing product split — one currency,
-- one field. What the copy has to carry instead is what a Frost Star actually
-- is, because it is not the currency players spend: they spend gems, and Frost
-- Stars are what the store takes. A customer who expects gems to appear in their
-- balance and sees Frost Stars will open a ticket.
--
-- Apply on prod (operator psql):
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     psql -U yupay_app -d yupay -f - < scripts/seed/whiteout_survival_seo.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Brand translations (highlights, short_description, description, instructions)
-- ---------------------------------------------------------------------------

UPDATE brand_translations SET
    highlights = $c$["Оплата в сумах","По Player ID","Проверка ника","Без пароля"]$c$::json,
    short_description = $c$Пополнение Whiteout Survival — Frost Stars по Player ID, оплата в сумах, без пароля.$c$,
    description = $c$Whiteout Survival — мобильная стратегия на выживание в вечной мерзлоте: вы отстраиваете убежище, греете поселенцев, собираете героев и воюете за ресурсы в альянсах. Frost Star — валюта пополнения: это то, чем вы платите во внутриигровом магазине за гемы, наборы ресурсов, снаряжение героев и сезонные предложения.

YuPay пополняет аккаунт по публичному Player ID — пароль и вход в аккаунт не нужны. Перед оплатой мы проверяем ID и показываем привязанное к нему имя, чтобы покупка не ушла чужому игроку. Оплатить можно в сумах картами Uzcard и Humo через Click, Payme или Uzum; курс виден до оплаты, а Frost Stars зачисляются автоматически после подтверждения платежа.$c$,
    instructions = $c$Как пополнить Whiteout Survival:

1. Выберите номинал Frost Stars.
2. Введите Player ID — только цифры, без имени. Пароль не нужен.
3. Дождитесь проверки: мы покажем имя, привязанное к этому ID. Сверьте его со своим, прежде чем платить.
4. Выберите способ оплаты: Click, Payme или Uzum. Курс и итог показываются до оплаты.
5. Оплатите — Frost Stars зачисляются автоматически после подтверждения платежа.

Где найти Player ID: откройте Whiteout Survival и нажмите на аватар в левом верхнем углу. Player ID показан в профиле под именем, рядом с ним есть кнопка копирования — пользуйтесь ей, а не набирайте номер вручную.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'whiteout-survival') AND locale = 'ru';

UPDATE brand_translations SET
    highlights = $c$["Pay in UZS","By Player ID","Nickname check","No password"]$c$::json,
    short_description = $c$Top up Whiteout Survival — Frost Stars by Player ID, pay in sum, no password.$c$,
    description = $c$Whiteout Survival is a mobile survival strategy set in a frozen world: you rebuild a shelter, keep your settlers warm, collect heroes and fight alliances over resources. Frost Star is the top-up currency — it is what you pay with in the in-game store for gems, resource bundles, hero gear and seasonal offers.

YuPay tops up your account by its public Player ID — no password and no account login needed. Before you pay we verify the ID and show the name attached to it, so the purchase never lands on a stranger's account. You can pay in Uzbek sum with Uzcard and Humo cards via Click, Payme or Uzum; the rate is shown before you pay, and Frost Stars are credited automatically once your payment is confirmed.$c$,
    instructions = $c$How to top up Whiteout Survival:

1. Choose a Frost Stars amount.
2. Enter your Player ID — digits only, not your name. No password required.
3. Wait for the check: we show the name attached to that ID. Confirm it is yours before paying.
4. Choose a payment method: Click, Payme or Uzum. The rate and total are shown before you pay.
5. Pay — Frost Stars are credited automatically once your payment is confirmed.

Where to find your Player ID: open Whiteout Survival and tap your avatar in the top-left corner. The Player ID sits in the profile under your name with a copy button beside it — use the button rather than retyping the number.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'whiteout-survival') AND locale = 'en';

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","Player ID orqali","Nik tekshiruvi","Parolsiz"]$c$::json,
    short_description = $c$Whiteout Survival toʻldirish — Frost Stars Player ID orqali, soʻmda toʻlov, parolsiz.$c$,
    description = $c$Whiteout Survival — muzlagan dunyoda omon qolish haqidagi mobil strategiya: siz boshpana quryapsiz, aholini isitasiz, qahramonlar toʻplaysiz va alyanslar bilan resurslar uchun kurashasiz. Frost Star — toʻldirish valyutasi: oʻyin ichidagi doʻkonda gemlar, resurs toʻplamlari, qahramon jihozlari va mavsumiy takliflar uchun aynan shu bilan toʻlanadi.

YuPay hisobingizni ochiq Player ID orqali toʻldiradi — parol va akkauntga kirish talab qilinmaydi. Toʻlovdan oldin biz ID ni tekshirib, unga bogʻlangan ismni koʻrsatamiz, shunda xarid begona oʻyinchiga tushmaydi. Toʻlovni soʻmda Uzcard va Humo kartalari bilan Click, Payme yoki Uzum orqali amalga oshirishingiz mumkin; kurs toʻlovdan oldin koʻrinadi, Frost Stars esa toʻlov tasdiqlangach avtomatik tushadi.$c$,
    instructions = $c$Whiteout Survival hisobini qanday toʻldirish:

1. Frost Stars nominalini tanlang.
2. Player ID ni kiriting — faqat raqamlar, ism emas. Parol kerak emas.
3. Tekshiruvni kuting: shu ID ga bogʻlangan ismni koʻrsatamiz. Toʻlashdan oldin oʻzingiznikiga solishtiring.
4. Toʻlov usulini tanlang: Click, Payme yoki Uzum. Kurs va yakuniy summa toʻlovdan oldin koʻrsatiladi.
5. Toʻlang — Frost Stars toʻlov tasdiqlangach avtomatik tushadi.

Player ID ni qayerdan topish mumkin: Whiteout Survival ni oching va chap yuqori burchakdagi avatarni bosing. Player ID profilda ism ostida, yonida nusxa olish tugmasi bilan koʻrsatiladi — raqamni qoʻlda termay, oʻsha tugmadan foydalaning.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'whiteout-survival') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- 2. Product name per locale
--
-- `import_game` writes the operator's single product name into all three locale
-- rows. "Frost Stars" stays untranslated — it is the in-game name of the
-- currency and the storefront should say what the store says — but the subtitle
-- is localized, because that is where a customer learns what they are buying.
-- ---------------------------------------------------------------------------

UPDATE product_translations SET
    name = $c$Frost Stars$c$,
    short_description = $c$Валюта пополнения: тратится во внутриигровом магазине на гемы и наборы.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'whiteout-survival-frost-stars')
  AND locale = 'ru';
UPDATE product_translations SET
    name = $c$Frost Stars$c$,
    short_description = $c$The top-up currency: spent in the in-game store on gems and bundles.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'whiteout-survival-frost-stars')
  AND locale = 'en';
UPDATE product_translations SET
    name = $c$Frost Stars$c$,
    short_description = $c$Toʻldirish valyutasi: oʻyin doʻkonida gem va toʻplamlarga sarflanadi.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'whiteout-survival-frost-stars')
  AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- 3. FAQs (rebuilt each run: delete cascades to brand_faq_translations)
-- ---------------------------------------------------------------------------

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'whiteout-survival');

WITH wos AS (
    SELECT id FROM brands WHERE slug = 'whiteout-survival'
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), wos.id, v.sort_order, true
    FROM wos, (VALUES (1), (2), (3), (4), (5), (6), (7)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. Frost Star против гемов — главный источник недопонимания.
        (1, 'ru', $q$Что такое Frost Star и чем он отличается от гемов?$q$,
            $a$Frost Star — это валюта пополнения, а не та, которой вы платите внутри игры за постройки. После зачисления Frost Stars появляются на балансе, и уже за них во внутриигровом магазине берут гемы, наборы ресурсов, снаряжение героев и сезонные предложения. То есть гемы вы покупаете за Frost Stars, а не получаете напрямую. Курс у издателя фиксированный: 100 Frost Stars за один доллар, поэтому номинал 999 соответствует официальному набору за $9.99.$a$),
        (1, 'en', $q$What is a Frost Star, and how is it different from gems?$q$,
            $a$A Frost Star is the top-up currency, not the one you spend in-game on construction. Once credited, Frost Stars sit in your balance and the in-game store takes them for gems, resource bundles, hero gear and seasonal offers. So you buy gems with Frost Stars rather than receiving gems directly. The publisher's rate is fixed at 100 Frost Stars per US dollar, which is why the 999 tier matches the official $9.99 pack.$a$),
        (1, 'uz', $q$Frost Star nima va u gemlardan nimasi bilan farq qiladi?$q$,
            $a$Frost Star — toʻldirish valyutasi, oʻyin ichida qurilishga sarflanadigani emas. Hisobga tushgach, Frost Stars balansda turadi va oʻyin doʻkoni ular evaziga gemlar, resurs toʻplamlari, qahramon jihozlari va mavsumiy takliflarni beradi. Yaʼni gemlarni bevosita olmaysiz, ularni Frost Stars evaziga sotib olasiz. Noshirning kursi qatʼiy: bir dollarga 100 Frost Star, shuning uchun 999 nominal rasmiy $9.99 toʻplamiga toʻgʻri keladi.$a$),

        -- 2. Player ID.
        (2, 'ru', $q$Как узнать свой Player ID в Whiteout Survival?$q$,
            $a$Откройте игру и нажмите на аватар в левом верхнем углу. Player ID показан в профиле под вашим именем, рядом с ним есть кнопка копирования. Пользуйтесь кнопкой, а не набирайте вручную: ID состоит только из цифр, а одна неверная цифра отправит покупку чужому игроку.$a$),
        (2, 'en', $q$How do I find my Whiteout Survival Player ID?$q$,
            $a$Open the game and tap your avatar in the top-left corner. The Player ID is shown in the profile under your name, with a copy button beside it. Use the button rather than retyping: the ID is digits only, and one wrong digit sends the purchase to a stranger.$a$),
        (2, 'uz', $q$Whiteout Survival'da Player ID ni qanday bilish mumkin?$q$,
            $a$Oʻyinni oching va chap yuqori burchakdagi avatarni bosing. Player ID profilda ismingiz ostida, yonida nusxa olish tugmasi bilan koʻrsatiladi. Qoʻlda termay, tugmadan foydalaning: ID faqat raqamlardan iborat va bitta xato raqam xaridni begona oʻyinchiga yuboradi.$a$),

        -- 3. Проверка до оплаты.
        (3, 'ru', $q$Как убедиться, что пополнение уйдёт на мой аккаунт?$q$,
            $a$После ввода Player ID нажмите «Проверить» — мы запросим у поставщика имя, привязанное к этому ID, и покажем его до оплаты. Если имя ваше, всё верно. Если имя чужое или не находится — не платите: проверьте, что скопировали ID из своего профиля полностью и без пробелов.$a$),
        (3, 'en', $q$How do I make sure the top-up reaches my account?$q$,
            $a$After entering your Player ID, tap “Check” — we ask the supplier for the name attached to that ID and show it to you before payment. If it is yours, you are set. If it is someone else's or nothing is found, do not pay: check that you copied the ID from your own profile, in full and with no spaces.$a$),
        (3, 'uz', $q$Toʻldirish mening hisobimga tushishiga qanday ishonch hosil qilaman?$q$,
            $a$Player ID ni kiritgach, «Tekshirish» tugmasini bosing — biz taʼminotchidan shu ID ga bogʻlangan ismni soʻrab, toʻlovdan oldin koʻrsatamiz. Ism sizniki boʻlsa, hammasi joyida. Agar ism begona boʻlsa yoki topilmasa, toʻlamang: ID ni oʻz profilingizdan toʻliq va boʻshliqsiz nusxalaganingizni tekshiring.$a$),

        -- 4. Какой номинал брать.
        (4, 'ru', $q$Какой номинал выгоднее?$q$,
            $a$У издателя Frost Star стоит одинаково в любом наборе — 100 звёзд за доллар, — поэтому «скидки за объём» здесь нет: 999 звёзд стоят ровно вдесятеро дороже 99. Выгода крупных наборов появляется уже внутри игры, в акциях магазина, где часть предложений доступна только от определённой суммы. Берите тот номинал, который закрывает нужную покупку, — дробить смысла нет.$a$),
        (4, 'en', $q$Which amount is the better deal?$q$,
            $a$The publisher prices Frost Stars identically in every pack — 100 per dollar — so there is no bulk discount here: 999 stars cost exactly ten times what 99 do. The advantage of larger amounts shows up inside the game, in store promotions that unlock above a certain spend. Pick the amount that covers the purchase you have in mind; splitting it gains you nothing.$a$),
        (4, 'uz', $q$Qaysi nominal foydaliroq?$q$,
            $a$Noshir Frost Star narxini har qanday toʻplamda bir xil belgilaydi — dollariga 100 ta, — shuning uchun bu yerda hajm uchun chegirma yoʻq: 999 yulduz 99 tasidan roppa-rosa oʻn barobar qimmat. Katta nominalning foydasi oʻyin ichida, maʼlum summadan boshlab ochiladigan doʻkon aksiyalarida koʻrinadi. Rejalashtirgan xaridingizni qoplaydigan nominalni oling — boʻlib olishning maʼnosi yoʻq.$a$),

        -- 5. Пароль.
        (5, 'ru', $q$Нужен ли пароль от аккаунта?$q$,
            $a$Нет. Пополнение проходит по публичному Player ID — пароль и вход в аккаунт не требуются, и мы их не запрашиваем. Любой сервис, который просит пароль от игрового аккаунта, — повод насторожиться.$a$),
        (5, 'en', $q$Do you need my account password?$q$,
            $a$No. Top-ups run on your public Player ID — no password and no account login are required, and we never ask for them. Any service that asks for your game password is a red flag.$a$),
        (5, 'uz', $q$Akkaunt paroli kerakmi?$q$,
            $a$Yoʻq. Toʻldirish ochiq Player ID orqali amalga oshadi — parol va akkauntga kirish talab qilinmaydi, biz ularni soʻramaymiz. Oʻyin parolini soʻraydigan har qanday xizmat — ehtiyot boʻlish uchun sabab.$a$),

        -- 6. Оплата и скорость.
        (6, 'ru', $q$Можно ли платить в сумах и за сколько зачисляется?$q$,
            $a$Да, оплата в узбекских сумах доступна картами Uzcard и Humo через Click, Payme и Uzum; курс и итоговая сумма показываются до оплаты. Frost Stars зачисляются автоматически после подтверждения платежа, обычно в течение нескольких минут.$a$),
        (6, 'en', $q$Can I pay in Uzbek sum, and how fast is it credited?$q$,
            $a$Yes — you can pay in Uzbek sum with Uzcard and Humo cards via Click, Payme and Uzum, and the rate and final total are shown before you pay. Frost Stars are credited automatically once your payment is confirmed, usually within a few minutes.$a$),
        (6, 'uz', $q$Soʻmda toʻlash mumkinmi va qancha vaqtda tushadi?$q$,
            $a$Ha — oʻzbek soʻmida Uzcard va Humo kartalari orqali Click, Payme va Uzum bilan toʻlash mumkin, kurs va yakuniy summa toʻlovdan oldin koʻrsatiladi. Frost Stars toʻlov tasdiqlangach avtomatik tushadi, odatda bir necha daqiqada.$a$),

        -- 7. Официальность.
        (7, 'ru', $q$Это официальный сайт Whiteout Survival?$q$,
            $a$Нет. YuPay — независимый сервис пополнения и не связан с Century Games, издателем Whiteout Survival. Мы покупаем и перепродаём пополнения по прозрачному курсу, который виден до оплаты.$a$),
        (7, 'en', $q$Is this the official Whiteout Survival website?$q$,
            $a$No. YuPay is an independent top-up service and is not affiliated with Century Games, the publisher of Whiteout Survival. We buy and resell top-ups at a transparent rate that is shown before you pay.$a$),
        (7, 'uz', $q$Bu Whiteout Survival rasmiy saytimi?$q$,
            $a$Yoʻq. YuPay — mustaqil toʻldirish xizmati va Whiteout Survival noshiri Century Games bilan bogʻliq emas. Biz toʻldirishlarni shaffof kurs boʻyicha sotib olib, qayta sotamiz; kurs toʻlovdan oldin koʻrinadi.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
