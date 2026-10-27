-- scripts/seed/2026-10-27_standoff2_by_id_seo.sql
--
-- Copy for /store/standoff-2-id: Standoff 2 Gold by player id. Run AFTER
-- 2026-10-27_standoff2_split.sql, which creates the brand.
--
-- The promo-code page (/store/standoff-2, standoff2_seo.sql) keeps «промокод»,
-- «код на голду»; this one takes «пополнение по ID» — the split its header
-- planned for. (First applied to `standoff-2` itself the same morning, before
-- the two were split.)
-- Still absent on purpose: any promise that the game endorses the purchase —
-- Standoff 2's own support says buying currency outside the game is against its
-- Code of Conduct.
--
-- Prices in the «сколько стоит» answer are a guide at 9 % over the store price
-- on 2026-10-27, USD→UZS 12 000. Idempotent.
--
-- Apply on prod (operator psql):
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     psql -v ON_ERROR_STOP=1 -U yupay_app -d yupay < scripts/seed/2026-10-27_standoff2_by_id_seo.sql

BEGIN;

UPDATE brand_translations bt SET
    highlights = v.highlights::json,
    short_description = v.short_description,
    description = v.description,
    instructions = v.instructions,
    seo_title = v.seo_title,
    seo_description = v.seo_description
FROM brands b, (VALUES
  ('ru',
   $c$["Оплата в сумах","Только ID игрока","Без пароля"]$c$,
   $c$Пополнение Gold в Standoff 2 по ID игрока. Оплата в сумах через Click, Payme или Uzum.$c$,
   $c$Gold — премиальная валюта Standoff 2: за неё покупают скины оружия и ножей на рынке и открывают кейсы.

Для пополнения нужен только ID игрока. Логин, пароль и коды подтверждения не нужны.

Оплата в сумах картой Uzcard или Humo через Click, Payme или Uzum. Итоговая сумма видна до оплаты.$c$,
   $c$1. Откройте профиль в Standoff 2 и скопируйте ID игрока.
2. Выберите пакет Gold и вставьте ID.
3. Оплатите заказ.
4. Gold придёт на аккаунт с этим ID. Статус заказа — в «Мои заказы».

⚠️ Проверьте ID перед оплатой: Gold зачисляется на указанный аккаунт, перевести его на другой нельзя.$c$,
   'Пополнить Standoff 2 по ID — голда за сумы в Узбекистане',
   'Gold для Standoff 2 по ID игрока: от 100 до 3000 Gold. Оплата в сумах через Click, Payme или Uzum, без пароля от аккаунта.'),
  ('en',
   $c$["Pay in soʻm","Player ID only","No password"]$c$,
   $c$Standoff 2 Gold top-up by player ID. Pay in soʻm with Click, Payme or Uzum.$c$,
   $c$Gold is the premium currency of Standoff 2: it buys weapon and knife skins on the market and opens cases.

All a top-up needs is your player ID. No login, password or confirmation codes.

Pay in soʻm with an Uzcard or Humo card via Click, Payme or Uzum. The total is shown before you pay.$c$,
   $c$1. Open your profile in Standoff 2 and copy your player ID.
2. Pick a Gold pack and paste the ID.
3. Pay for the order.
4. The Gold arrives on the account with that ID. Order status is under “My orders”.

⚠️ Check the ID before paying: Gold is credited to that account and cannot be moved to another.$c$,
   'Standoff 2 top-up by ID — Gold for soʻm in Uzbekistan',
   'Standoff 2 Gold by player ID, from 100 to 3000 Gold. Pay in soʻm with Click, Payme or Uzum. No account password.'),
  ('uz',
   $c$["Soʻmda toʻlov","Faqat oʻyinchi ID","Parolsiz"]$c$,
   $c$Standoff 2 Gold ni oʻyinchi ID orqali toʻldirish. Click, Payme yoki Uzum orqali soʻmda toʻlov.$c$,
   $c$Gold — Standoff 2 ning premium valyutasi: unga bozorda qurol va pichoq skinlari sotib olinadi va keyslar ochiladi.

Toʻldirish uchun faqat oʻyinchi ID kerak. Login, parol va tasdiqlash kodlari kerak emas.

Uzcard yoki Humo kartasi bilan Click, Payme yoki Uzum orqali soʻmda toʻlov. Yakuniy summa toʻlovdan oldin koʻrinadi.$c$,
   $c$1. Standoff 2 da profilni oching va oʻyinchi ID ni nusxalang.
2. Gold paketini tanlang va ID ni kiriting.
3. Buyurtmani toʻlang.
4. Gold shu ID li akkauntga keladi. Buyurtma holati — «Mening buyurtmalarim» boʻlimida.

⚠️ Toʻlovdan oldin ID ni tekshiring: Gold koʻrsatilgan akkauntga tushadi, uni boshqasiga oʻtkazib boʻlmaydi.$c$,
   'Standoff 2 ni ID orqali toʻldirish — Gold soʻmda, Oʻzbekiston',
   'Standoff 2 Gold oʻyinchi ID orqali: 100 dan 3000 Gold gacha. Click, Payme yoki Uzum orqali soʻmda toʻlov, parolsiz.')
) AS v(locale, highlights, short_description, description, instructions, seo_title, seo_description)
WHERE b.slug = 'standoff-2-id' AND bt.brand_id = b.id AND bt.locale = v.locale;

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'standoff-2-id');

WITH so2 AS (
    SELECT id FROM brands WHERE slug = 'standoff-2-id'
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), so2.id, v.sort_order, true
    FROM so2, (VALUES (1), (2), (3), (4), (5), (6)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        (1, 'ru', $q$Что нужно для пополнения?$q$,
            $a$Только ID игрока. Логин, пароль и коды подтверждения мы не спрашиваем.$a$),
        (1, 'en', $q$What do you need for a top-up?$q$,
            $a$Only your player ID. We never ask for a login, password or confirmation code.$a$),
        (1, 'uz', $q$Toʻldirish uchun nima kerak?$q$,
            $a$Faqat oʻyinchi ID. Login, parol va tasdiqlash kodlarini soʻramaymiz.$a$),

        (2, 'ru', $q$Где найти ID игрока?$q$,
            $a$В профиле игрока в Standoff 2. Скопируйте ID целиком — это только цифры.$a$),
        (2, 'en', $q$Where do I find my player ID?$q$,
            $a$In your player profile in Standoff 2. Copy the whole ID — it is digits only.$a$),
        (2, 'uz', $q$Oʻyinchi ID qayerda?$q$,
            $a$Standoff 2 dagi oʻyinchi profilida. ID ni toʻliq nusxalang — u faqat raqamlardan iborat.$a$),

        (3, 'ru', $q$Сколько стоит голда в Standoff 2?$q$,
            $a$Точная цена видна до оплаты и зависит от курса. Ориентир: 100 Gold ≈ 19 000 сум, 500 Gold ≈ 81 000 сум, 1000 Gold ≈ 146 000 сум, 3000 Gold ≈ 325 000 сум.$a$),
        (3, 'en', $q$How much does Standoff 2 Gold cost?$q$,
            $a$The exact price is shown before payment and depends on the exchange rate. As a guide: 100 Gold ≈ 19,000 soʻm, 500 Gold ≈ 81,000 soʻm, 1,000 Gold ≈ 146,000 soʻm, 3,000 Gold ≈ 325,000 soʻm.$a$),
        (3, 'uz', $q$Standoff 2 Gold qancha turadi?$q$,
            $a$Aniq narx toʻlovdan oldin koʻrinadi va kursga bogʻliq. Taxminan: 100 Gold ≈ 19 000 soʻm, 500 Gold ≈ 81 000 soʻm, 1000 Gold ≈ 146 000 soʻm, 3000 Gold ≈ 325 000 soʻm.$a$),

        (4, 'ru', $q$Что делать, если я ошибся в ID?$q$,
            $a$Сразу напишите в поддержку с номером заказа. Пока Gold не зачислен, ID можно исправить. После зачисления перевести Gold на другой аккаунт нельзя.$a$),
        (4, 'en', $q$What if I entered the wrong ID?$q$,
            $a$Message support with the order number right away. Until the Gold is credited, the ID can be corrected. Once credited, it cannot be moved to another account.$a$),
        (4, 'uz', $q$ID ni xato kiritsam nima qilaman?$q$,
            $a$Darhol buyurtma raqami bilan qoʻllab-quvvatlashga yozing. Gold tushmaguncha ID ni tuzatish mumkin. Tushgandan keyin uni boshqa akkauntga oʻtkazib boʻlmaydi.$a$),

        (5, 'ru', $q$Что такое Gold?$q$,
            $a$Премиальная валюта Standoff 2. За неё покупают скины оружия и ножей на рынке у других игроков и открывают кейсы.$a$),
        (5, 'en', $q$What is Gold?$q$,
            $a$The premium currency of Standoff 2. It buys weapon and knife skins from other players on the market and opens cases.$a$),
        (5, 'uz', $q$Gold nima?$q$,
            $a$Standoff 2 ning premium valyutasi. Unga bozorda boshqa oʻyinchilardan qurol va pichoq skinlari sotib olinadi va keyslar ochiladi.$a$),

        (6, 'ru', $q$Как оплатить в сумах?$q$,
            $a$Картой Uzcard или Humo через Click, Payme или Uzum. Сумма в сумах видна до оплаты, комиссии сверху нет.$a$),
        (6, 'en', $q$How do I pay in soʻm?$q$,
            $a$With an Uzcard or Humo card via Click, Payme or Uzum. The total in soʻm is shown before you pay, with no extra fee.$a$),
        (6, 'uz', $q$Soʻmda qanday toʻlayman?$q$,
            $a$Uzcard yoki Humo kartasi bilan Click, Payme yoki Uzum orqali. Soʻmdagi summa toʻlovdan oldin koʻrinadi, ustiga komissiya yoʻq.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
