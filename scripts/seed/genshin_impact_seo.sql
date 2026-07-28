-- scripts/seed/genshin_impact_seo.sql
--
-- SEO content pack for the `genshin-impact` brand: highlights + short/long
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
    highlights = $c$["Оплата в сумах","По UID","Автоматически","Без пароля"]$c$::json,
    short_description = $c$Пополнение Genshin Impact — Кристаллы Сотворения и Благословение полой луны по UID и серверу, оплата в сумах.$c$,
    description = $c$Кристаллы Сотворения (Genesis Crystals) — внутриигровая валюта Genshin Impact. Их конвертируют один к одному в Primogems (примогемы), а примогемы тратят на «молитвы» (wishes) — розыгрыш персонажей и оружия. «Благословение полой луны» (Blessing of the Welkin Moon) — 30-дневная подписка: сразу начисляет 300 Кристаллов Сотворения, а затем по 90 примогемов каждый день в течение 30 дней, когда вы заходите в игру.

YuPay — независимый сервис пополнения в Узбекистане. Мы пополняем аккаунт по публичному UID и выбранному серверу — пароль и вход в аккаунт не нужны. Оплата в сумах картами Uzcard и Humo через Click, Payme и Uzum; курс виден ещё до подтверждения заказа, а зачисление происходит автоматически после подтверждения оплаты. YuPay не связан с HoYoverse (miHoYo) — издателем Genshin Impact.$c$,
    instructions = $c$Как пополнить Genshin Impact:

1. Введите UID вашего аккаунта Genshin Impact.
2. Выберите сервер аккаунта: America, Europe, Asia или TW-HK-MO.
3. Выберите, что пополнить: Кристаллы Сотворения или Благословение полой луны.
4. Выберите способ оплаты: Click, Payme или Uzum. Курс и итог к оплате показываются заранее.
5. Оплатите — начисление на ваш аккаунт произойдёт автоматически после подтверждения оплаты.

Где найти UID в Genshin Impact: UID — это 9-значный номер в правом нижнем углу экрана в игре. Его также можно открыть через меню Паймон — нажмите значок Паймон в левом верхнем углу, и UID будет показан под именем персонажа. Пароль и данные для входа передавать не нужно.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'genshin-impact') AND locale = 'ru';

UPDATE brand_translations SET
    highlights = $c$["Pay in UZS","By UID","Automatic","No password"]$c$::json,
    short_description = $c$Top up Genshin Impact — Genesis Crystals and the Blessing of the Welkin Moon by UID and server, pay in sum.$c$,
    description = $c$Genesis Crystals are the in-game currency of Genshin Impact. They convert one to one into Primogems, and Primogems are spent on wishes — the draws for characters and weapons. The Blessing of the Welkin Moon is a 30-day pass: it grants 300 Genesis Crystals immediately, then 90 Primogems every day for 30 days each time you log in.

YuPay is an independent top-up service in Uzbekistan. We top up your account by its public UID and the server you select — no password and no account login required. Pay in sum with Uzcard and Humo cards via Click, Payme and Uzum; the rate is shown before you confirm the order, and the top-up is credited automatically once your payment is confirmed. YuPay is not affiliated with HoYoverse (miHoYo), the publisher of Genshin Impact.$c$,
    instructions = $c$How to top up Genshin Impact:

1. Enter the UID of your Genshin Impact account.
2. Select your account server: America, Europe, Asia or TW-HK-MO.
3. Choose what to top up: Genesis Crystals or the Blessing of the Welkin Moon.
4. Choose a payment method: Click, Payme or Uzum. The rate and total to pay are shown in advance.
5. Pay — your account is credited automatically once the payment is confirmed.

Where to find your UID in Genshin Impact: your UID is the 9-digit number in the bottom-right corner of the screen in-game. You can also open the Paimon menu — tap the Paimon icon in the top-left corner and your UID is shown under your character name. You never need to share your password or login details.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'genshin-impact') AND locale = 'en';

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","UID orqali","Avtomatik","Parolsiz"]$c$::json,
    short_description = $c$Genshin Impact toʻldirish — Genesis Crystals va Blessing of the Welkin Moon UID va server orqali, soʻmda toʻlov.$c$,
    description = $c$Genesis Crystals — Genshin Impact oʻyinining ichki valyutasi. Ular birma-bir Primogems (primogem)ga aylantiriladi, primogemlar esa «molitva» (wishes) — personaj va qurollarni oʻynab yutish uchun sarflanadi. «Blessing of the Welkin Moon» — 30 kunlik obuna: darhol 300 Genesis Crystals beradi, soʻngra 30 kun davomida oʻyinga kirganingizda har kuni 90 primogem beradi.

YuPay — Oʻzbekistondagi mustaqil toʻldirish xizmati. Biz akkauntni ommaviy UID va tanlangan server orqali toʻldiramiz — parol va akkauntga kirish kerak emas. Toʻlov soʻmda Uzcard va Humo kartalari bilan Click, Payme va Uzum orqali; kurs buyurtmani tasdiqlashdan oldin koʻrinadi, mablagʻ esa toʻlov tasdiqlangach avtomatik tushadi. YuPay Genshin Impact noshiri HoYoverse (miHoYo) bilan bogʻliq emas.$c$,
    instructions = $c$Genshin Impact hisobini qanday toʻldirish:

1. Genshin Impact akkauntingiz UID raqamini kiriting.
2. Akkaunt serverini tanlang: America, Europe, Asia yoki TW-HK-MO.
3. Nimani toʻldirishni tanlang: Genesis Crystals yoki Blessing of the Welkin Moon.
4. Toʻlov usulini tanlang: Click, Payme yoki Uzum. Kurs va toʻlov summasi oldindan koʻrsatiladi.
5. Toʻlang — mablagʻ toʻlov tasdiqlangach akkauntingizga avtomatik tushadi.

Genshin Impact ichida UID qayerdan topiladi: UID — oʻyin ekranining oʻng pastki burchagidagi 9 xonali raqam. Uni Paimon menyusi orqali ham koʻrish mumkin — yuqori chap burchakdagi Paimon belgisini bosing, UID personaj nomi ostida koʻrsatiladi. Parol va kirish maʼlumotlarini berish shart emas.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'genshin-impact') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- 2. FAQs (rebuilt each run: delete cascades to brand_faq_translations)
-- ---------------------------------------------------------------------------

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'genshin-impact');

WITH genshin AS (
    SELECT id FROM brands WHERE slug = 'genshin-impact'
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), genshin.id, v.sort_order, true
    FROM genshin, (VALUES (1), (2), (3), (4), (5), (6), (7)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. Что такое Кристаллы Сотворения?
        (1, 'ru', $q$Что такое Кристаллы Сотворения (Genesis Crystals)?$q$,
            $a$Это внутриигровая валюта Genshin Impact, которую покупают за реальные деньги. Кристаллы конвертируются один к одному в Primogems (примогемы), а примогемы тратятся на «молитвы» (wishes) — розыгрыш персонажей и оружия.$a$),
        (1, 'en', $q$What are Genesis Crystals in Genshin Impact?$q$,
            $a$They are the in-game currency of Genshin Impact, bought with real money. Genesis Crystals convert one to one into Primogems, and Primogems are spent on wishes — the draws for characters and weapons.$a$),
        (1, 'uz', $q$Genesis Crystals (Kristallar) nima?$q$,
            $a$Bu — real pulga sotib olinadigan Genshin Impact ichki valyutasi. Genesis Crystals birma-bir Primogems (primogem)ga aylanadi, primogemlar esa «molitva» (wishes) — personaj va qurollarni oʻynab yutish uchun sarflanadi.$a$),

        -- 2. Как найти свой UID?
        (2, 'ru', $q$Как найти свой UID в Genshin Impact?$q$,
            $a$UID — это 9-значный номер в правом нижнем углу экрана в игре. Его также можно открыть через меню Паймон: нажмите значок Паймон в левом верхнем углу — UID показан под именем персонажа. Для пополнения нужен только UID, а не логин или e-mail.$a$),
        (2, 'en', $q$How do I find my UID in Genshin Impact?$q$,
            $a$Your UID is the 9-digit number in the bottom-right corner of the screen in-game. You can also open the Paimon menu — tap the Paimon icon in the top-left and your UID appears under your character name. A top-up needs only your UID, not your login or e-mail.$a$),
        (2, 'uz', $q$Genshin Impact ichida UID qanday topiladi?$q$,
            $a$UID — oʻyin ichida ekranning oʻng pastki burchagidagi 9 xonali raqam. Uni Paimon menyusi orqali ham koʻrish mumkin: yuqori chap burchakdagi Paimon belgisini bosing — UID personaj nomi ostida koʻrinadi. Toʻldirish uchun faqat UID kerak, login yoki e-mail emas.$a$),

        -- 3. Какой сервер выбрать?
        (3, 'ru', $q$Какой сервер выбрать при пополнении?$q$,
            $a$Выберите сервер, к которому привязан ваш аккаунт: America, Europe, Asia или TW-HK-MO. Сервер должен совпадать с регионом аккаунта в игре — от него зависит, куда придёт пополнение. Если не уверены, сверьтесь с регионом, выбранным при входе в Genshin Impact.$a$),
        (3, 'en', $q$Which server should I select?$q$,
            $a$Choose the server your account is on: America, Europe, Asia or TW-HK-MO. The server must match your account's in-game region, because it determines where the top-up is delivered. If unsure, check the region you selected when logging into Genshin Impact.$a$),
        (3, 'uz', $q$Toʻldirishda qaysi serverni tanlashim kerak?$q$,
            $a$Akkauntingiz bogʻlangan serverni tanlang: America, Europe, Asia yoki TW-HK-MO. Server oʻyindagi akkaunt mintaqasiga mos boʻlishi kerak, chunki toʻldirish qayerga tushishi shunga bogʻliq. Ishonchingiz komil boʻlmasa, Genshin Impact ichiga kirishda tanlagan mintaqangizni tekshiring.$a$),

        -- 4. Нужен ли пароль?
        (4, 'ru', $q$Нужен ли пароль от аккаунта?$q$,
            $a$Нет. Для пополнения достаточно публичного UID и сервера — пароль, код из SMS (OTP) или вход в аккаунт передавать не нужно, и мы их не запрашиваем. Любой, кто просит пароль или OTP, пытается украсть аккаунт.$a$),
        (4, 'en', $q$Do you need my account password?$q$,
            $a$No. A top-up only needs your public UID and server — you never share your password, SMS code (OTP) or account login, and we never ask for them. Anyone asking for a password or OTP is trying to steal the account.$a$),
        (4, 'uz', $q$Akkaunt paroli kerakmi?$q$,
            $a$Yoʻq. Toʻldirish uchun ommaviy UID va server yetarli — parol, SMS kod (OTP) yoki akkauntga kirishni berish shart emas, biz ularni soʻramaymiz. Kim parol yoki OTP soʻrasa, akkauntni oʻgʻirlamoqchi boʻladi.$a$),

        -- 5. Можно ли платить в сумах?
        (5, 'ru', $q$Можно ли платить в сумах и как быстро зачислится?$q$,
            $a$Да. Оплата в узбекских сумах картами Uzcard и Humo через Click, Payme и Uzum. Курс виден до подтверждения заказа, а зачисление на аккаунт происходит автоматически после подтверждения оплаты.$a$),
        (5, 'en', $q$Can I pay in sum, and how fast is it credited?$q$,
            $a$Yes. You pay in Uzbek sum with Uzcard and Humo cards via Click, Payme and Uzum. The rate is shown before you confirm the order, and the top-up is credited to your account automatically once your payment is confirmed.$a$),
        (5, 'uz', $q$Soʻmda toʻlash mumkinmi va qancha vaqtda tushadi?$q$,
            $a$Ha. Oʻzbek soʻmida Uzcard va Humo kartalari bilan Click, Payme va Uzum orqali toʻlanadi. Kurs buyurtmani tasdiqlashdan oldin koʻrinadi, mablagʻ esa toʻlov tasdiqlangach akkauntingizga avtomatik tushadi.$a$),

        -- 6. Что даёт Благословение полой луны?
        (6, 'ru', $q$Что даёт Благословение полой луны (Welkin Moon)?$q$,
            $a$Это подписка на 30 дней. Сразу начисляются 300 Кристаллов Сотворения, а затем по 90 примогемов каждый день в течение 30 дней. Ежедневную часть нужно забирать самому, заходя в игру: пропущенный день не восстанавливается.$a$),
        (6, 'en', $q$What does the Blessing of the Welkin Moon give?$q$,
            $a$It is a 30-day pass. You get 300 Genesis Crystals immediately, then 90 Primogems every day for 30 days. The daily part is claimed by you in-game each day you log in — a missed day is not recoverable.$a$),
        (6, 'uz', $q$Blessing of the Welkin Moon nima beradi?$q$,
            $a$Bu — 30 kunlik obuna. Darhol 300 Genesis Crystals beriladi, soʻngra 30 kun davomida har kuni 90 primogem beriladi. Kundalik qismini oʻzingiz oʻyinga kirib olishingiz kerak: oʻtkazib yuborilgan kun tiklanmaydi.$a$),

        -- 7. Это официальный сайт Genshin Impact?
        (7, 'ru', $q$Это официальный сайт Genshin Impact?$q$,
            $a$Нет. YuPay — независимый сервис пополнения, не связанный с HoYoverse (miHoYo), издателем Genshin Impact. Мы пополняем аккаунты по UID по прозрачному курсу, который виден до оплаты.$a$),
        (7, 'en', $q$Is this the official Genshin Impact website?$q$,
            $a$No. YuPay is an independent top-up service, not affiliated with HoYoverse (miHoYo), the publisher of Genshin Impact. We top up accounts by UID at a transparent rate shown before you pay.$a$),
        (7, 'uz', $q$Bu Genshin Impactning rasmiy saytimi?$q$,
            $a$Yoʻq. YuPay — mustaqil toʻldirish xizmati, Genshin Impact noshiri HoYoverse (miHoYo) bilan bogʻliq emas. Biz akkauntlarni UID orqali, toʻlovdan oldin koʻrinadigan shaffof kurs boʻyicha toʻldiramiz.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
