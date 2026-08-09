-- scripts/seed/blood_strike_seo.sql
--
-- SEO content pack for the `blood-strike` brand: highlights + short/long
-- descriptions + instructions on `brand_translations`, product names per locale,
-- and 7 FAQ entries with ru/en/uz answers.
--
-- Content-managed, NOT a fixture and NOT an Alembic data migration. Applied to
-- prod by an operator (psql / `!`), gated by the standing deploy rule. Depends
-- on scripts/seed/2026-08-09_blood_strike_import.py having created the brand.
--
-- Idempotent: brand_translations and product_translations rows are UPDATEd in
-- place; FAQs are rebuilt via delete-then-insert, inside one transaction.
--
-- Strings are dollar-quoted ($c$…$c$ / $q$…$q$ / $a$…$a$) so the apostrophe-heavy
-- Uzbek copy needs no escaping.
--
-- Unlike the two Moonton games, this brand has no region trap to warn about —
-- G2B serves Blood Strike from one worldwide product. The question that leads
-- here instead is the UID, because NetEase credits whatever id it is given and
-- does not reverse it: a mistyped digit is gold delivered to a stranger.
--
-- Apply on prod (operator psql):
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     psql -U yupay_app -d yupay -f - < scripts/seed/blood_strike_seo.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Brand translations (highlights, short_description, description, instructions)
-- ---------------------------------------------------------------------------

UPDATE brand_translations SET
    highlights = $c$["Оплата в сумах","По User ID","Проверка ника","Без пароля"]$c$::json,
    short_description = $c$Пополнение Blood Strike — золото и пропуска по User ID, оплата в сумах, без пароля.$c$,
    description = $c$Blood Strike — мобильная королевская битва от NetEase: быстрые раунды, подкаты и стрельба от третьего лица. Золото служит внутриигровой валютой — за него берут скины оружия и персонажей, наборы и сезонные пропуска Strike Pass, а Level Up Pass ускоряет прокачку сезона.

YuPay пополняет аккаунт по публичному User ID — пароль и вход в аккаунт не нужны. Перед оплатой мы проверяем ID и показываем привязанный к нему ник, чтобы золото не ушло чужому игроку: NetEase зачисляет на тот ID, который получил, и обратно перевод не отыгрывает. Оплатить можно в сумах картами Uzcard и Humo через Click, Payme или Uzum; курс виден до оплаты, а золото зачисляется автоматически после подтверждения платежа.$c$,
    instructions = $c$Как пополнить Blood Strike:

1. Выберите, что нужно: золото или пропуск (Level Up Pass, Strike Pass Elite или Premium).
2. Введите User ID — только цифры, без ника. Пароль не нужен.
3. Дождитесь проверки: мы покажем ник, привязанный к этому ID. Сверьте его со своим, прежде чем платить.
4. Выберите способ оплаты: Click, Payme или Uzum. Курс и итог показываются до оплаты.
5. Оплатите — золото или пропуск зачисляются автоматически после подтверждения платежа.

Где найти User ID: откройте Blood Strike и нажмите на аватар в левом верхнем углу лобби — ID показан в профиле. Надёжнее зайти через «Settings» → «Account» → «User ID». Копируйте номер кнопкой копирования, а не вручную.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'blood-strike') AND locale = 'ru';

UPDATE brand_translations SET
    highlights = $c$["Pay in UZS","By User ID","Nickname check","No password"]$c$::json,
    short_description = $c$Top up Blood Strike — gold and passes by User ID, pay in sum, no password.$c$,
    description = $c$Blood Strike is a mobile battle royale by NetEase: fast rounds, slide-tackles and third-person gunplay. Gold is the in-game currency — it buys weapon and character skins, bundles and the seasonal Strike Pass, while the Level Up Pass speeds up season progress.

YuPay tops up your account by its public User ID — no password and no account login needed. Before you pay we verify the ID and show the nickname attached to it, so gold never lands on a stranger's account: NetEase credits whatever id it is given and does not reverse the transfer. You can pay in Uzbek sum with Uzcard and Humo cards via Click, Payme or Uzum; the rate is shown before you pay, and gold is credited automatically once your payment is confirmed.$c$,
    instructions = $c$How to top up Blood Strike:

1. Choose what you need: gold, or a pass (Level Up Pass, Strike Pass Elite or Premium).
2. Enter your User ID — digits only, not your nickname. No password required.
3. Wait for the check: we show the nickname attached to that ID. Confirm it is yours before paying.
4. Choose a payment method: Click, Payme or Uzum. The rate and total are shown before you pay.
5. Pay — gold or the pass is credited automatically once your payment is confirmed.

Where to find your User ID: open Blood Strike and tap your avatar in the top-left corner of the lobby — the ID is on the profile screen. The more reliable route is Settings → Account → User ID. Copy the number with the copy button rather than retyping it.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'blood-strike') AND locale = 'en';

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","User ID orqali","Nik tekshiruvi","Parolsiz"]$c$::json,
    short_description = $c$Blood Strike toʻldirish — oltin va passlar User ID orqali, soʻmda toʻlov, parolsiz.$c$,
    description = $c$Blood Strike — NetEase kompaniyasining mobil battle royale oʻyini: tez raundlar, sirpanishlar va uchinchi shaxsdan otishma. Oltin oʻyin ichidagi valyuta — unga qurol va personaj skinlari, toʻplamlar va mavsumiy Strike Pass olinadi, Level Up Pass esa mavsum darajasini tezlashtiradi.

YuPay hisobingizni ochiq User ID orqali toʻldiradi — parol va akkauntga kirish talab qilinmaydi. Toʻlovdan oldin biz ID ni tekshirib, unga bogʻlangan nikni koʻrsatamiz, shunda oltin begona oʻyinchiga tushmaydi: NetEase qaysi ID berilgan boʻlsa, oʻshanga hisoblaydi va oʻtkazmani orqaga qaytarmaydi. Toʻlovni soʻmda Uzcard va Humo kartalari bilan Click, Payme yoki Uzum orqali amalga oshirishingiz mumkin; kurs toʻlovdan oldin koʻrinadi, oltin esa toʻlov tasdiqlangach avtomatik tushadi.$c$,
    instructions = $c$Blood Strike hisobini qanday toʻldirish:

1. Nima kerakligini tanlang: oltin yoki pass (Level Up Pass, Strike Pass Elite yoki Premium).
2. User ID ni kiriting — faqat raqamlar, nik emas. Parol kerak emas.
3. Tekshiruvni kuting: shu ID ga bogʻlangan nikni koʻrsatamiz. Toʻlashdan oldin oʻzingiznikiga solishtiring.
4. Toʻlov usulini tanlang: Click, Payme yoki Uzum. Kurs va yakuniy summa toʻlovdan oldin koʻrsatiladi.
5. Toʻlang — oltin yoki pass toʻlov tasdiqlangach avtomatik tushadi.

User ID ni qayerdan topish mumkin: Blood Strike ni oching va lobbi chap yuqori burchagidagi avatarni bosing — ID profil ekranida. Ishonchliroq yoʻl: «Settings» → «Account» → «User ID». Raqamni qoʻlda termay, nusxa olish tugmasi bilan koʻchiring.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'blood-strike') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- 2. Product names per locale
--
-- `import_game` writes the operator's single product name into all three locale
-- rows, so without this an English or Uzbek visitor reads the Russian one.
-- ---------------------------------------------------------------------------

UPDATE product_translations SET
    name = $c$Золото$c$,
    short_description = $c$Внутриигровая валюта Blood Strike — скины, наборы и покупки в магазине.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'blood-strike-gold') AND locale = 'ru';
UPDATE product_translations SET
    name = $c$Gold$c$,
    short_description = $c$Blood Strike's in-game currency — skins, bundles and shop purchases.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'blood-strike-gold') AND locale = 'en';
UPDATE product_translations SET
    name = $c$Oltin$c$,
    short_description = $c$Blood Strike ichki valyutasi — skinlar, toʻplamlar va doʻkon xaridlari.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'blood-strike-gold') AND locale = 'uz';

UPDATE product_translations SET
    name = $c$Пропуска$c$,
    short_description = $c$Сезонный Strike Pass и Level Up Pass — награды и ускоренная прокачка.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'blood-strike-passes') AND locale = 'ru';
UPDATE product_translations SET
    name = $c$Passes$c$,
    short_description = $c$The seasonal Strike Pass and Level Up Pass — rewards and faster progress.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'blood-strike-passes') AND locale = 'en';
UPDATE product_translations SET
    name = $c$Passlar$c$,
    short_description = $c$Mavsumiy Strike Pass va Level Up Pass — mukofotlar va tez daraja.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'blood-strike-passes') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- 3. FAQs (rebuilt each run: delete cascades to brand_faq_translations)
-- ---------------------------------------------------------------------------

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'blood-strike');

WITH bs AS (
    SELECT id FROM brands WHERE slug = 'blood-strike'
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), bs.id, v.sort_order, true
    FROM bs, (VALUES (1), (2), (3), (4), (5), (6), (7)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. UID — единственная необратимая ошибка на этой странице.
        (1, 'ru', $q$Как узнать свой User ID в Blood Strike?$q$,
            $a$Откройте игру и нажмите на аватар в левом верхнем углу лобби — User ID показан в профиле. Надёжнее зайти через «Settings» → «Account» → «User ID». ID состоит только из цифр, ник вводить не нужно. Копируйте номер кнопкой копирования рядом с ним, а не вручную: NetEase зачисляет на тот ID, который получил, и одна неверная цифра отправит золото чужому игроку без возможности вернуть.$a$),
        (1, 'en', $q$How do I find my Blood Strike User ID?$q$,
            $a$Open the game and tap your avatar in the top-left corner of the lobby — the User ID is on the profile screen. The more reliable route is Settings → Account → User ID. The ID is digits only; do not enter your nickname. Copy it with the copy button next to it rather than retyping: NetEase credits whatever id it receives, and one wrong digit sends the gold to a stranger with no way back.$a$),
        (1, 'uz', $q$Blood Strike'da User ID ni qanday bilish mumkin?$q$,
            $a$Oʻyinni oching va lobbi chap yuqori burchagidagi avatarni bosing — User ID profil ekranida koʻrsatiladi. Ishonchliroq yoʻl: «Settings» → «Account» → «User ID». ID faqat raqamlardan iborat, nik kiritish shart emas. Raqamni qoʻlda termay, yonidagi nusxa olish tugmasi bilan koʻchiring: NetEase qaysi ID ni olgan boʻlsa, oʻshanga hisoblaydi va bitta xato raqam oltinni begona oʻyinchiga, qaytarib boʻlmaydigan qilib yuboradi.$a$),

        -- 2. Проверка ника до оплаты.
        (2, 'ru', $q$Как убедиться, что золото уйдёт на мой аккаунт?$q$,
            $a$После ввода User ID нажмите «Проверить» — мы запросим у поставщика ник, привязанный к этому ID, и покажем его до оплаты. Если ник ваш, всё верно. Если ник чужой или не находится — не платите: проверьте, что скопировали ID из своего аккаунта полностью и без пробелов.$a$),
        (2, 'en', $q$How do I make sure the gold reaches my account?$q$,
            $a$After entering your User ID, tap “Check” — we ask the supplier for the nickname attached to that ID and show it to you before payment. If it is yours, you are set. If it is someone else's or nothing is found, do not pay: check that you copied the ID from your own account, in full and with no spaces.$a$),
        (2, 'uz', $q$Oltin mening hisobimga tushishiga qanday ishonch hosil qilaman?$q$,
            $a$User ID ni kiritgach, «Tekshirish» tugmasini bosing — biz taʼminotchidan shu ID ga bogʻlangan nikni soʻrab, toʻlovdan oldin koʻrsatamiz. Nik sizniki boʻlsa, hammasi joyida. Agar nik begona boʻlsa yoki topilmasa, toʻlamang: ID ni oʻz hisobingizdan toʻliq va boʻshliqsiz nusxalaganingizni tekshiring.$a$),

        -- 3. Что такое золото.
        (3, 'ru', $q$Что такое золото Blood Strike и что на него купить?$q$,
            $a$Золото — внутриигровая валюта Blood Strike. За него покупают скины оружия и персонажей, наборы и предметы в магазине, а также открывают сезонные пропуска. Чем крупнее номинал, тем выгоднее выходит единица золота.$a$),
        (3, 'en', $q$What is Blood Strike gold and what can I buy with it?$q$,
            $a$Gold is the in-game currency of Blood Strike. It buys weapon and character skins, bundles and shop items, and unlocks the seasonal passes. The larger the pack, the better the price per unit of gold.$a$),
        (3, 'uz', $q$Blood Strike oltini nima va unga nima sotib olish mumkin?$q$,
            $a$Oltin — Blood Strike oʻyinining ichki valyutasi. Unga qurol va personaj skinlari, toʻplamlar va doʻkon buyumlari olinadi, mavsumiy passlar ochiladi. Nominal qanchalik katta boʻlsa, bir birlik oltin shunchalik arzonga tushadi.$a$),

        -- 4. Пропуска — чем отличаются.
        (4, 'ru', $q$Чем отличаются Level Up Pass и Strike Pass?$q$,
            $a$Strike Pass — сезонный боевой пропуск: он открывает платную ветку наград, которые выдаются по мере набора уровней сезона. Elite и Premium отличаются объёмом наград. Level Up Pass — не набор наград, а ускорение: он поднимает уровень сезона, чтобы награды открылись быстрее. Если сезон только начался, обычно берут Strike Pass; Level Up Pass имеет смысл ближе к концу сезона.$a$),
        (4, 'en', $q$What is the difference between the Level Up Pass and the Strike Pass?$q$,
            $a$The Strike Pass is the seasonal battle pass: it unlocks the paid reward track, handed out as you gain season levels. Elite and Premium differ in how much they contain. The Level Up Pass is not a reward set but an accelerator — it raises your season level so the rewards unlock sooner. Early in a season people usually buy the Strike Pass; the Level Up Pass makes more sense near the end.$a$),
        (4, 'uz', $q$Level Up Pass va Strike Pass orasidagi farq nima?$q$,
            $a$Strike Pass — mavsumiy jangovar pass: u mavsum darajalari toʻplangan sari beriladigan pullik mukofot yoʻlagini ochadi. Elite va Premium mukofotlar hajmi bilan farqlanadi. Level Up Pass esa mukofot toʻplami emas, tezlatkich — u mavsum darajasini koʻtaradi, shunda mukofotlar tezroq ochiladi. Mavsum boshida odatda Strike Pass olinadi, Level Up Pass esa mavsum oxiriga yaqin mantiqli.$a$),

        -- 5. Пароль.
        (5, 'ru', $q$Нужен ли пароль от аккаунта?$q$,
            $a$Нет. Пополнение проходит по публичному User ID — пароль и вход в аккаунт не требуются, и мы их не запрашиваем. Любой сервис, который просит пароль от игрового аккаунта, — повод насторожиться.$a$),
        (5, 'en', $q$Do you need my account password?$q$,
            $a$No. Top-ups run on your public User ID — no password and no account login are required, and we never ask for them. Any service that asks for your game password is a red flag.$a$),
        (5, 'uz', $q$Akkaunt paroli kerakmi?$q$,
            $a$Yoʻq. Toʻldirish ochiq User ID orqali amalga oshadi — parol va akkauntga kirish talab qilinmaydi, biz ularni soʻramaymiz. Oʻyin parolini soʻraydigan har qanday xizmat — ehtiyot boʻlish uchun sabab.$a$),

        -- 6. Оплата и скорость.
        (6, 'ru', $q$Можно ли платить в сумах и за сколько зачисляется золото?$q$,
            $a$Да, оплата в узбекских сумах доступна картами Uzcard и Humo через Click, Payme и Uzum; курс и итоговая сумма показываются до оплаты. Золото и пропуска зачисляются автоматически после подтверждения платежа, обычно в течение нескольких минут.$a$),
        (6, 'en', $q$Can I pay in Uzbek sum, and how fast is gold credited?$q$,
            $a$Yes — you can pay in Uzbek sum with Uzcard and Humo cards via Click, Payme and Uzum, and the rate and final total are shown before you pay. Gold and passes are credited automatically once your payment is confirmed, usually within a few minutes.$a$),
        (6, 'uz', $q$Soʻmda toʻlash mumkinmi va oltin qancha vaqtda tushadi?$q$,
            $a$Ha — oʻzbek soʻmida Uzcard va Humo kartalari orqali Click, Payme va Uzum bilan toʻlash mumkin, kurs va yakuniy summa toʻlovdan oldin koʻrsatiladi. Oltin va passlar toʻlov tasdiqlangach avtomatik tushadi, odatda bir necha daqiqada.$a$),

        -- 7. Официальность.
        (7, 'ru', $q$Это официальный сайт Blood Strike?$q$,
            $a$Нет. YuPay — независимый сервис пополнения и не связан с NetEase, издателем Blood Strike. Мы покупаем и перепродаём пополнения по прозрачному курсу, который виден до оплаты.$a$),
        (7, 'en', $q$Is this the official Blood Strike website?$q$,
            $a$No. YuPay is an independent top-up service and is not affiliated with NetEase, the publisher of Blood Strike. We buy and resell top-ups at a transparent rate that is shown before you pay.$a$),
        (7, 'uz', $q$Bu Blood Strike rasmiy saytimi?$q$,
            $a$Yoʻq. YuPay — mustaqil toʻldirish xizmati va Blood Strike noshiri NetEase bilan bogʻliq emas. Biz toʻldirishlarni shaffof kurs boʻyicha sotib olib, qayta sotamiz; kurs toʻlovdan oldin koʻrinadi.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
