-- scripts/seed/steam_gifts_seo.sql
--
-- SEO content pack for the `steam-gifts` brand: highlights + short/long
-- descriptions + instructions on `brand_translations`, and 6 FAQ entries with
-- ru/en/uz answers.
--
-- Content-managed, NOT a fixture and NOT an Alembic data migration. Applied to
-- prod by an operator (psql / `!`), gated by the standing deploy rule.
--
-- UPSERT, not UPDATE — unlike every sibling seed in this directory. Not because
-- a row was missing: all three locales exist, with correct per-locale names. An
-- upsert simply works either way, and the cost of being wrong in the other
-- direction is a seed that reports success having updated nothing.
--
-- (The "rows are missing" reading came from probing
-- `/catalog/brands/steam-gifts?locale=en`, which returned the Russian name. The
-- catalog API ignores that query parameter — it localises by `Accept-Language`,
-- which is what `apps/web/src/lib/api.ts` sends. Worth knowing before drawing a
-- conclusion from a hand-rolled curl against it.)
--
-- The conflict branch deliberately leaves `name` alone: it is supplied only so
-- the INSERT can satisfy NOT NULL on a locale that has no row yet. The names
-- already in the table are right, and are not this file's to overwrite.
--
-- Idempotent: translations upsert on (brand_id, locale); FAQs are rebuilt via
-- delete-then-insert. One transaction, so a half-run cannot leave partial
-- state. Re-running yields identical final content (FAQ row ids are
-- regenerated each run, which is fine — nothing references them).
--
-- Strings are dollar-quoted ($c$…$c$ / $q$…$q$ / $a$…$a$) so the
-- apostrophe-heavy Uzbek copy needs no escaping.
--
-- On the price claim: measured 2026-09-16 against Steam's own Uzbekistan
-- storefront (`appdetails?cc=uz`) over 21 randomly sampled titles — cheaper on
-- 17, level on 2, DEARER on 2 (Planet Zoo 2 by 9%, Armored Core VI by 3%);
-- median saving among the wins was 15%, best 54%. So the copy says "обычно" /
-- "usually" and never "always", and the page shows the price before payment
-- so a visitor can check. Do not strengthen this wording without re-measuring.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Brand translations (highlights, short_description, description, instructions)
-- ---------------------------------------------------------------------------

INSERT INTO brand_translations (brand_id, locale, name, highlights, short_description, description, instructions)
SELECT b.id, 'ru', $n$Steam Игры$n$,
    $c$["Обычно дешевле Steam","Оплата в сумах","Uzcard и Humo","Игра за минуты"]$c$::json,
    $c$Купить игры Steam в Узбекистане за сумы: более 4000 игр и дополнений, обычно дешевле, чем в самом Steam. Оплата картами Uzcard и Humo через Click, Payme и Uzum — игра приходит подарком на аккаунт Steam, обычно в течение часа.$c$,
    $c$YuPay — это покупка игр Steam в Узбекистане за сумы. В каталоге больше 4000 игр и дополнений: от крупных релизов до инди. Цены показаны в узбекских сумах, оплата — местными картами. Зарубежная карта, отдельный аккаунт и VPN не нужны: вы платите так же, как платите за всё остальное.

Почему обычно выходит дешевле. Цена игры в Steam зависит от региона аккаунта — одна и та же игра в разных регионах стоит по-разному, и цена для Узбекистана редко оказывается самой низкой. Мы продаём подарки в нескольких регионах — СНГ, Россия, Казахстан, Украина — и вы выбираете тот, что подходит получателю. Поэтому в большинстве случаев итог ниже, чем цена Steam для Узбекистана, иногда в полтора-два раза. Но не всегда: по отдельным играм разница невелика или её нет вовсе. Цену мы показываем до оплаты — сравните сами.

Что именно вы получаете. Это не ключ активации, а подарок Steam: игра приходит на аккаунт получателя и остаётся в его библиотеке навсегда. Нужна только ссылка на профиль получателя — пароль от аккаунта мы не спрашиваем никогда. Важно, чтобы регион аккаунта совпадал с регионом подарка, иначе Steam не даст его принять; регион выбирается при оформлении заказа.

Оплатить можно картами Uzcard и Humo через Click, Payme и Uzum — в сумах, без отдельной комиссии поверх цены.$c$,
    $c$Как купить игру в Steam из Узбекистана:

1. Найдите игру в каталоге — поиском по названию или просто листая список.
2. Выберите издание, если их несколько, и регион аккаунта получателя.
3. Вставьте ссылку на профиль Steam получателя. Мы покажем ник и аватар, чтобы вы убедились, что это тот человек, — мимо адресата подарок не уйдёт.
4. Оплатите картой Uzcard или Humo через Click, Payme или Uzum.
5. Дождитесь подарка — он придёт на аккаунт получателя, обычно в течение часа.

Где взять ссылку на профиль Steam: откройте Steam, нажмите на имя профиля, выберите «Просмотреть профиль» и скопируйте адрес из адресной строки. Подойдёт и ссылка-приглашение вида steamcommunity.com/user/…

Как узнать регион аккаунта: Steam → «Об аккаунте» (store.steampowered.com/account) → строка «Страна». Регион подарка должен совпадать с этой страной — иначе Steam не даст принять подарок.

Если игра оказалась дополнением (DLC): оно заработает только тогда, когда у получателя уже есть основная игра. Покупать DLC «про запас» тому, у кого основной игры нет, смысла нет.$c$
FROM brands b WHERE b.slug = 'steam-gifts'
ON CONFLICT (brand_id, locale) DO UPDATE SET
    highlights = EXCLUDED.highlights,
    short_description = EXCLUDED.short_description,
    description = EXCLUDED.description,
    instructions = EXCLUDED.instructions;

INSERT INTO brand_translations (brand_id, locale, name, highlights, short_description, description, instructions)
SELECT b.id, 'en', $n$Steam Games$n$,
    $c$["Usually cheaper than Steam","Pay in UZS","Uzcard & Humo","Delivered in minutes"]$c$::json,
    $c$Buy Steam games in Uzbekistan in sum: over 4000 games and DLC, usually cheaper than Steam itself. Pay with Uzcard or Humo via Click, Payme or Uzum — the game arrives as a Steam gift on the recipient's account, usually within an hour.$c$,
    $c$YuPay lets you buy Steam games in Uzbekistan and pay in sum. The catalogue holds over 4000 games and add-ons, from major releases to indie titles. Prices are shown in Uzbek sum and you pay with local cards — no foreign card, no second account, no VPN.

Why it usually works out cheaper. A Steam game's price depends on the account's region: the same title costs different amounts in different regions, and the Uzbekistan price is rarely the lowest of them. We sell gifts across several regions — CIS, Russia, Kazakhstan, Ukraine — and you pick the one that suits the recipient. That usually lands below Steam's own Uzbekistan price, sometimes by half. Not always, though: on some titles the gap is small or absent. The price is shown before you pay, so you can compare for yourself.

What you actually get. Not an activation key — a Steam gift. The game lands on the recipient's account and stays in their library for good. All we need is a link to their profile; we never ask for an account password. The account's region must match the gift's region or Steam will not let them accept it, and you choose that region at checkout.

Pay with Uzcard and Humo via Click, Payme and Uzum, in sum, with no separate fee on top of the price.$c$,
    $c$How to buy a Steam game from Uzbekistan:

1. Find the game in the catalogue — search by name, or just browse the list.
2. Pick the edition, if there is more than one, and the recipient's account region.
3. Paste a link to the recipient's Steam profile. We show their nickname and avatar so you can confirm it is the right person before paying.
4. Pay with an Uzcard or Humo card via Click, Payme or Uzum.
5. Wait for the gift — it reaches the recipient's account, usually within an hour.

Where to find a Steam profile link: open Steam, click the profile name, choose "View my profile" and copy the address from the address bar. An invite link of the form steamcommunity.com/user/… works too.

How to check an account's region: Steam → "Account details" (store.steampowered.com/account) → the "Country" line. The gift's region has to match that country, or Steam will refuse the gift.

If the title turns out to be DLC: it only works once the recipient already owns the base game. Buying DLC for someone who does not own the game achieves nothing.$c$
FROM brands b WHERE b.slug = 'steam-gifts'
ON CONFLICT (brand_id, locale) DO UPDATE SET
    highlights = EXCLUDED.highlights,
    short_description = EXCLUDED.short_description,
    description = EXCLUDED.description,
    instructions = EXCLUDED.instructions;

INSERT INTO brand_translations (brand_id, locale, name, highlights, short_description, description, instructions)
SELECT b.id, 'uz', $n$Steam Oʻyinlari$n$,
    $c$["Odatda Steamdan arzon","Soʻmda toʻlov","Uzcard va Humo","Bir necha daqiqada"]$c$::json,
    $c$Oʻzbekistonda Steam oʻyinlarini soʻmda sotib oling: 4000 dan ortiq oʻyin va qoʻshimcha, odatda Steamning oʻzidan arzon. Uzcard va Humo kartalari orqali Click, Payme yoki Uzum bilan toʻlang — oʻyin qabul qiluvchining Steam akkauntiga sovgʻa sifatida, odatda bir soat ichida yetib boradi.$c$,
    $c$YuPay orqali Oʻzbekistonda Steam oʻyinlarini soʻmda sotib olasiz. Katalogda 4000 dan ortiq oʻyin va qoʻshimcha bor — yirik relizlardan indi loyihalargacha. Narxlar oʻzbek soʻmida koʻrsatiladi, toʻlov mahalliy kartalar bilan. Chet el kartasi, alohida akkaunt yoki VPN kerak emas.

Nega odatda arzonroq chiqadi. Steamda oʻyin narxi akkaunt mintaqasiga bogʻliq: bitta oʻyin turli mintaqalarda turlicha turadi va Oʻzbekiston uchun narx kamdan-kam eng past boʻladi. Biz sovgʻalarni bir necha mintaqada sotamiz — MDH, Rossiya, Qozogʻiston, Ukraina — va siz qabul qiluvchiga mos keladiganini tanlaysiz. Shu sababli koʻp hollarda yakuniy narx Steamning Oʻzbekiston uchun narxidan past chiqadi, baʼzan ikki barobargacha. Lekin har doim emas: ayrim oʻyinlarda farq kichik yoki umuman yoʻq. Narxni toʻlovdan oldin koʻrsatamiz — oʻzingiz solishtiring.

Aynan nima olasiz. Bu aktivatsiya kaliti emas, balki Steam sovgʻasi: oʻyin qabul qiluvchining akkauntiga tushadi va kutubxonasida butunlay qoladi. Bizga faqat uning profiliga havola kerak — akkaunt parolini hech qachon soʻramaymiz. Akkaunt mintaqasi sovgʻa mintaqasiga mos kelishi shart, aks holda Steam uni qabul qilishga ruxsat bermaydi; mintaqa buyurtma rasmiylashtirishda tanlanadi.

Toʻlov — Uzcard va Humo kartalari orqali Click, Payme va Uzum bilan, soʻmda, narx ustiga alohida komissiyasiz.$c$,
    $c$Oʻzbekistondan Steam oʻyinini qanday sotib olish kerak:

1. Katalogdan oʻyinni toping — nomi boʻyicha qidiring yoki roʻyxatni koʻrib chiqing.
2. Agar bir nechta boʻlsa, nashrni va qabul qiluvchi akkaunti mintaqasini tanlang.
3. Qabul qiluvchining Steam profiliga havolani joylashtiring. Biz uning taxallusi va avatarini koʻrsatamiz — toʻlovdan oldin toʻgʻri odam ekaniga ishonch hosil qilasiz.
4. Uzcard yoki Humo kartasi bilan Click, Payme yoki Uzum orqali toʻlang.
5. Sovgʻani kuting — u qabul qiluvchining akkauntiga, odatda bir soat ichida yetib boradi.

Steam profiliga havolani qayerdan olish kerak: Steamni oching, profil nomini bosing, «Profilni koʻrish» ni tanlang va manzil satridan havolani nusxalang. steamcommunity.com/user/… koʻrinishidagi taklif havolasi ham boʻladi.

Akkaunt mintaqasini qanday bilish mumkin: Steam → «Akkaunt haqida» (store.steampowered.com/account) → «Mamlakat» qatori. Sovgʻa mintaqasi shu mamlakat bilan mos kelishi kerak, aks holda Steam sovgʻani qabul qildirmaydi.

Agar oʻyin qoʻshimcha (DLC) boʻlib chiqsa: u faqat qabul qiluvchida asosiy oʻyin bor boʻlgandagina ishlaydi. Asosiy oʻyini yoʻq odamga DLC sotib olishdan foyda yoʻq.$c$
FROM brands b WHERE b.slug = 'steam-gifts'
ON CONFLICT (brand_id, locale) DO UPDATE SET
    highlights = EXCLUDED.highlights,
    short_description = EXCLUDED.short_description,
    description = EXCLUDED.description,
    instructions = EXCLUDED.instructions;

-- ---------------------------------------------------------------------------
-- 2. FAQ entries (6, each in ru/en/uz)
-- ---------------------------------------------------------------------------

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'steam-gifts');

WITH gifts AS (
    SELECT id FROM brands WHERE slug = 'steam-gifts'
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), gifts.id, v.sort_order, true
    FROM gifts, (VALUES (1), (2), (3), (4), (5), (6)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. Почему дешевле Steam
        (1, 'ru', $q$Почему у вас дешевле, чем в Steam?$q$,
            $a$Цена игры в Steam зависит от региона аккаунта: одна и та же игра в разных регионах стоит по-разному, и цена для Узбекистана редко самая низкая. Мы продаём подарки в нескольких регионах, и вы выбираете подходящий получателю. В большинстве случаев так выходит дешевле, чем покупать напрямую, иногда в полтора-два раза — но не всегда: по отдельным играм разницы почти нет. Цена видна до оплаты, так что сравнить можно заранее.$a$),
        (1, 'en', $q$Why is it cheaper here than on Steam?$q$,
            $a$A Steam game's price depends on the account's region: the same title costs different amounts in different regions, and the Uzbekistan price is rarely the lowest. We sell gifts across several regions and you pick the one that suits the recipient. That usually comes out below buying directly, sometimes by half — but not always: on some titles there is barely a gap. The price is shown before you pay, so you can compare up front.$a$),
        (1, 'uz', $q$Nega sizda Steamdan arzonroq?$q$,
            $a$Steamda oʻyin narxi akkaunt mintaqasiga bogʻliq: bitta oʻyin turli mintaqalarda turlicha turadi va Oʻzbekiston uchun narx kamdan-kam eng past boʻladi. Biz sovgʻalarni bir necha mintaqada sotamiz, siz esa qabul qiluvchiga mos keladiganini tanlaysiz. Koʻp hollarda bu toʻgʻridan-toʻgʻri sotib olishdan arzonroq, baʼzan ikki barobargacha — lekin har doim emas: ayrim oʻyinlarda farq deyarli yoʻq. Narx toʻlovdan oldin koʻrinadi, shuning uchun oldindan solishtirish mumkin.$a$),

        -- 2. Ключ или подарок
        (2, 'ru', $q$Это ключ активации или подарок Steam?$q$,
            $a$Подарок Steam. Игра приходит прямо на аккаунт получателя и остаётся в его библиотеке навсегда — вводить ключ никуда не нужно. Поэтому нам нужна ссылка на профиль получателя, а не его логин и тем более не пароль.$a$),
        (2, 'en', $q$Is this an activation key or a Steam gift?$q$,
            $a$A Steam gift. The game lands directly on the recipient's account and stays in their library for good — there is no key to enter anywhere. That is why we need a link to their profile, not their login, and certainly not their password.$a$),
        (2, 'uz', $q$Bu aktivatsiya kalitimi yoki Steam sovgʻasimi?$q$,
            $a$Steam sovgʻasi. Oʻyin toʻgʻridan-toʻgʻri qabul qiluvchining akkauntiga tushadi va kutubxonasida butunlay qoladi — hech qayerga kalit kiritish shart emas. Shuning uchun bizga uning profiliga havola kerak, login emas va, albatta, parol ham emas.$a$),

        -- 3. Регион аккаунта
        (3, 'ru', $q$Какой регион аккаунта нужен получателю?$q$,
            $a$Регион подарка должен совпадать со страной аккаунта получателя — иначе Steam не даст подарок принять. Проверить страну можно так: Steam → «Об аккаунте» (store.steampowered.com/account) → строка «Страна». Регион выбирается при оформлении заказа; мы продаём в СНГ, России, Казахстане и Украине, набор доступных регионов зависит от конкретной игры.$a$),
        (3, 'en', $q$Which account region does the recipient need?$q$,
            $a$The gift's region has to match the country on the recipient's account, or Steam will not let them accept it. To check: Steam → "Account details" (store.steampowered.com/account) → the "Country" line. You choose the region at checkout; we sell across the CIS, Russia, Kazakhstan and Ukraine, and which of those are available depends on the individual game.$a$),
        (3, 'uz', $q$Qabul qiluvchiga qaysi akkaunt mintaqasi kerak?$q$,
            $a$Sovgʻa mintaqasi qabul qiluvchi akkauntidagi mamlakat bilan mos kelishi kerak, aks holda Steam uni qabul qildirmaydi. Tekshirish: Steam → «Akkaunt haqida» (store.steampowered.com/account) → «Mamlakat» qatori. Mintaqa buyurtma rasmiylashtirishda tanlanadi; biz MDH, Rossiya, Qozogʻiston va Ukrainada sotamiz, mavjud mintaqalar toʻplami aniq oʻyinga bogʻliq.$a$),

        -- 4. Сроки
        (4, 'ru', $q$Как быстро придёт игра?$q$,
            $a$Обычно в течение часа после оплаты. Подарок приходит на аккаунт получателя, и о готовности мы сообщаем в заказе. Если что-то идёт не так — например, регион аккаунта не совпал, — заказ не зависает молча: с вами свяжется поддержка.$a$),
        (4, 'en', $q$How quickly does the game arrive?$q$,
            $a$Usually within an hour of payment. The gift reaches the recipient's account and the order tells you when it is done. If something goes wrong — a region mismatch, say — the order does not just hang in silence: support gets in touch.$a$),
        (4, 'uz', $q$Oʻyin qanchalik tez yetib boradi?$q$,
            $a$Odatda toʻlovdan keyin bir soat ichida. Sovgʻa qabul qiluvchining akkauntiga tushadi, tayyor boʻlgani haqida buyurtmada xabar beramiz. Agar nimadir notoʻgʻri ketsa — masalan, akkaunt mintaqasi mos kelmasa — buyurtma jimgina osilib qolmaydi: qoʻllab-quvvatlash xizmati siz bilan bogʻlanadi.$a$),

        -- 5. Пароль / безопасность
        (5, 'ru', $q$Нужен ли пароль от аккаунта Steam?$q$,
            $a$Нет, никогда. Для подарка достаточно публичной ссылки на профиль получателя. Если кто-то просит у вас пароль от Steam ради покупки игры — это мошенники, у нас такого запроса быть не может.$a$),
        (5, 'en', $q$Do you need my Steam account password?$q$,
            $a$No, never. A public link to the recipient's profile is all a gift needs. If anyone asks for your Steam password in order to buy you a game, they are scamming you — we will never make that request.$a$),
        (5, 'uz', $q$Steam akkaunti paroli kerakmi?$q$,
            $a$Yoʻq, hech qachon. Sovgʻa uchun qabul qiluvchi profiliga ochiq havola yetarli. Agar kimdir oʻyin sotib olish uchun sizdan Steam parolini soʻrasa — bu firibgarlar, bizda bunday soʻrov boʻlishi mumkin emas.$a$),

        -- 6. Если подарок не приняли
        (6, 'ru', $q$Что будет, если получатель не примет подарок?$q$,
            $a$Непринятый подарок не пропадает: он висит в предложениях у получателя, пока тот его не примет или не отклонит. Если принять не получается — чаще всего из-за несовпадения региона — напишите в поддержку, разберёмся с конкретным заказом. Чтобы такого не было, проверьте страну аккаунта до оплаты.$a$),
        (6, 'en', $q$What if the recipient does not accept the gift?$q$,
            $a$An unaccepted gift is not lost: it sits in the recipient's pending gifts until they accept or decline it. If they cannot accept it — usually a region mismatch — message support and we will sort out that specific order. To avoid it entirely, check the account's country before paying.$a$),
        (6, 'uz', $q$Agar qabul qiluvchi sovgʻani qabul qilmasa nima boʻladi?$q$,
            $a$Qabul qilinmagan sovgʻa yoʻqolmaydi: u qabul qiluvchida kutilayotgan sovgʻalar orasida, qabul qilinguncha yoki rad etilguncha turadi. Agar qabul qilib boʻlmasa — koʻpincha mintaqa mos kelmagani uchun — qoʻllab-quvvatlash xizmatiga yozing, aniq buyurtma boʻyicha hal qilamiz. Bunday boʻlmasligi uchun toʻlovdan oldin akkaunt mamlakatini tekshiring.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
