-- scripts/seed/delta_force_seo.sql
--
-- SEO content pack for the `delta-force` brand: highlights + short/long
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
    short_description = $c$Пополнение Delta Force — Delta Coins и Season Pass по игровому ID, оплата в сумах, без пароля.$c$,
    description = $c$Delta Force — бесплатный тактический шутер от Team Jade и TiMi Studio Group. Delta Coins — внутриигровая валюта: за неё покупают облики оперативников, скины оружия, Season Pass и другие косметические предметы. Season Pass открывает премиум-линию наград сезона — эксклюзивные скины, чертежи оружия и бонусы, недоступные на бесплатном треке.

YuPay пополняет Delta Coins и Season Pass в Узбекистане за сумы. Пополнение идёт по ID игрока — пароль от аккаунта не нужен и не запрашивается. Оплатить можно картами Uzcard и Humo через Click, Payme и Uzum. После подтверждения оплаты Delta Coins зачисляются автоматически, а итоговую сумму и курс вы видите ещё до подтверждения заказа. YuPay — независимый сервис и не связан с издателями игры.$c$,
    instructions = $c$Как пополнить Delta Force:

1. Введите ID игрока (Player ID) — пароль от аккаунта не нужен.
2. Выберите, что пополнить: Delta Coins или Season Pass, и нужный номинал.
3. Выберите способ оплаты: Click, Payme или Uzum.
4. Оплатите — Delta Coins зачисляются автоматически после подтверждения оплаты.

Где найти ID игрока в Delta Force: зайдите в лобби игры и откройте профиль (значок в правом нижнем углу) — ваш ID игрока (Player ID) показан там. Перед оплатой внимательно проверьте ID: средства, отправленные на неверный ID, вернуть сложно.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'delta-force') AND locale = 'ru';

UPDATE brand_translations SET
    highlights = $c$["Pay in UZS","By player ID","Automatic","No password"]$c$::json,
    short_description = $c$Top up Delta Force — Delta Coins and the Season Pass by player ID, pay in sum, no password.$c$,
    description = $c$Delta Force is a free-to-play tactical shooter by Team Jade and TiMi Studio Group. Delta Coins are its in-game currency: use them to buy operator outfits, weapon skins, the Season Pass and other cosmetic items. The Season Pass unlocks the premium reward track for the current season — exclusive skins, weapon blueprints and bonuses the free track never gives.

YuPay tops up Delta Coins and the Season Pass in Uzbekistan in sum. Top-ups go by your player ID — your account password is never needed and never requested. Pay with Uzcard and Humo cards via Click, Payme and Uzum. Once your payment is confirmed, Delta Coins are credited automatically, and you see the total and the rate before you confirm the order. YuPay is an independent service and is not affiliated with the game's publishers.$c$,
    instructions = $c$How to top up Delta Force:

1. Enter your player ID (Player ID) — no account password required.
2. Choose what to top up: Delta Coins or the Season Pass, and the amount you need.
3. Choose a payment method: Click, Payme or Uzum.
4. Pay — Delta Coins are credited automatically once your payment is confirmed.

Where to find your Delta Force player ID: open the game lobby and open your profile (the icon in the bottom-right corner) — your player ID (Player ID) is shown there. Double-check the ID before paying: funds sent to the wrong ID are hard to recover.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'delta-force') AND locale = 'en';

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","Oʻyinchi ID boʻyicha","Avtomatik","Parolsiz"]$c$::json,
    short_description = $c$Delta Force toʻldirish — Delta Coins va Season Pass oʻyin IDsi orqali, soʻmda toʻlov, parolsiz.$c$,
    description = $c$Delta Force — Team Jade va TiMi Studio Group tomonidan ishlab chiqilgan bepul taktik shooter. Delta Coins — oʻyinning ichki valyutasi: unga operativchilar qiyofasi, qurol skinlari, Season Pass va boshqa kosmetik buyumlar sotib olinadi. Season Pass mavsumning premium mukofot liniyasini ochadi — bepul trekda mavjud boʻlmagan eksklyuziv skinlar, qurol chizmalari va bonuslar.

YuPay Delta Coins va Season Pass ni Oʻzbekistonda soʻmda toʻldiradi. Toʻldirish oʻyinchi ID boʻyicha amalga oshiriladi — akkaunt paroli kerak emas va soʻralmaydi. Toʻlovni Uzcard va Humo kartalari orqali Click, Payme va Uzum bilan qilish mumkin. Toʻlov tasdiqlangach Delta Coins avtomatik tushadi, yakuniy summa va kursni esa buyurtmani tasdiqlashdan oldin koʻrasiz. YuPay — mustaqil xizmat va oʻyin nashriyoti bilan bogʻliq emas.$c$,
    instructions = $c$Delta Force ni qanday toʻldirish:

1. Oʻyinchi ID (Player ID) ni kiriting — akkaunt paroli kerak emas.
2. Nimani toʻldirishni tanlang: Delta Coins yoki Season Pass va kerakli nominal.
3. Toʻlov usulini tanlang: Click, Payme yoki Uzum.
4. Toʻlang — Delta Coins toʻlov tasdiqlangach avtomatik tushadi.

Delta Force da oʻyinchi ID ni qayerdan topish mumkin: oʻyin lobbisiga kiring, profilni oching (pastki oʻng burchakdagi belgi) — oʻyinchi ID (Player ID) oʻsha yerda koʻrsatiladi. Toʻlovdan oldin ID ni diqqat bilan tekshiring: notoʻgʻri ID ga yuborilgan mablagʻni qaytarish qiyin.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'delta-force') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- 2. FAQs (rebuilt each run: delete cascades to brand_faq_translations)
-- ---------------------------------------------------------------------------

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'delta-force');

WITH delta_force AS (
    SELECT id FROM brands WHERE slug = 'delta-force'
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), delta_force.id, v.sort_order, true
    FROM delta_force, (VALUES (1), (2), (3), (4), (5), (6), (7)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. Что такое Delta Coins?
        (1, 'ru', $q$Что такое Delta Coins и что на них можно купить?$q$,
            $a$Delta Coins — внутриигровая валюта Delta Force. За неё покупают облики оперативников, скины оружия, Season Pass, ваучеры и другие косметические предметы. На геймплей они не влияют — только на внешний вид.$a$),
        (1, 'en', $q$What are Delta Coins and what can you buy with them?$q$,
            $a$Delta Coins are the in-game currency of Delta Force. Use them to buy operator outfits, weapon skins, the Season Pass, vouchers and other cosmetic items. They do not affect gameplay — only how things look.$a$),
        (1, 'uz', $q$Delta Coins nima va unga nimalar sotib olish mumkin?$q$,
            $a$Delta Coins — Delta Force oʻyinining ichki valyutasi. Unga operativchilar qiyofasi, qurol skinlari, Season Pass, vaucherlar va boshqa kosmetik buyumlar sotib olinadi. Ular geympleyga taʼsir qilmaydi — faqat tashqi koʻrinishga.$a$),

        -- 2. Как узнать ID игрока?
        (2, 'ru', $q$Как узнать свой ID игрока в Delta Force?$q$,
            $a$Зайдите в лобби игры и откройте профиль — значок в правом нижнем углу. Ваш ID игрока (Player ID) показан там. Перед оплатой проверьте его: Delta Coins привязаны к ID, а не к устройству.$a$),
        (2, 'en', $q$How do I find my Delta Force player ID?$q$,
            $a$Open the game lobby and open your profile — the icon in the bottom-right corner. Your player ID (Player ID) is shown there. Check it before paying: Delta Coins are tied to your ID, not your device.$a$),
        (2, 'uz', $q$Delta Force da oʻyinchi ID sini qanday bilish mumkin?$q$,
            $a$Oʻyin lobbisiga kiring va profilni oching — pastki oʻng burchakdagi belgi. Oʻyinchi ID (Player ID) oʻsha yerda koʻrsatiladi. Toʻlovdan oldin uni tekshiring: Delta Coins qurilmaga emas, ID ga bogʻlangan.$a$),

        -- 3. Нужен ли пароль?
        (3, 'ru', $q$Нужен ли пароль от аккаунта?$q$,
            $a$Нет. Для пополнения достаточно ID игрока — пароль от аккаунта передавать не нужно, и мы его не запрашиваем.$a$),
        (3, 'en', $q$Do you need my account password?$q$,
            $a$No. Your player ID is all we need to top up — you never share your account password, and we never ask for it.$a$),
        (3, 'uz', $q$Akkaunt paroli kerakmi?$q$,
            $a$Yoʻq. Toʻldirish uchun oʻyinchi ID yetarli — akkaunt parolini bermaysiz, biz uni soʻramaymiz.$a$),

        -- 4. Оплата в сумах?
        (4, 'ru', $q$Можно ли платить в сумах и какими способами?$q$,
            $a$Да. Оплата в узбекских сумах картами Uzcard и Humo через Click, Payme и Uzum. Итоговую сумму и курс вы видите до подтверждения заказа.$a$),
        (4, 'en', $q$Can I pay in sum, and with which methods?$q$,
            $a$Yes. Pay in Uzbek sum with Uzcard and Humo cards via Click, Payme and Uzum. You see the total and the rate before you confirm the order.$a$),
        (4, 'uz', $q$Soʻmda va qaysi usullarda toʻlash mumkin?$q$,
            $a$Ha. Oʻzbek soʻmida Uzcard va Humo kartalari orqali Click, Payme va Uzum bilan. Toʻlov summasi va kursni buyurtmani tasdiqlashdan oldin koʻrasiz.$a$),

        -- 5. За сколько зачислятся?
        (5, 'ru', $q$За сколько зачислятся Delta Coins?$q$,
            $a$Delta Coins зачисляются автоматически после подтверждения оплаты. Отдельных действий с вашей стороны не требуется.$a$),
        (5, 'en', $q$How fast are Delta Coins credited?$q$,
            $a$Delta Coins are credited automatically once your payment is confirmed. Nothing else is required on your side.$a$),
        (5, 'uz', $q$Delta Coins qancha vaqtda tushadi?$q$,
            $a$Delta Coins toʻlov tasdiqlangach avtomatik tushadi. Sizdan qoʻshimcha harakat talab qilinmaydi.$a$),

        -- 6. Это официальный сайт?
        (6, 'ru', $q$Это официальный сайт Delta Force?$q$,
            $a$Нет. YuPay — независимый сервис пополнения и не связан с издателями игры (Team Jade, TiMi Studio Group / Level Infinite). Мы покупаем и перепродаём пополнения по прозрачному курсу.$a$),
        (6, 'en', $q$Is this the official Delta Force website?$q$,
            $a$No. YuPay is an independent top-up service and is not affiliated with the game's publishers (Team Jade, TiMi Studio Group / Level Infinite). We buy and resell top-ups at a transparent rate.$a$),
        (6, 'uz', $q$Bu Delta Force ning rasmiy saytimi?$q$,
            $a$Yoʻq. YuPay — mustaqil toʻldirish xizmati va oʻyin nashriyotlari (Team Jade, TiMi Studio Group / Level Infinite) bilan bogʻliq emas. Biz toʻldirishlarni shaffof kurs boʻyicha sotib olib, qayta sotamiz.$a$),

        -- 7. Что даёт Season Pass?
        (7, 'ru', $q$Что даёт Season Pass?$q$,
            $a$Season Pass открывает премиум-линию наград текущего сезона: эксклюзивные облики оперативников, скины и чертежи оружия и другие предметы, недоступные на бесплатном треке. Награды выдаются по мере прокачки уровней сезона.$a$),
        (7, 'en', $q$What does the Season Pass give you?$q$,
            $a$The Season Pass unlocks the premium reward track for the current season: exclusive operator outfits, weapon skins and blueprints, and other items the free track doesn't include. Rewards are handed out as you level up through the season.$a$),
        (7, 'uz', $q$Season Pass nima beradi?$q$,
            $a$Season Pass joriy mavsumning premium mukofot liniyasini ochadi: eksklyuziv operativchi qiyofalari, qurol skinlari va chizmalari hamda bepul trekda mavjud boʻlmagan boshqa buyumlar. Mukofotlar mavsum darajalari oshgani sayin beriladi.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
