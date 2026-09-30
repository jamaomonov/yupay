-- «Алмазы MLBB в Узбекистане: MobaPay, Smile One или оплата в сумах» — ru, en, uz.
--
-- Written 2026-10-01 from Keyword Planner, Uzbekistan: «mobapay» and «smile one»
-- are 100–1k searches a month each, «mlbb diamond» / «mobile legends diamond»
-- 100–1k. Unlike the Midasbuy article there is no price table for the other
-- stores, because there is nothing honest to put in one: on 2026-10-01
-- MobaPay's page for Uzbekistan switched to another country (Indonesia, prices
-- in rupiah), and Smile One is a Brazilian site priced in reais, where buyers
-- outside Brazil pay with its Smile Coin and, by its own notice, Moonton adds
-- 0–0.43% to the price. The article says what each store is, what buying there
-- involves from Uzbekistan, and our own prices — no «cheaper» claim we cannot
-- back with a like-for-like number.
--
-- Links: the global and RU store pages and the existing top-up guide
-- (`mobile-legends` / `how-to-top-up-mobile-legends` /
-- `mobile-legends-toldirish`). Cover `Cover-mlbb-diamonds`. Brand
-- `mobile-legends`. Status stays `draft`. Idempotent.

BEGIN;

\set post_id '''a7842d11-5791-46cf-8311-5e2224b23d5d'''

INSERT INTO blog_posts (id, kind, status, primary_brand_id, show_buy_card, pin_on_brand, cover_image_url)
SELECT :post_id, 'guide', 'draft', b.id, true, false,
       'https://cdn.yupay.uz/blog_image/2026/09/01a0f3bb-ffc5-7452-83ee-b58546e1caeb.jpg'
FROM brands b WHERE b.slug = 'mobile-legends'
ON CONFLICT (id) DO UPDATE
SET primary_brand_id = EXCLUDED.primary_brand_id,
    cover_image_url = EXCLUDED.cover_image_url,
    updated_at = now();

DELETE FROM blog_post_translations WHERE post_id = :post_id;
DELETE FROM blog_post_faqs WHERE post_id = :post_id;

-- ---------------------------------------------------------------- Russian --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'ru', 'almazy-mlbb-mobapay-smile-one',
  'Алмазы MLBB в Узбекистане: MobaPay, Smile One или оплата в сумах',
  'Где купить алмазы Mobile Legends из Узбекистана: чем отличаются MobaPay, Smile One и покупка в сумах через Click, Payme или Uzum.',
$html$<h2>Главное</h2>
<ul>
<li>MobaPay — официальный партнёр Moonton по пополнению Mobile Legends. Цены и способы оплаты там зависят от выбранной страны.</li>
<li>Smile One — бразильский сайт, цены в реалах. Покупатели не из Бразилии платят через Smile Coin.</li>
<li>На YuPay алмазы продаются в сумах: оплата через Click, Payme, Uzum, Paynet или с баланса, по ID игрока и ID сервера.</li>
</ul>
<h2>MobaPay</h2>
<p>Официальный магазин пополнения Mobile Legends. Нужны ID игрока и ID сервера, после проверки показывается ник. Страна выбирается вверху страницы, и от неё зависят валюта цен и способы оплаты. У MobaPay бывают свои акции: например, двойные алмазы за первое пополнение и скидки на Weekly Diamond Pass.</p>
<p>Отдельной страницы для Узбекистана с ценами в сумах мы на 1 октября 2026 года не нашли: при попытке открыть её сайт переключался на другую страну. Если покупаете там, заранее проверьте, примет ли выбранная страна вашу карту.</p>
<h2>Smile One</h2>
<p>Бразильский сайт с пополнениями разных игр, включая Mobile Legends. Цены — в бразильских реалах. Покупатели не из Бразилии платят через Smile Coin, внутреннюю валюту сайта. По сообщению самого Smile One, для таких покупок Moonton поднимает цену алмазов на 0–0,43 %.</p>
<h2>YuPay</h2>
<ul>
<li><strong>Цены в сумах:</strong> 23 пакета, от 55 алмазов за 10 174 сум до 9994 алмазов (цены на 1 октября 2026 года).</li>
<li><strong>Оплата:</strong> Click, Payme, Uzum, Paynet или баланс YuPay — без ввода данных карты на чужом сайте.</li>
<li><strong>Проверка перед оплатой:</strong> по ID игрока и ID сервера покажем ник, чтобы алмазы не ушли на чужой аккаунт.</li>
<li><strong>Пропуски и наборы:</strong> Weekly Diamond Pass и другие — на той же странице.</li>
<li><strong>Российский аккаунт:</strong> для него отдельная страница — <a href="/store/mobile-legends-ru">Mobile Legends RU</a>.</li>
<li><strong>Поддержка:</strong> в Telegram, на русском и узбекском.</li>
</ul>
<h2>Что выбрать</h2>
<ul>
<li><strong>Нужны события и промо MobaPay</strong> — они есть только в официальном магазине.</li>
<li><strong>Хотите платить в сумах через Click, Payme или Uzum</strong> — удобнее YuPay.</li>
<li><strong>Сравниваете цену</strong> — пересчитайте цену MobaPay или Smile One в сумы по курсу вашего банка и добавьте комиссию за оплату иностранной валютой, если она есть. Только так сравнение будет честным.</li>
</ul>
<h2>Как купить алмазы на YuPay</h2>
<ol>
<li>Откройте <a href="/store/mobile-legends">пополнение Mobile Legends</a>.</li>
<li>Выберите пакет алмазов.</li>
<li>Введите ID игрока и ID сервера — они в игре, в профиле, под аватаром. Проверьте ник.</li>
<li>Оплатите в сумах. Алмазы приходят на аккаунт автоматически.</li>
</ol>
<p>Пароль не нужен ни у нас, ни в MobaPay, ни в Smile One — никому его не сообщайте. Подробнее — в <a href="/blog/mobile-legends">гайде по пополнению Mobile Legends</a>.</p>$html$,
  'Алмазы MLBB в Узбекистане: MobaPay, Smile One или оплата в сумах',
  'Где купить алмазы Mobile Legends (млбб) из Узбекистана: MobaPay, Smile One или YuPay с оплатой в сумах через Click, Payme, Uzum.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
(gen_random_uuid(), :post_id, 'ru', 0, 'Что такое MobaPay?',
 'Официальный партнёр Moonton по пополнению Mobile Legends. Цены и способы оплаты там зависят от выбранной страны; нужны ID игрока и ID сервера.'),
(gen_random_uuid(), :post_id, 'ru', 1, 'Что такое Smile One?',
 'Бразильский сайт пополнения игр, цены в реалах. Покупатели не из Бразилии платят через Smile Coin, и, по сообщению самого сайта, Moonton поднимает для них цену на 0–0,43 %.'),
(gen_random_uuid(), :post_id, 'ru', 2, 'Можно ли купить алмазы MLBB через Click или Payme?',
 'Да, на YuPay: Click, Payme, Uzum, Paynet или баланс YuPay. Цены в сумах, алмазы приходят автоматически по ID игрока и ID сервера.'),
(gen_random_uuid(), :post_id, 'ru', 3, 'Нужен ли пароль от аккаунта?',
 'Нет. Для пополнения нужны только ID игрока и ID сервера. Никому не сообщайте пароль.');

-- ---------------------------------------------------------------- English --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'en', 'mlbb-diamonds-mobapay-smile-one',
  'MLBB diamonds in Uzbekistan: MobaPay, Smile One or paying in soʻm',
  'Where to buy Mobile Legends diamonds from Uzbekistan: how MobaPay, Smile One and paying in soʻm with Click, Payme or Uzum differ.',
$html$<h2>The short version</h2>
<ul>
<li>MobaPay is Moonton's official Mobile Legends top-up partner. Its prices and payment methods depend on the country you pick.</li>
<li>Smile One is a Brazilian site priced in reais. Buyers outside Brazil pay with Smile Coin.</li>
<li>On YuPay diamonds are sold in soʻm: pay with Click, Payme, Uzum, Paynet or your balance, by player ID and server ID.</li>
</ul>
<h2>MobaPay</h2>
<p>The official Mobile Legends top-up store. It needs your player ID and server ID and shows your name once checked. You pick a country at the top of the page, and that decides the price currency and the payment methods. MobaPay runs its own promotions — for example double diamonds on a first top-up and discounts on the Weekly Diamond Pass.</p>
<p>On 1 October 2026 we found no separate Uzbekistan page with prices in soʻm: trying to open one switched the site to another country. If you buy there, check first that the country you pick accepts your card.</p>
<h2>Smile One</h2>
<p>A Brazilian top-up site for many games, Mobile Legends included. Prices are in Brazilian reais. Buyers outside Brazil pay with Smile Coin, the site's own currency. By Smile One's own notice, Moonton adds 0–0.43% to the diamond price for such purchases.</p>
<h2>YuPay</h2>
<ul>
<li><strong>Prices in soʻm:</strong> 23 packs, from 55 diamonds for 10,174 soʻm up to 9994 diamonds (prices as of 1 October 2026).</li>
<li><strong>Payment:</strong> Click, Payme, Uzum, Paynet or your YuPay balance — no card details typed into a foreign site.</li>
<li><strong>A check before you pay:</strong> by player ID and server ID we show the account name, so diamonds do not go to someone else.</li>
<li><strong>Passes and bundles:</strong> the Weekly Diamond Pass and others are on the same page.</li>
<li><strong>Russian account:</strong> it has its own page — <a href="/en/store/mobile-legends-ru">Mobile Legends RU</a>.</li>
<li><strong>Support:</strong> on Telegram, in Russian and Uzbek.</li>
</ul>
<h2>Which to choose</h2>
<ul>
<li><strong>You want MobaPay's events and promos</strong> — they exist only in the official store.</li>
<li><strong>You want to pay in soʻm with Click, Payme or Uzum</strong> — YuPay is simpler.</li>
<li><strong>You are comparing prices</strong> — convert the MobaPay or Smile One price into soʻm at your bank's rate and add any fee for paying in a foreign currency. That is the only fair comparison.</li>
</ul>
<h2>How to buy diamonds on YuPay</h2>
<ol>
<li>Open <a href="/en/store/mobile-legends">Mobile Legends top-up</a>.</li>
<li>Pick a diamond pack.</li>
<li>Enter your player ID and server ID — they are in the game, on your profile, under your avatar. Check the name.</li>
<li>Pay in soʻm. The diamonds arrive on the account automatically.</li>
</ol>
<p>Neither we, MobaPay nor Smile One need your password — never share it. More in our <a href="/en/blog/how-to-top-up-mobile-legends">Mobile Legends top-up guide</a>.</p>$html$,
  'MLBB diamonds in Uzbekistan: MobaPay, Smile One or paying in soʻm',
  'Where to buy Mobile Legends diamonds from Uzbekistan: MobaPay, Smile One, or YuPay paid in soʻm with Click, Payme or Uzum.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
(gen_random_uuid(), :post_id, 'en', 0, 'What is MobaPay?',
 'Moonton''s official Mobile Legends top-up partner. Prices and payment methods depend on the country you pick; it needs your player ID and server ID.'),
(gen_random_uuid(), :post_id, 'en', 1, 'What is Smile One?',
 'A Brazilian game top-up site priced in reais. Buyers outside Brazil pay with Smile Coin, and by the site''s own notice Moonton adds 0–0.43% to the price for them.'),
(gen_random_uuid(), :post_id, 'en', 2, 'Can I buy MLBB diamonds with Click or Payme?',
 'Yes, on YuPay: Click, Payme, Uzum, Paynet or your YuPay balance. Prices are in soʻm, and diamonds arrive automatically by player ID and server ID.'),
(gen_random_uuid(), :post_id, 'en', 3, 'Do I need my account password?',
 'No. A top-up needs only your player ID and server ID. Never share your password.');

-- ------------------------------------------------------------------ Uzbek --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'uz', 'mlbb-olmos-mobapay-smile-one',
  'Oʻzbekistonda MLBB olmoslari: MobaPay, Smile One yoki soʻmda toʻlov',
  'Oʻzbekistondan Mobile Legends olmoslarini qayerdan sotib olish: MobaPay, Smile One va Click, Payme yoki Uzum orqali soʻmda toʻlovning farqi.',
$html$<h2>Asosiysi</h2>
<ul>
<li>MobaPay — Moonton’ning Mobile Legends toʻldirish boʻyicha rasmiy hamkori. U yerdagi narxlar va toʻlov usullari tanlangan davlatga bogʻliq.</li>
<li>Smile One — Braziliya sayti, narxlar realda. Braziliyadan tashqaridagi xaridorlar Smile Coin orqali toʻlaydi.</li>
<li>YuPay’da olmoslar soʻmda sotiladi: Click, Payme, Uzum, Paynet yoki balans orqali toʻlov, oʻyinchi ID va server ID boʻyicha.</li>
</ul>
<h2>MobaPay</h2>
<p>Mobile Legends’ning rasmiy toʻldirish doʻkoni. Oʻyinchi ID va server ID kerak, tekshiruvdan keyin nik koʻrsatiladi. Davlat sahifa tepasida tanlanadi va narx valyutasi hamda toʻlov usullari shunga bogʻliq. MobaPay’da oʻz aksiyalari boʻladi: masalan, birinchi toʻldirishda ikki barobar olmos va Weekly Diamond Pass’ga chegirmalar.</p>
<p>2026-yil 1-oktabr holatiga Oʻzbekiston uchun soʻmdagi narxli alohida sahifa topmadik: uni ochmoqchi boʻlganimizda sayt boshqa davlatga oʻtib ketdi. U yerdan sotib olsangiz, tanlangan davlat kartangizni qabul qilishini oldindan tekshiring.</p>
<h2>Smile One</h2>
<p>Turli oʻyinlarni, jumladan Mobile Legends’ni toʻldirish uchun Braziliya sayti. Narxlar Braziliya realida. Braziliyadan tashqaridagi xaridorlar saytning ichki valyutasi Smile Coin orqali toʻlaydi. Smile One’ning oʻz xabariga koʻra, bunday xaridlar uchun Moonton olmos narxini 0–0,43 % oshiradi.</p>
<h2>YuPay</h2>
<ul>
<li><strong>Narxlar soʻmda:</strong> 23 ta paket, 55 ta olmos 10 174 soʻmdan 9994 ta olmosgacha (narxlar 2026-yil 1-oktabr holatiga).</li>
<li><strong>Toʻlov:</strong> Click, Payme, Uzum, Paynet yoki YuPay balansi — begona saytga karta maʼlumotlarini kiritmasdan.</li>
<li><strong>Toʻlovdan oldin tekshiruv:</strong> oʻyinchi ID va server ID boʻyicha nikni koʻrsatamiz, olmoslar boshqa akkauntga ketmasligi uchun.</li>
<li><strong>Passlar va toʻplamlar:</strong> Weekly Diamond Pass va boshqalar — oʻsha sahifada.</li>
<li><strong>Rossiya akkaunti:</strong> uning uchun alohida sahifa — <a href="/uz/store/mobile-legends-ru">Mobile Legends RU</a>.</li>
<li><strong>Yordam:</strong> Telegram’da, rus va oʻzbek tilida.</li>
</ul>
<h2>Nimani tanlash kerak</h2>
<ul>
<li><strong>MobaPay tadbirlari va promo kerak boʻlsa</strong> — ular faqat rasmiy doʻkonda.</li>
<li><strong>Click, Payme yoki Uzum orqali soʻmda toʻlamoqchi boʻlsangiz</strong> — YuPay qulayroq.</li>
<li><strong>Narxni solishtirayotgan boʻlsangiz</strong> — MobaPay yoki Smile One narxini bankingiz kursi boʻyicha soʻmga oʻtkazing va xorijiy valyutada toʻlov komissiyasini qoʻshing, agar boʻlsa. Faqat shunda solishtirish adolatli boʻladi.</li>
</ul>
<h2>YuPay’da olmos qanday sotib olinadi</h2>
<ol>
<li><a href="/uz/store/mobile-legends">Mobile Legends toʻldirish</a> sahifasini oching.</li>
<li>Olmos paketini tanlang.</li>
<li>Oʻyinchi ID va server ID’ni kiriting — ular oʻyinda, profilda, avatar ostida. Nikni tekshiring.</li>
<li>Soʻmda toʻlang. Olmoslar akkauntga avtomatik tushadi.</li>
</ol>
<p>Bizga ham, MobaPay va Smile One’ga ham parol kerak emas — uni hech kimga aytmang. Batafsil — <a href="/uz/blog/mobile-legends-toldirish">Mobile Legends toʻldirish qoʻllanmasida</a>.</p>$html$,
  'Oʻzbekistonda MLBB olmoslari: MobaPay, Smile One yoki soʻmda toʻlov',
  'Oʻzbekistondan Mobile Legends olmoslarini qayerdan olish: MobaPay, Smile One yoki Click, Payme, Uzum orqali soʻmda toʻlanadigan YuPay.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
(gen_random_uuid(), :post_id, 'uz', 0, 'MobaPay nima?',
 'Moonton’ning Mobile Legends toʻldirish boʻyicha rasmiy hamkori. Narxlar va toʻlov usullari tanlangan davlatga bogʻliq; oʻyinchi ID va server ID kerak.'),
(gen_random_uuid(), :post_id, 'uz', 1, 'Smile One nima?',
 'Narxlari realda boʻlgan Braziliya oʻyin toʻldirish sayti. Braziliyadan tashqaridagi xaridorlar Smile Coin orqali toʻlaydi va saytning oʻz xabariga koʻra Moonton ular uchun narxni 0–0,43 % oshiradi.'),
(gen_random_uuid(), :post_id, 'uz', 2, 'MLBB olmoslarini Click yoki Payme orqali sotib olish mumkinmi?',
 'Ha, YuPay’da: Click, Payme, Uzum, Paynet yoki YuPay balansi. Narxlar soʻmda, olmoslar oʻyinchi ID va server ID boʻyicha avtomatik tushadi.'),
(gen_random_uuid(), :post_id, 'uz', 3, 'Akkaunt paroli kerakmi?',
 'Yoʻq. Toʻldirish uchun faqat oʻyinchi ID va server ID kerak. Parolni hech kimga aytmang.');

COMMIT;
