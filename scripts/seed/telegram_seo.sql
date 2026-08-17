-- scripts/seed/telegram_seo.sql
--
-- SEO content pack for the `telegram-stars` and `telegram-premium` brands:
-- highlights + short/long descriptions + instructions on `brand_translations`,
-- and 7 FAQ entries each with ru/en/uz answers.
--
-- Run AFTER scripts/seed/2026-08-17_telegram_import.py, which creates the brands.
--
-- Content-managed, NOT a fixture and NOT an Alembic data migration. Applied to
-- prod by an operator (psql / `!`), gated by the standing deploy rule.
--
-- Idempotent: brand_translations rows are UPDATEd in place; FAQs are rebuilt via
-- delete-then-insert. Wrapped in a single transaction so a half-run cannot leave
-- partial state.
--
-- Search intent this targets, from what people in Uzbekistan actually type:
--   ru — «купить telegram stars», «телеграм звёзды», «telegram premium
--        Узбекистан», «оплата в сумах», «через Click Payme», «без карты Visa»
--   uz — «telegram stars sotib olish», «telegram yulduzlari», «telegram premium
--        narxi», «Click orqali», «UzCard Humo», «username orqali»
--   en — «buy telegram stars uzbekistan», «telegram premium pay in sum»
--
-- The local pain point every competitor page leads with, and so does this one:
-- Telegram's own checkout wants an App Store / Google Play account or an
-- international card, which an Uzcard or Humo holder does not have. That is the
-- reason this product exists, so it is the first thing each page says.
--
-- Strings are dollar-quoted ($c$…$c$ / $q$…$q$ / $a$…$a$) so the apostrophe-heavy
-- Uzbek copy needs no escaping.

BEGIN;

-- ===========================================================================
-- 1. Telegram Stars — brand translations
-- ===========================================================================

UPDATE brand_translations SET
    highlights = $c$["Оплата в сумах","По username","Без пароля","Автоматически"]$c$::json,
    short_description = $c$Купить Telegram Stars в Узбекистане — по username, оплата в сумах через Click, Payme или Uzum, без карты Visa.$c$,
    description = $c$Telegram Stars (звёзды Telegram) — официальная внутренняя валюта мессенджера. Звёздами оплачивают покупки в ботах и мини-приложениях, платные посты и подписки на закрытые каналы, реакции звёздами, а также подарки другим пользователям — подарок остаётся на профиле получателя. За звёзды можно оформить и подписку Telegram Premium в подарок.

Купить звёзды внутри самого Telegram из Узбекистана мешает оплата: официальная покупка идёт через App Store или Google Play либо требует международную карту. YuPay снимает этот шаг — вы платите картой Uzcard или Humo в сумах через Click, Payme или Uzum, а звёзды приходят на аккаунт по username.

Пароль, код входа и доступ к аккаунту не нужны — мы спрашиваем только публичное имя пользователя. Курс и итоговая сумма в сумах видны до оплаты, а звёзды зачисляются автоматически после подтверждения платежа. Минимальный пакет — 50 звёзд: это ограничение самого Telegram, меньше перевести нельзя.$c$,
    instructions = $c$Как купить Telegram Stars:

1. Выберите пакет звёзд — от 50 до 2500.
2. Введите свой username в Telegram (например, @username) — пароль и код входа не нужны.
3. Выберите способ оплаты: Click, Payme или Uzum. Курс и итог в сумах показываются до оплаты.
4. Оплатите — звёзды зачисляются на аккаунт автоматически после подтверждения платежа.

Где найти свой username: откройте Telegram → Настройки → Имя пользователя. Если поле пустое, придумайте username и сохраните — без него звёзды отправить некуда.

Хотите подарить звёзды другому человеку? Введите его username вместо своего — всё остальное так же.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'telegram-stars') AND locale = 'ru';

UPDATE brand_translations SET
    highlights = $c$["Pay in UZS","By username","No password","Automatic"]$c$::json,
    short_description = $c$Buy Telegram Stars in Uzbekistan — by username, pay in sum via Click, Payme or Uzum, no Visa card needed.$c$,
    description = $c$Telegram Stars are the official in-app currency of Telegram. Stars pay for purchases in bots and mini apps, paid posts and private channel subscriptions, star reactions, and gifts to other users — a gift stays on the recipient's profile. Stars also buy a Telegram Premium subscription as a gift.

Buying Stars inside Telegram from Uzbekistan runs into payment: the official route goes through the App Store or Google Play, or wants an international card. YuPay removes that step — you pay with an Uzcard or Humo card in sum via Click, Payme or Uzum, and the Stars arrive by username.

No password, no login code, no account access — we ask only for your public username. The rate and the total in sum are shown before you pay, and Stars are credited automatically once the payment is confirmed. The smallest pack is 50 Stars: that is Telegram's own floor, not ours.$c$,
    instructions = $c$How to buy Telegram Stars:

1. Pick a pack — from 50 to 2500 Stars.
2. Enter your Telegram username (for example @username) — no password, no login code.
3. Choose how to pay: Click, Payme or Uzum. The rate and the total in sum appear before you pay.
4. Pay — Stars are credited automatically once your payment is confirmed.

Where to find your username: open Telegram → Settings → Username. If it is empty, set one and save — without a username there is nowhere to send the Stars.

Sending Stars to someone else? Enter their username instead of yours; everything else is the same.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'telegram-stars') AND locale = 'en';

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","Username orqali","Parolsiz","Avtomatik"]$c$::json,
    short_description = $c$Oʻzbekistonda Telegram Stars sotib olish — username orqali, Click, Payme yoki Uzum bilan soʻmda toʻlov, Visa kartasiz.$c$,
    description = $c$Telegram Stars (Telegram yulduzlari) — messenjerning rasmiy ichki valyutasi. Yulduzlar bilan botlar va mini ilovalardagi xaridlar, pullik postlar va yopiq kanallarga obuna, yulduzli reaksiyalar hamda boshqa foydalanuvchilarga sovgʻalar toʻlanadi — sovgʻa qabul qiluvchining profilida qoladi. Yulduzlarga Telegram Premium obunasini sovgʻa qilish ham mumkin.

Oʻzbekistondan Telegramning oʻzida yulduz sotib olishga toʻlov toʻsqinlik qiladi: rasmiy yoʻl App Store yoki Google Play orqali oʻtadi, yoxud xalqaro karta talab qiladi. YuPay bu bosqichni olib tashlaydi — siz Uzcard yoki Humo kartangiz bilan Click, Payme yoki Uzum orqali soʻmda toʻlaysiz, yulduzlar esa username boʻyicha keladi.

Parol ham, kirish kodi ham, akkauntga kirish ham kerak emas — bizga faqat ochiq foydalanuvchi nomi kifoya. Kurs va soʻmdagi yakuniy summa toʻlovdan oldin koʻrinadi, yulduzlar esa toʻlov tasdiqlangach avtomatik tushadi. Eng kichik paket — 50 yulduz: bu Telegramning oʻz cheklovi, bizniki emas.$c$,
    instructions = $c$Telegram Stars qanday sotib olinadi:

1. Paketni tanlang — 50 tadan 2500 tagacha yulduz.
2. Telegramdagi username'ingizni kiriting (masalan, @username) — parol va kirish kodi kerak emas.
3. Toʻlov usulini tanlang: Click, Payme yoki Uzum. Kurs va soʻmdagi yakun toʻlovdan oldin koʻrsatiladi.
4. Toʻlovni amalga oshiring — yulduzlar toʻlov tasdiqlangach avtomatik tushadi.

Username'ni qayerdan topish mumkin: Telegram → Sozlamalar → Foydalanuvchi nomi. Agar maydon boʻsh boʻlsa, username oʻylab topib saqlang — usiz yulduzlarni yuborib boʻlmaydi.

Yulduzlarni boshqa odamga sovgʻa qilmoqchimisiz? Oʻzingiznikining oʻrniga uning username'ini kiriting — qolgani bir xil.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'telegram-stars') AND locale = 'uz';

-- ===========================================================================
-- 2. Telegram Premium — brand translations
-- ===========================================================================

UPDATE brand_translations SET
    highlights = $c$["Оплата в сумах","По username","Без пароля","3, 6 или 12 месяцев"]$c$::json,
    short_description = $c$Telegram Premium в Узбекистане — на 3, 6 или 12 месяцев по username, оплата в сумах через Click, Payme или Uzum.$c$,
    description = $c$Telegram Premium — платная подписка Telegram, которая снимает лимиты мессенджера. Файлы до 4 ГБ вместо 2 ГБ, до 1000 каналов и групп, 20 папок, ускоренная загрузка, отключённая реклама в публичных каналах, расшифровка голосовых сообщений в текст, эксклюзивные стикеры и реакции, анимированные аватарки и значок Premium рядом с именем.

Оформить подписку напрямую из Узбекистана мешает оплата: App Store и Google Play требуют привязанную международную карту. YuPay продаёт Premium за сумы — вы платите картой Uzcard или Humo через Click, Payme или Uzum, а подписка активируется по username.

Пароль и код входа не нужны — только публичное имя пользователя. Поэтому Premium так же просто подарить: введите username друга вместо своего. Если подписка у получателя уже активна, оплаченные месяцы добавятся к текущему сроку, а не сгорят.$c$,
    instructions = $c$Как оформить Telegram Premium:

1. Выберите срок подписки: 3, 6 или 12 месяцев.
2. Введите username в Telegram (например, @username) — пароль и код входа не нужны.
3. Выберите способ оплаты: Click, Payme или Uzum. Итог в сумах показывается до оплаты.
4. Оплатите — Premium активируется автоматически после подтверждения платежа.

Где найти свой username: откройте Telegram → Настройки → Имя пользователя. Если поле пустое, придумайте username и сохраните.

Дарите подписку? Введите username получателя вместо своего — подтверждение придёт ему в Telegram.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'telegram-premium') AND locale = 'ru';

UPDATE brand_translations SET
    highlights = $c$["Pay in UZS","By username","No password","3, 6 or 12 months"]$c$::json,
    short_description = $c$Telegram Premium in Uzbekistan — 3, 6 or 12 months by username, pay in sum via Click, Payme or Uzum.$c$,
    description = $c$Telegram Premium is Telegram's paid subscription, and it mostly removes limits. Uploads up to 4 GB instead of 2 GB, up to 1000 channels and groups, 20 folders, faster downloads, no ads in public channels, voice-to-text transcription, exclusive stickers and reactions, animated profile pictures and a Premium badge next to your name.

Subscribing directly from Uzbekistan runs into payment: the App Store and Google Play want an international card on file. YuPay sells Premium for sum — you pay with an Uzcard or Humo card via Click, Payme or Uzum, and the subscription activates by username.

No password and no login code — just the public username. That is also why gifting is easy: enter your friend's username instead of your own. If the recipient's subscription is already active, the months you pay for are added to it rather than lost.$c$,
    instructions = $c$How to get Telegram Premium:

1. Choose the term: 3, 6 or 12 months.
2. Enter the Telegram username (for example @username) — no password, no login code.
3. Choose how to pay: Click, Payme or Uzum. The total in sum is shown before you pay.
4. Pay — Premium activates automatically once your payment is confirmed.

Where to find your username: open Telegram → Settings → Username. If it is empty, set one and save.

Giving it as a gift? Enter the recipient's username instead of yours — their confirmation arrives in Telegram.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'telegram-premium') AND locale = 'en';

UPDATE brand_translations SET
    highlights = $c$["Soʻmda toʻlov","Username orqali","Parolsiz","3, 6 yoki 12 oy"]$c$::json,
    short_description = $c$Oʻzbekistonda Telegram Premium — 3, 6 yoki 12 oyga username orqali, Click, Payme yoki Uzum bilan soʻmda toʻlov.$c$,
    description = $c$Telegram Premium — Telegramning pullik obunasi, u messenjer cheklovlarini olib tashlaydi. 2 GB oʻrniga 4 GB gacha fayllar, 1000 tagacha kanal va guruh, 20 ta papka, tezlashtirilgan yuklab olish, ommaviy kanallarda reklamaning oʻchirilishi, ovozli xabarlarni matnga oʻgirish, eksklyuziv stikerlar va reaksiyalar, animatsiyali avatarlar hamda ism yonidagi Premium belgisi.

Oʻzbekistondan toʻgʻridan-toʻgʻri obuna boʻlishga toʻlov halaqit beradi: App Store va Google Play xalqaro kartani talab qiladi. YuPay Premium'ni soʻmga sotadi — siz Uzcard yoki Humo kartangiz bilan Click, Payme yoki Uzum orqali toʻlaysiz, obuna esa username boʻyicha faollashadi.

Parol va kirish kodi kerak emas — faqat ochiq foydalanuvchi nomi. Shu bois obunani sovgʻa qilish ham oson: oʻzingiznikining oʻrniga doʻstingizning username'ini kiriting. Agar qabul qiluvchining obunasi allaqachon faol boʻlsa, toʻlangan oylar mavjud muddatga qoʻshiladi, yoʻqolmaydi.$c$,
    instructions = $c$Telegram Premium qanday rasmiylashtiriladi:

1. Muddatni tanlang: 3, 6 yoki 12 oy.
2. Telegramdagi username'ni kiriting (masalan, @username) — parol va kirish kodi kerak emas.
3. Toʻlov usulini tanlang: Click, Payme yoki Uzum. Soʻmdagi yakun toʻlovdan oldin koʻrsatiladi.
4. Toʻlovni amalga oshiring — Premium toʻlov tasdiqlangach avtomatik faollashadi.

Username'ni qayerdan topish mumkin: Telegram → Sozlamalar → Foydalanuvchi nomi. Agar maydon boʻsh boʻlsa, username oʻylab topib saqlang.

Sovgʻa qilyapsizmi? Oʻzingiznikining oʻrniga qabul qiluvchining username'ini kiriting — tasdiq unga Telegramda keladi.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'telegram-premium') AND locale = 'uz';

-- ===========================================================================
-- 3. Telegram Stars — FAQ
-- ===========================================================================

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'telegram-stars');

WITH tg_stars AS (
    SELECT id FROM brands WHERE slug = 'telegram-stars'
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), tg_stars.id, v.sort_order, true
    FROM tg_stars, (VALUES (1), (2), (3), (4), (5), (6), (7)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. Что это и зачем
        (1, 'ru', $q$Что такое Telegram Stars и что на них можно купить?$q$,
            $a$Stars — официальная внутренняя валюта Telegram. Звёздами платят за покупки в ботах и мини-приложениях, за платные посты и подписку на закрытые каналы, ставят звёздные реакции и отправляют подарки другим пользователям. За звёзды также оформляют подписку Telegram Premium в подарок.$a$),
        (1, 'en', $q$What are Telegram Stars and what can I buy with them?$q$,
            $a$Stars are Telegram's official in-app currency. They pay for purchases in bots and mini apps, paid posts and private channel subscriptions, star reactions, and gifts to other users. Stars also buy a Telegram Premium subscription as a gift.$a$),
        (1, 'uz', $q$Telegram Stars nima va ularga nima sotib olish mumkin?$q$,
            $a$Stars — Telegramning rasmiy ichki valyutasi. Yulduzlar bilan botlar va mini ilovalardagi xaridlar, pullik postlar va yopiq kanallarga obuna toʻlanadi, yulduzli reaksiyalar qoʻyiladi va boshqa foydalanuvchilarga sovgʻalar yuboriladi. Yulduzlarga Telegram Premium obunasini sovgʻa qilish ham mumkin.$a$),

        -- 2. Пароль — главный страх покупателя
        (2, 'ru', $q$Нужен ли пароль от Telegram или код входа?$q$,
            $a$Нет. Мы спрашиваем только публичный username — то самое имя после «@», которое видно всем в вашем профиле. Пароль, облачный пароль и код подтверждения входа не нужны и никогда не запрашиваются. Если у вас просят код из Telegram — это мошенники, а не мы.$a$),
        (2, 'en', $q$Do you need my Telegram password or login code?$q$,
            $a$No. We ask only for the public username — the handle after the “@” that everyone already sees on your profile. No password, no cloud password, no login confirmation code, ever. If someone asks you for a code from Telegram, that is a scam and it is not us.$a$),
        (2, 'uz', $q$Telegram paroli yoki kirish kodi kerakmi?$q$,
            $a$Yoʻq. Biz faqat ochiq username'ni soʻraymiz — profilingizda hammaga koʻrinadigan “@” dan keyingi nom. Parol, bulutli parol va kirish tasdigʻi kodi kerak emas va hech qachon soʻralmaydi. Agar sizdan Telegramdagi kodni soʻrashsa — bu firibgarlar, biz emas.$a$),

        -- 3. Где взять username
        (3, 'ru', $q$Как узнать свой username в Telegram?$q$,
            $a$Откройте Telegram → Настройки → Имя пользователя. Там указано ваше имя вида @username. Если поле пустое, придумайте username и сохраните — без него звёзды отправить некуда. Вводить можно как с «@», так и без него.$a$),
        (3, 'en', $q$How do I find my Telegram username?$q$,
            $a$Open Telegram → Settings → Username. Your handle looks like @username. If the field is empty, set one and save — without a username there is nowhere to send the Stars. You can type it with or without the “@”.$a$),
        (3, 'uz', $q$Telegramdagi username'imni qanday bilaman?$q$,
            $a$Telegram → Sozlamalar → Foydalanuvchi nomi boʻlimini oching. U yerda @username koʻrinishidagi nomingiz turadi. Agar maydon boʻsh boʻlsa, username oʻylab topib saqlang — usiz yulduzlarni yuborib boʻlmaydi. “@” bilan ham, usiz ham kiritish mumkin.$a$),

        -- 4. Минимум 50 — самый частый вопрос по нижней границе
        (4, 'ru', $q$Почему нельзя купить меньше 50 звёзд?$q$,
            $a$50 звёзд — минимальный перевод в самом Telegram, а не наше ограничение. Пакетов меньше не существует ни у нас, ни у кого-либо ещё. Если нужно немного больше — берите 75 или 100.$a$),
        (4, 'en', $q$Why can't I buy fewer than 50 Stars?$q$,
            $a$50 Stars is Telegram's own minimum transfer, not a limit we invented. Smaller packs do not exist here or anywhere else. If you need a little more, take 75 or 100.$a$),
        (4, 'uz', $q$Nega 50 tadan kam yulduz sotib olib boʻlmaydi?$q$,
            $a$50 yulduz — Telegramning oʻzidagi eng kichik oʻtkazma, bizning cheklovimiz emas. Bundan kichik paketlar na bizda, na boshqa joyda mavjud. Agar biroz koʻproq kerak boʻlsa, 75 yoki 100 tasini oling.$a$),

        -- 5. Подарок другому
        (5, 'ru', $q$Можно ли купить звёзды другому человеку?$q$,
            $a$Да. Введите его username вместо своего — остальное точно так же. Звёзды придут на его аккаунт, ваш при этом вообще не участвует. Так же дарят и Premium.$a$),
        (5, 'en', $q$Can I buy Stars for someone else?$q$,
            $a$Yes. Enter their username instead of yours — everything else is the same. The Stars land on their account; yours is not involved at all. Premium works the same way.$a$),
        (5, 'uz', $q$Yulduzlarni boshqa odamga sotib olsa boʻladimi?$q$,
            $a$Ha. Oʻzingiznikining oʻrniga uning username'ini kiriting — qolgani aynan bir xil. Yulduzlar uning akkauntiga tushadi, sizniki umuman ishtirok etmaydi. Premium ham xuddi shunday sovgʻa qilinadi.$a$),

        -- 6. Оплата — ядро локального интента
        (6, 'ru', $q$Как оплатить из Узбекистана без карты Visa?$q$,
            $a$Картой Uzcard или Humo через Click, Payme или Uzum — в сумах. Международная карта, App Store и Google Play не нужны: именно из-за них купить звёзды напрямую в Telegram из Узбекистана неудобно. Курс и итоговая сумма в сумах видны до оплаты.$a$),
        (6, 'en', $q$How do I pay from Uzbekistan without a Visa card?$q$,
            $a$With an Uzcard or Humo card via Click, Payme or Uzum — in sum. No international card, no App Store, no Google Play: those are exactly what makes buying Stars inside Telegram awkward from Uzbekistan. The rate and the total in sum are shown before you pay.$a$),
        (6, 'uz', $q$Oʻzbekistondan Visa kartasiz qanday toʻlayman?$q$,
            $a$Uzcard yoki Humo kartasi bilan Click, Payme yoki Uzum orqali — soʻmda. Xalqaro karta, App Store va Google Play kerak emas: aynan shular tufayli Oʻzbekistondan Telegramda toʻgʻridan-toʻgʻri yulduz sotib olish noqulay. Kurs va soʻmdagi yakuniy summa toʻlovdan oldin koʻrinadi.$a$),

        -- 7. Сроки — без обещания секунд
        (7, 'ru', $q$Когда придут звёзды?$q$,
            $a$Заказ уходит поставщику сразу после подтверждения оплаты и выполняется автоматически — обычно это минуты. Статус виден в разделе «Мои заказы», а если что-то пойдёт не так, деньги вернутся на баланс. Ничего подтверждать вручную не нужно.$a$),
        (7, 'en', $q$When do the Stars arrive?$q$,
            $a$The order goes to the supplier as soon as your payment is confirmed and is filled automatically — usually within minutes. You can follow it under “My orders”, and if anything goes wrong the money returns to your balance. Nothing needs confirming by hand.$a$),
        (7, 'uz', $q$Yulduzlar qachon keladi?$q$,
            $a$Buyurtma toʻlov tasdiqlangach darhol taʼminotchiga ketadi va avtomatik bajariladi — odatda bir necha daqiqada. Holatni “Mening buyurtmalarim” boʻlimida kuzatasiz, agar biror narsa notoʻgʻri ketsa, pul balansga qaytadi. Qoʻlda hech narsani tasdiqlash kerak emas.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

-- ===========================================================================
-- 4. Telegram Premium — FAQ
-- ===========================================================================

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'telegram-premium');

WITH tg_premium AS (
    SELECT id FROM brands WHERE slug = 'telegram-premium'
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), tg_premium.id, v.sort_order, true
    FROM tg_premium, (VALUES (1), (2), (3), (4), (5), (6), (7)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. Что даёт подписка
        (1, 'ru', $q$Что даёт Telegram Premium?$q$,
            $a$Файлы до 4 ГБ вместо 2 ГБ, до 1000 каналов и групп, 20 папок, ускоренную загрузку, отключённую рекламу в публичных каналах, расшифровку голосовых сообщений в текст, эксклюзивные стикеры и реакции, анимированные аватарки и значок Premium рядом с именем.$a$),
        (1, 'en', $q$What does Telegram Premium give me?$q$,
            $a$Uploads up to 4 GB instead of 2 GB, up to 1000 channels and groups, 20 folders, faster downloads, no ads in public channels, voice-to-text transcription, exclusive stickers and reactions, animated profile pictures and a Premium badge next to your name.$a$),
        (1, 'uz', $q$Telegram Premium nima beradi?$q$,
            $a$2 GB oʻrniga 4 GB gacha fayllar, 1000 tagacha kanal va guruh, 20 ta papka, tezlashtirilgan yuklab olish, ommaviy kanallarda reklamaning oʻchirilishi, ovozli xabarlarni matnga oʻgirish, eksklyuziv stikerlar va reaksiyalar, animatsiyali avatarlar hamda ism yonidagi Premium belgisi.$a$),

        -- 2. Пароль
        (2, 'ru', $q$Нужен ли пароль от аккаунта?$q$,
            $a$Нет. Нужен только публичный username — имя после «@» из вашего профиля. Пароль, облачный пароль и код входа мы не спрашиваем никогда. Если у вас просят код из Telegram — это мошенники.$a$),
        (2, 'en', $q$Do you need my account password?$q$,
            $a$No. Only the public username — the handle after the “@” on your profile. We never ask for a password, a cloud password or a login code. If someone asks you for a code from Telegram, that is a scam.$a$),
        (2, 'uz', $q$Akkaunt paroli kerakmi?$q$,
            $a$Yoʻq. Faqat ochiq username kerak — profilingizdagi “@” dan keyingi nom. Parol, bulutli parol va kirish kodini biz hech qachon soʻramaymiz. Agar sizdan Telegramdagi kodni soʻrashsa — bu firibgarlar.$a$),

        -- 3. Подарок — крупный сегмент спроса
        (3, 'ru', $q$Можно ли подарить Premium другому человеку?$q$,
            $a$Да, для этого ничего особенного делать не нужно: введите username получателя вместо своего. Подписка активируется на его аккаунте, уведомление придёт ему в Telegram.$a$),
        (3, 'en', $q$Can I give Premium to someone else?$q$,
            $a$Yes, and it takes nothing special: enter the recipient's username instead of your own. The subscription activates on their account and the notification arrives in their Telegram.$a$),
        (3, 'uz', $q$Premium'ni boshqa odamga sovgʻa qilsa boʻladimi?$q$,
            $a$Ha, buning uchun alohida hech narsa qilish shart emas: oʻzingiznikining oʻrniga qabul qiluvchining username'ini kiriting. Obuna uning akkauntida faollashadi, bildirishnoma unga Telegramda keladi.$a$),

        -- 4. Уже есть подписка
        (4, 'ru', $q$Что будет, если подписка уже активна?$q$,
            $a$Оплаченные месяцы добавятся к текущему сроку — подписка продлится, а не начнётся заново. Поэтому продлевать можно заранее, ничего не сгорит.$a$),
        (4, 'en', $q$What if the subscription is already active?$q$,
            $a$The months you pay for are added to the current term — the subscription extends rather than restarting. So you can renew early without losing anything.$a$),
        (4, 'uz', $q$Agar obuna allaqachon faol boʻlsa-chi?$q$,
            $a$Toʻlangan oylar joriy muddatga qoʻshiladi — obuna qaytadan boshlanmay, uzayadi. Shuning uchun oldindan uzaytirish mumkin, hech narsa yoʻqolmaydi.$a$),

        -- 5. Оплата
        (5, 'ru', $q$Как оплатить Premium в сумах?$q$,
            $a$Картой Uzcard или Humo через Click, Payme или Uzum. Международная карта и привязка к App Store или Google Play не нужны — именно они мешают оформить подписку напрямую из Узбекистана. Итоговая сумма в сумах видна до оплаты.$a$),
        (5, 'en', $q$How do I pay for Premium in sum?$q$,
            $a$With an Uzcard or Humo card via Click, Payme or Uzum. No international card and no App Store or Google Play account — those are exactly what stands in the way of subscribing directly from Uzbekistan. The total in sum is shown before you pay.$a$),
        (5, 'uz', $q$Premium uchun soʻmda qanday toʻlanadi?$q$,
            $a$Uzcard yoki Humo kartasi bilan Click, Payme yoki Uzum orqali. Xalqaro karta hamda App Store yoki Google Play'ga bogʻlanish kerak emas — aynan shular Oʻzbekistondan toʻgʻridan-toʻgʻri obuna boʻlishga xalaqit beradi. Soʻmdagi yakuniy summa toʻlovdan oldin koʻrinadi.$a$),

        -- 6. Устройства
        (6, 'ru', $q$Работает ли Premium на iPhone и Android?$q$,
            $a$Да. Подписка привязана к аккаунту Telegram, а не к устройству, поэтому она действует сразу везде, где вы вошли: на iPhone, Android, в веб-версии и на компьютере.$a$),
        (6, 'en', $q$Does Premium work on both iPhone and Android?$q$,
            $a$Yes. The subscription belongs to the Telegram account, not to a device, so it applies everywhere you are signed in at once: iPhone, Android, web and desktop.$a$),
        (6, 'uz', $q$Premium iPhone va Android'da ishlaydimi?$q$,
            $a$Ha. Obuna qurilmaga emas, Telegram akkauntiga bogʻlanadi, shuning uchun siz kirgan hamma joyda birdaniga amal qiladi: iPhone, Android, veb-versiya va kompyuterda.$a$),

        -- 7. Сроки
        (7, 'ru', $q$Когда активируется подписка?$q$,
            $a$Заказ уходит поставщику сразу после подтверждения оплаты и выполняется автоматически — обычно это минуты. Статус виден в разделе «Мои заказы», а если выдать подписку не удастся, деньги вернутся на баланс.$a$),
        (7, 'en', $q$When does the subscription activate?$q$,
            $a$The order goes to the supplier as soon as your payment is confirmed and is filled automatically — usually within minutes. You can follow it under “My orders”, and if the subscription cannot be delivered the money returns to your balance.$a$),
        (7, 'uz', $q$Obuna qachon faollashadi?$q$,
            $a$Buyurtma toʻlov tasdiqlangach darhol taʼminotchiga ketadi va avtomatik bajariladi — odatda bir necha daqiqada. Holatni “Mening buyurtmalarim” boʻlimida kuzatasiz, agar obunani berib boʻlmasa, pul balansga qaytadi.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
