-- scripts/seed/oxide_seo.sql
--
-- SEO content pack for the `oxide-survival-island` brand: highlights +
-- short/long descriptions + instructions on `brand_translations`, product names
-- per locale, and 7 FAQ entries with ru/en/uz answers.
--
-- Content-managed, NOT a fixture and NOT an Alembic data migration. Applied to
-- prod by an operator (psql / `!`), gated by the standing deploy rule. Depends
-- on scripts/seed/2026-08-25_oxide_import.py having created the brand.
--
-- Idempotent: brand_translations and product_translations rows are UPDATEd in
-- place; FAQs are rebuilt via delete-then-insert, inside one transaction.
--
-- Strings are dollar-quoted ($c$…$c$ / $q$…$q$ / $a$…$a$) so the apostrophe-heavy
-- Uzbek copy needs no escaping.
--
-- **This brand promises no nickname check, and the copy must not imply one.**
-- G2B's checkPlayerId answers any Oxide id of six characters or more with
-- "valid" and echoes the input back as the nickname, so there is nothing
-- truthful to show the buyer before payment. Blood Strike's pack sells the
-- check as a safeguard; here the safeguard is the copy button, and every
-- mention of the id says so. Getting this wrong would be a promise the page
-- cannot keep at the one step that is irreversible.
--
-- The other thing that leads here is the bonus ladder: every tier we sell is
-- the WEB BONUS one, so 50 coins is really 55 and 7500 is really 11250. That is
-- a real advantage over the plain tier at the same price and it belongs in the
-- copy rather than only in the SKU label.
--
-- Apply on prod (operator psql):
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     psql -U yupay_app -d yupay -f - < scripts/seed/oxide_seo.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Brand translations (highlights, short_description, description, instructions)
-- ---------------------------------------------------------------------------

UPDATE brand_translations SET
    highlights = $c$["Оплата в сумах","По User ID","Бонусные монеты","Без пароля"]$c$::json,
    short_description = $c$Пополнение Oxide: Survival Island — монеты по User ID, оплата в сумах, без пароля.$c$,
    description = $c$Oxide: Survival Island — мобильный выживач от студии HYPERHUG, устроенный по образцу Rust: открытый остров, три биома, добыча ресурсов, крафт, строительство базы и рейды других игроков. Монеты (Coins) — премиальная валюта игры: за них открывают чертежи оружия и снаряжения, докупают дерево, камень и металл, когда до налёта остаются минуты, оплачивают содержание шкафа, чтобы постройки не разрушились, и берут скины.

YuPay пополняет аккаунт по публичному User ID — пароль и вход в аккаунт не нужны. Мы продаём бонусные пакеты: к каждому номиналу игра добавляет монеты сверху, поэтому за те же деньги приходит больше, чем в обычном наборе — 55 вместо 50, 315 вместо 250, 11250 вместо 7500. Оплатить можно в сумах картами Uzcard и Humo через Click, Payme или Uzum; курс виден до оплаты, а монеты зачисляются автоматически после подтверждения платежа.$c$,
    instructions = $c$Как пополнить Oxide: Survival Island:

1. Выберите пакет монет. В скобках показано, сколько идёт бонусом сверх основного номинала.
2. Введите User ID. Пароль и вход в аккаунт не нужны.
3. Выберите способ оплаты: Click, Payme или Uzum. Курс и итоговая сумма показываются до оплаты.
4. Оплатите — монеты зачисляются автоматически после подтверждения платежа, обычно за несколько минут.

Где найти User ID: откройте игру и нажмите на профиль на главном экране — ID показан под иконкой профиля, он же есть в «Параметрах» (Settings). Скопируйте его кнопкой копирования и вставьте в поле, не набирайте вручную: монеты уходят на тот ID, который получен, и вернуть их нельзя.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'oxide-survival-island') AND locale = 'ru';

UPDATE brand_translations SET
    highlights = $c$["Pay in UZS","By User ID","Bonus coins","No password"]$c$::json,
    short_description = $c$Oxide: Survival Island top-up — coins by User ID, pay in UZS, no password.$c$,
    description = $c$Oxide: Survival Island is HYPERHUG's mobile survival game, built along the lines of Rust: an open island across three biomes, resource gathering, crafting, base building and raids from other players. Coins are its premium currency — they unlock blueprints for weapons and gear, top up the wood, stone and metal you are short of when a raid is minutes away, pay the cupboard upkeep that keeps your base standing, and buy skins.

YuPay tops the account up by public User ID — no password, no account login. We sell the bonus packs: the game adds coins on top of every tier, so the same money brings more than the plain pack does — 55 instead of 50, 315 instead of 250, 11250 instead of 7500. Pay in UZS with Uzcard or Humo through Click, Payme or Uzum; the rate is shown before you pay, and coins are credited automatically once the payment clears.$c$,
    instructions = $c$How to top up Oxide: Survival Island:

1. Pick a coin pack. The figure in brackets is how much of it is bonus on top of the base tier.
2. Enter your User ID. No password or account login required.
3. Choose a payment method: Click, Payme or Uzum. The rate and the total are shown before you pay.
4. Pay — the coins are credited automatically once the payment clears, usually within a few minutes.

Where to find the User ID: open the game and tap your profile on the main screen — the ID sits under the profile icon, and is also in Settings. Copy it with the copy button and paste it in; do not retype it. Coins go to whatever id we are given and cannot be taken back.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'oxide-survival-island') AND locale = 'en';

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","User ID orqali","Bonus tangalar","Parolsiz"]$c$::json,
    short_description = $c$Oxide: Survival Island toʻldirish — User ID orqali tangalar, soʻmda toʻlov, parolsiz.$c$,
    description = $c$Oxide: Survival Island — HYPERHUG studiyasining mobil survival oʻyini, Rust uslubida qurilgan: ochiq orol, uchta biom, resurs yigʻish, kraft, baza qurish va boshqa oʻyinchilar reydlari. Tangalar (Coins) — oʻyinning premium valyutasi: ular bilan qurol va jihoz chizmalari ochiladi, reydga daqiqalar qolganda yetishmayotgan yogʻoch, tosh va metall sotib olinadi, postroykalar buzilmasligi uchun shkaf xarajati toʻlanadi va skinlar olinadi.

YuPay hisobni ommaviy User ID orqali toʻldiradi — parol va akkauntga kirish kerak emas. Biz bonusli paketlarni sotamiz: oʻyin har bir nominal ustiga tanga qoʻshadi, shuning uchun oʻsha pulga oddiy toʻplamdan koʻra koʻproq keladi — 50 oʻrniga 55, 250 oʻrniga 315, 7500 oʻrniga 11250. Uzcard va Humo kartalari bilan Click, Payme yoki Uzum orqali soʻmda toʻlash mumkin; kurs toʻlovdan oldin koʻrinadi, tangalar esa toʻlov tasdiqlangach avtomatik tushadi.$c$,
    instructions = $c$Oxide: Survival Island ni qanday toʻldirish:

1. Tanga paketini tanlang. Qavs ichida asosiy nominal ustiga qancha bonus qoʻshilishi koʻrsatilgan.
2. User ID ni kiriting. Parol va akkauntga kirish kerak emas.
3. Toʻlov usulini tanlang: Click, Payme yoki Uzum. Kurs va yakuniy summa toʻlovdan oldin koʻrsatiladi.
4. Toʻlang — tangalar toʻlov tasdiqlangach avtomatik, odatda bir necha daqiqada tushadi.

User ID ni qayerdan topish kerak: oʻyinni oching va bosh ekranda profilni bosing — ID profil belgisi ostida, shuningdek «Settings» boʻlimida koʻrsatiladi. Uni nusxa olish tugmasi bilan koʻchirib joylashtiring, qoʻlda termang: tangalar qaysi ID berilsa oʻshanga tushadi va qaytarib boʻlmaydi.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'oxide-survival-island') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- 2. Product translations
-- ---------------------------------------------------------------------------

UPDATE product_translations SET
    name = $c$Монеты$c$,
    short_description = $c$Премиальная валюта Oxide — чертежи, ресурсы, содержание шкафа и скины.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'oxide-coins') AND locale = 'ru';
UPDATE product_translations SET
    name = $c$Coins$c$,
    short_description = $c$Oxide's premium currency — blueprints, resources, cupboard upkeep and skins.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'oxide-coins') AND locale = 'en';
UPDATE product_translations SET
    name = $c$Tangalar$c$,
    short_description = $c$Oxide premium valyutasi — chizmalar, resurslar, shkaf xarajati va skinlar.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'oxide-coins') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- 3. FAQs (rebuilt each run: delete cascades to brand_faq_translations)
-- ---------------------------------------------------------------------------

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'oxide-survival-island');

WITH ox AS (
    SELECT id FROM brands WHERE slug = 'oxide-survival-island'
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), ox.id, v.sort_order, true
    FROM ox, (VALUES (1), (2), (3), (4), (5), (6), (7)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. User ID — единственная необратимая ошибка на этой странице.
        --    Никакой проверки ника мы не обещаем: у поставщика её нет.
        (1, 'ru', $q$Как узнать свой User ID в Oxide: Survival Island?$q$,
            $a$Откройте игру и нажмите на профиль на главном экране — User ID показан под иконкой профиля. Тот же ID есть в «Параметрах» (Settings). Скопируйте его кнопкой копирования и вставьте в поле на нашем сайте, а не набирайте вручную: монеты зачисляются на тот ID, который был указан, и вернуть их нельзя. ID может состоять из букв, цифр и дефисов — вводите его целиком, как показан.$a$),
        (1, 'en', $q$How do I find my Oxide: Survival Island User ID?$q$,
            $a$Open the game and tap your profile on the main screen — the User ID is shown under the profile icon. The same ID is in Settings. Copy it with the copy button and paste it into the field here rather than retyping it: coins are credited to whatever ID was entered and cannot be taken back. The ID may contain letters, digits and hyphens — enter it exactly as shown, in full.$a$),
        (1, 'uz', $q$Oxide: Survival Island'da User ID ni qanday bilish mumkin?$q$,
            $a$Oʻyinni oching va bosh ekranda profilni bosing — User ID profil belgisi ostida koʻrsatiladi. Shu ID «Settings» boʻlimida ham bor. Uni nusxa olish tugmasi bilan koʻchirib, saytimizdagi maydonga joylashtiring, qoʻlda termang: tangalar qaysi ID koʻrsatilgan boʻlsa, oʻshanga tushadi va qaytarib boʻlmaydi. ID harflar, raqamlar va defislardan iborat boʻlishi mumkin — qanday koʻrsatilgan boʻlsa, toʻliq shunday kiriting.$a$),

        -- 2. Что такое монеты.
        (2, 'ru', $q$Что такое монеты в Oxide и на что они тратятся?$q$,
            $a$Монеты (Coins) — премиальная валюта Oxide: Survival Island. За них открывают чертежи оружия, инструментов и тёплой одежды, докупают дерево, камень и металл для крафта, оплачивают содержание шкафа, чтобы постройки не разрушились, и берут скины и наборы. Проще говоря, монеты экономят время: то, на что иначе уйдёт несколько часов фарма, покупается сразу.$a$),
        (2, 'en', $q$What are Oxide coins and what do they buy?$q$,
            $a$Coins are the premium currency of Oxide: Survival Island. They unlock blueprints for weapons, tools and cold-weather gear, top up the wood, stone and metal you need for crafting, pay the cupboard upkeep that keeps your base from decaying, and buy skins and bundles. In short, coins buy time: what would otherwise take hours of farming is available at once.$a$),
        (2, 'uz', $q$Oxide tangalari nima va ular nimaga sarflanadi?$q$,
            $a$Tangalar (Coins) — Oxide: Survival Island premium valyutasi. Ular bilan qurol, asbob va issiq kiyim chizmalari ochiladi, kraft uchun yogʻoch, tosh va metall sotib olinadi, postroykalar buzilmasligi uchun shkaf xarajati toʻlanadi, skin va toʻplamlar olinadi. Qisqasi, tangalar vaqtni tejaydi: bir necha soat farm talab qiladigan narsa darhol olinadi.$a$),

        -- 3. Бонусная лестница — наше реальное преимущество, не маркетинг.
        (3, 'ru', $q$Почему в пакете больше монет, чем написано в номинале?$q$,
            $a$Мы продаём бонусные пакеты: к основному номиналу игра добавляет монеты сверху. Например, в пакете «55 Coins (50 + 5)» на счёт приходит 55 монет — 50 основных и 5 бонусных. То же со всеми остальными: 145 вместо 125, 315 вместо 250, 675 вместо 500, 1750 вместо 1250, 3750 вместо 2500 и 11250 вместо 7500. Цена при этом такая же, как у обычного набора того же уровня, поэтому брать бонусный выгоднее всегда.$a$),
        (3, 'en', $q$Why does the pack contain more coins than its tier says?$q$,
            $a$We sell the bonus packs: the game adds coins on top of the base tier. In "55 Coins (50 + 5)", for instance, 55 coins reach the account — 50 base and 5 bonus. The same holds for the rest: 145 instead of 125, 315 instead of 250, 675 instead of 500, 1750 instead of 1250, 3750 instead of 2500 and 11250 instead of 7500. The price matches the plain pack at the same level, so the bonus one is always the better buy.$a$),
        (3, 'uz', $q$Nega paketda nominalda yozilganidan koʻproq tanga bor?$q$,
            $a$Biz bonusli paketlarni sotamiz: oʻyin asosiy nominal ustiga tanga qoʻshadi. Masalan, «55 Coins (50 + 5)» paketida hisobga 55 tanga tushadi — 50 asosiy va 5 bonus. Qolganlarida ham shunday: 125 oʻrniga 145, 250 oʻrniga 315, 500 oʻrniga 675, 1250 oʻrniga 1750, 2500 oʻrniga 3750 va 7500 oʻrniga 11250. Narx esa oʻsha darajadagi oddiy paket bilan bir xil, shuning uchun bonuslisini olish har doim foydali.$a$),

        -- 4. Сроки зачисления.
        (4, 'ru', $q$Как быстро приходят монеты?$q$,
            $a$Обычно в течение нескольких минут после подтверждения платежа — заказ уходит поставщику автоматически, вручную ничего подтверждать не нужно. Если у поставщика очередь, зачисление может занять до получаса. Статус заказа виден на странице заказа, а когда монеты зачислены, мы присылаем письмо на указанную почту.$a$),
        (4, 'en', $q$How quickly do the coins arrive?$q$,
            $a$Usually within a few minutes of the payment clearing — the order goes to the supplier automatically, with nothing to confirm by hand. If the supplier has a queue it can take up to half an hour. The order page shows the current status, and we email you at the address on the order once the coins are credited.$a$),
        (4, 'uz', $q$Tangalar qanchalik tez keladi?$q$,
            $a$Odatda toʻlov tasdiqlangach bir necha daqiqada — buyurtma taʼminotchiga avtomatik ketadi, qoʻlda hech narsa tasdiqlash shart emas. Taʼminotchida navbat boʻlsa, yarim soatgacha choʻzilishi mumkin. Buyurtma sahifasida holat koʻrinadi, tangalar tushgach esa buyurtmadagi pochtaga xat yuboramiz.$a$),

        -- 5. Безопасность — почему без пароля.
        (5, 'ru', $q$Нужен ли пароль от аккаунта?$q$,
            $a$Нет. Пополнение идёт по публичному User ID — это открытый идентификатор, который игра показывает в вашем же профиле. Ни пароль, ни доступ к аккаунту, ни привязанная почта нам не нужны, и запрашивать их мы никогда не будем. Если какой-то сервис просит логин и пароль от Oxide, это повод отказаться: по ID монеты зачисляются точно так же, но аккаунт остаётся только у вас.$a$),
        (5, 'en', $q$Do you need my account password?$q$,
            $a$No. The top-up runs on the public User ID — an open identifier the game shows on your own profile screen. We need no password, no account access and no linked email, and we will never ask for them. If a service asks for your Oxide login and password, that is a reason to walk away: crediting by ID works exactly the same and leaves the account yours alone.$a$),
        (5, 'uz', $q$Akkaunt paroli kerakmi?$q$,
            $a$Yoʻq. Toʻldirish ommaviy User ID orqali amalga oshadi — bu oʻyin oʻz profilingizda koʻrsatadigan ochiq identifikator. Bizga na parol, na akkauntga kirish, na bogʻlangan pochta kerak va biz ularni hech qachon soʻramaymiz. Agar biror xizmat Oxide login va parolini soʻrasa, bu rad etish uchun sabab: ID orqali tangalar xuddi shunday tushadi, akkaunt esa faqat sizda qoladi.$a$),

        -- 6. Оплата в сумах.
        (6, 'ru', $q$Как оплатить в сумах?$q$,
            $a$Картой Uzcard или Humo через Click, Payme или Uzum — способ выбирается на странице оформления. Итоговая сумма в сумах и курс показываются до оплаты, скрытых комиссий нет. Валютную карту заводить не нужно.$a$),
        (6, 'en', $q$How do I pay in UZS?$q$,
            $a$With an Uzcard or Humo card through Click, Payme or Uzum — you pick the method at checkout. The total in UZS and the rate are shown before you pay, with no hidden fees. There is no need for a foreign-currency card.$a$),
        (6, 'uz', $q$Soʻmda qanday toʻlayman?$q$,
            $a$Uzcard yoki Humo kartasi bilan Click, Payme yoki Uzum orqali — usul rasmiylashtirish sahifasida tanlanadi. Soʻmdagi yakuniy summa va kurs toʻlovdan oldin koʻrsatiladi, yashirin komissiya yoʻq. Valyuta kartasi ochish shart emas.$a$),

        -- 7. Что делать, если не пришло.
        (7, 'ru', $q$Что делать, если монеты не пришли?$q$,
            $a$Сначала перезайдите в игру — баланс обновляется при входе. Если через полчаса после оплаты монет нет, напишите нам в поддержку и приложите номер заказа: мы видим статус у поставщика и доведём заказ до конца или вернём деньги. Если же выяснится, что User ID был указан с ошибкой, вернуть монеты уже нельзя — они ушли на тот аккаунт, который был введён. Поэтому ID стоит копировать, а не набирать.$a$),
        (7, 'en', $q$What if the coins do not arrive?$q$,
            $a$Restart the game first — the balance refreshes on login. If half an hour has passed since payment and there is still nothing, message our support with the order number: we can see the supplier's status and will either see the order through or refund you. If it turns out the User ID was entered wrongly, the coins cannot be recovered — they went to the account that was entered. Which is why the ID is worth copying rather than typing.$a$),
        (7, 'uz', $q$Agar tangalar kelmasa nima qilish kerak?$q$,
            $a$Avval oʻyinga qayta kiring — balans kirishda yangilanadi. Toʻlovdan keyin yarim soat oʻtib ham tangalar boʻlmasa, buyurtma raqami bilan qoʻllab-quvvatlashga yozing: biz taʼminotchidagi holatni koʻramiz va buyurtmani oxiriga yetkazamiz yoki pulni qaytaramiz. Agar User ID xato kiritilgani aniqlansa, tangalarni qaytarib boʻlmaydi — ular kiritilgan hisobga ketgan. Shuning uchun ID ni termay, nusxalash maʼqul.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
