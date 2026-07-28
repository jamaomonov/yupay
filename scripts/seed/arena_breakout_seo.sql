-- scripts/seed/arena_breakout_seo.sql
--
-- SEO content pack for the `arena-breakout` brand (Arena Breakout, the MOBILE
-- tactical extraction shooter by Morefun Studios / Level Infinite): highlights +
-- short/long descriptions + instructions on `brand_translations`, and 7 FAQ
-- entries with ru/en/uz answers. Products topped up: Bonds and Battle Pass.
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
    short_description = $c$Пополнение Arena Breakout — Bonds и Battle Pass по игровому ID, оплата в сумах, без пароля.$c$,
    description = $c$YuPay — это пополнение Arena Breakout в Узбекистане за сумы. Arena Breakout — мобильный тактический шутер на выживание от Morefun Studios и Level Infinite, где Bonds служат премиум-валютой: за них берут расширение схрона и защищённые контейнеры, чертежи оружия, подписки и Battle Pass, а Battle Pass открывает награды текущего сезона. Мы пополняем ваш игровой аккаунт по публичному ID — быстро и без передачи пароля.

Оплатить можно привычными способами: картами Uzcard и Humo через Click, Payme и Uzum. Итоговая сумма в сумах и курс видны ещё до подтверждения заказа, а Bonds или Battle Pass зачисляются на аккаунт автоматически после подтверждения оплаты. YuPay — независимый сервис и не связан с Morefun Studios и Level Infinite; мы покупаем и перепродаём пополнения по прозрачному курсу.$c$,
    instructions = $c$Как пополнить Arena Breakout:

1. Введите ID игрока (UID) вашего аккаунта Arena Breakout — пароль не нужен.
2. Выберите, что пополнить: Bonds или Battle Pass.
3. Выберите способ оплаты: Click, Payme или Uzum. Сумма в сумах и курс показываются до оплаты.
4. Оплатите — Bonds или Battle Pass зачисляются на аккаунт автоматически после подтверждения платежа.

Где найти ID игрока в Arena Breakout: откройте игру и нажмите на аватар (значок профиля) в левом верхнем углу главного экрана — ваш ID игрока (UID) будет показан в профиле. Для пополнения нужен только этот ID; пароль передавать не требуется.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'arena-breakout') AND locale = 'ru';

UPDATE brand_translations SET
    highlights = $c$["Pay in UZS","By player ID","Automatic","No password"]$c$::json,
    short_description = $c$Top up Arena Breakout — Bonds and the Battle Pass by player ID, pay in sum, no password.$c$,
    description = $c$YuPay lets you top up Arena Breakout in Uzbekistan in sum. Arena Breakout is a mobile tactical extraction shooter from Morefun Studios and Level Infinite, where Bonds are the premium currency: they buy stash expansions and secure containers, weapon blueprints, subscriptions and the Battle Pass, while the Battle Pass unlocks the current season's rewards. We top up your game account by its public player ID — fast and with no password handover.

Pay the way you already do: Uzcard and Humo cards via Click, Payme and Uzum. The total in sum and the rate are shown before you confirm the order, and your Bonds or Battle Pass are credited to the account automatically once your payment is confirmed. YuPay is an independent service and is not affiliated with Morefun Studios or Level Infinite; we buy and resell top-ups at a transparent rate.$c$,
    instructions = $c$How to top up Arena Breakout:

1. Enter your Arena Breakout player ID (UID) — no password required.
2. Choose what to top up: Bonds or the Battle Pass.
3. Choose a payment method: Click, Payme or Uzum. The amount in sum and the rate are shown before you pay.
4. Pay — your Bonds or Battle Pass are credited to the account automatically once the payment is confirmed.

Where to find your Arena Breakout player ID: open the game and tap your avatar (profile icon) in the top-left corner of the main screen — your player ID (UID) is shown in your profile. Only this ID is needed to top up; you never share your password.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'arena-breakout') AND locale = 'en';

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","Oʻyinchi ID boʻyicha","Avtomatik","Parolsiz"]$c$::json,
    short_description = $c$Arena Breakout toʻldirish — Bonds va Battle Pass oʻyin IDsi orqali, soʻmda toʻlov, parolsiz.$c$,
    description = $c$YuPay — Oʻzbekistonda Arena Breakout hisobini soʻmda toʻldirish. Arena Breakout — Morefun Studios va Level Infinite tomonidan yaratilgan mobil taktik ekstraksiya-shuteri boʻlib, unda Bonds premium valyuta hisoblanadi: ular ombor kengaytmasi va himoyalangan konteynerlar, qurol chizmalari, obunalar hamda Battle Pass uchun ishlatiladi, Battle Pass esa joriy mavsum mukofotlarini ochadi. Biz oʻyin akkauntingizni ochiq ID boʻyicha toʻldiramiz — tez va parolni bermasdan.

Toʻlovni odatdagi usullarda amalga oshiring: Uzcard va Humo kartalari Click, Payme va Uzum orqali. Soʻmdagi yakuniy summa va kurs buyurtmani tasdiqlashdan oldin koʻrinadi, Bonds yoki Battle Pass esa toʻlov tasdiqlangach akkauntga avtomatik tushadi. YuPay — mustaqil xizmat va Morefun Studios hamda Level Infinite bilan bogʻliq emas; biz toʻldirishlarni shaffof kurs boʻyicha sotib olib, qayta sotamiz.$c$,
    instructions = $c$Arena Breakout hisobini qanday toʻldirish:

1. Arena Breakout akkauntingizning oʻyinchi ID (UID) raqamini kiriting — parol kerak emas.
2. Nimani toʻldirishni tanlang: Bonds yoki Battle Pass.
3. Toʻlov usulini tanlang: Click, Payme yoki Uzum. Soʻmdagi summa va kurs toʻlovdan oldin koʻrsatiladi.
4. Toʻlang — Bonds yoki Battle Pass toʻlov tasdiqlangach akkauntga avtomatik tushadi.

Oʻyinchi ID ni qayerdan topish mumkin: oʻyinni oching va asosiy ekranning yuqori chap burchagidagi avatar (profil belgisi)ni bosing — oʻyinchi ID (UID) profilingizda koʻrsatiladi. Toʻldirish uchun faqat shu ID kerak; parolni berish shart emas.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'arena-breakout') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- 2. FAQs (rebuilt each run: delete cascades to brand_faq_translations)
-- ---------------------------------------------------------------------------

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'arena-breakout');

WITH arena AS (
    SELECT id FROM brands WHERE slug = 'arena-breakout'
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), arena.id, v.sort_order, true
    FROM arena, (VALUES (1), (2), (3), (4), (5), (6), (7)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. Что такое Bonds?
        (1, 'ru', $q$Что такое Bonds в Arena Breakout?$q$,
            $a$Bonds — это премиум-валюта Arena Breakout. За них покупают расширение схрона и защищённые контейнеры, чертежи оружия, подписки, косметику из событий и Battle Pass. YuPay пополняет Bonds на ваш аккаунт по ID игрока.$a$),
        (1, 'en', $q$What are Bonds in Arena Breakout?$q$,
            $a$Bonds are the premium currency in Arena Breakout. They buy stash expansions and secure containers, weapon blueprints, subscriptions, event cosmetics and the Battle Pass. YuPay tops up Bonds to your account by your player ID.$a$),
        (1, 'uz', $q$Arena Breakoutda Bonds nima?$q$,
            $a$Bonds — Arena Breakout premium valyutasi. Ular ombor kengaytmasi va himoyalangan konteynerlar, qurol chizmalari, obunalar, tadbir kosmetikasi va Battle Pass uchun ishlatiladi. YuPay Bonds ni oʻyinchi ID boʻyicha akkauntingizga toʻldiradi.$a$),

        -- 2. Что даёт Battle Pass?
        (2, 'ru', $q$Что даёт Battle Pass в Arena Breakout?$q$,
            $a$Battle Pass открывает награды текущего сезона: продвигаясь по уровням, вы получаете предметы, косметику и Bonds на высоких тиерах. YuPay активирует Battle Pass на ваш аккаунт по ID игрока — пароль не нужен.$a$),
        (2, 'en', $q$What does the Battle Pass grant in Arena Breakout?$q$,
            $a$The Battle Pass unlocks the current season's rewards: as you climb the tiers you earn items, cosmetics and Bonds at the higher tiers. YuPay activates the Battle Pass on your account by your player ID — no password needed.$a$),
        (2, 'uz', $q$Arena Breakoutda Battle Pass nima beradi?$q$,
            $a$Battle Pass joriy mavsum mukofotlarini ochadi: darajalar boʻyicha oldinga siljib, buyumlar, kosmetika va yuqori tierlarda Bonds olasiz. YuPay Battle Pass ni oʻyinchi ID boʻyicha faollashtiradi — parol kerak emas.$a$),

        -- 3. Как узнать ID игрока?
        (3, 'ru', $q$Как узнать ID игрока в Arena Breakout?$q$,
            $a$Откройте игру и нажмите на аватар в левом верхнем углу главного экрана — ваш ID игрока (UID) показан в профиле. Для пополнения нужен только этот ID.$a$),
        (3, 'en', $q$How do I find my Arena Breakout player ID?$q$,
            $a$Open the game and tap your avatar in the top-left corner of the main screen — your player ID (UID) is shown in your profile. Only this ID is needed to top up.$a$),
        (3, 'uz', $q$Arena Breakoutda oʻyinchi ID ni qanday bilish mumkin?$q$,
            $a$Oʻyinni oching va asosiy ekranning yuqori chap burchagidagi avatarni bosing — oʻyinchi ID (UID) profilingizda koʻrsatiladi. Toʻldirish uchun faqat shu ID kerak.$a$),

        -- 4. Нужен ли пароль?
        (4, 'ru', $q$Нужен ли пароль от аккаунта?$q$,
            $a$Нет. Для пополнения достаточно публичного ID игрока — пароль от аккаунта передавать не нужно, и мы его не запрашиваем.$a$),
        (4, 'en', $q$Do you need my account password?$q$,
            $a$No. Your public player ID is all we need to top up — you never share your account password, and we never ask for it.$a$),
        (4, 'uz', $q$Akkaunt paroli kerakmi?$q$,
            $a$Yoʻq. Toʻldirish uchun ochiq oʻyinchi ID yetarli — akkaunt parolini bermaysiz, biz uni soʻramaymiz.$a$),

        -- 5. Можно ли платить в сумах?
        (5, 'ru', $q$Можно ли платить в сумах?$q$,
            $a$Да. Оплата в узбекских сумах доступна картами Uzcard и Humo через Click, Payme и Uzum. Сумма и курс показываются до оплаты.$a$),
        (5, 'en', $q$Can I pay in Uzbek sum?$q$,
            $a$Yes. You can pay in Uzbek sum with Uzcard and Humo cards via Click, Payme and Uzum. The amount and rate are shown before you pay.$a$),
        (5, 'uz', $q$Soʻmda toʻlash mumkinmi?$q$,
            $a$Ha. Oʻzbek soʻmida Uzcard va Humo kartalari orqali Click, Payme va Uzum bilan toʻlash mumkin. Summa va kurs toʻlovdan oldin koʻrsatiladi.$a$),

        -- 6. Как быстро зачислятся?
        (6, 'ru', $q$Как быстро зачислятся Bonds?$q$,
            $a$Bonds и Battle Pass зачисляются на игровой аккаунт автоматически после подтверждения оплаты.$a$),
        (6, 'en', $q$How fast are Bonds credited?$q$,
            $a$Your Bonds and Battle Pass are credited to your game account automatically once your payment is confirmed.$a$),
        (6, 'uz', $q$Bonds qancha vaqtda tushadi?$q$,
            $a$Bonds va Battle Pass toʻlov tasdiqlangach oʻyin akkauntiga avtomatik tushadi.$a$),

        -- 7. Это официальный сайт Arena Breakout?
        (7, 'ru', $q$Это официальный сайт Arena Breakout?$q$,
            $a$Нет. YuPay — независимый сервис пополнения и не связан с разработчиками игры Morefun Studios и Level Infinite. Мы покупаем и перепродаём пополнения по прозрачному курсу.$a$),
        (7, 'en', $q$Is this the official Arena Breakout website?$q$,
            $a$No. YuPay is an independent top-up service and is not affiliated with the game's developers Morefun Studios and Level Infinite. We buy and resell top-ups at a transparent rate.$a$),
        (7, 'uz', $q$Bu Arena Breakoutning rasmiy saytimi?$q$,
            $a$Yoʻq. YuPay — mustaqil toʻldirish xizmati va oʻyin ishlab chiquvchilari Morefun Studios hamda Level Infinite bilan bogʻliq emas. Biz toʻldirishlarni shaffof kurs boʻyicha sotib olib, qayta sotamiz.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
