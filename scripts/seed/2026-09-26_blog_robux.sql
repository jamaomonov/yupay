-- Robux guide: review of the Russian original, plus English and Uzbek.
--
-- Arrived from Bunzy on 2026-09-26 as a draft with slug `robux-roblox`. What
-- the review changed in Russian:
--
--   * It described a direct top-up — "Robux зачисляются на ваш профиль", "нужен
--     только идентификатор аккаунта". We sell global Roblox gift cards: a code
--     arrives by email and on the order page, the buyer redeems it at
--     roblox.com/redeem, and the Robux land on the balance straight away
--     ("50 will be added to your balance" — checked on a real redemption
--     2026-09-26; no Roblox Credit step, whatever the brand FAQ says).
--   * Dropped the "$1.5 billion paid to creators in 2025, +63%" figure: it
--     could not be traced to the linked Roblox page, and it sold nothing.
--   * The package section was generic. Now it names our range (50–24 000
--     Robux) and the one number that matters — per Robux, the 10 000 card
--     costs about half of the 50 one — and says the curve is not monotonic,
--     which our price list shows (1500 and 3000 sit above their neighbours).
--   * The closing store link pointed at `/en/store/roblox` from the Russian
--     text — the same locale bug as in the Genshin and Steam posts.
--   * Two filler paragraphs went.
--
-- Links carry a locale prefix. `oplata-igr-v-sumah` exists only in Russian,
-- so en/uz point at `buy-game-top-ups-in-uzbekistan` /
-- `ozbekistonda-donat-sotib-olish`, as the Steam translations did.
--
-- Also sets the brand (publish refuses without one) and the cover, rendered
-- in yupay-motion (`Cover-robux`) and uploaded through the admin presign path.
-- Leaves the status alone: publishing is a person pressing «Опубликовать».
--
-- Idempotent: re-running rewrites all three translations and FAQ sets.

BEGIN;

\set post_id '''01a0dbc5-06bd-72e0-bcce-aa861c8925f0'''

UPDATE blog_posts
SET primary_brand_id = (SELECT id FROM brands WHERE slug = 'roblox'),
    cover_image_url = 'https://cdn.yupay.uz/blog_image/2026/09/01a0dd00-d262-7ce1-a709-66fa2c3784e0.jpg',
    updated_at = now()
WHERE id = :post_id;

DELETE FROM blog_post_translations WHERE post_id = :post_id;
DELETE FROM blog_post_faqs WHERE post_id = :post_id;

-- ---------------------------------------------------------------- Russian --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'ru', 'robux-roblox',
  'Как купить Robux в Roblox из Узбекистана',
  'Как купить Robux из Узбекистана за сумы без валютной карты: подарочная карта Roblox, активация кода и какой номинал выгоднее.',
$html$<h2>Главное</h2>
<ul>
<li>Robux — внутренняя валюта Roblox: за неё покупают одежду и аксессуары для аватара, игровые пропуска и предметы внутри игр.</li>
<li>Из Узбекистана Robux проще всего купить подарочной картой Roblox: оплата в сумах через Click, Payme или Uzum, валютная карта не нужна.</li>
<li>Код приходит на почту и на страницу заказа, а активируете его вы сами на roblox.com/redeem. Пароль от аккаунта никому не нужен.</li>
<li>После активации Robux сразу зачисляются на баланс аккаунта.</li>
<li>В крупных номиналах Robux дешевле: в карте на 10 000 один Robux стоит примерно вдвое меньше, чем в карте на 50.</li>
</ul>
<p>Купить Robux в Узбекистане без валютной карты можно через глобальную подарочную карту Roblox. Вы платите в сумах привычным способом, получаете код и активируете его на сайте Roblox под своим аккаунтом. Ниже — что такое Robux, почему покупка в самом приложении не всегда проходит, как активировать код и какой номинал выбрать.</p>
<h2>Что такое Robux</h2>
<p>Robux — внутренняя валюта платформы Roblox. За неё покупают одежду и аксессуары для аватара, игровые пропуска, ускорители и платные возможности внутри пользовательских игр. Получить Robux можно покупкой, подпиской Roblox Premium или заработать как создатель игр.</p>
<p>Когда игрок тратит Robux внутри игры, часть суммы получает её разработчик — на этом держится вся экономика Roblox.</p>
<h2>Почему не купить прямо в приложении</h2>
<p>Покупка Robux в приложении требует карты, которую принимают международные платёжные системы. У многих игроков в Узбекистане такой карты нет, а если есть — итоговую цену меняют курс и комиссия банка.</p>
<p>Подарочная карта снимает эту проблему. Это код на фиксированную сумму: его можно оплатить в сумах, а Roblox примет его как обычный платёж. Мы продаём глобальные карты — они не привязаны к стране аккаунта и подходят для аккаунта из Узбекистана.</p>
<h2>Как купить Robux в сумах</h2>
<ol>
<li>Откройте страницу <a href="https://yupay.uz/store/roblox">Roblox в каталоге YuPay</a> и выберите номинал — от 50 до 24 000 Robux. Цена в сумах видна до оплаты, комиссии сверху нет.</li>
<li>Укажите почту и оплатите через Click, Payme или Uzum.</li>
<li>Код придёт на почту сразу после оплаты и появится на странице заказа.</li>
</ol>
<p>Как устроены локальные способы оплаты, мы разбирали в гайде про <a href="https://yupay.uz/blog/oplata-igr-v-sumah">оплату игр в сумах</a>.</p>
<h2>Как активировать код</h2>
<ol>
<li>Откройте <a href="https://www.roblox.com/redeem">roblox.com/redeem</a> в браузере — с телефона тоже подойдёт. В самом приложении Roblox поля для кода нет, исключение — устройства Samsung Galaxy.</li>
<li>Войдите в аккаунт, на который нужны Robux, и проверьте имя в правом верхнем углу: перенести баланс на другой аккаунт потом нельзя.</li>
<li>Введите код и нажмите «Redeem».</li>
</ol>
<p>Roblox покажет «Code Successfully Redeemed» и сколько Robux добавлено — они сразу появятся на балансе. Если значок баланса ещё не обновился, перезагрузите страницу.</p>
<h2>Как не потерять аккаунт</h2>
<p>Roblox прямо предупреждает: сайты и предложения с «бесплатными Robux» — мошенничество. Чаще всего они выманивают логин и пароль, после чего аккаунт уводят.</p>
<ul>
<li>Никому не сообщайте пароль. Нормальному продавцу он не нужен: код вы активируете сами.</li>
<li>Включите двухфакторную аутентификацию в настройках Roblox.</li>
<li>Обещания удвоить Robux или выдать их бесплатно — повод закрыть страницу.</li>
</ul>
<h2>Какой номинал выгоднее</h2>
<p>Сравнивайте не итоговую сумму, а цену одного Robux. У нас в крупных картах он заметно дешевле: в карте на 10 000 Robux — примерно вдвое дешевле, чем в карте на 50. Но правило работает не на каждом шаге — некоторые средние номиналы выходят дороже соседних, поэтому перед покупкой стоит сравнить пару вариантов.</p>
<p>Простое правило: прикиньте, сколько Robux вы тратите за месяц, и берите карту, которая покрывает этот расход с запасом. Одна крупная карта обычно выгоднее нескольких мелких. Актуальные номиналы и цены — на <a href="https://yupay.uz/store/roblox">странице Roblox</a>.</p>$html$,
  'Как купить Robux в Узбекистане за сумы',
  'Robux из Узбекистана без валютной карты: подарочная карта Roblox за сумы через Click, Payme или Uzum, код на почту и активация на roblox.com/redeem — Robux сразу на балансе.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
  (gen_random_uuid(), :post_id, 'ru', 0,
   'Можно ли купить Robux в Узбекистане за сумы?',
   'Да. На YuPay продаются глобальные подарочные карты Roblox: оплата в сумах через Click, Payme или Uzum, валютная карта не нужна. Код приходит на почту и на страницу заказа.'),
  (gen_random_uuid(), :post_id, 'ru', 1,
   'Когда Robux появятся на аккаунте?',
   'Сразу после активации кода: Roblox пишет, сколько Robux добавлено на баланс. Если значок баланса не обновился, перезагрузите страницу.'),
  (gen_random_uuid(), :post_id, 'ru', 2,
   'Где вводить код?',
   'На roblox.com/redeem в браузере, в том числе с телефона. В приложении Roblox поля для кода нет, кроме устройств Samsung Galaxy. Сначала убедитесь, что вошли в нужный аккаунт: перенести баланс потом нельзя.'),
  (gen_random_uuid(), :post_id, 'ru', 3,
   'Нужен ли пароль от аккаунта Roblox?',
   'Нет. Вы получаете код и активируете его сами. Любой сервис, который просит пароль от игрового аккаунта, — повод насторожиться.'),
  (gen_random_uuid(), :post_id, 'ru', 4,
   'Правда ли, что можно получить бесплатные Robux?',
   'Нет. Roblox предупреждает, что сайты с бесплатными Robux — мошенничество. Robux можно купить, получить с подпиской Premium или заработать как создатель игр.');

-- ---------------------------------------------------------------- English --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'en', 'buy-robux-in-uzbekistan',
  'How to buy Robux in Roblox from Uzbekistan',
  'How to buy Robux from Uzbekistan in soʻm without a foreign-currency card: a Roblox gift card, redeeming the code, and which card is the better deal.',
$html$<h2>Key points</h2>
<ul>
<li>Robux is Roblox’s in-game currency: it buys avatar clothing and accessories, game passes and items inside experiences.</li>
<li>From Uzbekistan the easiest way to get Robux is a Roblox gift card, paid in soʻm with Click, Payme or Uzum — no foreign-currency card needed.</li>
<li>The code arrives by email and on the order page, and you redeem it yourself at roblox.com/redeem. Nobody needs your password.</li>
<li>Once redeemed, the Robux go straight to your account balance.</li>
<li>Bigger cards are cheaper per Robux: on the 10,000 card one Robux costs about half of what it does on the 50 card.</li>
</ul>
<p>You can buy Robux in Uzbekistan without a foreign-currency card by using a global Roblox gift card. You pay in soʻm the way you always do, get a code, and redeem it on the Roblox website under your own account. Below: what Robux is, why buying inside the app often fails, how to redeem the code, and which card to pick.</p>
<h2>What Robux is</h2>
<p>Robux is the currency of the Roblox platform. It buys avatar clothing and accessories, game passes, boosts and paid features inside user-made games. You can buy Robux, receive them with a Roblox Premium subscription, or earn them as a creator.</p>
<p>When a player spends Robux in a game, part of it goes to that game’s developer — the whole Roblox economy runs on this.</p>
<h2>Why not buy inside the app</h2>
<p>Buying Robux in the app requires a card accepted by international payment networks. Many players in Uzbekistan don’t have one, and those who do see the final price shift with the exchange rate and bank fees.</p>
<p>A gift card solves this. It is a code for a fixed amount: you pay for it in soʻm, and Roblox accepts it like any other payment. We sell global cards — they are not tied to the account’s country and work for accounts from Uzbekistan.</p>
<h2>How to buy Robux in soʻm</h2>
<ol>
<li>Open the <a href="https://yupay.uz/en/store/roblox">Roblox page on YuPay</a> and pick a card — from 50 to 24,000 Robux. The price in soʻm is shown before you pay, with no fee on top.</li>
<li>Enter your email and pay with Click, Payme or Uzum.</li>
<li>The code arrives by email right after payment and appears on the order page.</li>
</ol>
<p>We covered how local payment methods work in our guide to <a href="https://yupay.uz/en/blog/buy-game-top-ups-in-uzbekistan">buying game top-ups in Uzbekistan</a>.</p>
<h2>How to redeem the code</h2>
<ol>
<li>Open <a href="https://www.roblox.com/redeem">roblox.com/redeem</a> in a browser — a phone browser works too. The Roblox app itself has no field for codes, except on Samsung Galaxy devices.</li>
<li>Sign in to the account that needs the Robux and check the name in the top-right corner: the balance can’t be moved to another account later.</li>
<li>Enter the code and press “Redeem”.</li>
</ol>
<p>Roblox shows “Code Successfully Redeemed” and how many Robux were added — they land on your balance right away. If the balance icon hasn’t updated yet, reload the page.</p>
<h2>How to keep your account safe</h2>
<p>Roblox is explicit: sites and offers promising “free Robux” are scams. Most of them are after your login and password, and the account is gone soon after.</p>
<ul>
<li>Never share your password. A legitimate seller doesn’t need it: you redeem the code yourself.</li>
<li>Turn on two-step verification in your Roblox settings.</li>
<li>Promises to double your Robux or hand them out for free are a reason to close the page.</li>
</ul>
<h2>Which card is the better deal</h2>
<p>Compare the price of one Robux, not the total. On our cards it drops noticeably as the card grows: on the 10,000 Robux card it is about half the price of the 50 card. The rule doesn’t hold at every step, though — some mid-sized cards cost more per Robux than their neighbours, so compare a couple of options before you buy.</p>
<p>A simple rule: estimate how many Robux you spend a month and pick a card that covers it with some room to spare. One large card is usually cheaper than several small ones. Current cards and prices are on the <a href="https://yupay.uz/en/store/roblox">Roblox page</a>.</p>$html$,
  'How to buy Robux in Uzbekistan in soʻm',
  'Robux from Uzbekistan without a foreign-currency card: a Roblox gift card paid in soʻm with Click, Payme or Uzum, code by email, redeemed at roblox.com/redeem — Robux straight to your balance.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
  (gen_random_uuid(), :post_id, 'en', 0,
   'Can I buy Robux in Uzbekistan in soʻm?',
   'Yes. YuPay sells global Roblox gift cards: you pay in soʻm with Click, Payme or Uzum, no foreign-currency card needed. The code arrives by email and on the order page.'),
  (gen_random_uuid(), :post_id, 'en', 1,
   'When do the Robux show up on my account?',
   'Right after you redeem the code: Roblox tells you how many Robux were added to your balance. If the balance icon hasn’t updated, reload the page.'),
  (gen_random_uuid(), :post_id, 'en', 2,
   'Where do I enter the code?',
   'At roblox.com/redeem in a browser, including on a phone. The Roblox app has no code field except on Samsung Galaxy devices. Make sure you are signed in to the right account first: the balance can’t be moved later.'),
  (gen_random_uuid(), :post_id, 'en', 3,
   'Do you need my Roblox password?',
   'No. You get a code and redeem it yourself. Any service asking for your game account password is a red flag.'),
  (gen_random_uuid(), :post_id, 'en', 4,
   'Is it true you can get free Robux?',
   'No. Roblox warns that sites offering free Robux are scams. Robux can be bought, received with Premium, or earned as a creator.');

-- ----------------------------------------------------------------- Uzbek ---

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'uz', 'robux-sotib-olish',
  'Oʻzbekistondan Roblox’da Robux qanday sotib olinadi',
  'Oʻzbekistondan Robux’ni valyuta kartasisiz soʻmda qanday sotib olish: Roblox sovgʻa kartasi, kodni faollashtirish va qaysi nominal foydaliroq.',
$html$<h2>Asosiysi</h2>
<ul>
<li>Robux — Roblox’ning ichki valyutasi: u bilan avatar uchun kiyim va aksessuarlar, oʻyin propusklari va oʻyin ichidagi buyumlar sotib olinadi.</li>
<li>Oʻzbekistondan Robux olishning eng oson yoʻli — Roblox sovgʻa kartasi: Click, Payme yoki Uzum orqali soʻmda toʻlov, valyuta kartasi kerak emas.</li>
<li>Kod pochtaga va buyurtma sahifasiga keladi, uni roblox.com/redeem’da oʻzingiz faollashtirasiz. Akkaunt paroli hech kimga kerak emas.</li>
<li>Faollashtirilgach, Robux darhol akkaunt balansiga tushadi.</li>
<li>Katta nominallarda Robux arzonroq: 10 000 lik kartada bitta Robux 50 lik kartadagidan taxminan ikki baravar arzon.</li>
</ul>
<p>Oʻzbekistonda Robux’ni valyuta kartasisiz global Roblox sovgʻa kartasi orqali sotib olish mumkin. Odatdagidek soʻmda toʻlaysiz, kod olasiz va uni Roblox saytida oʻz akkauntingiz ostida faollashtirasiz. Quyida — Robux nima, nega ilovaning oʻzida xarid har doim ham oʻtmaydi, kod qanday faollashtiriladi va qaysi nominalni tanlash kerak.</p>
<h2>Robux nima</h2>
<p>Robux — Roblox platformasining valyutasi. U bilan avatar uchun kiyim va aksessuarlar, oʻyin propusklari, tezlatgichlar va foydalanuvchi oʻyinlari ichidagi pullik imkoniyatlar sotib olinadi. Robux’ni sotib olish, Roblox Premium obunasi bilan olish yoki oʻyin yaratuvchisi sifatida ishlab topish mumkin.</p>
<p>Oʻyinchi oʻyin ichida Robux sarflaganda, uning bir qismini shu oʻyinning dasturchisi oladi — Roblox’ning butun iqtisodiyoti shunga tayanadi.</p>
<h2>Nega ilovaning oʻzida sotib olmaslik kerak</h2>
<p>Ilovada Robux sotib olish uchun xalqaro toʻlov tizimlari qabul qiladigan karta kerak. Oʻzbekistondagi koʻp oʻyinchilarda bunday karta yoʻq, borlarida esa yakuniy narxni kurs va bank komissiyasi oʻzgartiradi.</p>
<p>Sovgʻa kartasi bu muammoni hal qiladi. Bu belgilangan summaga kod: uni soʻmda toʻlaysiz, Roblox esa uni oddiy toʻlov sifatida qabul qiladi. Biz global kartalarni sotamiz — ular akkaunt mamlakatiga bogʻlanmagan va Oʻzbekistondagi akkauntlarga mos keladi.</p>
<h2>Robux’ni soʻmda qanday sotib olish</h2>
<ol>
<li><a href="https://yupay.uz/uz/store/roblox">YuPay’dagi Roblox</a> sahifasini oching va nominalni tanlang — 50 dan 24 000 Robux’gacha. Soʻmdagi narx toʻlovdan oldin koʻrinadi, ustama komissiya yoʻq.</li>
<li>Pochtangizni kiriting va Click, Payme yoki Uzum orqali toʻlang.</li>
<li>Kod toʻlovdan soʻng darhol pochtaga keladi va buyurtma sahifasida paydo boʻladi.</li>
</ol>
<p>Mahalliy toʻlov usullari qanday ishlashini <a href="https://yupay.uz/uz/blog/ozbekistonda-donat-sotib-olish">Oʻzbekistonda donat sotib olish</a> boʻyicha qoʻllanmada koʻrib chiqqanmiz.</p>
<h2>Kodni qanday faollashtirish</h2>
<ol>
<li>Brauzerda <a href="https://www.roblox.com/redeem">roblox.com/redeem</a> sahifasini oching — telefon brauzeri ham boʻladi. Roblox ilovasining oʻzida kod uchun maydon yoʻq, Samsung Galaxy qurilmalari bundan mustasno.</li>
<li>Robux kerak boʻlgan akkauntga kiring va oʻng yuqori burchakdagi ismni tekshiring: balansni keyin boshqa akkauntga oʻtkazib boʻlmaydi.</li>
<li>Kodni kiriting va «Redeem» tugmasini bosing.</li>
</ol>
<p>Roblox «Code Successfully Redeemed» deb yozadi va qancha Robux qoʻshilganini koʻrsatadi — ular darhol balansda paydo boʻladi. Agar balans belgisi hali yangilanmagan boʻlsa, sahifani qayta yuklang.</p>
<h2>Akkauntni qanday himoya qilish</h2>
<p>Roblox ochiq ogohlantiradi: «bepul Robux» va’da qiladigan saytlar va takliflar — firibgarlik. Ularning aksariyati login va parolingizni oladi, keyin akkaunt oʻgʻirlanadi.</p>
<ul>
<li>Parolingizni hech kimga aytmang. Halol sotuvchiga u kerak emas: kodni oʻzingiz faollashtirasiz.</li>
<li>Roblox sozlamalarida ikki bosqichli tasdiqlashni yoqing.</li>
<li>Robux’ni ikki baravar koʻpaytirish yoki bepul berish va’dalari — sahifani yopish uchun sabab.</li>
</ul>
<h2>Qaysi nominal foydaliroq</h2>
<p>Yakuniy summani emas, bitta Robux narxini solishtiring. Bizda katta kartalarda u sezilarli arzonroq: 10 000 Robux’lik kartada 50 lik kartadagidan taxminan ikki baravar arzon. Lekin bu qoida har bir qadamda ishlamaydi — baʼzi oʻrta nominallar qoʻshnilaridan qimmatroq chiqadi, shuning uchun xariddan oldin bir-ikki variantni solishtirib koʻring.</p>
<p>Oddiy qoida: oyiga qancha Robux sarflashingizni chamalang va bu xarajatni zaxira bilan qoplaydigan kartani oling. Bitta katta karta odatda bir nechta kichigidan foydaliroq. Amaldagi nominallar va narxlar — <a href="https://yupay.uz/uz/store/roblox">Roblox sahifasida</a>.</p>$html$,
  'Oʻzbekistonda Robux’ni soʻmda qanday sotib olish',
  'Oʻzbekistondan valyuta kartasisiz Robux: Click, Payme yoki Uzum orqali soʻmda toʻlanadigan Roblox sovgʻa kartasi, kod pochtaga va roblox.com/redeem’da faollashtirish — Robux darhol balansda.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
  (gen_random_uuid(), :post_id, 'uz', 0,
   'Oʻzbekistonda Robux’ni soʻmda sotib olish mumkinmi?',
   'Ha. YuPay’da global Roblox sovgʻa kartalari sotiladi: Click, Payme yoki Uzum orqali soʻmda toʻlov, valyuta kartasi kerak emas. Kod pochtaga va buyurtma sahifasiga keladi.'),
  (gen_random_uuid(), :post_id, 'uz', 1,
   'Robux akkauntda qachon paydo boʻladi?',
   'Kodni faollashtirgandan soʻng darhol: Roblox balansga qancha Robux qoʻshilganini yozadi. Agar balans belgisi yangilanmagan boʻlsa, sahifani qayta yuklang.'),
  (gen_random_uuid(), :post_id, 'uz', 2,
   'Kodni qayerga kiritish kerak?',
   'Brauzerda roblox.com/redeem sahifasiga, telefondan ham boʻladi. Roblox ilovasida kod maydoni yoʻq, Samsung Galaxy qurilmalari bundan mustasno. Avval kerakli akkauntga kirganingizni tekshiring: balansni keyin oʻtkazib boʻlmaydi.'),
  (gen_random_uuid(), :post_id, 'uz', 3,
   'Roblox akkaunti paroli kerakmi?',
   'Yoʻq. Siz kod olasiz va uni oʻzingiz faollashtirasiz. Oʻyin akkaunti parolini soʻraydigan har qanday servis — ehtiyot boʻlish uchun sabab.'),
  (gen_random_uuid(), :post_id, 'uz', 4,
   'Bepul Robux olish mumkinligi rostmi?',
   'Yoʻq. Roblox bepul Robux taklif qiladigan saytlar firibgarlik ekanini ogohlantiradi. Robux’ni sotib olish, Premium bilan olish yoki oʻyin yaratuvchisi sifatida ishlab topish mumkin.');

COMMIT;
