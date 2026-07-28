-- scripts/seed/pubg_mobile_seo.sql
--
-- SEO content pack for the `pubg-mobile` brand: highlights + short/long
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
    short_description = $c$Пополнение PUBG Mobile — UC, Prime и Royale Pass по игровому ID, оплата в сумах, без пароля.$c$,
    description = $c$UC (Unknown Cash) — внутриигровая валюта PUBG Mobile. За UC покупают Royale Pass, наряды и скины оружия, открывают ящики и участвуют в розыгрышах. YuPay — быстрый способ пополнить UC в Узбекистане: вы платите в сумах по прозрачному курсу, который виден ещё до подтверждения заказа.

Пополнение идёт по публичному ID игрока — пароль и вход в аккаунт не нужны, и мы их не запрашиваем. Оплатить можно картами Uzcard и Humo через Click, Payme или Uzum. После подтверждения оплаты UC зачисляется на ваш аккаунт автоматически. YuPay — независимый сервис и не связан с издателем игры (Level Infinite / Tencent).$c$,
    instructions = $c$Как пополнить PUBG Mobile UC:

1. Введите ID игрока (Character ID) — пароль и вход в аккаунт не нужны.
2. Выберите нужный пакет UC. Итог к оплате в сумах показывается сразу.
3. Выберите способ оплаты: Click, Payme или Uzum.
4. Оплатите — UC зачисляется на ваш аккаунт автоматически после подтверждения платежа.

Где найти ID игрока PUBG Mobile: откройте игру и войдите в аккаунт, нажмите на аватар в правом верхнем углу лобби — числовой ID указан в профиле под именем персонажа, рядом есть иконка копирования. Этот ID (Character ID) не меняется и присваивается аккаунту при регистрации.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'pubg-mobile') AND locale = 'ru';

UPDATE brand_translations SET
    highlights = $c$["Pay in UZS","By player ID","Automatic","No password"]$c$::json,
    short_description = $c$Top up PUBG Mobile — UC, Prime and Royale Pass by player ID, pay in sum, no password.$c$,
    description = $c$UC (Unknown Cash) is the in-game currency of PUBG Mobile. You spend it on the Royale Pass, outfits and weapon skins, crates and lucky-draw events. YuPay is a fast way to top up UC in Uzbekistan: you pay in sum at a transparent rate that is shown before you confirm the order.

Top-ups go to your public player ID — no password and no account login are needed, and we never ask for them. Pay with Uzcard and Humo cards via Click, Payme or Uzum. Once your payment is confirmed, the UC is credited to your account automatically. YuPay is an independent service and is not affiliated with the game's publisher (Level Infinite / Tencent).$c$,
    instructions = $c$How to top up PUBG Mobile UC:

1. Enter your player ID (Character ID) — no password or account login required.
2. Choose the UC pack you want. The total to pay in sum is shown right away.
3. Choose a payment method: Click, Payme or Uzum.
4. Pay — the UC is credited to your account automatically once the payment is confirmed.

Where to find your PUBG Mobile player ID: open the game and sign in, tap your avatar in the top-right corner of the lobby — the numeric ID is shown on your profile below your character name, with a copy icon next to it. This ID (Character ID) never changes; it is assigned to the account at registration.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'pubg-mobile') AND locale = 'en';

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","Oʻyinchi ID boʻyicha","Avtomatik","Parolsiz"]$c$::json,
    short_description = $c$PUBG Mobile toʻldirish — UC, Prime va Royale Pass oʻyin IDsi orqali, soʻmda toʻlov, parolsiz.$c$,
    description = $c$UC (Unknown Cash) — PUBG Mobile ichki oʻyin valyutasi. UC hisobiga Royale Pass, liboslar va qurol skinlari sotib olinadi, qutilar ochiladi va sovrinli oʻyinlarda qatnashiladi. YuPay — Oʻzbekistonda UC toʻldirishning tez usuli: siz soʻmda, buyurtmani tasdiqlashdan oldin koʻrinadigan shaffof kurs boʻyicha toʻlaysiz.

Toʻldirish oʻyinchining ochiq ID raqami boʻyicha amalga oshiriladi — parol va akkauntga kirish kerak emas, biz ularni soʻramaymiz. Toʻlovni Uzcard va Humo kartalari orqali Click, Payme yoki Uzum bilan qilishingiz mumkin. Toʻlov tasdiqlangach, UC akkauntingizga avtomatik tushadi. YuPay — mustaqil xizmat va oʻyin nashriyoti (Level Infinite / Tencent) bilan bogʻliq emas.$c$,
    instructions = $c$PUBG Mobile UC ni qanday toʻldirish:

1. Oʻyinchi ID (Character ID) raqamini kiriting — parol yoki akkauntga kirish kerak emas.
2. Kerakli UC paketini tanlang. Soʻmdagi toʻlov summasi darhol koʻrsatiladi.
3. Toʻlov usulini tanlang: Click, Payme yoki Uzum.
4. Toʻlang — UC toʻlov tasdiqlangach akkauntingizga avtomatik tushadi.

PUBG Mobile oʻyinchi ID sini qayerdan topish mumkin: oʻyinni oching va akkauntga kiring, lobbining yuqori oʻng burchagidagi avatarni bosing — raqamli ID profil sahifasida, personaj nomi ostida koʻrsatiladi, yonida nusxa olish belgisi bor. Bu ID (Character ID) oʻzgarmaydi va roʻyxatdan oʻtishda akkauntga beriladi.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'pubg-mobile') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- 2. FAQs (rebuilt each run: delete cascades to brand_faq_translations)
-- ---------------------------------------------------------------------------

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'pubg-mobile');

WITH pubg AS (
    SELECT id FROM brands WHERE slug = 'pubg-mobile'
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), pubg.id, v.sort_order, true
    FROM pubg, (VALUES (1), (2), (3), (4), (5), (6), (7)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. Что такое UC и что на них купить?
        (1, 'ru', $q$Что такое UC в PUBG Mobile и что на них можно купить?$q$,
            $a$UC (Unknown Cash) — внутриигровая валюта PUBG Mobile. За UC покупают Royale Pass, наряды и скины оружия, эмоции, открывают ящики и участвуют в розыгрышах. Для самой игры UC не обязательны, но нужны для косметики и премиум-контента.$a$),
        (1, 'en', $q$What is UC in PUBG Mobile and what can I buy with it?$q$,
            $a$UC (Unknown Cash) is the in-game currency of PUBG Mobile. You spend UC on the Royale Pass, outfits and weapon skins, emotes, crates and lucky-draw events. UC is not needed to play, but it unlocks cosmetics and premium content.$a$),
        (1, 'uz', $q$PUBG Mobile oʻyinida UC nima va unga nima sotib olish mumkin?$q$,
            $a$UC (Unknown Cash) — PUBG Mobile ichki oʻyin valyutasi. UC hisobiga Royale Pass, liboslar va qurol skinlari, emotsiyalar sotib olinadi, qutilar ochiladi va sovrinli oʻyinlarda qatnashiladi. Oʻynash uchun UC shart emas, lekin kosmetika va premium kontent uchun kerak.$a$),

        -- 2. Как узнать свой ID?
        (2, 'ru', $q$Как узнать свой ID в PUBG Mobile?$q$,
            $a$Откройте игру, нажмите на аватар в правом верхнем углу лобби и посмотрите профиль — числовой ID указан под именем персонажа, рядом есть иконка копирования. Этот ID (Character ID) не меняется. Его и нужно ввести при пополнении.$a$),
        (2, 'en', $q$How do I find my PUBG Mobile ID?$q$,
            $a$Open the game, tap your avatar in the top-right corner of the lobby and open your profile — the numeric ID is shown below your character name, with a copy icon next to it. This ID (Character ID) never changes, and it is what you enter when topping up.$a$),
        (2, 'uz', $q$PUBG Mobile ID ni qanday bilish mumkin?$q$,
            $a$Oʻyinni oching, lobbining yuqori oʻng burchagidagi avatarni bosing va profilni koʻring — raqamli ID personaj nomi ostida koʻrsatiladi, yonida nusxa olish belgisi bor. Bu ID (Character ID) oʻzgarmaydi va toʻldirishda aynan shu raqam kiritiladi.$a$),

        -- 3. Нужен ли пароль / безопасно ли?
        (3, 'ru', $q$Нужен ли пароль от аккаунта и безопасно ли это?$q$,
            $a$Пароль не нужен. UC зачисляется по публичному ID игрока — вход в аккаунт и передача пароля не требуются, и мы их не запрашиваем. Достаточно правильно указать ID.$a$),
        (3, 'en', $q$Do I need my account password, and is it safe?$q$,
            $a$No password is needed. UC is credited by your public player ID — you never log in or share a password, and we never ask for one. All you need is to enter the correct ID.$a$),
        (3, 'uz', $q$Akkaunt paroli kerakmi va bu xavfsizmi?$q$,
            $a$Parol kerak emas. UC ochiq oʻyinchi ID boʻyicha tushadi — akkauntga kirish va parol berish talab qilinmaydi, biz ularni soʻramaymiz. ID ni toʻgʻri kiritishning oʻzi yetarli.$a$),

        -- 4. Оплата в сумах и способы
        (4, 'ru', $q$Можно ли оплатить UC в сумах и какими способами?$q$,
            $a$Да. Оплата в узбекских сумах доступна картами Uzcard и Humo через Click, Payme и Uzum. Курс и итоговая сумма видны до оплаты.$a$),
        (4, 'en', $q$Can I pay for UC in sum, and which methods are available?$q$,
            $a$Yes. You can pay in Uzbek sum with Uzcard and Humo cards via Click, Payme and Uzum. The rate and the final amount are shown before you pay.$a$),
        (4, 'uz', $q$UC uchun soʻmda va qanday usullarda toʻlash mumkin?$q$,
            $a$Ha. Oʻzbek soʻmida Uzcard va Humo kartalari orqali Click, Payme va Uzum bilan toʻlash mumkin. Kurs va yakuniy summa toʻlovdan oldin koʻrinadi.$a$),

        -- 5. За сколько зачислится?
        (5, 'ru', $q$За сколько зачисляется UC?$q$,
            $a$UC зачисляется на аккаунт автоматически после подтверждения оплаты. Дополнительных действий с вашей стороны не требуется — главное правильно указать ID игрока.$a$),
        (5, 'en', $q$How fast is the UC credited?$q$,
            $a$The UC is credited to your account automatically once your payment is confirmed. Nothing else is required from you — just make sure the player ID is correct.$a$),
        (5, 'uz', $q$UC qancha vaqtda tushadi?$q$,
            $a$UC toʻlov tasdiqlangach akkauntga avtomatik tushadi. Sizdan qoʻshimcha amal talab qilinmaydi — faqat oʻyinchi ID toʻgʻri koʻrsatilgan boʻlsin.$a$),

        -- 6. Официальный сайт?
        (6, 'ru', $q$Это официальный сайт PUBG Mobile?$q$,
            $a$Нет. YuPay — независимый сервис пополнения, не связанный с издателем игры (Level Infinite / Tencent). Мы покупаем и перепродаём UC по прозрачному курсу, который виден до оплаты.$a$),
        (6, 'en', $q$Is this the official PUBG Mobile website?$q$,
            $a$No. YuPay is an independent top-up service, not affiliated with the game's publisher (Level Infinite / Tencent). We buy and resell UC at a transparent rate that is shown before you pay.$a$),
        (6, 'uz', $q$Bu PUBG Mobile rasmiy saytimi?$q$,
            $a$Yoʻq. YuPay — mustaqil toʻldirish xizmati, oʻyin nashriyoti (Level Infinite / Tencent) bilan bogʻliq emas. Biz UC ni shaffof kurs boʻyicha sotib olib, qayta sotamiz; kurs toʻlovdan oldin koʻrinadi.$a$),

        -- 7. UC для Royale Pass / Prime
        (7, 'ru', $q$Можно ли купить UC для Royale Pass или Prime?$q$,
            $a$Да. Пополните UC, а затем в самой игре потратьте баланс на Elite Royale Pass, подписку Prime или Prime Plus, ящики и наряды. YuPay пополняет UC на ваш аккаунт, а покупки внутри игры вы совершаете сами.$a$),
        (7, 'en', $q$Can I buy UC for the Royale Pass or Prime?$q$,
            $a$Yes. Top up UC, then spend the balance inside the game on the Elite Royale Pass, a Prime or Prime Plus subscription, crates and outfits. YuPay adds UC to your account; you make the in-game purchases yourself.$a$),
        (7, 'uz', $q$Royale Pass yoki Prime uchun UC sotib olsa boʻladimi?$q$,
            $a$Ha. Avval UC toʻldiring, keyin oʻyin ichida balansni Elite Royale Pass, Prime yoki Prime Plus obunasi, qutilar va liboslarga sarflang. YuPay UC ni akkauntingizga qoʻshadi, oʻyin ichidagi xaridlarni esa oʻzingiz qilasiz.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
