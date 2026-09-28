-- Standoff 2 Gold guide: review of the Russian original, plus English and Uzbek.
--
-- Arrived from Bunzy on 2026-09-27 as a draft with slug `standoff-2`. What the
-- review changed in Russian:
--
--   * It sold a top-up "по игровому ID" with the Gold "зачисляется на баланс".
--     We sell Gold promo codes (`standoff-2-gold`, kind voucher): the code
--     arrives by email and on the order page, and the buyer redeems it in the
--     official Standoff 2 store (Sign In by account ID → Promo Code) or in the
--     game (Inventory → Shop → Promocode) — not on iPhone/iPad, where only the
--     store works. Rewritten around that, matching the brand page.
--   * It linked Axlebolt's "purchasing outside the game is prohibited" article
--     right next to our store link. The rule is kept — as the reason never to
--     buy Gold or skins from other players or with someone else's account —
--     but not the link, which read as a verdict on the product being sold.
--   * Dropped the Moloco "300 million downloads" figure (sold nothing) and
--     "ставки на Маркетплейсе" (the market is buying and selling, not bets).
--   * The package section now names our four codes (100–3000 Gold), the
--     per-Gold spread (3000 costs about half of 100 per unit) and that codes
--     are stocked per denomination, so one can be out.
--   * The closing store link pointed at `/en/store/standoff-2` from the
--     Russian text. Two filler paragraphs and most of the collecting tips went.
--
-- Links carry a locale prefix. `oplata-igr-v-sumah` exists only in Russian,
-- so en/uz point at `buy-game-top-ups-in-uzbekistan` /
-- `ozbekistonda-donat-sotib-olish`.
--
-- Also sets the brand (publish refuses without one) and the cover, rendered
-- in yupay-motion (`Cover-standoff2`) and uploaded through the admin presign
-- path. Leaves the status alone: publishing is a person pressing
-- «Опубликовать».
--
-- Idempotent: re-running rewrites all three translations and FAQ sets.

BEGIN;

\set post_id '''01a0e122-5239-74e2-871f-6a40fb579164'''

UPDATE blog_posts
SET primary_brand_id = (SELECT id FROM brands WHERE slug = 'standoff-2'),
    cover_image_url = 'https://cdn.yupay.uz/blog_image/2026/09/01a0e69d-c1ff-7bd3-ad07-e5f9465206f2.jpg',
    updated_at = now()
WHERE id = :post_id;

DELETE FROM blog_post_translations WHERE post_id = :post_id;
DELETE FROM blog_post_faqs WHERE post_id = :post_id;

-- ---------------------------------------------------------------- Russian --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'ru', 'standoff-2',
  'Standoff 2: как купить голду и открыть скины',
  'Как купить голду Standoff 2 в Узбекистане: промокод за сумы, активация в официальном магазине или в игре, что делать на iPhone и какой номинал выгоднее.',
$html$<h2>Главное</h2>
<ul>
<li>Голда (Gold) — премиум-валюта Standoff 2: за неё покупают скины на внутриигровом рынке и открывают премиальные кейсы.</li>
<li>Из Узбекистана голду удобно купить промокодом: оплата в сумах через Click, Payme или Uzum, код приходит на почту.</li>
<li>Код вы активируете сами — в официальном магазине Standoff 2 или в игре. Логин и пароль никому не нужны.</li>
<li>На iPhone и iPad код в игре не вводится — только через официальный магазин.</li>
<li>В крупных кодах голда дешевле: в коде на 3000 Gold единица стоит примерно вдвое меньше, чем в коде на 100.</li>
</ul>
<p>Купить голду Standoff 2 в Узбекистане проще всего промокодом. Вы платите в сумах, получаете код на почту и активируете его на своём аккаунте. Ниже — что такое голда, почему покупка в самой игре не всегда проходит, как активировать код и какой номинал выбрать.</p>
<h2>Что такое голда в Standoff 2</h2>
<p>Голда — премиум-валюта Standoff 2 от Axlebolt. За неё покупают скины оружия и ножей у других игроков на внутриигровом рынке и открывают премиальные кейсы. Обычная валюта, которая копится за матчи, на рынке не работает — поэтому голду в основном покупают.</p>
<p>Скины не меняют урон и характеристики оружия, это косметика. Их цена на рынке зависит от редкости и спроса, поэтому редкий предмет иногда стоит больше, чем голда, потраченная на кейс, из которого он выпал.</p>
<h2>Почему не купить прямо в игре</h2>
<p>В игре голду продают через Google Play или App Store. Для этого нужна карта, которую принимает магазин приложений: карты Uzcard и Humo там обычно не принимаются, а с валютной картой итоговую цену меняют курс и комиссия.</p>
<p>Промокод снимает эту проблему. Это код на фиксированное количество голды: его можно оплатить в сумах, а активируете вы его сами в официальном магазине Standoff 2 или в игре.</p>
<h2>Как купить голду в сумах</h2>
<ol>
<li>Откройте страницу <a href="https://yupay.uz/store/standoff-2">Standoff 2 в каталоге YuPay</a> и выберите номинал — 100, 500, 1000 или 3000 Gold. Цена в сумах видна до оплаты.</li>
<li>Укажите почту и оплатите через Click, Payme или Uzum.</li>
<li>Код придёт на почту сразу после оплаты и останется в разделе «Мои заказы».</li>
</ol>
<p>Коды — товар штучный. Если номинал закончился, кнопка покупки неактивна: заплатить за код, которого нет, не получится.</p>
<p>Как устроены локальные способы оплаты, мы разбирали в гайде про <a href="https://yupay.uz/blog/oplata-igr-v-sumah">оплату игр в сумах</a>.</p>
<h2>Как активировать промокод</h2>
<p><strong>Через официальный магазин Standoff 2</strong> — работает на любом устройстве:</p>
<ol>
<li>Откройте официальный магазин Standoff 2 и нажмите Sign In.</li>
<li>Введите ID своего игрового аккаунта и выберите аккаунт из списка.</li>
<li>Перейдите в раздел Promo Code, введите код и нажмите Apply.</li>
</ol>
<p><strong>В игре</strong> — на Android: Inventory → Shop → Promocode → введите код → Apply.</p>
<p>На iPhone и iPad активация в игре недоступна — это ограничение самой игры. Используйте официальный магазин: тот же код сработает там.</p>
<p>Код вводится целиком, вместе с дефисами. Если он не принимается, напишите нам из раздела «Мои заказы» — мы видим заказ и разберёмся.</p>
<h2>Как не потерять аккаунт</h2>
<p>Правила Standoff 2 запрещают покупать голду и скины в обход официальных способов — например, переводом у других игроков или вместе с чужим аккаунтом. За это аккаунт могут заблокировать, а потерянные предметы не возвращают.</p>
<ul>
<li>Никому не сообщайте логин, пароль и код подтверждения. Для промокода они не нужны: ID аккаунта вы вводите сами и только на официальном сайте.</li>
<li>Не покупайте аккаунты с готовыми скинами.</li>
<li>Не платите переводом на карту частному лицу за «голду по дешёвке».</li>
</ul>
<h2>Какой номинал выгоднее</h2>
<p>Сравнивайте цену одной единицы голды. Чем крупнее код, тем она ниже: в коде на 3000 Gold голда почти вдвое дешевле, чем в коде на 100.</p>
<ul>
<li>Нужен один конкретный скин — берите код, который закрывает его цену.</li>
<li>Регулярно торгуете на рынке или открываете кейсы — крупный код сэкономит больше.</li>
</ul>
<p>Кейсы — это случайность: больше голды даёт больше попыток, а не гарантию редкого предмета. Если нужен конкретный скин, часто дешевле купить его на рынке, чем выбивать из кейсов. Актуальные номиналы и наличие — на <a href="https://yupay.uz/store/standoff-2">странице Standoff 2</a>.</p>$html$,
  'Как купить голду Standoff 2 в Узбекистане за сумы',
  'Голда Standoff 2 из Узбекистана: промокод за сумы через Click, Payme или Uzum, код на почту, активация в официальном магазине или в игре, без логина и пароля.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
  (gen_random_uuid(), :post_id, 'ru', 0,
   'Что именно я покупаю — код или пополнение аккаунта?',
   'Код. Он приходит на почту и в раздел «Мои заказы», а активируете его вы сами — в официальном магазине Standoff 2 или в игре. Мы не заходим в ваш аккаунт.'),
  (gen_random_uuid(), :post_id, 'ru', 1,
   'Можно ли купить голду Standoff 2 в Узбекистане за сумы?',
   'Да. Промокоды на 100, 500, 1000 и 3000 Gold оплачиваются в сумах через Click, Payme или Uzum. Итоговая сумма видна до оплаты.'),
  (gen_random_uuid(), :post_id, 'ru', 2,
   'Почему промокод не вводится на iPhone?',
   'На iPhone и iPad активация в игре недоступна — это ограничение Standoff 2. Откройте официальный магазин в браузере, войдите по ID аккаунта и введите код в разделе Promo Code.'),
  (gen_random_uuid(), :post_id, 'ru', 3,
   'Нужен ли логин или пароль от аккаунта?',
   'Нет. Для покупки нужна только почта. ID аккаунта вы вводите сами и только на официальном сайте Standoff 2.'),
  (gen_random_uuid(), :post_id, 'ru', 4,
   'Какой номинал выгоднее?',
   'Крупный: в коде на 3000 Gold единица голды почти вдвое дешевле, чем в коде на 100. Если нужен один скин, берите код, который закрывает его цену.');

-- ---------------------------------------------------------------- English --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'en', 'standoff-2-gold',
  'Standoff 2: how to buy Gold and unlock skins',
  'How to buy Standoff 2 Gold in Uzbekistan: a promo code paid in soʻm, redeemed in the official store or in the game, what to do on iPhone, and which code is the better deal.',
$html$<h2>Key points</h2>
<ul>
<li>Gold is Standoff 2’s premium currency: it buys skins on the in-game market and opens premium cases.</li>
<li>From Uzbekistan the easy way to get Gold is a promo code: pay in soʻm with Click, Payme or Uzum, and the code arrives by email.</li>
<li>You redeem the code yourself — in the official Standoff 2 store or in the game. Nobody needs your login or password.</li>
<li>On iPhone and iPad the code can’t be entered in the game — only in the official store.</li>
<li>Bigger codes are cheaper per Gold: on the 3000 Gold code a unit costs about half of what it does on the 100 code.</li>
</ul>
<p>The simplest way to buy Standoff 2 Gold in Uzbekistan is a promo code. You pay in soʻm, get the code by email and redeem it on your own account. Below: what Gold is, why buying inside the game often fails, how to redeem the code, and which code to pick.</p>
<h2>What Gold is in Standoff 2</h2>
<p>Gold is the premium currency of Axlebolt’s Standoff 2. It buys weapon and knife skins from other players on the in-game market and opens premium cases. The regular currency you earn in matches doesn’t work on the market — which is why most Gold is bought.</p>
<p>Skins don’t change damage or weapon stats; they are cosmetic. Their market price depends on rarity and demand, so a rare item is sometimes worth more than the Gold spent on the case it dropped from.</p>
<h2>Why not buy inside the game</h2>
<p>In the game, Gold is sold through Google Play or the App Store. That needs a card the app store accepts: Uzcard and Humo usually aren’t accepted, and with a foreign-currency card the final price shifts with the exchange rate and fees.</p>
<p>A promo code solves this. It is a code for a fixed amount of Gold: you pay for it in soʻm and redeem it yourself in the official Standoff 2 store or in the game.</p>
<h2>How to buy Gold in soʻm</h2>
<ol>
<li>Open the <a href="https://yupay.uz/en/store/standoff-2">Standoff 2 page on YuPay</a> and pick a code — 100, 500, 1000 or 3000 Gold. The price in soʻm is shown before you pay.</li>
<li>Enter your email and pay with Click, Payme or Uzum.</li>
<li>The code arrives by email right after payment and stays in “My orders”.</li>
</ol>
<p>Codes are stocked one by one. If a code is sold out, the buy button is disabled — you can’t pay for a code that isn’t there.</p>
<p>We covered how local payment methods work in our guide to <a href="https://yupay.uz/en/blog/buy-game-top-ups-in-uzbekistan">buying game top-ups in Uzbekistan</a>.</p>
<h2>How to redeem the promo code</h2>
<p><strong>In the official Standoff 2 store</strong> — works on any device:</p>
<ol>
<li>Open the official Standoff 2 store and press Sign In.</li>
<li>Enter your game account ID and pick the account from the list.</li>
<li>Go to Promo Code, enter the code and press Apply.</li>
</ol>
<p><strong>In the game</strong> — on Android: Inventory → Shop → Promocode → enter the code → Apply.</p>
<p>On iPhone and iPad redeeming in the game isn’t available — a limit of the game itself. Use the official store: the same code works there.</p>
<p>Enter the code in full, dashes included. If it isn’t accepted, message us from “My orders” — we can see the order and will sort it out.</p>
<h2>How to keep your account safe</h2>
<p>Standoff 2’s rules forbid buying Gold or skins outside the official routes — from other players by transfer, or together with someone else’s account. The account can be banned for it, and lost items aren’t returned.</p>
<ul>
<li>Never share your login, password or confirmation code. A promo code doesn’t need them: you enter the account ID yourself, and only on the official site.</li>
<li>Don’t buy accounts with skins already on them.</li>
<li>Don’t pay a private person by card transfer for “cheap Gold”.</li>
</ul>
<h2>Which code is the better deal</h2>
<p>Compare the price of one unit of Gold. The bigger the code, the lower it is: on the 3000 Gold code Gold is almost half the price of the 100 code.</p>
<ul>
<li>Need one particular skin — pick the code that covers its price.</li>
<li>Trade on the market or open cases regularly — a bigger code saves more.</li>
</ul>
<p>Cases are chance: more Gold means more tries, not a guaranteed rare item. If you want a specific skin, buying it on the market is often cheaper than chasing it in cases. Current codes and stock are on the <a href="https://yupay.uz/en/store/standoff-2">Standoff 2 page</a>.</p>$html$,
  'How to buy Standoff 2 Gold in Uzbekistan in soʻm',
  'Standoff 2 Gold from Uzbekistan: a promo code paid in soʻm with Click, Payme or Uzum, code by email, redeemed in the official store or in the game, no login or password.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
  (gen_random_uuid(), :post_id, 'en', 0,
   'What exactly am I buying — a code or a top-up?',
   'A code. It arrives by email and in “My orders”, and you redeem it yourself — in the official Standoff 2 store or in the game. We never sign in to your account.'),
  (gen_random_uuid(), :post_id, 'en', 1,
   'Can I buy Standoff 2 Gold in Uzbekistan in soʻm?',
   'Yes. Promo codes for 100, 500, 1000 and 3000 Gold are paid in soʻm with Click, Payme or Uzum. The total is shown before you pay.'),
  (gen_random_uuid(), :post_id, 'en', 2,
   'Why can’t I enter the code on iPhone?',
   'On iPhone and iPad redeeming in the game isn’t available — a Standoff 2 limit. Open the official store in a browser, sign in with your account ID and enter the code under Promo Code.'),
  (gen_random_uuid(), :post_id, 'en', 3,
   'Do you need my login or password?',
   'No. All we need is an email. You enter the account ID yourself, and only on the official Standoff 2 site.'),
  (gen_random_uuid(), :post_id, 'en', 4,
   'Which code is the better deal?',
   'The bigger one: on the 3000 Gold code a unit of Gold is almost half the price of the 100 code. If you need one skin, pick the code that covers its price.');

-- ----------------------------------------------------------------- Uzbek ---

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'uz', 'standoff-2-gold-olish',
  'Standoff 2: Gold qanday sotib olinadi va skinlar ochiladi',
  'Oʻzbekistonda Standoff 2 Gold’ini qanday sotib olish: soʻmda toʻlanadigan promokod, rasmiy doʻkonda yoki oʻyinda faollashtirish, iPhone’da nima qilish va qaysi nominal foydaliroq.',
$html$<h2>Asosiysi</h2>
<ul>
<li>Gold — Standoff 2’ning premium valyutasi: u bilan oʻyin ichidagi bozorda skinlar sotib olinadi va premium keyslar ochiladi.</li>
<li>Oʻzbekistondan Gold olishning qulay yoʻli — promokod: Click, Payme yoki Uzum orqali soʻmda toʻlov, kod pochtaga keladi.</li>
<li>Kodni oʻzingiz faollashtirasiz — Standoff 2’ning rasmiy doʻkonida yoki oʻyinda. Login va parol hech kimga kerak emas.</li>
<li>iPhone va iPad’da kodni oʻyinda kiritib boʻlmaydi — faqat rasmiy doʻkon orqali.</li>
<li>Katta kodlarda Gold arzonroq: 3000 Gold’lik kodda bir birlik 100 lik koddagidan taxminan ikki baravar arzon.</li>
</ul>
<p>Oʻzbekistonda Standoff 2 Gold’ini sotib olishning eng oson yoʻli — promokod. Soʻmda toʻlaysiz, kodni pochtaga olasiz va uni oʻz akkauntingizda faollashtirasiz. Quyida — Gold nima, nega oʻyinning oʻzida xarid har doim ham oʻtmaydi, kod qanday faollashtiriladi va qaysi nominalni tanlash kerak.</p>
<h2>Standoff 2’da Gold nima</h2>
<p>Gold — Axlebolt’ning Standoff 2 oʻyinidagi premium valyuta. U bilan oʻyin ichidagi bozorda boshqa oʻyinchilardan qurol va pichoq skinlari sotib olinadi va premium keyslar ochiladi. Matchlarda yigʻiladigan oddiy valyuta bozorda ishlamaydi — shuning uchun Gold asosan sotib olinadi.</p>
<p>Skinlar zarba kuchi va qurol xususiyatlarini oʻzgartirmaydi, bu kosmetika. Ularning bozordagi narxi nodirligi va talabga bogʻliq, shuning uchun nodir buyum baʼzan u tushgan keysga sarflangan Gold’dan qimmatroq turadi.</p>
<h2>Nega oʻyinning oʻzida sotib olmaslik kerak</h2>
<p>Oʻyinda Gold Google Play yoki App Store orqali sotiladi. Buning uchun ilovalar doʻkoni qabul qiladigan karta kerak: Uzcard va Humo u yerda odatda qabul qilinmaydi, valyuta kartasida esa yakuniy narxni kurs va komissiya oʻzgartiradi.</p>
<p>Promokod bu muammoni hal qiladi. Bu belgilangan miqdordagi Gold uchun kod: uni soʻmda toʻlaysiz va Standoff 2’ning rasmiy doʻkonida yoki oʻyinda oʻzingiz faollashtirasiz.</p>
<h2>Gold’ni soʻmda qanday sotib olish</h2>
<ol>
<li><a href="https://yupay.uz/uz/store/standoff-2">YuPay’dagi Standoff 2</a> sahifasini oching va nominalni tanlang — 100, 500, 1000 yoki 3000 Gold. Soʻmdagi narx toʻlovdan oldin koʻrinadi.</li>
<li>Pochtangizni kiriting va Click, Payme yoki Uzum orqali toʻlang.</li>
<li>Kod toʻlovdan soʻng darhol pochtaga keladi va «Buyurtmalarim» boʻlimida saqlanadi.</li>
</ol>
<p>Kodlar dona-dona sotiladi. Agar nominal tugagan boʻlsa, xarid tugmasi faol boʻlmaydi — mavjud boʻlmagan kod uchun toʻlab qoʻymaysiz.</p>
<p>Mahalliy toʻlov usullari qanday ishlashini <a href="https://yupay.uz/uz/blog/ozbekistonda-donat-sotib-olish">Oʻzbekistonda donat sotib olish</a> boʻyicha qoʻllanmada koʻrib chiqqanmiz.</p>
<h2>Promokodni qanday faollashtirish</h2>
<p><strong>Standoff 2’ning rasmiy doʻkoni orqali</strong> — istalgan qurilmada ishlaydi:</p>
<ol>
<li>Standoff 2’ning rasmiy doʻkonini oching va Sign In tugmasini bosing.</li>
<li>Oʻyin akkauntingiz ID’sini kiriting va roʻyxatdan akkauntni tanlang.</li>
<li>Promo Code boʻlimiga oʻting, kodni kiriting va Apply tugmasini bosing.</li>
</ol>
<p><strong>Oʻyinda</strong> — Android’da: Inventory → Shop → Promocode → kodni kiriting → Apply.</p>
<p>iPhone va iPad’da oʻyin ichida faollashtirish mavjud emas — bu oʻyinning oʻz cheklovi. Rasmiy doʻkondan foydalaning: oʻsha kod u yerda ishlaydi.</p>
<p>Kod toʻliq, chiziqchalari bilan kiritiladi. Agar qabul qilinmasa, «Buyurtmalarim» boʻlimidan bizga yozing — buyurtmani koʻramiz va hal qilamiz.</p>
<h2>Akkauntni qanday himoya qilish</h2>
<p>Standoff 2 qoidalari Gold va skinlarni rasmiy yoʻllarni chetlab sotib olishni taqiqlaydi — masalan, boshqa oʻyinchilardan pul oʻtkazib yoki begona akkaunt bilan birga. Buning uchun akkaunt bloklanishi mumkin, yoʻqolgan buyumlar esa qaytarilmaydi.</p>
<ul>
<li>Login, parol va tasdiqlash kodini hech kimga aytmang. Promokod uchun ular kerak emas: akkaunt ID’sini oʻzingiz va faqat rasmiy saytda kiritasiz.</li>
<li>Tayyor skinli akkauntlarni sotib olmang.</li>
<li>«Arzon Gold» uchun jismoniy shaxs kartasiga pul oʻtkazmang.</li>
</ul>
<h2>Qaysi nominal foydaliroq</h2>
<p>Bir birlik Gold narxini solishtiring. Kod qancha katta boʻlsa, u shuncha past: 3000 Gold’lik kodda Gold 100 lik koddagidan deyarli ikki baravar arzon.</p>
<ul>
<li>Bitta aniq skin kerak — uning narxini qoplaydigan kodni oling.</li>
<li>Bozorda muntazam savdo qilasiz yoki keys ochasiz — katta kod koʻproq tejaydi.</li>
</ul>
<p>Keyslar — tasodif: koʻproq Gold koʻproq urinish beradi, nodir buyum kafolatini emas. Aniq skin kerak boʻlsa, uni bozorda sotib olish koʻpincha keyslardan chiqarishdan arzonroq. Amaldagi nominallar va mavjudlik — <a href="https://yupay.uz/uz/store/standoff-2">Standoff 2 sahifasida</a>.</p>$html$,
  'Oʻzbekistonda Standoff 2 Gold’ini soʻmda qanday sotib olish',
  'Oʻzbekistondan Standoff 2 Gold: Click, Payme yoki Uzum orqali soʻmda toʻlanadigan promokod, kod pochtaga, rasmiy doʻkonda yoki oʻyinda faollashtirish, login va parolsiz.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
  (gen_random_uuid(), :post_id, 'uz', 0,
   'Aynan nima sotib olaman — kodmi yoki akkauntni toʻldirishmi?',
   'Kod. U pochtaga va «Buyurtmalarim» boʻlimiga keladi, uni esa oʻzingiz faollashtirasiz — Standoff 2’ning rasmiy doʻkonida yoki oʻyinda. Biz akkauntingizga kirmaymiz.'),
  (gen_random_uuid(), :post_id, 'uz', 1,
   'Oʻzbekistonda Standoff 2 Gold’ini soʻmda sotib olish mumkinmi?',
   'Ha. 100, 500, 1000 va 3000 Gold’lik promokodlar Click, Payme yoki Uzum orqali soʻmda toʻlanadi. Yakuniy summa toʻlovdan oldin koʻrinadi.'),
  (gen_random_uuid(), :post_id, 'uz', 2,
   'Nega promokod iPhone’da kiritilmaydi?',
   'iPhone va iPad’da oʻyin ichida faollashtirish mavjud emas — bu Standoff 2 cheklovi. Brauzerda rasmiy doʻkonni oching, akkaunt ID’si bilan kiring va kodni Promo Code boʻlimida kiriting.'),
  (gen_random_uuid(), :post_id, 'uz', 3,
   'Akkaunt logini yoki paroli kerakmi?',
   'Yoʻq. Xarid uchun faqat pochta kerak. Akkaunt ID’sini oʻzingiz va faqat Standoff 2’ning rasmiy saytida kiritasiz.'),
  (gen_random_uuid(), :post_id, 'uz', 4,
   'Qaysi nominal foydaliroq?',
   'Kattasi: 3000 Gold’lik kodda bir birlik Gold 100 lik koddagidan deyarli ikki baravar arzon. Bitta skin kerak boʻlsa, uning narxini qoplaydigan kodni oling.');

COMMIT;
