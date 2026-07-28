-- scripts/seed/free_fire_seo.sql
--
-- SEO content pack for the `free-fire` brand: highlights + short/long
-- descriptions + instructions on `brand_translations`, and 7 FAQ entries with
-- ru/en/uz answers.
--
-- Content-managed, NOT a fixture and NOT an Alembic data migration. Applied to
-- prod by an operator (psql / `!`), gated by the standing deploy rule. Depends on
-- migration 0032_brand_highlights (adds `brand_translations.highlights`).
--
-- Idempotent: brand_translations rows are UPDATEd in place; FAQs are rebuilt via
-- delete-then-insert. Wrapped in a single transaction so a half-run cannot leave
-- partial state. Re-running yields identical final content (FAQ row ids are
-- regenerated each run, which is fine — nothing references them).
--
-- Strings are dollar-quoted ($c$…$c$ / $q$…$q$ / $a$…$a$) so the apostrophe-heavy
-- Uzbek copy needs no escaping.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Brand translations (highlights, short_description, description, instructions)
-- ---------------------------------------------------------------------------

UPDATE brand_translations SET
    highlights = $c$["Оплата в сумах","По ID игрока","Автоматически","Без пароля"]$c$::json,
    short_description = $c$Пополнение Free Fire — алмазы и подписка по игровому ID, оплата в сумах, без пароля.$c$,
    description = $c$Free Fire (и Free Fire MAX от Garena) — мобильная королевская битва, где алмазы служат внутриигровой валютой. За алмазы покупают скины оружия и персонажей, эмоуты, наряды и Elite Pass текущего сезона, а недельная и месячная подписка ежедневно начисляют алмазы и дают бонусы для активных игроков.

YuPay пополняет ваш аккаунт по публичному игровому ID — пароль и вход в аккаунт не нужны. Оплатить можно в сумах картами Uzcard и Humo через Click, Payme или Uzum; курс показывается до оплаты, а алмазы или подписка зачисляются автоматически после подтверждения платежа.$c$,
    instructions = $c$Как пополнить Free Fire:

1. Введите игровой ID Free Fire (ваш публичный ID из профиля) — пароль не нужен.
2. Выберите, что нужно: алмазы или подписку (недельную или месячную).
3. Выберите способ оплаты: Click, Payme или Uzum. Курс и итог показываются до оплаты.
4. Оплатите — алмазы или подписка зачисляются на аккаунт автоматически после подтверждения платежа.

Где найти игровой ID Free Fire: откройте игру и в лобби нажмите на аватар в левом верхнем углу — ID игрока указан под вашим никнеймом в профиле.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'free-fire') AND locale = 'ru';

UPDATE brand_translations SET
    highlights = $c$["Pay in UZS","By player ID","Automatic","No password"]$c$::json,
    short_description = $c$Top up Free Fire — diamonds and membership by player ID, pay in sum, no password.$c$,
    description = $c$Free Fire (and Free Fire MAX by Garena) is a mobile battle royale where diamonds are the in-game currency. Diamonds buy weapon and character skins, emotes, outfits and the current season's Elite Pass, while the weekly and monthly memberships grant diamonds every day plus perks for active players.

YuPay tops up your account by its public in-game ID — no password and no account login needed. You can pay in sum with Uzcard and Humo cards via Click, Payme or Uzum; the rate is shown before you pay, and diamonds or membership are credited automatically once your payment is confirmed.$c$,
    instructions = $c$How to top up Free Fire:

1. Enter your Free Fire player ID (the public ID from your profile) — no password required.
2. Choose what you need: diamonds or a membership (weekly or monthly).
3. Choose a payment method: Click, Payme or Uzum. The rate and total are shown before you pay.
4. Pay — diamonds or membership are credited to your account automatically once your payment is confirmed.

Where to find your Free Fire player ID: open the game and, in the lobby, tap your avatar in the top-left corner — your player ID is shown under your nickname in the profile.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'free-fire') AND locale = 'en';

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","Oʻyin ID orqali","Avtomatik","Parolsiz"]$c$::json,
    short_description = $c$Free Fire toʻldirish — olmoslar va obuna oʻyin IDsi orqali, soʻmda toʻlov, parolsiz.$c$,
    description = $c$Free Fire (va Garena kompaniyasining Free Fire MAX oʻyini) — mobil battle royale boʻlib, unda olmoslar oʻyin ichidagi valyuta hisoblanadi. Olmoslarga qurol va personaj skinlari, emoutlar, kiyimlar hamda joriy mavsum Elite Pass sotib olinadi; haftalik va oylik obuna esa faol oʻyinchilarga har kuni olmos va qoʻshimcha imtiyozlar beradi.

YuPay hisobingizni uning ochiq oʻyin ID raqami orqali toʻldiradi — parol va akkauntga kirish talab qilinmaydi. Toʻlovni soʻmda Uzcard va Humo kartalari bilan Click, Payme yoki Uzum orqali amalga oshirishingiz mumkin; kurs toʻlovdan oldin koʻrsatiladi, olmoslar yoki obuna esa toʻlov tasdiqlangach avtomatik tushadi.$c$,
    instructions = $c$Free Fire hisobini qanday toʻldirish:

1. Free Fire oʻyin ID raqamingizni (profildagi ochiq ID) kiriting — parol kerak emas.
2. Nima kerakligini tanlang: olmoslar yoki obuna (haftalik yoki oylik).
3. Toʻlov usulini tanlang: Click, Payme yoki Uzum. Kurs va yakuniy summa toʻlovdan oldin koʻrsatiladi.
4. Toʻlang — olmoslar yoki obuna toʻlov tasdiqlangach hisobingizga avtomatik tushadi.

Free Fire oʻyin ID raqamini qayerdan topish mumkin: oʻyinni oching va lobbida chap yuqori burchakdagi avatarni bosing — oʻyinchi ID raqamingiz profildagi nik ostida koʻrsatilgan.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'free-fire') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- 2. FAQs (rebuilt each run: delete cascades to brand_faq_translations)
-- ---------------------------------------------------------------------------

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'free-fire');

WITH free_fire AS (
    SELECT id FROM brands WHERE slug = 'free-fire'
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), free_fire.id, v.sort_order, true
    FROM free_fire, (VALUES (1), (2), (3), (4), (5), (6), (7)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. Что такое алмазы и что на них купить?
        (1, 'ru', $q$Что такое алмазы Free Fire и что на них можно купить?$q$,
            $a$Алмазы — внутриигровая валюта Free Fire. За них покупают скины оружия и персонажей, эмоуты, наряды, а также Elite Pass текущего сезона. Аккаунты Free Fire и Free Fire MAX от Garena общие, поэтому алмазы доступны в обоих клиентах.$a$),
        (1, 'en', $q$What are Free Fire diamonds and what can I buy with them?$q$,
            $a$Diamonds are the in-game currency of Free Fire. They buy weapon and character skins, emotes, outfits and the current season's Elite Pass. Free Fire and Free Fire MAX by Garena share one account, so diamonds work in both clients.$a$),
        (1, 'uz', $q$Free Fire olmoslari nima va ularga nima sotib olish mumkin?$q$,
            $a$Olmoslar — Free Fire oʻyinining ichki valyutasi. Ularga qurol va personaj skinlari, emoutlar, kiyimlar hamda joriy mavsum Elite Pass sotib olinadi. Free Fire va Free Fire MAX oʻyinlari umumiy akkauntga ega, shuning uchun olmoslar ikkala klientda ham ishlaydi.$a$),

        -- 2. Как узнать свой ID?
        (2, 'ru', $q$Как узнать свой ID в Free Fire?$q$,
            $a$Откройте игру и в лобби нажмите на аватар в левом верхнем углу, чтобы открыть профиль. Игровой ID (UID) указан под вашим никнеймом — это тот номер, который нужен для пополнения.$a$),
        (2, 'en', $q$How do I find my Free Fire ID?$q$,
            $a$Open the game and, in the lobby, tap your avatar in the top-left corner to open your profile. Your player ID (UID) is shown under your nickname — that is the number you need for a top-up.$a$),
        (2, 'uz', $q$Free Fire ID raqamini qanday bilish mumkin?$q$,
            $a$Oʻyinni oching va lobbida chap yuqori burchakdagi avatarni bosib, profilni oching. Oʻyinchi ID (UID) nik ostida koʻrsatilgan — toʻldirish uchun aynan shu raqam kerak.$a$),

        -- 3. Нужен ли пароль?
        (3, 'ru', $q$Нужен ли пароль от аккаунта?$q$,
            $a$Нет. Пополнение проходит по публичному игровому ID — пароль и вход в аккаунт не требуются, и мы их не запрашиваем.$a$),
        (3, 'en', $q$Do you need my account password?$q$,
            $a$No. Top-ups run on your public player ID — no password and no account login are required, and we never ask for them.$a$),
        (3, 'uz', $q$Akkaunt paroli kerakmi?$q$,
            $a$Yoʻq. Toʻldirish ochiq oʻyin ID orqali amalga oshadi — parol va akkauntga kirish talab qilinmaydi, biz ularni soʻramaymiz.$a$),

        -- 4. Можно ли платить в сумах?
        (4, 'ru', $q$Можно ли платить в сумах?$q$,
            $a$Да. Оплата в узбекских сумах доступна картами Uzcard и Humo через Click, Payme и Uzum. Курс и итоговая сумма показываются до оплаты.$a$),
        (4, 'en', $q$Can I pay in Uzbek sum?$q$,
            $a$Yes. You can pay in Uzbek sum with Uzcard and Humo cards via Click, Payme and Uzum. The rate and final total are shown before you pay.$a$),
        (4, 'uz', $q$Soʻmda toʻlash mumkinmi?$q$,
            $a$Ha. Oʻzbek soʻmida Uzcard va Humo kartalari orqali Click, Payme va Uzum bilan toʻlash mumkin. Kurs va yakuniy summa toʻlovdan oldin koʻrsatiladi.$a$),

        -- 5. За сколько зачислится?
        (5, 'ru', $q$За сколько зачисляются алмазы?$q$,
            $a$Алмазы и подписка зачисляются на аккаунт автоматически после подтверждения оплаты. Достаточно правильно указать игровой ID.$a$),
        (5, 'en', $q$How fast are diamonds credited?$q$,
            $a$Diamonds and membership are credited to your account automatically once your payment is confirmed. Just make sure your player ID is correct.$a$),
        (5, 'uz', $q$Olmoslar qancha vaqtda tushadi?$q$,
            $a$Olmoslar va obuna toʻlov tasdiqlangach hisobingizga avtomatik tushadi. Faqat oʻyin ID raqamini toʻgʻri kiriting.$a$),

        -- 6. Это официальный сайт?
        (6, 'ru', $q$Это официальный сайт Free Fire?$q$,
            $a$Нет. YuPay — независимый сервис пополнения и не связан с Garena, издателем Free Fire. Мы покупаем и перепродаём пополнения по прозрачному курсу, который виден до оплаты.$a$),
        (6, 'en', $q$Is this the official Free Fire website?$q$,
            $a$No. YuPay is an independent top-up service and is not affiliated with Garena, the publisher of Free Fire. We buy and resell top-ups at a transparent rate that is shown before you pay.$a$),
        (6, 'uz', $q$Bu Free Fire rasmiy saytimi?$q$,
            $a$Yoʻq. YuPay — mustaqil toʻldirish xizmati va Free Fire noshiri Garena bilan bogʻliq emas. Biz toʻldirishlarni shaffof kurs boʻyicha sotib olib, qayta sotamiz; kurs toʻlovdan oldin koʻrinadi.$a$),

        -- 7. Что даёт подписка?
        (7, 'ru', $q$Что даёт недельная и месячная подписка?$q$,
            $a$Подписка выгоднее разовой покупки алмазов: при активации вы получаете стартовый бонус алмазов, а затем — алмазы каждый день в течение срока подписки (7 дней у недельной, 30 у месячной). Чтобы забрать ежедневные алмазы, нужно заходить в игру каждый день. Также подписка даёт бонусы: значок участника, скидки в магазине и награды сезона.$a$),
        (7, 'en', $q$What do the weekly and monthly memberships give?$q$,
            $a$A membership is better value than a one-off diamond purchase: on activation you get a starter diamond bonus, then diamonds every day for the membership period (7 days for weekly, 30 for monthly). You need to log in each day to claim the daily diamonds. Memberships also add perks: a member icon, store discounts and season rewards.$a$),
        (7, 'uz', $q$Haftalik va oylik obuna nima beradi?$q$,
            $a$Obuna olmoslarni bir martalik sotib olishdan koʻra foydaliroq: faollashtirilganda boshlangʻich olmos bonusini olasiz, soʻngra obuna muddati davomida har kuni olmos beriladi (haftalikda 7 kun, oylikda 30 kun). Kunlik olmoslarni olish uchun har kuni oʻyinga kirishingiz kerak. Obuna qoʻshimcha imtiyozlar ham beradi: ishtirokchi belgisi, doʻkonda chegirmalar va mavsum mukofotlari.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
