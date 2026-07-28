-- scripts/seed/arena_breakout_infinite_seo.sql
--
-- SEO content pack for the `arena-breakout-infinite` brand: highlights +
-- short/long descriptions + instructions on `brand_translations`, and 7 FAQ
-- entries with ru/en/uz answers.
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
    highlights = $c$["Оплата в сумах","По ID аккаунта","Автоматически","Без пароля"]$c$::json,
    short_description = $c$Пополнение Arena Breakout: Infinite — Bonds и Battle Pass по UID (из лаунчера или профиля игры), оплата в сумах.$c$,
    description = $c$Arena Breakout: Infinite — тактический шутер-эвакуатор для PC от Morefun Studios и Level Infinite (Tencent). Это отдельная игра, а не мобильная Arena Breakout. Bonds — премиум-валюта: на неё берут скины оружия, облик оперативников, расширение склада, защищённые кейсы и боевой пропуск. Боевой пропуск открывает сезонный трек наград, которые вы получаете, выполняя задания и рейды.

YuPay помогает пополнить Arena Breakout: Infinite за узбекские сумы. Мы независимый сервис: покупаем Bonds и пропуск и перепродаём их по прозрачному курсу, который вы видите до оплаты. Оплатить можно картами Uzcard и Humo через Click, Payme и Uzum. Начисление автоматическое после подтверждения оплаты, а для пополнения нужен только публичный ID вашего аккаунта — пароль передавать не требуется.$c$,
    instructions = $c$Как пополнить Arena Breakout: Infinite:

1. Введите UID аккаунта Arena Breakout: Infinite — его можно найти в лаунчере игры или в профиле внутри самой игры. Пароль не нужен.
2. Выберите, что пополнить: Bonds или боевой пропуск. Итог к оплате и курс показываются сразу.
3. Выберите способ оплаты: Click, Payme или Uzum.
4. Оплатите — Bonds или пропуск зачисляются на аккаунт автоматически после подтверждения оплаты.

Где найти свой UID Arena Breakout: Infinite: UID можно найти двумя способами — в лаунчере игры (в Account Center лаунчера Level Infinite) или в профиле внутри самой игры (запустите игру на PC, нажмите на аватар и откройте профиль — UID указан на странице профиля). Скопируйте именно UID; логин и пароль от аккаунта передавать не нужно.

Обратите внимание: это PC-версия. Bonds и пропуск, купленные здесь, зачисляются только на PC-аккаунт и не переносятся в мобильную Arena Breakout.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'arena-breakout-infinite') AND locale = 'ru';

UPDATE brand_translations SET
    highlights = $c$["Pay in UZS","By account ID","Automatic","No password"]$c$::json,
    short_description = $c$Top up Arena Breakout: Infinite — Bonds and the Battle Pass by UID (from the launcher or your in-game profile), pay in sum.$c$,
    description = $c$Arena Breakout: Infinite is a tactical extraction shooter for PC by Morefun Studios and Level Infinite (Tencent). It is a separate game, not the mobile Arena Breakout. Bonds are the premium currency: they buy weapon skins, operator looks, stash expansions, secure cases and the Battle Pass. The Battle Pass unlocks a seasonal reward track you progress by completing missions and raids.

YuPay helps you top up Arena Breakout: Infinite in Uzbek sum. We are an independent service: we buy Bonds and the pass and resell them at a transparent rate shown before you pay. You can pay with Uzcard and Humo cards via Click, Payme and Uzum. Crediting is automatic once your payment is confirmed, and all we need is your public account ID — no password is required.$c$,
    instructions = $c$How to top up Arena Breakout: Infinite:

1. Enter your Arena Breakout: Infinite UID — you can find it in the game launcher or in your in-game profile. No password required.
2. Choose what to top up: Bonds or the Battle Pass. The total to pay and the rate are shown right away.
3. Choose a payment method: Click, Payme or Uzum.
4. Pay — your Bonds or pass are credited to the account automatically once payment is confirmed.

Where to find your Arena Breakout: Infinite UID: you can find it two ways — in the game launcher (the Level Infinite launcher's Account Center) or in your in-game profile (launch the game on PC, click your avatar and open your profile — the UID is shown on the profile page). Copy the UID only; you never share your account login or password.

Please note: this is the PC version. Bonds and the pass bought here are credited to PC accounts only and do not carry over to the mobile Arena Breakout.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'arena-breakout-infinite') AND locale = 'en';

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","Akkaunt ID orqali","Avtomatik","Parolsiz"]$c$::json,
    short_description = $c$Arena Breakout: Infinite toʻldirish — Bonds va Battle Pass UID orqali (launcherdan yoki oʻyin profilidan), soʻmda toʻlov.$c$,
    description = $c$Arena Breakout: Infinite — Morefun Studios va Level Infinite (Tencent) tomonidan yaratilgan PC uchun taktik evakuatsiya shuteri. Bu alohida oʻyin, mobil Arena Breakout emas. Bonds — premium valyuta: unga qurol skinlari, operator koʻrinishi, ombor kengaytmasi, himoyalangan keyslar va jangovar propusk olinadi. Jangovar propusk mavsumiy mukofotlar trekini ochadi, ularni vazifalar va reydlarni bajarib olasiz.

YuPay Arena Breakout: Infinite hisobini oʻzbek soʻmida toʻldirishga yordam beradi. Biz mustaqil xizmatmiz: Bonds va propuskni sotib olib, ularni shaffof kurs boʻyicha qayta sotamiz, kurs toʻlovdan oldin koʻrinadi. Toʻlovni Uzcard va Humo kartalari orqali Click, Payme va Uzum bilan amalga oshirasiz. Hisobga oʻtkazish toʻlov tasdiqlangach avtomatik boʻladi, toʻldirish uchun esa faqat akkauntingizning ommaviy IDsi kerak — parolni berish shart emas.$c$,
    instructions = $c$Arena Breakout: Infinite hisobini qanday toʻldirish:

1. Arena Breakout: Infinite UID raqamini kiriting — uni oʻyin launcherida yoki oʻyin profilida topishingiz mumkin. Parol kerak emas.
2. Nimani toʻldirishni tanlang: Bonds yoki jangovar propusk. Toʻlov summasi va kurs darhol koʻrsatiladi.
3. Toʻlov usulini tanlang: Click, Payme yoki Uzum.
4. Toʻlang — Bonds yoki propusk toʻlov tasdiqlangach akkauntga avtomatik tushadi.

Arena Breakout: Infinite UID raqamini qayerdan topish mumkin: UID ni ikki joydan topishingiz mumkin — oʻyin launcherida (Level Infinite launcheridagi Account Center) yoki oʻyin profilida (oʻyinni PCda ishga tushiring, avatarni bosib profilni oching — UID profil sahifasida koʻrsatiladi). Faqat UID ni nusxalang; akkaunt login va parolini berish shart emas.

Eslatma: bu PC versiyasi. Bu yerda olingan Bonds va propusk faqat PC akkauntga tushadi va mobil Arena Breakoutga oʻtmaydi.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'arena-breakout-infinite') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- 2. FAQs (rebuilt each run: delete cascades to brand_faq_translations)
-- ---------------------------------------------------------------------------

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'arena-breakout-infinite');

WITH abi AS (
    SELECT id FROM brands WHERE slug = 'arena-breakout-infinite'
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), abi.id, v.sort_order, true
    FROM abi, (VALUES (1), (2), (3), (4), (5), (6), (7)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. Что такое Bonds и что на них можно купить?
        (1, 'ru', $q$Что такое Bonds в Arena Breakout: Infinite и что на них можно купить?$q$,
            $a$Bonds — премиум-валюта Arena Breakout: Infinite. На неё покупают скины оружия, облик оперативников, расширение склада, защищённые кейсы для сохранения лута и боевой пропуск. Это в основном косметика, хранилище и прогресс, а не преимущество в бою.$a$),
        (1, 'en', $q$What are Bonds in Arena Breakout: Infinite and what can I buy with them?$q$,
            $a$Bonds are the premium currency of Arena Breakout: Infinite. They buy weapon skins, operator looks, stash expansions, secure cases that protect your loot, and the Battle Pass. They are mostly cosmetics, storage and progression rather than a combat advantage.$a$),
        (1, 'uz', $q$Arena Breakout: Infiniteda Bonds nima va unga nima sotib olish mumkin?$q$,
            $a$Bonds — Arena Breakout: Infinite premium valyutasi. Unga qurol skinlari, operator koʻrinishi, ombor kengaytmasi, lutni saqlaydigan himoyalangan keyslar va jangovar propusk olinadi. Bu asosan kosmetika, ombor va progress, jangdagi ustunlik emas.$a$),

        -- 2. Что даёт боевой пропуск?
        (2, 'ru', $q$Что даёт боевой пропуск (Battle Pass)?$q$,
            $a$Боевой пропуск открывает сезонный трек наград: скины, ресурсы, токены и другие бонусы. Награды вы получаете, повышая уровень пропуска за выполнение заданий, рейдов и еженедельных целей. Набор наград зависит от текущего сезона и выбранного пропуска.$a$),
        (2, 'en', $q$What does the Battle Pass give me?$q$,
            $a$The Battle Pass unlocks a seasonal reward track: skins, resources, tokens and other bonuses. You earn the rewards by levelling up the pass through missions, raids and weekly objectives. The exact rewards depend on the current season and the pass tier you choose.$a$),
        (2, 'uz', $q$Jangovar propusk (Battle Pass) nima beradi?$q$,
            $a$Jangovar propusk mavsumiy mukofotlar trekini ochadi: skinlar, resurslar, tokenlar va boshqa bonuslar. Mukofotlarni vazifalar, reydlar va haftalik maqsadlarni bajarib, propusk darajasini oshirib olasiz. Mukofotlar toʻplami joriy mavsum va tanlangan propuskka bogʻliq.$a$),

        -- 3. Это то же, что мобильная Arena Breakout?
        (3, 'ru', $q$Это то же, что мобильная Arena Breakout?$q$,
            $a$Нет. Arena Breakout: Infinite — отдельная игра для PC, а Arena Breakout — мобильная игра. У них разные аккаунты и валюта. Пополнение, купленное для PC-версии, зачисляется только на PC-аккаунт и не переносится в мобильную игру.$a$),
        (3, 'en', $q$Is this the same as the mobile Arena Breakout?$q$,
            $a$No. Arena Breakout: Infinite is a separate PC game, while Arena Breakout is the mobile game. They use different accounts and currency. A top-up bought for the PC version is credited to PC accounts only and does not carry over to the mobile game.$a$),
        (3, 'uz', $q$Bu mobil Arena Breakout bilan bir xilmi?$q$,
            $a$Yoʻq. Arena Breakout: Infinite — PC uchun alohida oʻyin, Arena Breakout esa mobil oʻyin. Ularning akkaunti va valyutasi har xil. PC versiyasi uchun olingan toʻldirish faqat PC akkauntga tushadi va mobil oʻyinga oʻtmaydi.$a$),

        -- 4. Как узнать свой ID?
        (4, 'ru', $q$Как узнать свой ID в Arena Breakout: Infinite?$q$,
            $a$UID можно найти двумя способами: в лаунчере игры (в Account Center лаунчера Level Infinite) или в профиле внутри самой игры — запустите игру на PC, нажмите на аватар и откройте профиль, UID указан на странице профиля. Копируйте именно UID; логин и пароль передавать не нужно.$a$),
        (4, 'en', $q$How do I find my Arena Breakout: Infinite ID?$q$,
            $a$You can find your UID two ways: in the game launcher (the Level Infinite launcher's Account Center) or in your in-game profile — launch the game on PC, click your avatar and open your profile, where the UID is shown. Copy the UID only; you never share your login or password.$a$),
        (4, 'uz', $q$Arena Breakout: Infinite IDsini qanday bilish mumkin?$q$,
            $a$UID ni ikki joydan topishingiz mumkin: oʻyin launcherida (Level Infinite launcheridagi Account Center) yoki oʻyin profilida — oʻyinni PCda ishga tushiring, avatarni bosib profilni oching, UID shu yerda koʻrsatiladi. Faqat UID ni nusxalang; login va parolni berish shart emas.$a$),

        -- 5. Нужен ли пароль?
        (5, 'ru', $q$Нужен ли пароль от аккаунта?$q$,
            $a$Нет. Для пополнения достаточно публичного ID аккаунта — пароль и данные для входа передавать не нужно, и мы их не запрашиваем.$a$),
        (5, 'en', $q$Do you need my account password?$q$,
            $a$No. Your public account ID is all we need to top up — you never share your password or login details, and we never ask for them.$a$),
        (5, 'uz', $q$Akkaunt paroli kerakmi?$q$,
            $a$Yoʻq. Toʻldirish uchun akkauntning ommaviy IDsi yetarli — parol va kirish maʼlumotlarini berish shart emas, biz ularni soʻramaymiz.$a$),

        -- 6. Можно ли платить в сумах и как быстро зачислится?
        (6, 'ru', $q$Можно ли платить в сумах и как быстро зачислится?$q$,
            $a$Да. Оплата в узбекских сумах доступна картами Uzcard и Humo через Click, Payme и Uzum. Курс виден до оплаты. После подтверждения платежа Bonds или пропуск зачисляются на аккаунт автоматически.$a$),
        (6, 'en', $q$Can I pay in sum, and how fast is it credited?$q$,
            $a$Yes. You can pay in Uzbek sum with Uzcard and Humo cards via Click, Payme and Uzum, with the rate shown before you pay. Once the payment is confirmed, your Bonds or pass are credited to the account automatically.$a$),
        (6, 'uz', $q$Soʻmda toʻlash mumkinmi va qancha vaqtda tushadi?$q$,
            $a$Ha. Oʻzbek soʻmida Uzcard va Humo kartalari orqali Click, Payme va Uzum bilan toʻlash mumkin, kurs toʻlovdan oldin koʻrinadi. Toʻlov tasdiqlangach Bonds yoki propusk akkauntga avtomatik tushadi.$a$),

        -- 7. Это официальный сайт?
        (7, 'ru', $q$Это официальный сайт Arena Breakout: Infinite?$q$,
            $a$Нет. YuPay — независимый сервис пополнения, не связанный с Morefun Studios и Level Infinite (Tencent). Мы покупаем и перепродаём Bonds и боевой пропуск по прозрачному курсу, который вы видите до оплаты.$a$),
        (7, 'en', $q$Is this the official Arena Breakout: Infinite website?$q$,
            $a$No. YuPay is an independent top-up service, not affiliated with Morefun Studios or Level Infinite (Tencent). We buy and resell Bonds and the Battle Pass at a transparent rate that you see before you pay.$a$),
        (7, 'uz', $q$Bu Arena Breakout: Infinitening rasmiy saytimi?$q$,
            $a$Yoʻq. YuPay — mustaqil toʻldirish xizmati, Morefun Studios va Level Infinite (Tencent) bilan bogʻliq emas. Biz Bonds va jangovar propuskni shaffof kurs boʻyicha sotib olib, qayta sotamiz, kurs toʻlovdan oldin koʻrinadi.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
