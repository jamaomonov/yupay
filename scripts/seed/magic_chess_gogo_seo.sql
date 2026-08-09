-- scripts/seed/magic_chess_gogo_seo.sql
--
-- SEO content pack for the `magic-chess-gogo` brand: highlights + short/long
-- descriptions + instructions on `brand_translations`, product names per locale,
-- and 8 FAQ entries with ru/en/uz answers.
--
-- Content-managed, NOT a fixture and NOT an Alembic data migration. Applied to
-- prod by an operator (psql / `!`), gated by the standing deploy rule. Depends
-- on scripts/seed/2026-08-09_magic_chess_gogo_import.py having created the brand.
--
-- Idempotent: brand_translations and product_translations rows are UPDATEd in
-- place; FAQs are rebuilt via delete-then-insert. Wrapped in a single
-- transaction so a half-run cannot leave partial state.
--
-- Strings are dollar-quoted ($c$…$c$ / $q$…$q$ / $a$…$a$) so the apostrophe-heavy
-- Uzbek copy needs no escaping.
--
-- The region question leads the FAQ for the same reason it does on Mobile
-- Legends (ADR-0048): it is the only choice on the page a customer cannot undo.
-- The fourth question is specific to this game — Magic Chess: Go Go lives in the
-- Mobile Legends universe and a player who has both will reach for the wrong ID.
--
-- Apply on prod (operator psql):
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     psql -U yupay_app -d yupay -f - < scripts/seed/magic_chess_gogo_seo.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Brand translations (highlights, short_description, description, instructions)
-- ---------------------------------------------------------------------------

UPDATE brand_translations SET
    highlights = $c$["Оплата в сумах","По ID и серверу","Проверка ника","Без пароля"]$c$::json,
    short_description = $c$Пополнение Magic Chess: Go Go — алмазы по ID игрока и ID сервера, оплата в сумах, без пароля.$c$,
    description = $c$Magic Chess: Go Go (MCGG) — мобильный автобаттлер от Moonton по вселенной Mobile Legends: вы не управляете боем напрямую, а собираете состав и расставляете фигуры, а дальше раунд идёт сам. Алмазы служат внутриигровой валютой: за них открывают облики и скины, покупают наборы событий и сезонные пропуска.

YuPay пополняет аккаунт по публичному ID игрока и ID сервера — пароль и вход в аккаунт не нужны. Перед оплатой мы проверяем связку ID и сервера и показываем привязанный к ней ник, чтобы алмазы не ушли чужому игроку. Оплатить можно в сумах картами Uzcard и Humo через Click, Payme или Uzum; курс виден до оплаты, а алмазы зачисляются автоматически после подтверждения платежа.

Важно: у Magic Chess: Go Go есть отдельный российский регион и глобальный, и пополнения между ними не переходят. Выберите на витрине тот продукт, который соответствует вашему аккаунту.$c$,
    instructions = $c$Как пополнить Magic Chess: Go Go:

1. Выберите продукт под свой аккаунт: «Алмазы — глобальный аккаунт» (Узбекистан и большинство стран СНГ) или «Алмазы — российский аккаунт» (если вы играете в российской версии игры).
2. Введите ID игрока и ID сервера — оба числа есть в профиле, пароль не нужен.
3. Дождитесь проверки: мы покажем ник, привязанный к этой связке. Если ник не находится — скорее всего, выбран не тот регион, попробуйте второй продукт.
4. Выберите номинал и способ оплаты: Click, Payme или Uzum. Курс и итог показываются до оплаты.
5. Оплатите — алмазы зачисляются на аккаунт автоматически после подтверждения платежа.

Где найти ID: откройте Magic Chess: Go Go и нажмите на аватар в левом верхнем углу. На экране профиля Game ID и сервер показаны рядом в виде «123456789 (1234)» — первое число это ID игрока, число в скобках это ID сервера.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'magic-chess-gogo') AND locale = 'ru';

UPDATE brand_translations SET
    highlights = $c$["Pay in UZS","By ID and server","Nickname check","No password"]$c$::json,
    short_description = $c$Top up Magic Chess: Go Go — diamonds by player ID and server ID, pay in sum, no password.$c$,
    description = $c$Magic Chess: Go Go (MCGG) is a mobile auto battler by Moonton set in the Mobile Legends universe: you do not control the fight directly, you assemble a line-up and place your pieces, and the round plays itself out. Diamonds are the in-game currency — they unlock looks and skins, and buy event bundles and seasonal passes.

YuPay tops up your account by its public player ID and server ID — no password and no account login needed. Before you pay we verify the ID and server pair and show you the nickname attached to it, so diamonds never land on a stranger's account. You can pay in Uzbek sum with Uzcard and Humo cards via Click, Payme or Uzum; the rate is shown before you pay, and diamonds are credited automatically once your payment is confirmed.

One thing to know: Magic Chess: Go Go has a separate Russian region alongside the global one, and top-ups do not cross between them. Pick the product on this page that matches your account.$c$,
    instructions = $c$How to top up Magic Chess: Go Go:

1. Pick the product that matches your account: “Diamonds — global account” (Uzbekistan and most CIS countries) or “Diamonds — Russian account” (if you play the Russian version of the game).
2. Enter your player ID and server ID — both numbers are in your profile, and no password is needed.
3. Wait for the check: we show the nickname attached to that pair. If no nickname is found, the region is probably wrong — try the other product.
4. Choose an amount and a payment method: Click, Payme or Uzum. The rate and total are shown before you pay.
5. Pay — diamonds are credited to your account automatically once your payment is confirmed.

Where to find your ID: open Magic Chess: Go Go and tap your avatar in the upper-left corner. The profile screen shows your Game ID and server together as “123456789 (1234)” — the first number is your player ID, the number in brackets is your server ID.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'magic-chess-gogo') AND locale = 'en';

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","ID va server orqali","Nik tekshiruvi","Parolsiz"]$c$::json,
    short_description = $c$Magic Chess: Go Go toʻldirish — olmoslar oʻyinchi ID va server ID orqali, soʻmda toʻlov, parolsiz.$c$,
    description = $c$Magic Chess: Go Go (MCGG) — Moonton kompaniyasining Mobile Legends olamida qurilgan mobil avtobattleri: siz jangni bevosita boshqarmaysiz, balki tarkib toʻplab, figuralarni joylashtirasiz, raund esa oʻzi oʻtadi. Olmoslar oʻyin ichidagi valyuta hisoblanadi: ularga koʻrinishlar va skinlar ochiladi, tadbir toʻplamlari va mavsumiy passlar sotib olinadi.

YuPay hisobingizni ochiq oʻyinchi ID va server ID orqali toʻldiradi — parol va akkauntga kirish talab qilinmaydi. Toʻlovdan oldin biz ID va server juftligini tekshirib, unga bogʻlangan nikni koʻrsatamiz, shunda olmoslar begona oʻyinchiga tushmaydi. Toʻlovni soʻmda Uzcard va Humo kartalari bilan Click, Payme yoki Uzum orqali amalga oshirishingiz mumkin; kurs toʻlovdan oldin koʻrinadi, olmoslar esa toʻlov tasdiqlangach avtomatik tushadi.

Muhim: Magic Chess: Go Go oʻyinida global regiondan tashqari alohida Rossiya regioni bor va toʻldirishlar ular oʻrtasida oʻtmaydi. Sahifada akkauntingizga mos mahsulotni tanlang.$c$,
    instructions = $c$Magic Chess: Go Go hisobini qanday toʻldirish:

1. Akkauntingizga mos mahsulotni tanlang: «Olmoslar — global akkaunt» (Oʻzbekiston va koʻpchilik MDH davlatlari) yoki «Olmoslar — Rossiya akkaunti» (agar oʻyinning rus versiyasida oʻynasangiz).
2. Oʻyinchi ID va server ID raqamlarini kiriting — ikkalasi ham profilda, parol kerak emas.
3. Tekshiruvni kuting: shu juftlikka bogʻlangan nikni koʻrsatamiz. Agar nik topilmasa — ehtimol region notoʻgʻri tanlangan, ikkinchi mahsulotni sinab koʻring.
4. Nominal va toʻlov usulini tanlang: Click, Payme yoki Uzum. Kurs va yakuniy summa toʻlovdan oldin koʻrsatiladi.
5. Toʻlang — olmoslar toʻlov tasdiqlangach hisobingizga avtomatik tushadi.

ID raqamini qayerdan topish mumkin: Magic Chess: Go Go ni oching va chap yuqori burchakdagi avatarni bosing. Profil ekranida Game ID va server «123456789 (1234)» koʻrinishida yonma-yon koʻrsatiladi — birinchi raqam oʻyinchi ID, qavs ichidagi raqam server ID.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'magic-chess-gogo') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- 2. Product names per locale
--
-- `import_game` writes the operator's single product name into all three locale
-- rows. The product name is the only place the storefront states which account
-- the top-up is for, so an untranslated one hands a non-Russian-speaking
-- customer the one choice that cannot be undone.
-- ---------------------------------------------------------------------------

UPDATE product_translations SET
    name = $c$Алмазы — глобальный аккаунт$c$,
    short_description = $c$Для аккаунтов Узбекистана и СНГ на глобальном регионе.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'mcgg-diamonds') AND locale = 'ru';
UPDATE product_translations SET
    name = $c$Diamonds — global account$c$,
    short_description = $c$For Uzbekistan and CIS accounts on the global region.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'mcgg-diamonds') AND locale = 'en';
UPDATE product_translations SET
    name = $c$Olmoslar — global akkaunt$c$,
    short_description = $c$Oʻzbekiston va MDH akkauntlari uchun, global region.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'mcgg-diamonds') AND locale = 'uz';

UPDATE product_translations SET
    name = $c$Алмазы — российский аккаунт$c$,
    short_description = $c$Для тех, кто играет в российской версии Magic Chess: Go Go.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'mcgg-diamonds-ru') AND locale = 'ru';
UPDATE product_translations SET
    name = $c$Diamonds — Russian account$c$,
    short_description = $c$For players on the Russian version of Magic Chess: Go Go.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'mcgg-diamonds-ru') AND locale = 'en';
UPDATE product_translations SET
    name = $c$Olmoslar — Rossiya akkaunti$c$,
    short_description = $c$Magic Chess: Go Go rus versiyasida oʻynaydiganlar uchun.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'mcgg-diamonds-ru') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- 3. FAQs (rebuilt each run: delete cascades to brand_faq_translations)
-- ---------------------------------------------------------------------------

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'magic-chess-gogo');

WITH mcgg AS (
    SELECT id FROM brands WHERE slug = 'magic-chess-gogo'
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), mcgg.id, v.sort_order, true
    FROM mcgg, (VALUES (1), (2), (3), (4), (5), (6), (7), (8)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. Регион — единственный необратимый выбор на странице.
        (1, 'ru', $q$Что выбрать — глобальный или российский аккаунт?$q$,
            $a$Если вы играете в Узбекистане или другой стране СНГ и скачали игру в обычном Google Play или App Store, у вас глобальный аккаунт — выбирайте «Алмазы — глобальный аккаунт». Российский регион у Magic Chess: Go Go отдельный: он нужен тем, кто играет в российской версии игры. Пополнения между регионами не переходят. Самый надёжный способ проверить — ввести ID игрока и ID сервера: мы покажем ник до оплаты, и если ник не находится, значит нужен второй продукт.$a$),
        (1, 'en', $q$Global or Russian account — which do I pick?$q$,
            $a$If you play in Uzbekistan or another CIS country and installed the game from the ordinary Google Play or App Store, your account is global — choose “Diamonds — global account”. Magic Chess: Go Go runs a separate Russian region for players on the Russian version of the game. Top-ups do not cross between regions. The surest way to check is to enter your player ID and server ID: we show the nickname before payment, and if no nickname is found you need the other product.$a$),
        (1, 'uz', $q$Global yoki Rossiya akkaunti — qaysi birini tanlash kerak?$q$,
            $a$Agar Oʻzbekistonda yoki boshqa MDH davlatida oʻynasangiz va oʻyinni oddiy Google Play yoki App Store'dan yuklagan boʻlsangiz, akkauntingiz global — «Olmoslar — global akkaunt» ni tanlang. Magic Chess: Go Go oʻyinining rus versiyasida oʻynaydiganlar uchun alohida Rossiya regioni bor. Toʻldirishlar regionlar oʻrtasida oʻtmaydi. Eng ishonchli usul — oʻyinchi ID va server ID kiritish: nikni toʻlovdan oldin koʻrsatamiz, agar nik topilmasa, ikkinchi mahsulot kerak.$a$),

        -- 2. Где взять ID и сервер.
        (2, 'ru', $q$Как узнать ID игрока и ID сервера в Magic Chess: Go Go?$q$,
            $a$Откройте игру и нажмите на аватар в левом верхнем углу. На экране профиля Game ID и сервер показаны рядом в виде «123456789 (1234)»: первое число — ID игрока, число в скобках — ID сервера (Zone ID), обычно четыре цифры. Для пополнения нужны оба числа: без ID сервера алмазы не найдут аккаунт.$a$),
        (2, 'en', $q$How do I find my player ID and server ID in Magic Chess: Go Go?$q$,
            $a$Open the game and tap your avatar in the upper-left corner. The profile screen shows your Game ID and server together as “123456789 (1234)”: the first number is the player ID and the number in brackets is the server ID (Zone ID), usually four digits. A top-up needs both — without the server ID the diamonds cannot find the account.$a$),
        (2, 'uz', $q$Magic Chess: Go Go'da oʻyinchi ID va server ID ni qanday bilish mumkin?$q$,
            $a$Oʻyinni oching va chap yuqori burchakdagi avatarni bosing. Profil ekranida Game ID va server «123456789 (1234)» koʻrinishida yonma-yon koʻrsatiladi: birinchi raqam — oʻyinchi ID, qavs ichidagi raqam — server ID (Zone ID), odatda toʻrt xonali. Toʻldirish uchun ikkalasi ham kerak: server ID siz olmoslar hisobni topa olmaydi.$a$),

        -- 3. Ошибка в регионе.
        (3, 'ru', $q$Что будет, если выбрать не тот регион?$q$,
            $a$До оплаты — ничего: проверка просто не найдёт ник по вашей связке ID и сервера, и вы сможете переключиться на второй продукт. Именно поэтому мы показываем ник перед оплатой. Если ник не находится ни в одном из продуктов, проверьте, что ID и сервер скопированы полностью и без пробелов, и напишите в поддержку — разберёмся до того, как вы заплатите.$a$),
        (3, 'en', $q$What happens if I pick the wrong region?$q$,
            $a$Before payment, nothing: the check simply will not find a nickname for your ID and server pair, and you can switch to the other product. That is exactly why we show the nickname before you pay. If neither product finds a nickname, check that the ID and server were copied in full with no spaces, and message support — we will sort it out before you pay anything.$a$),
        (3, 'uz', $q$Notoʻgʻri region tanlansa nima boʻladi?$q$,
            $a$Toʻlovdan oldin — hech nima: tekshiruv sizning ID va server juftligingiz boʻyicha nikni topa olmaydi va siz ikkinchi mahsulotga oʻtishingiz mumkin. Aynan shuning uchun nikni toʻlovdan oldin koʻrsatamiz. Agar ikkala mahsulotda ham nik topilmasa, ID va server toʻliq, boʻshliqsiz nusxalanganini tekshiring va qoʻllab-quvvatlashga yozing — toʻlovdan oldin hal qilamiz.$a$),

        -- 4. Не перепутать с Mobile Legends — игры соседние, ID разные.
        (4, 'ru', $q$Можно ли использовать ID из Mobile Legends?$q$,
            $a$Нет. Magic Chess: Go Go — отдельная игра, хоть и по вселенной Mobile Legends, и ID для пополнения нужно брать именно в ней: аватар в левом верхнем углу, дальше Game ID и сервер. ID из Mobile Legends сюда не подойдёт — проверка не найдёт по нему ник. Если вы играете в обе игры, сверьте, что скопировали номер из нужного приложения.$a$),
        (4, 'en', $q$Can I use my Mobile Legends ID?$q$,
            $a$No. Magic Chess: Go Go is its own game, even though it is set in the Mobile Legends universe, and the ID for a top-up has to come from inside it: avatar in the upper-left corner, then Game ID and server. A Mobile Legends ID will not work here — the check will not find a nickname for it. If you play both, double-check which app you copied the number from.$a$),
        (4, 'uz', $q$Mobile Legends ID sidan foydalansa boʻladimi?$q$,
            $a$Yoʻq. Magic Chess: Go Go — Mobile Legends olamida qurilgan boʻlsa-da, alohida oʻyin, va toʻldirish uchun ID aynan shu oʻyindan olinadi: chap yuqori burchakdagi avatar, soʻngra Game ID va server. Mobile Legends ID bu yerda ishlamaydi — tekshiruv unga nik topa olmaydi. Ikkala oʻyinda ham oʻynasangiz, raqamni qaysi ilovadan nusxalaganingizni tekshiring.$a$),

        -- 5. Что такое алмазы.
        (5, 'ru', $q$Что такое алмазы Magic Chess: Go Go и что на них купить?$q$,
            $a$Алмазы — внутриигровая валюта Magic Chess: Go Go. За них открывают облики и скины, покупают наборы событий и сезонные пропуска. Weekly Card выгоднее разовой покупки: алмазы по нему начисляются порциями в течение недели, поэтому заходить в игру нужно каждый день.$a$),
        (5, 'en', $q$What are Magic Chess: Go Go diamonds and what can I buy with them?$q$,
            $a$Diamonds are the in-game currency of Magic Chess: Go Go. They unlock looks and skins, and buy event bundles and seasonal passes. The Weekly Card is better value than a one-off purchase: its diamonds arrive in instalments across the week, so you need to log in each day.$a$),
        (5, 'uz', $q$Magic Chess: Go Go olmoslari nima va ularga nima sotib olish mumkin?$q$,
            $a$Olmoslar — Magic Chess: Go Go oʻyinining ichki valyutasi. Ularga koʻrinishlar va skinlar ochiladi, tadbir toʻplamlari va mavsumiy passlar sotib olinadi. Weekly Card bir martalik xariddan foydaliroq: undagi olmoslar hafta davomida boʻlib beriladi, shuning uchun oʻyinga har kuni kirish kerak.$a$),

        -- 6. Пароль.
        (6, 'ru', $q$Нужен ли пароль от аккаунта?$q$,
            $a$Нет. Пополнение проходит по публичному ID игрока и ID сервера — пароль и вход в аккаунт не требуются, и мы их не запрашиваем.$a$),
        (6, 'en', $q$Do you need my account password?$q$,
            $a$No. Top-ups run on your public player ID and server ID — no password and no account login are required, and we never ask for them.$a$),
        (6, 'uz', $q$Akkaunt paroli kerakmi?$q$,
            $a$Yoʻq. Toʻldirish ochiq oʻyinchi ID va server ID orqali amalga oshadi — parol va akkauntga kirish talab qilinmaydi, biz ularni soʻramaymiz.$a$),

        -- 7. Оплата и скорость.
        (7, 'ru', $q$Можно ли платить в сумах и за сколько зачисляются алмазы?$q$,
            $a$Да, оплата в узбекских сумах доступна картами Uzcard и Humo через Click, Payme и Uzum; курс и итоговая сумма показываются до оплаты. Алмазы зачисляются на аккаунт автоматически после подтверждения платежа, обычно в течение нескольких минут.$a$),
        (7, 'en', $q$Can I pay in Uzbek sum, and how fast are diamonds credited?$q$,
            $a$Yes — you can pay in Uzbek sum with Uzcard and Humo cards via Click, Payme and Uzum, and the rate and final total are shown before you pay. Diamonds are credited to your account automatically once your payment is confirmed, usually within a few minutes.$a$),
        (7, 'uz', $q$Soʻmda toʻlash mumkinmi va olmoslar qancha vaqtda tushadi?$q$,
            $a$Ha — oʻzbek soʻmida Uzcard va Humo kartalari orqali Click, Payme va Uzum bilan toʻlash mumkin, kurs va yakuniy summa toʻlovdan oldin koʻrsatiladi. Olmoslar toʻlov tasdiqlangach hisobingizga avtomatik tushadi, odatda bir necha daqiqada.$a$),

        -- 8. Официальность.
        (8, 'ru', $q$Это официальный сайт Magic Chess: Go Go?$q$,
            $a$Нет. YuPay — независимый сервис пополнения и не связан с Moonton, издателем Magic Chess: Go Go. Мы покупаем и перепродаём пополнения по прозрачному курсу, который виден до оплаты.$a$),
        (8, 'en', $q$Is this the official Magic Chess: Go Go website?$q$,
            $a$No. YuPay is an independent top-up service and is not affiliated with Moonton, the publisher of Magic Chess: Go Go. We buy and resell top-ups at a transparent rate that is shown before you pay.$a$),
        (8, 'uz', $q$Bu Magic Chess: Go Go rasmiy saytimi?$q$,
            $a$Yoʻq. YuPay — mustaqil toʻldirish xizmati va Magic Chess: Go Go noshiri Moonton bilan bogʻliq emas. Biz toʻldirishlarni shaffof kurs boʻyicha sotib olib, qayta sotamiz; kurs toʻlovdan oldin koʻrinadi.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
