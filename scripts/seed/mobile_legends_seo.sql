-- scripts/seed/mobile_legends_seo.sql
--
-- SEO content pack for the `mobile-legends` brand: highlights + short/long
-- descriptions + instructions on `brand_translations`, and 8 FAQ entries with
-- ru/en/uz answers.
--
-- Content-managed, NOT a fixture and NOT an Alembic data migration. Applied to
-- prod by an operator (psql / `!`), gated by the standing deploy rule. Depends
-- on scripts/seed/2026-08-09_mobile_legends_import.py having created the brand.
--
-- Idempotent: brand_translations rows are UPDATEd in place; FAQs are rebuilt via
-- delete-then-insert. Wrapped in a single transaction so a half-run cannot leave
-- partial state. Re-running yields identical final content (FAQ row ids are
-- regenerated each run, which is fine — nothing references them).
--
-- Strings are dollar-quoted ($c$…$c$ / $q$…$q$ / $a$…$a$) so the apostrophe-heavy
-- Uzbek copy needs no escaping.
--
-- The region question leads the FAQ on purpose. Every other question here costs
-- a customer a minute of confusion; this one costs them an order that cannot be
-- delivered, because a Mobile Legends account's region is fixed when it is
-- created and Moonton gives players no way to move it.
--
-- Apply on prod (operator psql):
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     psql -U yupay_app -d yupay -f - < scripts/seed/mobile_legends_seo.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Brand translations (highlights, short_description, description, instructions)
-- ---------------------------------------------------------------------------

UPDATE brand_translations SET
    highlights = $c$["Оплата в сумах","По ID и серверу","Проверка ника","Без пароля"]$c$::json,
    short_description = $c$Пополнение Mobile Legends — алмазы по ID игрока и ID сервера, оплата в сумах, без пароля.$c$,
    description = $c$Mobile Legends: Bang Bang (MLBB) — мобильная MOBA от Moonton, где команды 5 на 5 сражаются на трёх линиях. Алмазы служат внутриигровой валютой: за них открывают героев и скины, покупают Starlight-подписку, боевой пропуск сезона и наборы событий.

YuPay пополняет аккаунт по публичному игровому ID и ID сервера — пароль и вход в аккаунт не нужны. Перед оплатой мы проверяем связку ID и сервера и показываем ник, который к ней привязан, чтобы алмазы не ушли чужому игроку. Оплатить можно в сумах картами Uzcard и Humo через Click, Payme или Uzum; курс виден до оплаты, а алмазы зачисляются автоматически после подтверждения платежа.

Важно: у Mobile Legends есть отдельный российский регион и глобальный. Регион задаётся при создании аккаунта и не меняется, поэтому пополнения между регионами не переходят — выберите на витрине тот продукт, который соответствует вашему аккаунту.$c$,
    instructions = $c$Как пополнить Mobile Legends:

1. Выберите продукт под свой аккаунт: «Алмазы — глобальный аккаунт» (Узбекистан и большинство стран СНГ) или «Алмазы — российский аккаунт» (если вы играете в российской версии игры).
2. Введите ID игрока и ID сервера — оба числа есть в профиле, пароль не нужен.
3. Дождитесь проверки: мы покажем ник, привязанный к этой связке. Если ник не находится — скорее всего, выбран не тот регион, попробуйте второй продукт.
4. Выберите номинал и способ оплаты: Click, Payme или Uzum. Курс и итог показываются до оплаты.
5. Оплатите — алмазы зачисляются на аккаунт автоматически после подтверждения платежа.

Где найти ID: откройте Mobile Legends и нажмите на аватар в левом верхнем углу лобби. В профиле под ником указано «ID: 123456789 (1234)» — первое число это ID игрока, число в скобках это ID сервера.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'mobile-legends') AND locale = 'ru';

UPDATE brand_translations SET
    highlights = $c$["Pay in UZS","By ID and server","Nickname check","No password"]$c$::json,
    short_description = $c$Top up Mobile Legends — diamonds by player ID and server ID, pay in sum, no password.$c$,
    description = $c$Mobile Legends: Bang Bang (MLBB) is a mobile MOBA by Moonton where teams of five fight across three lanes. Diamonds are the in-game currency: they unlock heroes and skins, and buy the Starlight membership, the seasonal battle pass and event bundles.

YuPay tops up your account by its public player ID and server ID — no password and no account login needed. Before you pay we verify the ID and server pair and show you the nickname attached to it, so diamonds never land on a stranger's account. You can pay in Uzbek sum with Uzcard and Humo cards via Click, Payme or Uzum; the rate is shown before you pay, and diamonds are credited automatically once your payment is confirmed.

One thing to know: Mobile Legends has a separate Russian region alongside the global one. The region is fixed when an account is created and cannot be changed, so top-ups do not cross between them — pick the product on this page that matches your account.$c$,
    instructions = $c$How to top up Mobile Legends:

1. Pick the product that matches your account: “Diamonds — global account” (Uzbekistan and most CIS countries) or “Diamonds — Russian account” (if you play the Russian version of the game).
2. Enter your player ID and server ID — both numbers are in your profile, and no password is needed.
3. Wait for the check: we show the nickname attached to that pair. If no nickname is found, the region is probably wrong — try the other product.
4. Choose an amount and a payment method: Click, Payme or Uzum. The rate and total are shown before you pay.
5. Pay — diamonds are credited to your account automatically once your payment is confirmed.

Where to find your ID: open Mobile Legends and tap your avatar in the top-left corner of the lobby. Under your nickname the profile shows “ID: 123456789 (1234)” — the first number is your player ID, the number in brackets is your server ID.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'mobile-legends') AND locale = 'en';

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","ID va server orqali","Nik tekshiruvi","Parolsiz"]$c$::json,
    short_description = $c$Mobile Legends toʻldirish — olmoslar oʻyinchi ID va server ID orqali, soʻmda toʻlov, parolsiz.$c$,
    description = $c$Mobile Legends: Bang Bang (MLBB) — Moonton kompaniyasining mobil MOBA oʻyini, unda jamoalar uch yoʻlakda 5 ga 5 jang qiladi. Olmoslar oʻyin ichidagi valyuta hisoblanadi: ularga qahramonlar va skinlar ochiladi, Starlight obunasi, mavsumiy jangovar pass va tadbir toʻplamlari sotib olinadi.

YuPay hisobingizni ochiq oʻyin ID va server ID orqali toʻldiradi — parol va akkauntga kirish talab qilinmaydi. Toʻlovdan oldin biz ID va server juftligini tekshirib, unga bogʻlangan nikni koʻrsatamiz, shunda olmoslar begona oʻyinchiga tushmaydi. Toʻlovni soʻmda Uzcard va Humo kartalari bilan Click, Payme yoki Uzum orqali amalga oshirishingiz mumkin; kurs toʻlovdan oldin koʻrinadi, olmoslar esa toʻlov tasdiqlangach avtomatik tushadi.

Muhim: Mobile Legends oʻyinida global regiondan tashqari alohida Rossiya regioni ham bor. Region akkaunt yaratilganda belgilanadi va oʻzgarmaydi, shuning uchun toʻldirishlar regionlar oʻrtasida oʻtmaydi — sahifada akkauntingizga mos mahsulotni tanlang.$c$,
    instructions = $c$Mobile Legends hisobini qanday toʻldirish:

1. Akkauntingizga mos mahsulotni tanlang: «Olmoslar — global akkaunt» (Oʻzbekiston va koʻpchilik MDH davlatlari) yoki «Olmoslar — Rossiya akkaunti» (agar oʻyinning rus versiyasida oʻynasangiz).
2. Oʻyinchi ID va server ID raqamlarini kiriting — ikkalasi ham profilda, parol kerak emas.
3. Tekshiruvni kuting: shu juftlikka bogʻlangan nikni koʻrsatamiz. Agar nik topilmasa — ehtimol region notoʻgʻri tanlangan, ikkinchi mahsulotni sinab koʻring.
4. Nominal va toʻlov usulini tanlang: Click, Payme yoki Uzum. Kurs va yakuniy summa toʻlovdan oldin koʻrsatiladi.
5. Toʻlang — olmoslar toʻlov tasdiqlangach hisobingizga avtomatik tushadi.

ID raqamini qayerdan topish mumkin: Mobile Legends ni oching va lobbi chap yuqori burchagidagi avatarni bosing. Profilda taxallus ostida «ID: 123456789 (1234)» koʻrsatiladi — birinchi raqam oʻyinchi ID, qavs ichidagi raqam server ID.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'mobile-legends') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- 2. Product names per locale
--
-- `import_game` writes the operator's single product name into all three locale
-- rows, so an English or Uzbek visitor was reading the Russian name. For most
-- brands that is cosmetic; here the product name is the only place the storefront
-- states which account the top-up is for, so leaving it untranslated hands a
-- non-Russian-speaking customer the one choice that cannot be undone.
--
-- The short_description is not rendered on the brand page today. It is filled in
-- anyway: it is the natural home for this line the moment the product list shows
-- a subtitle, and it costs nothing to keep the three locales in step now.
-- ---------------------------------------------------------------------------

UPDATE product_translations SET
    name = $c$Алмазы — глобальный аккаунт$c$,
    short_description = $c$Для аккаунтов Узбекистана и СНГ на глобальном регионе.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'mlbb-diamonds') AND locale = 'ru';
UPDATE product_translations SET
    name = $c$Diamonds — global account$c$,
    short_description = $c$For Uzbekistan and CIS accounts on the global region.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'mlbb-diamonds') AND locale = 'en';
UPDATE product_translations SET
    name = $c$Olmoslar — global akkaunt$c$,
    short_description = $c$Oʻzbekiston va MDH akkauntlari uchun, global region.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'mlbb-diamonds') AND locale = 'uz';

UPDATE product_translations SET
    name = $c$Алмазы — российский аккаунт$c$,
    short_description = $c$Для тех, кто играет в российской версии Mobile Legends.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'mlbb-diamonds-ru') AND locale = 'ru';
UPDATE product_translations SET
    name = $c$Diamonds — Russian account$c$,
    short_description = $c$For players on the Russian version of Mobile Legends.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'mlbb-diamonds-ru') AND locale = 'en';
UPDATE product_translations SET
    name = $c$Olmoslar — Rossiya akkaunti$c$,
    short_description = $c$Mobile Legends rus versiyasida oʻynaydiganlar uchun.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'mlbb-diamonds-ru') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- 3. FAQs (rebuilt each run: delete cascades to brand_faq_translations)
-- ---------------------------------------------------------------------------

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'mobile-legends');

WITH mlbb AS (
    SELECT id FROM brands WHERE slug = 'mobile-legends'
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), mlbb.id, v.sort_order, true
    FROM mlbb, (VALUES (1), (2), (3), (4), (5), (6), (7), (8)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. Глобальный или российский — главный вопрос страницы.
        (1, 'ru', $q$Что выбрать — глобальный или российский аккаунт?$q$,
            $a$Если вы играете в Узбекистане или другой стране СНГ и скачали игру в обычном Google Play или App Store, у вас глобальный аккаунт — выбирайте «Алмазы — глобальный аккаунт». Российский регион у Mobile Legends отдельный: он нужен тем, кто играет в российской версии игры. Регион задаётся при создании аккаунта и не меняется, поэтому пополнения между регионами не переходят. Самый надёжный способ проверить — ввести ID игрока и ID сервера: мы покажем ник до оплаты, и если ник не находится, значит нужен второй продукт.$a$),
        (1, 'en', $q$Global or Russian account — which do I pick?$q$,
            $a$If you play in Uzbekistan or another CIS country and installed the game from the ordinary Google Play or App Store, your account is global — choose “Diamonds — global account”. Mobile Legends runs a separate Russian region for players on the Russian version of the game. The region is fixed when the account is created and cannot be changed, so top-ups do not cross between regions. The surest way to check is to enter your player ID and server ID: we show the nickname before payment, and if no nickname is found you need the other product.$a$),
        (1, 'uz', $q$Global yoki Rossiya akkaunti — qaysi birini tanlash kerak?$q$,
            $a$Agar Oʻzbekistonda yoki boshqa MDH davlatida oʻynasangiz va oʻyinni oddiy Google Play yoki App Store'dan yuklagan boʻlsangiz, akkauntingiz global — «Olmoslar — global akkaunt» ni tanlang. Mobile Legends oʻyinining rus versiyasida oʻynaydiganlar uchun alohida Rossiya regioni bor. Region akkaunt yaratilganda belgilanadi va oʻzgarmaydi, shuning uchun toʻldirishlar regionlar oʻrtasida oʻtmaydi. Eng ishonchli usul — oʻyinchi ID va server ID kiritish: nikni toʻlovdan oldin koʻrsatamiz, agar nik topilmasa, ikkinchi mahsulot kerak.$a$),

        -- 2. Где взять ID и сервер.
        (2, 'ru', $q$Как узнать ID игрока и ID сервера в Mobile Legends?$q$,
            $a$Откройте игру и нажмите на аватар в левом верхнем углу лобби. В профиле под ником указано «ID: 123456789 (1234)»: первое число — ID игрока, число в скобках — ID сервера (Zone ID), обычно четыре цифры. Для пополнения нужны оба числа: без ID сервера алмазы не найдут аккаунт.$a$),
        (2, 'en', $q$How do I find my player ID and server ID in Mobile Legends?$q$,
            $a$Open the game and tap your avatar in the top-left corner of the lobby. Under your nickname the profile shows “ID: 123456789 (1234)”: the first number is the player ID and the number in brackets is the server ID (Zone ID), usually four digits. A top-up needs both — without the server ID the diamonds cannot find the account.$a$),
        (2, 'uz', $q$Mobile Legends'da oʻyinchi ID va server ID ni qanday bilish mumkin?$q$,
            $a$Oʻyinni oching va lobbi chap yuqori burchagidagi avatarni bosing. Profilda taxallus ostida «ID: 123456789 (1234)» koʻrsatiladi: birinchi raqam — oʻyinchi ID, qavs ichidagi raqam — server ID (Zone ID), odatda toʻrt xonali. Toʻldirish uchun ikkalasi ham kerak: server ID siz olmoslar hisobni topa olmaydi.$a$),

        -- 3. Ошибка в регионе — что будет.
        (3, 'ru', $q$Что будет, если выбрать не тот регион?$q$,
            $a$До оплаты — ничего: проверка просто не найдёт ник по вашей связке ID и сервера, и вы сможете переключиться на второй продукт. Именно поэтому мы показываем ник перед оплатой. Если ник не находится ни в одном из продуктов, проверьте, что ID и сервер скопированы полностью и без пробелов, и напишите в поддержку — разберёмся до того, как вы заплатите.$a$),
        (3, 'en', $q$What happens if I pick the wrong region?$q$,
            $a$Before payment, nothing: the check simply will not find a nickname for your ID and server pair, and you can switch to the other product. That is exactly why we show the nickname before you pay. If neither product finds a nickname, check that the ID and server were copied in full with no spaces, and message support — we will sort it out before you pay anything.$a$),
        (3, 'uz', $q$Notoʻgʻri region tanlansa nima boʻladi?$q$,
            $a$Toʻlovdan oldin — hech nima: tekshiruv sizning ID va server juftligingiz boʻyicha nikni topa olmaydi va siz ikkinchi mahsulotga oʻtishingiz mumkin. Aynan shuning uchun nikni toʻlovdan oldin koʻrsatamiz. Agar ikkala mahsulotda ham nik topilmasa, ID va server toʻliq, boʻshliqsiz nusxalanganini tekshiring va qoʻllab-quvvatlashga yozing — toʻlovdan oldin hal qilamiz.$a$),

        -- 4. Что такое алмазы.
        (4, 'ru', $q$Что такое алмазы Mobile Legends и что на них купить?$q$,
            $a$Алмазы — внутриигровая валюта Mobile Legends. За них открывают героев и скины, покупают подписку Starlight, боевой пропуск сезона, наборы событий и предметы в магазине. Weekly Diamond Pass выгоднее разовой покупки: он начисляет алмазы порциями каждый день в течение недели, поэтому заходить в игру нужно ежедневно.$a$),
        (4, 'en', $q$What are Mobile Legends diamonds and what can I buy with them?$q$,
            $a$Diamonds are the in-game currency of Mobile Legends. They unlock heroes and skins, and buy the Starlight membership, the seasonal battle pass, event bundles and shop items. The Weekly Diamond Pass is better value than a one-off purchase: it pays out diamonds in daily instalments across the week, so you need to log in each day.$a$),
        (4, 'uz', $q$Mobile Legends olmoslari nima va ularga nima sotib olish mumkin?$q$,
            $a$Olmoslar — Mobile Legends oʻyinining ichki valyutasi. Ularga qahramonlar va skinlar ochiladi, Starlight obunasi, mavsumiy jangovar pass, tadbir toʻplamlari va doʻkon buyumlari sotib olinadi. Weekly Diamond Pass bir martalik xariddan foydaliroq: u hafta davomida har kuni olmoslarni boʻlib beradi, shuning uchun oʻyinga har kuni kirish kerak.$a$),

        -- 5. Пароль.
        (5, 'ru', $q$Нужен ли пароль от аккаунта?$q$,
            $a$Нет. Пополнение проходит по публичному ID игрока и ID сервера — пароль и вход в аккаунт не требуются, и мы их не запрашиваем.$a$),
        (5, 'en', $q$Do you need my account password?$q$,
            $a$No. Top-ups run on your public player ID and server ID — no password and no account login are required, and we never ask for them.$a$),
        (5, 'uz', $q$Akkaunt paroli kerakmi?$q$,
            $a$Yoʻq. Toʻldirish ochiq oʻyinchi ID va server ID orqali amalga oshadi — parol va akkauntga kirish talab qilinmaydi, biz ularni soʻramaymiz.$a$),

        -- 6. Оплата в сумах.
        (6, 'ru', $q$Можно ли платить в сумах?$q$,
            $a$Да. Оплата в узбекских сумах доступна картами Uzcard и Humo через Click, Payme и Uzum. Курс и итоговая сумма показываются до оплаты.$a$),
        (6, 'en', $q$Can I pay in Uzbek sum?$q$,
            $a$Yes. You can pay in Uzbek sum with Uzcard and Humo cards via Click, Payme and Uzum. The rate and final total are shown before you pay.$a$),
        (6, 'uz', $q$Soʻmda toʻlash mumkinmi?$q$,
            $a$Ha. Oʻzbek soʻmida Uzcard va Humo kartalari orqali Click, Payme va Uzum bilan toʻlash mumkin. Kurs va yakuniy summa toʻlovdan oldin koʻrsatiladi.$a$),

        -- 7. Скорость зачисления.
        (7, 'ru', $q$За сколько зачисляются алмазы?$q$,
            $a$Алмазы зачисляются на аккаунт автоматически после подтверждения оплаты, обычно в течение нескольких минут. Достаточно правильно указать ID игрока и ID сервера.$a$),
        (7, 'en', $q$How fast are diamonds credited?$q$,
            $a$Diamonds are credited to your account automatically once your payment is confirmed, usually within a few minutes. Just make sure your player ID and server ID are correct.$a$),
        (7, 'uz', $q$Olmoslar qancha vaqtda tushadi?$q$,
            $a$Olmoslar toʻlov tasdiqlangach hisobingizga avtomatik tushadi, odatda bir necha daqiqada. Faqat oʻyinchi ID va server ID ni toʻgʻri kiriting.$a$),

        -- 8. Официальность.
        (8, 'ru', $q$Это официальный сайт Mobile Legends?$q$,
            $a$Нет. YuPay — независимый сервис пополнения и не связан с Moonton, издателем Mobile Legends. Мы покупаем и перепродаём пополнения по прозрачному курсу, который виден до оплаты.$a$),
        (8, 'en', $q$Is this the official Mobile Legends website?$q$,
            $a$No. YuPay is an independent top-up service and is not affiliated with Moonton, the publisher of Mobile Legends. We buy and resell top-ups at a transparent rate that is shown before you pay.$a$),
        (8, 'uz', $q$Bu Mobile Legends rasmiy saytimi?$q$,
            $a$Yoʻq. YuPay — mustaqil toʻldirish xizmati va Mobile Legends noshiri Moonton bilan bogʻliq emas. Biz toʻldirishlarni shaffof kurs boʻyicha sotib olib, qayta sotamiz; kurs toʻlovdan oldin koʻrinadi.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
