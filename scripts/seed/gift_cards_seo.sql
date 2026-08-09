-- scripts/seed/gift_cards_seo.sql
--
-- SEO + activation content for the two Gift cards brands, `roblox` and
-- `discord`: highlights, short/long descriptions, activation instructions,
-- localized product names, and FAQs in ru/en/uz.
--
-- Content-managed, NOT a fixture and NOT an Alembic data migration. Applied to
-- prod by an operator (psql / `!`), gated by the standing deploy rule. Depends
-- on scripts/seed/2026-08-10_gift_cards_import.py having created the brands.
--
-- Idempotent: translations are UPDATEd in place; FAQs are rebuilt via
-- delete-then-insert, inside one transaction.
--
-- These two pages carry more weight than a top-up page does. A top-up lands in
-- the account by itself; a gift card arrives as a string the customer then has
-- to redeem somewhere, and for BOTH of these brands the somewhere is not where
-- a reasonable person would look:
--
--   * Roblox codes go to roblox.com/redeem in a BROWSER — the mobile app does
--     not accept them — and they land as Roblox Credit, not Robux. Buying the
--     Robux is a second step. Credit cannot be moved off the account it was
--     redeemed on, so the account has to be right the first time.
--   * Discord Nitro from this supplier is a POSA voucher. The code is entered
--     at posa.mintroute.com together with an email, NOT anywhere in Discord;
--     an activation link then arrives by mail. A customer who pastes it into
--     Discord's gift field will conclude we sold them a dead code.
--
-- So the activation steps lead both `instructions` blocks, and the first FAQ on
-- each brand is the misconception rather than a keyword.
--
-- Apply on prod (operator psql):
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     psql -U yupay_app -d yupay -f - < scripts/seed/gift_cards_seo.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- 0. Denominations to English
--
-- `Sku.denomination` is one string with no locale, and the whole catalog writes
-- it in English ("55 Diamonds", "Weekly Card"). The import seeded the Discord
-- tiers in Russian; this brings them back in line.
-- ---------------------------------------------------------------------------

UPDATE skus SET denomination = 'Nitro Basic — 1 month' WHERE sku_code = 'discord-nitro-basic-1m';
UPDATE skus SET denomination = 'Nitro — 1 month'       WHERE sku_code = 'discord-nitro-1m';
UPDATE skus SET denomination = 'Nitro — 1 year'        WHERE sku_code = 'discord-nitro-1y';

-- ---------------------------------------------------------------------------
-- 1. Roblox
-- ---------------------------------------------------------------------------

UPDATE brand_translations SET
    highlights = $c$["Оплата в сумах","Код на почту","Активация за минуту","Без пароля"]$c$::json,
    short_description = $c$Подарочные карты Roblox — код с Robux приходит на почту, оплата в сумах, без пароля от аккаунта.$c$,
    description = $c$Roblox — платформа, где играют в миллионы пользовательских игр и создают свои. Robux — внутренняя валюта: за неё покупают одежду и аксессуары для аватара, пропуска и предметы внутри игр, а также подписку Premium.

YuPay продаёт глобальные подарочные карты Roblox. После оплаты вы получаете код на почту и активируете его сами на сайте Roblox — пароль от аккаунта не нужен и мы его не спрашиваем. Оплатить можно в сумах картами Uzcard и Humo через Click, Payme или Uzum; курс виден до оплаты.

Важно понимать, как устроена активация: код зачисляется не робуксами, а балансом Roblox Credit, и уже за этот баланс вы покупаете Robux или Premium — это второй шаг, он делается там же на сайте.$c$,
    instructions = $c$Как активировать код Roblox:

1. Откройте roblox.com/redeem в браузере — на телефоне тоже подойдёт браузер. В самом приложении Roblox код ввести нельзя (исключение — устройства Samsung Galaxy).
2. Войдите в тот аккаунт, на который нужны Robux. Проверьте имя в правом верхнем углу: перенести баланс на другой аккаунт потом невозможно.
3. Введите код из письма в поле «Code» и нажмите «Redeem».
4. На аккаунт зачислится Roblox Credit — это баланс, а не сами Robux.
5. Нажмите «Get Robux» (или откройте раздел Robux) и обменяйте баланс на Robux либо на подписку Premium.

Код приходит на почту, указанную при заказе, сразу после подтверждения оплаты. Если письма нет — проверьте «Спам» и папку «Промоакции».$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'roblox') AND locale = 'ru';

UPDATE brand_translations SET
    highlights = $c$["Pay in UZS","Code by email","Redeem in a minute","No password"]$c$::json,
    short_description = $c$Roblox gift cards — a Robux code by email, pay in sum, no account password.$c$,
    description = $c$Roblox is a platform for playing millions of user-made games and building your own. Robux is its currency: it buys avatar clothing and accessories, in-game passes and items, and the Premium membership.

YuPay sells global Roblox gift cards. After payment the code arrives by email and you redeem it yourself on Roblox's site — no account password is needed and we never ask for one. You can pay in Uzbek sum with Uzcard and Humo cards via Click, Payme or Uzum; the rate is shown before you pay.

One thing worth knowing up front: the code does not deposit Robux. It adds Roblox Credit, a balance on the account, and you then spend that balance on Robux or Premium — a second step, done in the same place.$c$,
    instructions = $c$How to redeem your Roblox code:

1. Open roblox.com/redeem in a browser — a phone browser is fine. The code cannot be entered in the Roblox app itself (Samsung Galaxy devices are the exception).
2. Sign in to the account the Robux are for. Check the name in the top-right corner: the balance cannot be moved to another account afterwards.
3. Enter the code from the email into the Code box and click Redeem.
4. The account receives Roblox Credit — a balance, not the Robux themselves.
5. Click Get Robux (or open the Robux section) and exchange the balance for Robux or a Premium membership.

The code is emailed to the address on the order as soon as payment is confirmed. If it has not arrived, check Spam and Promotions.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'roblox') AND locale = 'en';

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","Kod pochtaga","Bir daqiqada faollashtirish","Parolsiz"]$c$::json,
    short_description = $c$Roblox sovgʻa kartalari — Robux kodi pochtaga keladi, soʻmda toʻlov, akkaunt parolisiz.$c$,
    description = $c$Roblox — millionlab foydalanuvchi oʻyinlarini oʻynash va oʻzingiznikini yaratish platformasi. Robux uning valyutasi: unga avatar uchun kiyim va aksessuarlar, oʻyin ichidagi passlar va buyumlar, shuningdek Premium obunasi sotib olinadi.

YuPay global Roblox sovgʻa kartalarini sotadi. Toʻlovdan soʻng kod pochtangizga keladi va uni Roblox saytida oʻzingiz faollashtirasiz — akkaunt paroli kerak emas va biz uni soʻramaymiz. Toʻlovni soʻmda Uzcard va Humo kartalari bilan Click, Payme yoki Uzum orqali amalga oshirishingiz mumkin; kurs toʻlovdan oldin koʻrinadi.

Muhimi: kod Robux emas, Roblox Credit balansini qoʻshadi, va Robux yoki Premium'ni siz oʻsha balansga sotib olasiz — bu ikkinchi qadam, oʻsha yerda bajariladi.$c$,
    instructions = $c$Roblox kodini qanday faollashtirish:

1. Brauzerda roblox.com/redeem ni oching — telefondagi brauzer ham boʻladi. Roblox ilovasining oʻzida kodni kiritib boʻlmaydi (Samsung Galaxy qurilmalari bundan mustasno).
2. Robux kerak boʻlgan akkauntga kiring. Oʻng yuqori burchakdagi nomni tekshiring: keyinchalik balansni boshqa akkauntga koʻchirib boʻlmaydi.
3. Xatdagi kodni «Code» maydoniga kiriting va «Redeem» ni bosing.
4. Hisobga Roblox Credit tushadi — bu balans, Robux'ning oʻzi emas.
5. «Get Robux» ni bosing (yoki Robux boʻlimini oching) va balansni Robux yoki Premium obunasiga almashtiring.

Kod toʻlov tasdiqlangach buyurtmada koʻrsatilgan pochtaga keladi. Xat kelmasa — «Spam» va «Promotions» papkalarini tekshiring.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'roblox') AND locale = 'uz';

UPDATE product_translations SET
    name = $c$Robux — глобальные карты$c$,
    short_description = $c$Код приходит на почту, активируется на roblox.com/redeem.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'roblox-robux-global') AND locale = 'ru';
UPDATE product_translations SET
    name = $c$Robux — global cards$c$,
    short_description = $c$The code arrives by email and is redeemed at roblox.com/redeem.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'roblox-robux-global') AND locale = 'en';
UPDATE product_translations SET
    name = $c$Robux — global kartalar$c$,
    short_description = $c$Kod pochtaga keladi, roblox.com/redeem da faollashtiriladi.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'roblox-robux-global') AND locale = 'uz';

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'roblox');

WITH rbx AS (SELECT id FROM brands WHERE slug = 'roblox'),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), rbx.id, v.sort_order, true
    FROM rbx, (VALUES (1), (2), (3), (4), (5), (6)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. Кредит, а не робуксы — то, из-за чего пишут в поддержку.
        (1, 'ru', $q$Почему после активации нет Robux, а есть какой-то баланс?$q$,
            $a$Так и должно быть. Подарочная карта Roblox зачисляет не сами Robux, а баланс Roblox Credit. Чтобы получить Robux, на сайте нажмите «Get Robux» и обменяйте баланс — или потратьте его на подписку Premium. Это второй шаг, он бесплатный и занимает несколько секунд.$a$),
        (1, 'en', $q$Why do I have a balance instead of Robux after redeeming?$q$,
            $a$That is how it works. A Roblox gift card adds Roblox Credit rather than Robux. To get the Robux, click Get Robux on the site and exchange the balance — or spend it on a Premium membership instead. That second step is free and takes seconds.$a$),
        (1, 'uz', $q$Faollashtirgach nega Robux emas, balans paydo boʻldi?$q$,
            $a$Shunday boʻlishi kerak. Roblox sovgʻa kartasi Robux emas, Roblox Credit balansini qoʻshadi. Robux olish uchun saytda «Get Robux» ni bosing va balansni almashtiring — yoki uni Premium obunasiga sarflang. Bu ikkinchi qadam bepul va bir necha soniya oladi.$a$),

        -- 2. Где вводить.
        (2, 'ru', $q$Где вводить код?$q$,
            $a$На странице roblox.com/redeem в браузере. С телефона тоже подойдёт браузер, а вот в самом приложении Roblox поля для кода нет — исключение только для устройств Samsung Galaxy. Перед вводом убедитесь, что вошли в нужный аккаунт: баланс останется на том, где вы активировали код, перенести его нельзя.$a$),
        (2, 'en', $q$Where do I enter the code?$q$,
            $a$At roblox.com/redeem in a browser. A phone browser works too, but the Roblox app has no code field — Samsung Galaxy devices are the one exception. Before entering it, make sure you are signed in to the right account: the balance stays on whichever account redeemed the code and cannot be moved.$a$),
        (2, 'uz', $q$Kodni qayerga kiritaman?$q$,
            $a$Brauzerda roblox.com/redeem sahifasida. Telefon brauzeri ham boʻladi, lekin Roblox ilovasida kod maydoni yoʻq — faqat Samsung Galaxy qurilmalari bundan mustasno. Kiritishdan oldin kerakli akkauntga kirganingizga ishonch hosil qiling: balans kod faollashtirilgan akkauntda qoladi va koʻchirilmaydi.$a$),

        -- 3. Когда придёт код.
        (3, 'ru', $q$Когда придёт код и куда?$q$,
            $a$На почту, указанную при оформлении заказа, сразу после подтверждения оплаты. Код также доступен на странице заказа. Если письма нет, проверьте папки «Спам» и «Промоакции» — и напишите в поддержку, мы вышлем повторно.$a$),
        (3, 'en', $q$When and where does the code arrive?$q$,
            $a$To the email you entered on the order, as soon as payment is confirmed. The code is also on the order page. If no email arrives, check Spam and Promotions — and message support, we will resend it.$a$),
        (3, 'uz', $q$Kod qachon va qayerga keladi?$q$,
            $a$Buyurtmada koʻrsatilgan pochtaga, toʻlov tasdiqlangach darhol. Kod buyurtma sahifasida ham koʻrinadi. Xat kelmasa, «Spam» va «Promotions» papkalarini tekshiring va qoʻllab-quvvatlashga yozing — qayta yuboramiz.$a$),

        -- 4. Пароль.
        (4, 'ru', $q$Нужен ли пароль от аккаунта Roblox?$q$,
            $a$Нет. Мы продаём код, а активируете его вы сами на сайте Roblox под своим логином. Пароль нам не нужен, и мы его не запрашиваем — любой сервис, который просит пароль от игрового аккаунта, повод насторожиться.$a$),
        (4, 'en', $q$Do you need my Roblox password?$q$,
            $a$No. We sell you a code and you redeem it yourself on Roblox's site under your own login. We do not need the password and never ask for it — any service that asks for your game password is a red flag.$a$),
        (4, 'uz', $q$Roblox akkaunt paroli kerakmi?$q$,
            $a$Yoʻq. Biz kod sotamiz, uni esa siz Roblox saytida oʻz loginingiz ostida faollashtirasiz. Parol bizga kerak emas va uni soʻramaymiz — oʻyin parolini soʻraydigan har qanday xizmat ehtiyot boʻlish uchun sabab.$a$),

        -- 5. Регион карты.
        (5, 'ru', $q$Подойдёт ли карта для аккаунта из Узбекистана?$q$,
            $a$Да. Мы продаём глобальные карты Roblox — они не привязаны к стране аккаунта и активируются на roblox.com/redeem из любого региона. Отдельная карта для Узбекистана не нужна.$a$),
        (5, 'en', $q$Will the card work on an account from Uzbekistan?$q$,
            $a$Yes. We sell global Roblox cards — they are not tied to the account's country and redeem at roblox.com/redeem from any region. No Uzbekistan-specific card is needed.$a$),
        (5, 'uz', $q$Karta Oʻzbekistondagi akkaunt uchun toʻgʻri keladimi?$q$,
            $a$Ha. Biz global Roblox kartalarini sotamiz — ular akkaunt davlatiga bogʻlanmagan va istalgan mintaqadan roblox.com/redeem da faollashtiriladi. Oʻzbekiston uchun alohida karta kerak emas.$a$),

        -- 6. Официальность.
        (6, 'ru', $q$Это официальный сайт Roblox?$q$,
            $a$Нет. YuPay — независимый магазин цифровых кодов и не связан с Roblox Corporation. Мы покупаем подарочные карты у поставщика и перепродаём их по прозрачной цене, которая видна до оплаты.$a$),
        (6, 'en', $q$Is this the official Roblox website?$q$,
            $a$No. YuPay is an independent digital-code shop and is not affiliated with Roblox Corporation. We buy gift cards from a supplier and resell them at a transparent price, shown before you pay.$a$),
        (6, 'uz', $q$Bu Roblox rasmiy saytimi?$q$,
            $a$Yoʻq. YuPay — mustaqil raqamli kodlar doʻkoni va Roblox Corporation bilan bogʻliq emas. Biz sovgʻa kartalarini taʼminotchidan sotib olib, shaffof narxda qayta sotamiz; narx toʻlovdan oldin koʻrinadi.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

-- ---------------------------------------------------------------------------
-- 2. Discord
-- ---------------------------------------------------------------------------

UPDATE brand_translations SET
    highlights = $c$["Оплата в сумах","Код на почту","Nitro и Nitro Basic","Без пароля"]$c$::json,
    short_description = $c$Подписка Discord Nitro — код на почту, оплата в сумах, активация без пароля от аккаунта.$c$,
    description = $c$Discord Nitro — платная подписка в мессенджере Discord. Она поднимает лимит на размер файлов, включает HD-стримы и демонстрацию экрана в высоком качестве, даёт анимированный аватар, собственный тег, кастомные эмодзи на всех серверах и бусты для сервера. Nitro Basic — упрощённый тариф: увеличенные файлы и эмодзи, но без бустов и стримов в максимальном качестве.

YuPay продаёт ваучеры на подписку. После оплаты код приходит на почту, а активируете вы его сами — пароль от Discord не нужен и мы его не спрашиваем. Оплатить можно в сумах картами Uzcard и Humo через Click, Payme или Uzum.

Обратите внимание: код активируется не внутри Discord, а на странице партнёра-дистрибьютора, откуда затем приходит ссылка активации на почту. Подробные шаги — ниже.$c$,
    instructions = $c$Как активировать код Discord Nitro:

1. Откройте posa.mintroute.com в браузере. Именно там активируется этот ваучер — в самом Discord поле для подарочных кодов работает с другими кодами, наш туда не подойдёт.
2. Выберите сервис Discord.
3. Выберите тот тариф, который вы купили: Nitro Basic на месяц, Nitro на месяц или Nitro на год. Тариф должен совпадать с купленным.
4. Введите код из письма и свой адрес электронной почты, нажмите «Redeem».
5. На указанную почту придёт письмо со ссылкой активации — перейдите по ней и следуйте подсказкам, чтобы привязать подписку к своему аккаунту Discord.

Код приходит на почту, указанную при заказе, сразу после подтверждения оплаты. Если письма нет — проверьте «Спам» и папку «Промоакции».$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'discord') AND locale = 'ru';

UPDATE brand_translations SET
    highlights = $c$["Pay in UZS","Code by email","Nitro and Nitro Basic","No password"]$c$::json,
    short_description = $c$Discord Nitro subscriptions — a code by email, pay in sum, no Discord password.$c$,
    description = $c$Discord Nitro is the paid subscription in the Discord messenger. It raises the file-size limit, unlocks HD streaming and high-quality screen share, and adds an animated avatar, a custom tag, custom emoji across every server and server boosts. Nitro Basic is the lighter tier: bigger uploads and emoji, without boosts or top-quality streaming.

YuPay sells subscription vouchers. After payment the code arrives by email and you activate it yourself — no Discord password is needed and we never ask for one. You can pay in Uzbek sum with Uzcard and Humo cards via Click, Payme or Uzum.

Note that the code is not redeemed inside Discord but on the distributor's page, which then emails you an activation link. Step-by-step below.$c$,
    instructions = $c$How to redeem your Discord Nitro code:

1. Open posa.mintroute.com in a browser. That is where this voucher is redeemed — Discord's own gift-code field takes a different kind of code and will not accept ours.
2. Select the Discord service.
3. Select the plan you bought: Nitro Basic monthly, Nitro monthly or Nitro yearly. It has to match what you purchased.
4. Enter the code from the email along with your email address and click Redeem.
5. An email with an activation link arrives at that address — follow it and the on-screen steps to attach the subscription to your Discord account.

The code is emailed to the address on the order as soon as payment is confirmed. If it has not arrived, check Spam and Promotions.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'discord') AND locale = 'en';

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","Kod pochtaga","Nitro va Nitro Basic","Parolsiz"]$c$::json,
    short_description = $c$Discord Nitro obunasi — kod pochtaga keladi, soʻmda toʻlov, Discord parolisiz.$c$,
    description = $c$Discord Nitro — Discord messenjeridagi pullik obuna. U fayl hajmi chegarasini oshiradi, HD-strim va yuqori sifatli ekran namoyishini ochadi, animatsion avatar, oʻz tegi, barcha serverlarda maxsus emojilar va server bustlarini beradi. Nitro Basic — yengilroq tarif: kattaroq fayllar va emojilar, ammo bustlar va eng yuqori sifatli strimsiz.

YuPay obuna vaucherlarini sotadi. Toʻlovdan soʻng kod pochtaga keladi, faollashtirishni esa siz oʻzingiz bajarasiz — Discord paroli kerak emas va biz uni soʻramaymiz. Toʻlovni soʻmda Uzcard va Humo kartalari bilan Click, Payme yoki Uzum orqali amalga oshirish mumkin.

Eʼtibor bering: kod Discord ichida emas, distribyutor sahifasida faollashtiriladi, soʻngra pochtaga faollashtirish havolasi keladi. Bosqichlar quyida.$c$,
    instructions = $c$Discord Nitro kodini qanday faollashtirish:

1. Brauzerda posa.mintroute.com ni oching. Bu vaucher aynan shu yerda faollashtiriladi — Discord ichidagi sovgʻa kodi maydoni boshqa turdagi kodlar uchun va bizingimizni qabul qilmaydi.
2. Discord xizmatini tanlang.
3. Sotib olgan tarifingizni tanlang: oylik Nitro Basic, oylik Nitro yoki yillik Nitro. U xaridingizga mos boʻlishi shart.
4. Xatdagi kodni va oʻz elektron pochta manzilingizni kiriting, «Redeem» ni bosing.
5. Oʻsha pochtaga faollashtirish havolasi bilan xat keladi — havolaga oʻting va obunani Discord akkauntingizga bogʻlash uchun koʻrsatmalarga amal qiling.

Kod toʻlov tasdiqlangach buyurtmada koʻrsatilgan pochtaga keladi. Xat kelmasa — «Spam» va «Promotions» papkalarini tekshiring.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'discord') AND locale = 'uz';

UPDATE product_translations SET
    name = $c$Nitro$c$,
    short_description = $c$Код приходит на почту, активируется на posa.mintroute.com.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'discord-nitro') AND locale = 'ru';
UPDATE product_translations SET
    name = $c$Nitro$c$,
    short_description = $c$The code arrives by email and is redeemed at posa.mintroute.com.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'discord-nitro') AND locale = 'en';
UPDATE product_translations SET
    name = $c$Nitro$c$,
    short_description = $c$Kod pochtaga keladi, posa.mintroute.com da faollashtiriladi.$c$
WHERE product_id = (SELECT id FROM products WHERE slug = 'discord-nitro') AND locale = 'uz';

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'discord');

WITH dsc AS (SELECT id FROM brands WHERE slug = 'discord'),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), dsc.id, v.sort_order, true
    FROM dsc, (VALUES (1), (2), (3), (4), (5), (6)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. Код не вводится в Discord — главная причина «код не работает».
        (1, 'ru', $q$Код не принимается в Discord — что делать?$q$,
            $a$Этот ваучер и не активируется внутри Discord. Откройте posa.mintroute.com, выберите сервис Discord, затем тариф, который вы купили, введите код и свою почту. На почту придёт письмо со ссылкой активации — по ней подписка привяжется к вашему аккаунту Discord. Поле «Подарки» в самом Discord рассчитано на другой тип кодов, наш туда не подойдёт.$a$),
        (1, 'en', $q$Discord will not accept the code — what now?$q$,
            $a$This voucher is not redeemed inside Discord at all. Open posa.mintroute.com, pick the Discord service, then the plan you bought, and enter the code with your email address. An activation link arrives by email and attaches the subscription to your Discord account. Discord's own gift field expects a different kind of code and will not take ours.$a$),
        (1, 'uz', $q$Discord kodni qabul qilmayapti — nima qilish kerak?$q$,
            $a$Bu vaucher Discord ichida faollashtirilmaydi. posa.mintroute.com ni oching, Discord xizmatini, soʻngra sotib olgan tarifingizni tanlang, kod va pochtangizni kiriting. Pochtaga faollashtirish havolasi keladi va obuna Discord akkauntingizga bogʻlanadi. Discord ichidagi sovgʻa maydoni boshqa turdagi kodlar uchun moʻljallangan.$a$),

        -- 2. Basic против обычного.
        (2, 'ru', $q$Чем Nitro Basic отличается от Nitro?$q$,
            $a$Nitro Basic — упрощённый тариф: увеличенный лимит на размер файлов и кастомные эмодзи, но без бустов для сервера и без стримов в максимальном качестве. Полный Nitro добавляет бусты, HD-стримы и демонстрацию экрана высокого качества, анимированный аватар и собственный тег. Если нужны бусты или стримы — берите полный Nitro.$a$),
        (2, 'en', $q$How does Nitro Basic differ from Nitro?$q$,
            $a$Nitro Basic is the lighter tier: a bigger file-size limit and custom emoji, but no server boosts and no top-quality streaming. Full Nitro adds boosts, HD streaming and high-quality screen share, an animated avatar and a custom tag. If you need boosts or streaming, take full Nitro.$a$),
        (2, 'uz', $q$Nitro Basic Nitro'dan nimasi bilan farq qiladi?$q$,
            $a$Nitro Basic — yengilroq tarif: fayl hajmi chegarasi kattaroq va maxsus emojilar bor, ammo server bustlari va eng yuqori sifatli strim yoʻq. Toʻliq Nitro bustlar, HD-strim va yuqori sifatli ekran namoyishi, animatsion avatar va oʻz tegini qoʻshadi. Bust yoki strim kerak boʻlsa — toʻliq Nitro oling.$a$),

        -- 3. Тариф должен совпасть.
        (3, 'ru', $q$Что будет, если выбрать на сайте активации не тот тариф?$q$,
            $a$Выбирайте тот тариф, который купили: код выпущен под конкретную подписку, и под другую он не подойдёт. Если вы взяли Nitro на месяц — выбирайте Nitro на месяц, а не Basic. Ошиблись при выборе — просто вернитесь на шаг назад и выберите верный тариф, код при этом не расходуется.$a$),
        (3, 'en', $q$What if I pick the wrong plan on the activation page?$q$,
            $a$Pick the plan you actually bought: the code is issued for one specific subscription and will not work against another. If you bought monthly Nitro, choose monthly Nitro rather than Basic. If you mis-click, just go back and choose the right plan — the code is not consumed.$a$),
        (3, 'uz', $q$Faollashtirish sahifasida notoʻgʻri tarif tanlansa-chi?$q$,
            $a$Sotib olgan tarifingizni tanlang: kod aniq bir obuna uchun chiqarilgan va boshqasiga toʻgʻri kelmaydi. Oylik Nitro olgan boʻlsangiz — Basic emas, oylik Nitro'ni tanlang. Xato bosilsa, ortga qaytib toʻgʻri tarifni tanlang, kod sarflanmaydi.$a$),

        -- 4. Куда придёт код.
        (4, 'ru', $q$Когда придёт код и куда?$q$,
            $a$На почту, указанную при оформлении заказа, сразу после подтверждения оплаты. Код также виден на странице заказа. Если письма нет, проверьте «Спам» и «Промоакции» — и напишите в поддержку, вышлем повторно.$a$),
        (4, 'en', $q$When and where does the code arrive?$q$,
            $a$To the email you entered on the order, as soon as payment is confirmed. It is also shown on the order page. If no email arrives, check Spam and Promotions — and message support, we will resend it.$a$),
        (4, 'uz', $q$Kod qachon va qayerga keladi?$q$,
            $a$Buyurtmada koʻrsatilgan pochtaga, toʻlov tasdiqlangach darhol. Kod buyurtma sahifasida ham koʻrinadi. Xat kelmasa, «Spam» va «Promotions» papkalarini tekshiring va qoʻllab-quvvatlashga yozing — qayta yuboramiz.$a$),

        -- 5. Пароль.
        (5, 'ru', $q$Нужен ли пароль от Discord?$q$,
            $a$Нет. Мы продаём код, а привязываете подписку вы сами через письмо активации. Пароль нам не нужен, и мы его не запрашиваем.$a$),
        (5, 'en', $q$Do you need my Discord password?$q$,
            $a$No. We sell you a code and you attach the subscription yourself through the activation email. We do not need the password and never ask for it.$a$),
        (5, 'uz', $q$Discord paroli kerakmi?$q$,
            $a$Yoʻq. Biz kod sotamiz, obunani esa siz faollashtirish xati orqali oʻzingiz bogʻlaysiz. Parol bizga kerak emas va uni soʻramaymiz.$a$),

        -- 6. Официальность.
        (6, 'ru', $q$Это официальный сайт Discord?$q$,
            $a$Нет. YuPay — независимый магазин цифровых кодов и не связан с Discord Inc. Мы покупаем ваучеры у поставщика и перепродаём их по прозрачной цене, которая видна до оплаты.$a$),
        (6, 'en', $q$Is this the official Discord website?$q$,
            $a$No. YuPay is an independent digital-code shop and is not affiliated with Discord Inc. We buy vouchers from a supplier and resell them at a transparent price, shown before you pay.$a$),
        (6, 'uz', $q$Bu Discord rasmiy saytimi?$q$,
            $a$Yoʻq. YuPay — mustaqil raqamli kodlar doʻkoni va Discord Inc. bilan bogʻliq emas. Biz vaucherlarni taʼminotchidan sotib olib, shaffof narxda qayta sotamiz; narx toʻlovdan oldin koʻrinadi.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
