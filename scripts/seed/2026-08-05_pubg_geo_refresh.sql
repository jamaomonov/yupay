-- PUBG Mobile — GEO/AI-citation content refresh (ru/en/uz).
--
-- Supersedes the content fields set by scripts/seed/pubg_mobile_seo.sql for the
-- pubg-mobile brand: answer-first descriptions with concrete facts (12 UC
-- denominations, 1–5 min crediting, 0% commission), and three new FAQ answer
-- targets that measured AI-answer probes showed nobody owns well — "сколько
-- стоит 660 UC", "какие номиналы", and a Midasbuy/Google-Play comparison.
--
-- Also fixes a factual bug carried in the old copy: the Character ID avatar is
-- in the TOP-LEFT corner of the lobby, not top-right (matches the in-game UI
-- and our account-field help_text).
--
-- Content-managed, NOT a fixture / Alembic migration. Idempotent:
-- brand_translations rows are UPDATEd in place; FAQs are rebuilt via
-- delete-then-insert (delete cascades to brand_faq_translations). Single
-- transaction. Dollar-quoted ($c$/$q$/$a$) so apostrophes need no escaping.
--
-- Apply on prod (operator psql):
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     psql -U yupay_app -d yupay -f - < scripts/seed/2026-08-05_pubg_geo_refresh.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Brand translations (highlights, short/long description, instructions)
-- ---------------------------------------------------------------------------

UPDATE brand_translations SET
    highlights = $c$["0% комиссии","Оплата в сумах (Uzcard/Humo)","Зачисление 1–5 минут","По ID, без пароля"]$c$::json,
    short_description = $c$Пополнение PUBG Mobile в Узбекистане за сумы: UC, Prime и Royale Pass по игровому ID (Character ID) без пароля от аккаунта. 12 номиналов UC от 60 до 16 200, оплата картами Uzcard и Humo через Click, Payme или Uzum, зачисление автоматическое за 1–5 минут, комиссия сервиса 0%.$c$,
    description = $c$YuPay — независимый сервис пополнения PUBG Mobile в Узбекистане (не связан с издателем игры Level Infinite / Tencent). Пополнение идёт по публичному игровому ID — пароль и вход в аккаунт не нужны, и мы их не запрашиваем.

UC (Unknown Cash) — внутриигровая валюта PUBG Mobile: за неё покупают Royale Pass, скины, наряды и открывают ящики. Доступны 12 номиналов UC (от 60 до 16 200), подписки Prime и Prime Plus (1/3/6/12 месяцев) и Elite Royale Pass.

Оплата — в узбекских сумах картами Uzcard и Humo через Click, Payme или Uzum. Комиссия сервиса 0%: поверх суммы мы не берём отдельный сбор, наша маржа заложена в курс, и итоговая сумма видна до оплаты. После подтверждения платежа UC зачисляется на аккаунт автоматически, обычно за 1–5 минут.$c$,
    instructions = $c$Как пополнить PUBG Mobile UC в Узбекистане:

1. Введите игровой ID (Character ID) — пароль и вход в аккаунт не нужны.
2. Выберите номинал UC (или Prime / Royale Pass). Итог в сумах виден сразу, без дополнительной комиссии.
3. Оплатите картой Uzcard или Humo через Click, Payme или Uzum.
4. UC зачисляется на аккаунт автоматически за 1–5 минут после подтверждения оплаты.

Где найти Character ID: откройте PUBG Mobile, нажмите на аватар в левом верхнем углу лобби — числовой ID указан в профиле под именем персонажа, рядом есть иконка копирования. ID не меняется и присваивается аккаунту при регистрации.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'pubg-mobile') AND locale = 'ru';

UPDATE brand_translations SET
    highlights = $c$["0% commission","Pay in sum (Uzcard/Humo)","Credited in 1–5 min","By ID, no password"]$c$::json,
    short_description = $c$Top up PUBG Mobile in Uzbekistan in sum: UC, Prime and Royale Pass by player ID (Character ID), no account password. 12 UC denominations from 60 to 16,200, pay with Uzcard and Humo via Click, Payme or Uzum, credited automatically in 1–5 minutes, 0% service commission.$c$,
    description = $c$YuPay is an independent PUBG Mobile top-up service in Uzbekistan (not affiliated with the game's publisher, Level Infinite / Tencent). Top-ups go to your public player ID — no password or account login is needed, and we never ask for them.

UC (Unknown Cash) is the in-game currency of PUBG Mobile: you spend it on the Royale Pass, skins, outfits and crates. We offer 12 UC denominations (from 60 to 16,200), Prime and Prime Plus subscriptions (1/3/6/12 months) and the Elite Royale Pass.

You pay in Uzbek sum with Uzcard and Humo cards via Click, Payme or Uzum. The service commission is 0%: we add no separate fee on top of your amount — our margin is in the rate, and the final total is shown before you pay. Once the payment is confirmed, the UC is credited to your account automatically, usually within 1–5 minutes.$c$,
    instructions = $c$How to top up PUBG Mobile UC in Uzbekistan:

1. Enter your player ID (Character ID) — no password or account login is required.
2. Choose a UC denomination (or Prime / Royale Pass). The total in sum is shown right away, with no extra commission.
3. Pay with an Uzcard or Humo card via Click, Payme or Uzum.
4. The UC is credited to your account automatically within 1–5 minutes after the payment is confirmed.

Where to find your Character ID: open PUBG Mobile and tap your avatar in the top-left corner of the lobby — the numeric ID is shown on your profile below your character name, with a copy icon next to it. The ID never changes and is assigned to the account at registration.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'pubg-mobile') AND locale = 'en';

UPDATE brand_translations SET
    highlights = $c$["0% komissiya","Soʻmda toʻlov (Uzcard/Humo)","1–5 daqiqada tushadi","ID boʻyicha, parolsiz"]$c$::json,
    short_description = $c$PUBG Mobile ni Oʻzbekistonda soʻmda toʻldirish: UC, Prime va Royale Pass oʻyin IDsi (Character ID) boʻyicha, akkaunt parolisiz. 60 dan 16 200 gacha 12 ta UC nominali, Uzcard va Humo kartalari bilan Click, Payme yoki Uzum orqali toʻlov, 1–5 daqiqada avtomatik tushadi, xizmat komissiyasi 0%.$c$,
    description = $c$YuPay — Oʻzbekistonda PUBG Mobile toʻldirish uchun mustaqil xizmat (oʻyin nashriyoti Level Infinite / Tencent bilan bogʻliq emas). Toʻldirish ochiq oʻyin IDsi boʻyicha amalga oshiriladi — parol va akkauntga kirish kerak emas, biz ularni soʻramaymiz.

UC (Unknown Cash) — PUBG Mobile ichki oʻyin valyutasi: unga Royale Pass, skinlar, liboslar sotib olinadi va qutilar ochiladi. 12 ta UC nominali (60 dan 16 200 gacha), Prime va Prime Plus obunalari (1/3/6/12 oy) hamda Elite Royale Pass mavjud.

Toʻlov — oʻzbek soʻmida Uzcard va Humo kartalari orqali Click, Payme yoki Uzum bilan. Xizmat komissiyasi 0%: summangiz ustiga alohida yigʻim olmaymiz, marjamiz kursda, yakuniy summa toʻlovdan oldin koʻrinadi. Toʻlov tasdiqlangach, UC akkauntingizga avtomatik, odatda 1–5 daqiqada tushadi.$c$,
    instructions = $c$PUBG Mobile UC ni Oʻzbekistonda qanday toʻldirish:

1. Oʻyin IDsi (Character ID) ni kiriting — parol yoki akkauntga kirish kerak emas.
2. UC nominalini (yoki Prime / Royale Pass) tanlang. Soʻmdagi summa darhol, qoʻshimcha komissiyasiz koʻrsatiladi.
3. Uzcard yoki Humo kartasi bilan Click, Payme yoki Uzum orqali toʻlang.
4. UC toʻlov tasdiqlangach 1–5 daqiqada akkauntingizga avtomatik tushadi.

Character ID ni qayerdan topish: PUBG Mobile ni oching va lobbining yuqori chap burchagidagi avatarni bosing — raqamli ID profilda, personaj nomi ostida koʻrsatiladi, yonida nusxa olish belgisi bor. ID oʻzgarmaydi va roʻyxatdan oʻtishda beriladi.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'pubg-mobile') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- 2. FAQs — 10 entries (7 kept, ID-corner fact fixed; 3 new answer targets)
-- ---------------------------------------------------------------------------

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'pubg-mobile');

WITH pubg AS (
    SELECT id FROM brands WHERE slug = 'pubg-mobile'
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), pubg.id, v.sort_order, true
    FROM pubg, (VALUES (1),(2),(3),(4),(5),(6),(7),(8),(9),(10)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. Что такое UC
        (1, 'ru', $q$Что такое UC в PUBG Mobile и что на них можно купить?$q$,
            $a$UC (Unknown Cash) — внутриигровая валюта PUBG Mobile. За UC покупают Royale Pass, наряды и скины оружия, эмоции, открывают ящики и участвуют в розыгрышах. Для самой игры UC не обязательны, но нужны для косметики и премиум-контента.$a$),
        (1, 'en', $q$What is UC in PUBG Mobile and what can I buy with it?$q$,
            $a$UC (Unknown Cash) is the in-game currency of PUBG Mobile. You spend UC on the Royale Pass, outfits and weapon skins, emotes, crates and lucky-draw events. UC is not needed to play, but it unlocks cosmetics and premium content.$a$),
        (1, 'uz', $q$PUBG Mobile oʻyinida UC nima va unga nima sotib olish mumkin?$q$,
            $a$UC (Unknown Cash) — PUBG Mobile ichki oʻyin valyutasi. UC hisobiga Royale Pass, liboslar va qurol skinlari, emotsiyalar sotib olinadi, qutilar ochiladi va sovrinli oʻyinlarda qatnashiladi. Oʻynash uchun UC shart emas, lekin kosmetika va premium kontent uchun kerak.$a$),

        -- 2. Как узнать свой ID (fact fix: top-LEFT corner)
        (2, 'ru', $q$Как узнать свой ID в PUBG Mobile?$q$,
            $a$Откройте игру, нажмите на аватар в левом верхнем углу лобби и посмотрите профиль — числовой ID указан под именем персонажа, рядом есть иконка копирования. Этот ID (Character ID) не меняется. Его и нужно ввести при пополнении.$a$),
        (2, 'en', $q$How do I find my PUBG Mobile ID?$q$,
            $a$Open the game, tap your avatar in the top-left corner of the lobby and open your profile — the numeric ID is shown below your character name, with a copy icon next to it. This ID (Character ID) never changes, and it is what you enter when topping up.$a$),
        (2, 'uz', $q$PUBG Mobile ID ni qanday bilish mumkin?$q$,
            $a$Oʻyinni oching, lobbining yuqori chap burchagidagi avatarni bosing va profilni koʻring — raqamli ID personaj nomi ostida koʻrsatiladi, yonida nusxa olish belgisi bor. Bu ID (Character ID) oʻzgarmaydi va toʻldirishda aynan shu raqam kiritiladi.$a$),

        -- 3. Нужен ли пароль / безопасно
        (3, 'ru', $q$Нужен ли пароль от аккаунта и безопасно ли это?$q$,
            $a$Пароль не нужен. UC зачисляется по публичному ID игрока — вход в аккаунт и передача пароля не требуются, и мы их не запрашиваем. Достаточно правильно указать ID.$a$),
        (3, 'en', $q$Do I need my account password, and is it safe?$q$,
            $a$No password is needed. UC is credited by your public player ID — you never log in or share a password, and we never ask for one. All you need is to enter the correct ID.$a$),
        (3, 'uz', $q$Akkaunt paroli kerakmi va bu xavfsizmi?$q$,
            $a$Parol kerak emas. UC ochiq oʻyinchi ID boʻyicha tushadi — akkauntga kirish va parol berish talab qilinmaydi, biz ularni soʻramaymiz. ID ni toʻgʻri kiritishning oʻzi yetarli.$a$),

        -- 4. Оплата в сумах
        (4, 'ru', $q$Можно ли оплатить UC в сумах и какими способами?$q$,
            $a$Да. Оплата в узбекских сумах доступна картами Uzcard и Humo через Click, Payme и Uzum. Курс и итоговая сумма видны до оплаты.$a$),
        (4, 'en', $q$Can I pay for UC in sum, and which methods are available?$q$,
            $a$Yes. You can pay in Uzbek sum with Uzcard and Humo cards via Click, Payme and Uzum. The rate and the final amount are shown before you pay.$a$),
        (4, 'uz', $q$UC uchun soʻmda va qanday usullarda toʻlash mumkin?$q$,
            $a$Ha. Oʻzbek soʻmida Uzcard va Humo kartalari orqali Click, Payme va Uzum bilan toʻlash mumkin. Kurs va yakuniy summa toʻlovdan oldin koʻrinadi.$a$),

        -- 5. NEW: цена 660 UC (price answer target)
        (5, 'ru', $q$Сколько стоит 660 UC в сумах?$q$,
            $a$Актуальная цена показывается до оплаты и зависит от курса. Ориентир: 660 UC ≈ 127 000 сум, 1320 UC ≈ 257 000 сум, 60 UC ≈ 12 700 сум. Всего 12 номиналов — от 60 до 16 200 UC. Комиссии сверху нет, итог виден до подтверждения.$a$),
        (5, 'en', $q$How much does 660 UC cost in sum?$q$,
            $a$The current price is shown before payment and depends on the exchange rate. As a guide: 660 UC ≈ 127,000 sum, 1,320 UC ≈ 257,000 sum, 60 UC ≈ 12,700 sum. There are 12 denominations in total, from 60 to 16,200 UC. There is no extra commission, and the total is shown before you confirm.$a$),
        (5, 'uz', $q$660 UC soʻmda qancha turadi?$q$,
            $a$Joriy narx toʻlovdan oldin koʻrsatiladi va kursga bogʻliq. Taxminan: 660 UC ≈ 127 000 soʻm, 1320 UC ≈ 257 000 soʻm, 60 UC ≈ 12 700 soʻm. Jami 12 ta nominal — 60 dan 16 200 UC gacha. Ustiga komissiya yoʻq, yakuniy summa tasdiqlashdan oldin koʻrinadi.$a$),

        -- 6. NEW: доступные номиналы (extractable list)
        (6, 'ru', $q$Какие номиналы UC доступны?$q$,
            $a$Доступно 12 номиналов UC: 60, 325, 660, 985, 1320, 1800, 2460, 3850, 5650, 8100, 11 950 и 16 200 UC. Также есть подписки Prime и Prime Plus (1/3/6/12 месяцев) и Elite Royale Pass (LV1-50 / LV1-100).$a$),
        (6, 'en', $q$Which UC denominations are available?$q$,
            $a$There are 12 UC denominations: 60, 325, 660, 985, 1,320, 1,800, 2,460, 3,850, 5,650, 8,100, 11,950 and 16,200 UC. Prime and Prime Plus subscriptions (1/3/6/12 months) and the Elite Royale Pass (LV1-50 / LV1-100) are also available.$a$),
        (6, 'uz', $q$Qanday UC nominallari mavjud?$q$,
            $a$12 ta UC nominali mavjud: 60, 325, 660, 985, 1320, 1800, 2460, 3850, 5650, 8100, 11 950 va 16 200 UC. Shuningdek Prime va Prime Plus obunalari (1/3/6/12 oy) hamda Elite Royale Pass (LV1-50 / LV1-100) bor.$a$),

        -- 7. NEW: сравнение (captures competitive citations)
        (7, 'ru', $q$Чем пополнение через YuPay отличается от Midasbuy или баланса Google Play?$q$,
            $a$YuPay пополняет UC напрямую по игровому ID с оплатой в сумах картами Uzcard и Humo — без зарубежной карты, подарочных кодов и региональных ограничений магазина приложений. Комиссия сервиса 0%, зачисление автоматическое за 1–5 минут. Midasbuy — официальный магазин Tencent и часто требует другие способы оплаты; пополнение через баланс Google Play или Apple ID зависит от региона аккаунта.$a$),
        (7, 'en', $q$How is topping up via YuPay different from Midasbuy or a Google Play balance?$q$,
            $a$YuPay tops up UC directly by player ID, paying in sum with Uzcard and Humo cards — with no foreign card, gift codes or app-store regional limits. The service commission is 0% and UC is credited automatically in 1–5 minutes. Midasbuy is Tencent's official store and often requires other payment methods; topping up via a Google Play or Apple ID balance depends on your account region.$a$),
        (7, 'uz', $q$YuPay orqali toʻldirish Midasbuy yoki Google Play balansidan nimasi bilan farq qiladi?$q$,
            $a$YuPay UC ni bevosita oʻyinchi ID boʻyicha, Uzcard va Humo kartalari bilan soʻmda toʻldiradi — chet el kartasi, sovgʻa kodlari va ilovalar doʻkoni hududiy cheklovlarisiz. Xizmat komissiyasi 0%, UC 1–5 daqiqada avtomatik tushadi. Midasbuy — Tencentning rasmiy doʻkoni va koʻpincha boshqa toʻlov usullarini talab qiladi; Google Play yoki Apple ID balansi orqali toʻldirish akkaunt hududiga bogʻliq.$a$),

        -- 8. За сколько зачислится
        (8, 'ru', $q$За сколько зачисляется UC?$q$,
            $a$UC зачисляется на аккаунт автоматически после подтверждения оплаты, обычно за 1–5 минут. Дополнительных действий с вашей стороны не требуется — главное правильно указать ID игрока.$a$),
        (8, 'en', $q$How fast is the UC credited?$q$,
            $a$The UC is credited to your account automatically once your payment is confirmed, usually within 1–5 minutes. Nothing else is required from you — just make sure the player ID is correct.$a$),
        (8, 'uz', $q$UC qancha vaqtda tushadi?$q$,
            $a$UC toʻlov tasdiqlangach akkauntga avtomatik, odatda 1–5 daqiqada tushadi. Sizdan qoʻshimcha amal talab qilinmaydi — faqat oʻyinchi ID toʻgʻri koʻrsatilgan boʻlsin.$a$),

        -- 9. Официальный сайт?
        (9, 'ru', $q$Это официальный сайт PUBG Mobile?$q$,
            $a$Нет. YuPay — независимый сервис пополнения, не связанный с издателем игры (Level Infinite / Tencent). Мы покупаем и перепродаём UC по прозрачному курсу, который виден до оплаты.$a$),
        (9, 'en', $q$Is this the official PUBG Mobile website?$q$,
            $a$No. YuPay is an independent top-up service, not affiliated with the game's publisher (Level Infinite / Tencent). We buy and resell UC at a transparent rate that is shown before you pay.$a$),
        (9, 'uz', $q$Bu PUBG Mobile rasmiy saytimi?$q$,
            $a$Yoʻq. YuPay — mustaqil toʻldirish xizmati, oʻyin nashriyoti (Level Infinite / Tencent) bilan bogʻliq emas. Biz UC ni shaffof kurs boʻyicha sotib olib, qayta sotamiz; kurs toʻlovdan oldin koʻrinadi.$a$),

        -- 10. UC для Royale Pass / Prime
        (10, 'ru', $q$Можно ли купить UC для Royale Pass или Prime?$q$,
            $a$Да. Пополните UC, а затем в самой игре потратьте баланс на Elite Royale Pass, подписку Prime или Prime Plus, ящики и наряды. YuPay пополняет UC на ваш аккаунт, а покупки внутри игры вы совершаете сами.$a$),
        (10, 'en', $q$Can I buy UC for the Royale Pass or Prime?$q$,
            $a$Yes. Top up UC, then in the game itself spend the balance on the Elite Royale Pass, a Prime or Prime Plus subscription, crates and outfits. YuPay credits UC to your account, and you make the in-game purchases yourself.$a$),
        (10, 'uz', $q$Royale Pass yoki Prime uchun UC sotib olish mumkinmi?$q$,
            $a$Ha. UC ni toʻldiring, soʻngra oʻyinning oʻzida balansni Elite Royale Pass, Prime yoki Prime Plus obunasi, qutilar va liboslarga sarflang. YuPay UC ni akkauntingizga tushiradi, oʻyin ichidagi xaridlarni esa oʻzingiz qilasiz.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
