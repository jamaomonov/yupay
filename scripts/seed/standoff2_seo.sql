-- scripts/seed/standoff2_seo.sql
--
-- SEO content pack for the `standoff-2` brand: highlights + short/long
-- descriptions + instructions on `brand_translations`, and 7 FAQ entries with
-- ru/en/uz answers.
--
-- Run AFTER scripts/seed/2026-08-17_standoff2_import.py, which creates the brand.
--
-- Content-managed, NOT a fixture and NOT an Alembic data migration. Applied to
-- prod by an operator (psql / `!`), gated by the standing deploy rule.
--
-- Idempotent: brand_translations rows are UPDATEd in place; FAQs are rebuilt via
-- delete-then-insert, inside one transaction.
--
-- ---------------------------------------------------------------------------
-- This page is about PROMO CODES, and says so in every locale.
--
-- A Standoff 2 top-up **by player id** is planned as a separate brand. The two
-- are different purchases — one the buyer redeems themselves, one we credit —
-- and pointing both at the same keywords would have them competing for the same
-- results while answering different questions. So the split is kept explicit:
--
--   this brand   — «промокод», «код на голду», «gift code», «promokod»,
--                  «активировать промокод Standoff 2»
--   the by-id one — «пополнить Standoff 2 по ID», «пополнение голды по ID»,
--                  «to'ldirish ID orqali»
--
-- Nothing below claims we credit an account, and nothing below uses the
-- «пополнение по ID» phrasing. Keep it that way when the second brand lands.
-- ---------------------------------------------------------------------------
--
-- One claim is deliberately absent: nothing here promises the purchase is
-- endorsed by Axlebolt or that an account cannot be penalised. Standoff 2's own
-- support article "Can I purchase Gold or skins outside of the game?" states
-- that buying currency outside in-game methods is against its Code of Conduct,
-- and it does not carve out promo codes. What the copy does say is factual and
-- checkable: this is a code the buyer redeems in the official store, and no
-- account credentials change hands.
--
-- Strings are dollar-quoted ($c$…$c$ / $q$…$q$ / $a$…$a$) so the apostrophe-heavy
-- Uzbek copy needs no escaping.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Brand translations
-- ---------------------------------------------------------------------------

UPDATE brand_translations SET
    highlights = $c$["Оплата в сумах","Код на почту","Без входа в аккаунт","Активируете сами"]$c$::json,
    short_description = $c$Купить промокод на Gold в Standoff 2 — код приходит на почту, активируете сами, оплата в сумах через Click, Payme или Uzum.$c$,
    description = $c$Промокод Standoff 2 на Gold — это цифровой код, который вы активируете сами и получаете золото на свой игровой аккаунт. Gold — премиальная валюта Standoff 2 от Axlebolt: за неё покупают скины оружия и ножей на внутриигровом рынке у других игроков и открывают премиальные кейсы.

Мы продаём именно код, а не «пополнение с доступом к аккаунту». Логин, пароль и код подтверждения не нужны и не запрашиваются — вы вводите промокод сами в официальном магазине Standoff 2 или в игре. Аккаунт при покупке никому не передаётся, и это главное отличие от продавцов, которые просят вход.

Оплатить можно в сумах картой Uzcard или Humo через Click, Payme или Uzum — итоговая сумма видна до оплаты. Код приходит на почту, указанную в заказе, сразу после подтверждения платежа.

Коды — товар штучный: их количество у поставщика ограничено. Если номинал закончился, кнопка покупки становится неактивной и на карточке написано, что позиции нет в наличии, — так вы не заплатите за код, которого нет.$c$,
    instructions = $c$Как активировать промокод Standoff 2:

Через официальный сайт Standoff 2:
1. Перейдите в официальный магазин Standoff 2.
2. Нажмите Sign In и введите ID своего игрового аккаунта.
3. Выберите нужный аккаунт из списка.
4. Перейдите в раздел Promo Code.
5. Введите полученный код и нажмите Apply.

Прямо в игре:
Inventory → Shop → Promocode → введите код → Apply.

⚠️ Важно: на iPhone и iPad активировать промокод через игру нельзя — воспользуйтесь официальным магазином Standoff 2.

После активации Gold зачисляется на выбранный игровой аккаунт. Продукт доступен для всех тарифных планов.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'standoff-2') AND locale = 'ru';

UPDATE brand_translations SET
    highlights = $c$["Pay in UZS","Code by email","No account login","You redeem it"]$c$::json,
    short_description = $c$Buy a Standoff 2 Gold promo code — delivered by email, redeemed by you, paid in sum via Click, Payme or Uzum.$c$,
    description = $c$A Standoff 2 Gold promo code is a digital code you redeem yourself to get Gold on your own game account. Gold is the premium currency of Standoff 2 by Axlebolt: it buys weapon and knife skins from other players on the in-game marketplace and opens premium cases.

What we sell is the code itself, not a "top-up with account access". No login, no password, no confirmation code is needed or asked for — you enter the promo code yourself, in the official Standoff 2 store or in the game. Your account never changes hands, which is the whole difference from sellers who want to sign in.

You pay in sum with an Uzcard or Humo card via Click, Payme or Uzum, and the total is shown before you pay. The code arrives at the email on your order as soon as the payment is confirmed.

Codes are physical stock: the supplier holds a limited number. When a denomination runs out its buy button goes inactive and the card says it is unavailable, so you never pay for a code that does not exist.$c$,
    instructions = $c$How to redeem a Standoff 2 promo code:

Through the official Standoff 2 website:
1. Go to the official Standoff 2 store.
2. Click Sign In and enter your game account ID.
3. Pick the account you want from the list.
4. Open the Promo Code section.
5. Enter the code you received and press Apply.

Directly in the game:
Inventory → Shop → Promocode → enter the code → Apply.

⚠️ Important: on iPhone and iPad the promo code cannot be redeemed through the game — use the official Standoff 2 store instead.

Once redeemed, the Gold is credited to the account you selected. The product works on every tariff plan.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'standoff-2') AND locale = 'en';

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","Kod pochtaga","Akkauntsiz","Oʻzingiz faollashtirasiz"]$c$::json,
    short_description = $c$Standoff 2 Gold promokodini sotib oling — kod pochtaga keladi, oʻzingiz faollashtirasiz, Click, Payme yoki Uzum bilan soʻmda toʻlov.$c$,
    description = $c$Standoff 2 Gold promokodi — bu siz oʻzingiz faollashtiradigan raqamli kod, natijada oltin oʻz oʻyin akkauntingizga tushadi. Gold — Axlebolt kompaniyasining Standoff 2 oʻyinidagi premium valyutasi: unga oʻyin ichidagi bozorda boshqa oʻyinchilardan qurol va pichoq skinlari sotib olinadi hamda premium keyslar ochiladi.

Biz aynan kodni sotamiz, «akkauntga kirish orqali toʻldirish»ni emas. Login, parol va tasdiqlash kodi kerak emas va soʻralmaydi — promokodni Standoff 2 rasmiy magazinida yoki oʻyinda oʻzingiz kiritasiz. Xarid vaqtida akkaunt hech kimga berilmaydi va bu kirishni soʻraydigan sotuvchilardan asosiy farqdir.

Toʻlovni Uzcard yoki Humo kartasi bilan Click, Payme yoki Uzum orqali soʻmda amalga oshirasiz — yakuniy summa toʻlovdan oldin koʻrinadi. Kod toʻlov tasdiqlangach buyurtmadagi pochtaga keladi.

Kodlar — donali tovar: taʼminotchidagi soni cheklangan. Agar nominal tugasa, sotib olish tugmasi faolsiz boʻladi va kartochkada mavjud emasligi yoziladi — shunda siz yoʻq kod uchun toʻlamaysiz.$c$,
    instructions = $c$Standoff 2 promokodini qanday faollashtirish kerak:

Rasmiy Standoff 2 sayti orqali:
1. Standoff 2 rasmiy magaziniga oʻting.
2. Sign In tugmasini bosing va oʻyin akkauntingiz ID sini kiriting.
3. Roʻyxatdan kerakli akkauntni tanlang.
4. Promo Code boʻlimiga oʻting.
5. Olingan kodni kiriting va Apply tugmasini bosing.

Toʻgʻridan-toʻgʻri oʻyinda:
Inventory → Shop → Promocode → kodni kiriting → Apply.

⚠️ Muhim: iPhone va iPad'da promokodni oʻyin orqali faollashtirib boʻlmaydi — Standoff 2 rasmiy magazinidan foydalaning.

Faollashtirilgandan soʻng Gold tanlangan oʻyin akkauntiga tushadi. Mahsulot barcha tarif rejalari uchun mavjud.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'standoff-2') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- 2. FAQ
-- ---------------------------------------------------------------------------

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'standoff-2');

WITH so2 AS (
    SELECT id FROM brands WHERE slug = 'standoff-2'
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), so2.id, v.sort_order, true
    FROM so2, (VALUES (1), (2), (3), (4), (5), (6), (7)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. Что покупаю — снимает главную путаницу «код или пополнение»
        (1, 'ru', $q$Что именно я покупаю — код или пополнение аккаунта?$q$,
            $a$Код. Вы получаете промокод на почту и активируете его сами — в официальном магазине Standoff 2 или в игре через Inventory → Shop → Promocode. Мы не заходим в ваш аккаунт и не зачисляем золото за вас.$a$),
        (1, 'en', $q$What am I actually buying — a code or an account top-up?$q$,
            $a$A code. You get a promo code by email and redeem it yourself, either in the official Standoff 2 store or in the game via Inventory → Shop → Promocode. We never sign in to your account and never credit the Gold for you.$a$),
        (1, 'uz', $q$Men aniq nimani sotib olaman — kodmi yoki akkaunt toʻldirishmi?$q$,
            $a$Kod. Siz promokodni pochtaga olasiz va uni oʻzingiz faollashtirasiz — Standoff 2 rasmiy magazinida yoki oʻyinda Inventory → Shop → Promocode orqali. Biz akkauntingizga kirmaymiz va oltinni siz uchun oʻtkazmaymiz.$a$),

        -- 2. Данные аккаунта — главный страх
        (2, 'ru', $q$Нужен ли логин или пароль от аккаунта?$q$,
            $a$Нет. Для покупки нужна только почта, куда придёт код. Логин, пароль и код подтверждения мы не спрашиваем никогда — активацию вы делаете сами, ID аккаунта вводите тоже вы и только на официальном сайте Standoff 2.$a$),
        (2, 'en', $q$Do you need my login or password?$q$,
            $a$No. All the purchase needs is an email address for the code. We never ask for a login, a password or a confirmation code — you redeem it yourself, and you enter your account ID only on the official Standoff 2 site.$a$),
        (2, 'uz', $q$Akkaunt logini yoki paroli kerakmi?$q$,
            $a$Yoʻq. Xarid uchun faqat kod keladigan pochta kerak. Login, parol va tasdiqlash kodini biz hech qachon soʻramaymiz — faollashtirishni oʻzingiz qilasiz, akkaunt ID sini ham faqat Standoff 2 rasmiy saytida oʻzingiz kiritasiz.$a$),

        -- 3. Что такое Gold
        (3, 'ru', $q$Что такое Gold и что на него можно купить?$q$,
            $a$Gold — премиальная валюта Standoff 2. За неё покупают скины оружия и ножей на внутриигровом рынке у других игроков и открывают премиальные кейсы. Обычная игровая валюта, которая копится за матчи, на рынке не работает.$a$),
        (3, 'en', $q$What is Gold and what can I buy with it?$q$,
            $a$Gold is the premium currency of Standoff 2. It buys weapon and knife skins from other players on the in-game marketplace and opens premium cases. The ordinary currency you earn from matches does not work on the marketplace.$a$),
        (3, 'uz', $q$Gold nima va unga nima sotib olish mumkin?$q$,
            $a$Gold — Standoff 2 ning premium valyutasi. Unga oʻyin ichidagi bozorda boshqa oʻyinchilardan qurol va pichoq skinlari sotib olinadi hamda premium keyslar ochiladi. Matchlarda yigʻiladigan oddiy valyuta bozorda ishlamaydi.$a$),

        -- 4. iPhone — практическая ловушка из официальной инструкции
        (4, 'ru', $q$Почему промокод не активируется на iPhone?$q$,
            $a$На iPhone и iPad активация промокода внутри игры недоступна — это ограничение самой игры, а не кода. Откройте официальный магазин Standoff 2 в браузере, войдите по ID аккаунта и активируйте код в разделе Promo Code. Тот же код сработает.$a$),
        (4, 'en', $q$Why won't the promo code redeem on my iPhone?$q$,
            $a$On iPhone and iPad, in-game redemption is not available — that is the game's own limitation, not a problem with the code. Open the official Standoff 2 store in a browser, sign in with your account ID and redeem it in the Promo Code section. The same code will work.$a$),
        (4, 'uz', $q$Nega promokod iPhone'da faollashmayapti?$q$,
            $a$iPhone va iPad'da oʻyin ichida faollashtirish mavjud emas — bu kodning emas, oʻyinning oʻz cheklovi. Brauzerda Standoff 2 rasmiy magazinini oching, akkaunt ID si bilan kiring va Promo Code boʻlimida faollashtiring. Xuddi shu kod ishlaydi.$a$),

        -- 5. Наличие — прямой ответ на неактивную кнопку
        (5, 'ru', $q$Почему кнопка покупки неактивна?$q$,
            $a$Значит, этот номинал закончился у поставщика. Коды — штучный товар, и мы не даём оплатить то, чего нет на складе: лучше неактивная кнопка, чем возврат денег через сутки. Запас пополняется, поэтому имеет смысл заглянуть позже или взять другой номинал.$a$),
        (5, 'en', $q$Why is the buy button greyed out?$q$,
            $a$That denomination has run out at the supplier. Codes are physical stock, and we would rather block the button than take your money for something we cannot send: an inactive button beats a refund a day later. Stock is replenished, so check back or pick another denomination.$a$),
        (5, 'uz', $q$Nega sotib olish tugmasi faolsiz?$q$,
            $a$Demak, bu nominal taʼminotchida tugagan. Kodlar — donali tovar, va biz yoʻq narsa uchun toʻlashga ruxsat bermaymiz: bir kundan keyin pul qaytarishdan koʻra faolsiz tugma yaxshiroq. Zaxira toʻldiriladi, shuning uchun keyinroq kiring yoki boshqa nominalni tanlang.$a$),

        -- 6. Оплата — локальный интент
        (6, 'ru', $q$Как оплатить в сумах и когда придёт код?$q$,
            $a$Картой Uzcard или Humo через Click, Payme или Uzum — сумма в сумах показывается до оплаты. Код приходит на почту, указанную в заказе, сразу после подтверждения платежа, и остаётся в разделе «Мои заказы» — если письмо потеряется, код всегда можно посмотреть там.$a$),
        (6, 'en', $q$How do I pay in sum, and when does the code arrive?$q$,
            $a$With an Uzcard or Humo card via Click, Payme or Uzum — the total in sum is shown before you pay. The code goes to the email on your order as soon as the payment is confirmed, and it stays under “My orders”, so a lost email is never a lost code.$a$),
        (6, 'uz', $q$Soʻmda qanday toʻlayman va kod qachon keladi?$q$,
            $a$Uzcard yoki Humo kartasi bilan Click, Payme yoki Uzum orqali — soʻmdagi summa toʻlovdan oldin koʻrsatiladi. Kod toʻlov tasdiqlangach buyurtmadagi pochtaga keladi va “Mening buyurtmalarim” boʻlimida saqlanadi — xat yoʻqolsa ham, kod yoʻqolmaydi.$a$),

        -- 7. Ошибка при активации
        (7, 'ru', $q$Что делать, если код не принимается?$q$,
            $a$Сначала проверьте очевидное: код вводится целиком, вместе с дефисами, без пробелов по краям, и активируется в разделе Promo Code, а не в поле для подарочной карты. Если вы на iPhone — активируйте через официальный сайт. Если и так не выходит, напишите нам из раздела «Мои заказы»: мы видим сам код и заказ и разберёмся с поставщиком.$a$),
        (7, 'en', $q$What if the code is not accepted?$q$,
            $a$Check the obvious first: paste the code in full, hyphens included, with no stray spaces, and redeem it in the Promo Code section rather than a gift-card field. On an iPhone, use the official website. If it still fails, message us from “My orders” — we can see the code and the order and will take it up with the supplier.$a$),
        (7, 'uz', $q$Agar kod qabul qilinmasa, nima qilish kerak?$q$,
            $a$Avval oddiy narsalarni tekshiring: kod toʻliq, defislari bilan, chetlarida boʻshliqsiz kiritiladi va sovgʻa kartasi maydonida emas, Promo Code boʻlimida faollashtiriladi. iPhone'da boʻlsangiz — rasmiy sayt orqali faollashtiring. Shunda ham chiqmasa, “Mening buyurtmalarim” boʻlimidan bizga yozing: biz kodni ham, buyurtmani ham koʻramiz va taʼminotchi bilan hal qilamiz.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
