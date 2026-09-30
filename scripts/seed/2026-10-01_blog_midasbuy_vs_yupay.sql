-- «Midasbuy или YuPay: где купить UC PUBG Mobile в Узбекистане» — ru, en, uz.
--
-- Written 2026-10-01 from search demand: «midasbuy» is 100k–1M searches a month
-- in Uzbekistan's Google (Keyword Planner), «pubg uc» / «uc pubg» 1k–10k. It is
-- a comparison, not an impersonation: Midasbuy is named as what it is (Tencent's
-- official top-up store), its logo is not used, and every claim about it was
-- read off its own Uzbekistan page on 2026-10-01 (prices in soʻm, Humo / Uzcard /
-- card payment, a −8.73% promotion on every pack).
--
-- Honesty is the point of the article. The table compares with Midasbuy's
-- *regular* prices, where YuPay is 3–8% lower, and the text says plainly that
-- during a Midasbuy promotion — including the one running on the day of
-- writing — some packs are cheaper there, so compare before buying. Prices are
-- dated. When our prices change, update the table.
--
-- Links: the store page and the existing UC guide (`uc-pubg-mobile` /
-- `how-to-get-uc-pubg-mobile` / `pubg-mobile-uc-olish`). Cover rendered in
-- yupay-motion (`Cover-pubg-uc`). Brand `pubg-mobile`. Status stays `draft`.
--
-- Idempotent: the post keeps its id; re-running rewrites translations and FAQs.

BEGIN;

\set post_id '''9911d0ba-2cad-4335-8805-6d062e014251'''

INSERT INTO blog_posts (id, kind, status, primary_brand_id, show_buy_card, pin_on_brand, cover_image_url)
SELECT :post_id, 'guide', 'draft', b.id, true, false,
       'https://cdn.yupay.uz/blog_image/2026/09/01a0f3b6-449e-7c40-9104-eb03e4beb995.jpg'
FROM brands b WHERE b.slug = 'pubg-mobile'
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
  :post_id, 'ru', 'midasbuy-ili-yupay-uc-pubg',
  'Midasbuy или YuPay: где купить UC PUBG Mobile в Узбекистане',
  'Сравниваем официальный магазин Midasbuy и YuPay: цены на UC в сумах, способы оплаты, пакеты и когда что выгоднее.',
$html$<h2>Главное</h2>
<ul>
<li>Midasbuy — официальный магазин пополнения PUBG Mobile от Tencent. Для Узбекистана он показывает цены в сумах и принимает карты Humo, Uzcard и международные.</li>
<li>YuPay — магазин в Узбекистане: UC по ID игрока, оплата через Click, Payme, Uzum, Paynet или с баланса YuPay.</li>
<li>По обычным ценам Midasbuy мы дешевле на 3–8 %. Но у Midasbuy бывают акции, и во время них часть пакетов у них дешевле, поэтому сравните перед покупкой.</li>
</ul>
<h2>Цены на UC: сравнение</h2>
<p>Цены на 1 октября 2026 года, в сумах. У Midasbuy — обычная цена, без акции.</p>
<table>
<thead>
<tr><th>Пакет</th><th>YuPay</th><th>Midasbuy</th></tr>
</thead>
<tbody>
<tr><td>60 UC</td><td>11 830</td><td>12 600</td></tr>
<tr><td>325 UC</td><td>59 980</td><td>63 000</td></tr>
<tr><td>660 UC</td><td>119 720</td><td>126 000</td></tr>
<tr><td>1800 UC</td><td>306 160</td><td>315 000</td></tr>
<tr><td>3850 UC</td><td>590 790</td><td>630 000</td></tr>
<tr><td>8100 UC</td><td>1 155 550</td><td>1 260 000</td></tr>
<tr><td>16200 UC</td><td>2 363 630</td><td>2 520 000</td></tr>
</tbody>
</table>
<p><strong>Про акции Midasbuy.</strong> 1 октября 2026 года у Midasbuy шла скидка 8,73 % на все пакеты. С ней, например, 1800 UC у них стоили 287 500 сум — дешевле нашего. Акции у них бывают регулярно, поэтому, если важна каждая тысяча, откройте обе страницы и сравните цену в день покупки.</p>
<p>У Midasbuy пакеты подписаны как «1500 + 300»: это основная сумма и бонус, на счёт приходит 1800 UC. У нас в названии сразу итог.</p>
<h2>Чем отличаются</h2>
<table>
<thead>
<tr><th></th><th>YuPay</th><th>Midasbuy</th></tr>
</thead>
<tbody>
<tr><td>Оплата</td><td>Click, Payme, Uzum, Paynet, баланс YuPay</td><td>Humo, Uzcard, международные карты</td></tr>
<tr><td>Пакеты</td><td>12 пакетов, в том числе 985, 1320, 2460, 5650 и 11950 UC</td><td>Стандартная линейка, от 30 UC</td></tr>
<tr><td>Что нужно</td><td>ID игрока</td><td>ID игрока</td></tr>
<tr><td>Поддержка</td><td>В Telegram, на русском и узбекском</td><td>Служба поддержки Midasbuy</td></tr>
<tr><td>Акции и события</td><td>Промокоды</td><td>Свои акции, розыгрыши и бонусы игры</td></tr>
</tbody>
</table>
<h2>Когда выгоднее Midasbuy</h2>
<ul>
<li>Во время их акции: на некоторых пакетах цена может быть ниже нашей.</li>
<li>Если нужны их внутренние события и розыгрыши — они есть только в официальном магазине.</li>
</ul>
<h2>Когда выгоднее YuPay</h2>
<ul>
<li>В обычные дни: по обычным ценам мы дешевле на всех общих пакетах.</li>
<li>Если удобнее платить через Click, Payme, Uzum или Paynet, а не вводить данные карты.</li>
<li>Если нужен пакет, которого нет в стандартной линейке: 985, 1320, 2460, 5650 или 11950 UC.</li>
<li>Если хочется написать в поддержку по-русски или по-узбекски в Telegram.</li>
</ul>
<h2>Как купить UC на YuPay</h2>
<ol>
<li>Откройте <a href="/store/pubg-mobile">пополнение PUBG Mobile</a>.</li>
<li>Выберите пакет UC.</li>
<li>Введите ID игрока — он в игре, в профиле, под ником.</li>
<li>Оплатите в сумах. UC приходят на аккаунт автоматически.</li>
</ol>
<p>Пароль и данные входа не нужны ни у нас, ни в Midasbuy. Подробнее о способах получить UC — в <a href="/blog/uc-pubg-mobile">гайде по UC</a>.</p>$html$,
  'Midasbuy или YuPay: где купить UC PUBG Mobile в Узбекистане',
  'Сравнение Midasbuy и YuPay: цены на UC PUBG Mobile в сумах, оплата Click, Payme, Uzum или картой, пакеты и акции.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
(gen_random_uuid(), :post_id, 'ru', 0, 'Что такое Midasbuy?',
 'Официальный магазин пополнения PUBG Mobile от Tencent. Для Узбекистана он показывает цены в сумах и принимает Humo, Uzcard и международные карты.'),
(gen_random_uuid(), :post_id, 'ru', 1, 'Где дешевле UC: на Midasbuy или на YuPay?',
 'По обычным ценам на 1 октября 2026 года YuPay дешевле на 3–8 % на всех общих пакетах. Во время акций Midasbuy часть пакетов у них может быть дешевле — сравните цену в день покупки.'),
(gen_random_uuid(), :post_id, 'ru', 2, 'Можно ли оплатить UC через Click или Payme?',
 'На YuPay — да: Click, Payme, Uzum, Paynet или баланс YuPay. Midasbuy принимает карты Humo, Uzcard и международные.'),
(gen_random_uuid(), :post_id, 'ru', 3, 'Нужен ли пароль от аккаунта?',
 'Нет. И нам, и Midasbuy нужен только ID игрока. Никому не сообщайте пароль и коды входа.');

-- ---------------------------------------------------------------- English --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'en', 'midasbuy-vs-yupay-pubg-uc',
  'Midasbuy or YuPay: where to buy PUBG Mobile UC in Uzbekistan',
  'Comparing the official Midasbuy store and YuPay: UC prices in soʻm, payment methods, packs, and when each one is cheaper.',
$html$<h2>The short version</h2>
<ul>
<li>Midasbuy is Tencent's official PUBG Mobile top-up store. For Uzbekistan it shows prices in soʻm and takes Humo, Uzcard and international cards.</li>
<li>YuPay is a store in Uzbekistan: UC by player ID, paid with Click, Payme, Uzum, Paynet or your YuPay balance.</li>
<li>Against Midasbuy's regular prices we are 3–8% cheaper. But Midasbuy runs promotions, and during them some packs are cheaper there — compare before you buy.</li>
</ul>
<h2>UC prices compared</h2>
<p>Prices as of 1 October 2026, in soʻm. Midasbuy's are its regular prices, without a promotion.</p>
<table>
<thead>
<tr><th>Pack</th><th>YuPay</th><th>Midasbuy</th></tr>
</thead>
<tbody>
<tr><td>60 UC</td><td>11,830</td><td>12,600</td></tr>
<tr><td>325 UC</td><td>59,980</td><td>63,000</td></tr>
<tr><td>660 UC</td><td>119,720</td><td>126,000</td></tr>
<tr><td>1800 UC</td><td>306,160</td><td>315,000</td></tr>
<tr><td>3850 UC</td><td>590,790</td><td>630,000</td></tr>
<tr><td>8100 UC</td><td>1,155,550</td><td>1,260,000</td></tr>
<tr><td>16200 UC</td><td>2,363,630</td><td>2,520,000</td></tr>
</tbody>
</table>
<p><strong>About Midasbuy promotions.</strong> On 1 October 2026 Midasbuy had 8.73% off every pack. With it, 1800 UC cost 287,500 soʻm there — less than ours. They run promotions regularly, so if every thousand counts, open both pages and compare on the day you buy.</p>
<p>Midasbuy labels packs like «1500 + 300»: the base amount and a bonus, and 1800 UC reach the account. Our names give the total.</p>
<h2>How they differ</h2>
<table>
<thead>
<tr><th></th><th>YuPay</th><th>Midasbuy</th></tr>
</thead>
<tbody>
<tr><td>Payment</td><td>Click, Payme, Uzum, Paynet, YuPay balance</td><td>Humo, Uzcard, international cards</td></tr>
<tr><td>Packs</td><td>12 packs, including 985, 1320, 2460, 5650 and 11950 UC</td><td>The standard ladder, from 30 UC</td></tr>
<tr><td>What you need</td><td>Player ID</td><td>Player ID</td></tr>
<tr><td>Support</td><td>On Telegram, in Russian and Uzbek</td><td>Midasbuy customer service</td></tr>
<tr><td>Promotions and events</td><td>Promo codes</td><td>Its own promotions, draws and in-game bonuses</td></tr>
</tbody>
</table>
<h2>When Midasbuy is the better deal</h2>
<ul>
<li>During its promotions: some packs can be cheaper than ours.</li>
<li>If you want its events and draws — they exist only in the official store.</li>
</ul>
<h2>When YuPay is the better deal</h2>
<ul>
<li>On ordinary days: against regular prices we are cheaper on every pack both stores sell.</li>
<li>If you would rather pay with Click, Payme, Uzum or Paynet than type in card details.</li>
<li>If you need a pack outside the standard ladder: 985, 1320, 2460, 5650 or 11950 UC.</li>
<li>If you want to reach support in Russian or Uzbek on Telegram.</li>
</ul>
<h2>How to buy UC on YuPay</h2>
<ol>
<li>Open <a href="/en/store/pubg-mobile">PUBG Mobile top-up</a>.</li>
<li>Pick a UC pack.</li>
<li>Enter your player ID — it is in the game, on your profile, under your name.</li>
<li>Pay in soʻm. The UC arrive on the account automatically.</li>
</ol>
<p>Neither we nor Midasbuy need your password or sign-in details. More ways to get UC are in our <a href="/en/blog/how-to-get-uc-pubg-mobile">UC guide</a>.</p>$html$,
  'Midasbuy or YuPay: where to buy PUBG Mobile UC in Uzbekistan',
  'Midasbuy vs YuPay: PUBG Mobile UC prices in soʻm, paying with Click, Payme, Uzum or a card, packs and promotions compared.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
(gen_random_uuid(), :post_id, 'en', 0, 'What is Midasbuy?',
 'Tencent''s official PUBG Mobile top-up store. For Uzbekistan it shows prices in soʻm and takes Humo, Uzcard and international cards.'),
(gen_random_uuid(), :post_id, 'en', 1, 'Where is UC cheaper, Midasbuy or YuPay?',
 'Against regular prices on 1 October 2026, YuPay is 3–8% cheaper on every pack both sell. During a Midasbuy promotion some packs can be cheaper there — compare on the day you buy.'),
(gen_random_uuid(), :post_id, 'en', 2, 'Can I pay for UC with Click or Payme?',
 'On YuPay, yes: Click, Payme, Uzum, Paynet or your YuPay balance. Midasbuy takes Humo, Uzcard and international cards.'),
(gen_random_uuid(), :post_id, 'en', 3, 'Do I need my account password?',
 'No. Both we and Midasbuy need only your player ID. Never share your password or sign-in codes.');

-- ------------------------------------------------------------------ Uzbek --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'uz', 'midasbuy-yoki-yupay-pubg-uc',
  'Midasbuy yoki YuPay: Oʻzbekistonda PUBG Mobile UC qayerdan sotib olish',
  'Rasmiy Midasbuy doʻkoni va YuPay’ni solishtiramiz: soʻmdagi UC narxlari, toʻlov usullari, paketlar va qachon qaysi biri arzonroq.',
$html$<h2>Asosiysi</h2>
<ul>
<li>Midasbuy — Tencent’ning PUBG Mobile uchun rasmiy toʻldirish doʻkoni. Oʻzbekiston uchun narxlarni soʻmda koʻrsatadi va Humo, Uzcard hamda xalqaro kartalarni qabul qiladi.</li>
<li>YuPay — Oʻzbekistondagi doʻkon: UC oʻyinchi ID orqali, Click, Payme, Uzum, Paynet yoki YuPay balansi orqali toʻlov.</li>
<li>Midasbuy’ning odatiy narxlariga nisbatan biz 3–8 % arzonmiz. Lekin Midasbuy’da aksiyalar boʻladi va ular paytida ayrim paketlar u yerda arzonroq — sotib olishdan oldin solishtiring.</li>
</ul>
<h2>UC narxlari: solishtirish</h2>
<p>Narxlar 2026-yil 1-oktabr holatiga, soʻmda. Midasbuy’niki — aksiyasiz odatiy narx.</p>
<table>
<thead>
<tr><th>Paket</th><th>YuPay</th><th>Midasbuy</th></tr>
</thead>
<tbody>
<tr><td>60 UC</td><td>11 830</td><td>12 600</td></tr>
<tr><td>325 UC</td><td>59 980</td><td>63 000</td></tr>
<tr><td>660 UC</td><td>119 720</td><td>126 000</td></tr>
<tr><td>1800 UC</td><td>306 160</td><td>315 000</td></tr>
<tr><td>3850 UC</td><td>590 790</td><td>630 000</td></tr>
<tr><td>8100 UC</td><td>1 155 550</td><td>1 260 000</td></tr>
<tr><td>16200 UC</td><td>2 363 630</td><td>2 520 000</td></tr>
</tbody>
</table>
<p><strong>Midasbuy aksiyalari haqida.</strong> 2026-yil 1-oktabrda Midasbuy’da barcha paketlarga 8,73 % chegirma bor edi. U bilan, masalan, 1800 UC u yerda 287 500 soʻm turardi — biznikidan arzon. Aksiyalar muntazam boʻlib turadi, shuning uchun har bir ming soʻm muhim boʻlsa, ikkala sahifani ochib, sotib olish kuni narxni solishtiring.</p>
<p>Midasbuy paketlarni «1500 + 300» deb yozadi: bu asosiy miqdor va bonus, akkauntga 1800 UC tushadi. Bizda nomda darhol jami koʻrsatilgan.</p>
<h2>Farqlari</h2>
<table>
<thead>
<tr><th></th><th>YuPay</th><th>Midasbuy</th></tr>
</thead>
<tbody>
<tr><td>Toʻlov</td><td>Click, Payme, Uzum, Paynet, YuPay balansi</td><td>Humo, Uzcard, xalqaro kartalar</td></tr>
<tr><td>Paketlar</td><td>12 ta paket, jumladan 985, 1320, 2460, 5650 va 11950 UC</td><td>Standart qator, 30 UC dan</td></tr>
<tr><td>Nima kerak</td><td>Oʻyinchi ID</td><td>Oʻyinchi ID</td></tr>
<tr><td>Yordam</td><td>Telegram’da, rus va oʻzbek tilida</td><td>Midasbuy mijozlarga xizmat koʻrsatish</td></tr>
<tr><td>Aksiya va tadbirlar</td><td>Promokodlar</td><td>Oʻz aksiyalari, oʻyinlari va bonuslari</td></tr>
</tbody>
</table>
<h2>Qachon Midasbuy foydaliroq</h2>
<ul>
<li>Ularning aksiyasi paytida: ayrim paketlar biznikidan arzon boʻlishi mumkin.</li>
<li>Ularning tadbirlari va oʻyinlari kerak boʻlsa — ular faqat rasmiy doʻkonda.</li>
</ul>
<h2>Qachon YuPay foydaliroq</h2>
<ul>
<li>Oddiy kunlarda: odatiy narxlarga nisbatan ikkala doʻkondagi barcha paketlarda biz arzonmiz.</li>
<li>Karta maʼlumotlarini kiritish oʻrniga Click, Payme, Uzum yoki Paynet orqali toʻlash qulayroq boʻlsa.</li>
<li>Standart qatorda yoʻq paket kerak boʻlsa: 985, 1320, 2460, 5650 yoki 11950 UC.</li>
<li>Telegram’da rus yoki oʻzbek tilida yordamga yozmoqchi boʻlsangiz.</li>
</ul>
<h2>YuPay’da UC qanday sotib olinadi</h2>
<ol>
<li><a href="/uz/store/pubg-mobile">PUBG Mobile toʻldirish</a> sahifasini oching.</li>
<li>UC paketini tanlang.</li>
<li>Oʻyinchi ID’ni kiriting — u oʻyinda, profilda, nik ostida.</li>
<li>Soʻmda toʻlang. UC akkauntga avtomatik tushadi.</li>
</ol>
<p>Bizga ham, Midasbuy’ga ham parol va kirish maʼlumotlari kerak emas. UC olishning boshqa yoʻllari — <a href="/uz/blog/pubg-mobile-uc-olish">UC boʻyicha qoʻllanmada</a>.</p>$html$,
  'Midasbuy yoki YuPay: Oʻzbekistonda PUBG Mobile UC sotib olish',
  'Midasbuy va YuPay solishtiruvi: PUBG Mobile UC narxlari soʻmda, Click, Payme, Uzum yoki karta orqali toʻlov, paketlar va aksiyalar.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
(gen_random_uuid(), :post_id, 'uz', 0, 'Midasbuy nima?',
 'Tencent’ning PUBG Mobile uchun rasmiy toʻldirish doʻkoni. Oʻzbekiston uchun narxlarni soʻmda koʻrsatadi va Humo, Uzcard hamda xalqaro kartalarni qabul qiladi.'),
(gen_random_uuid(), :post_id, 'uz', 1, 'UC qayerda arzon: Midasbuy’dami yoki YuPay’dami?',
 '2026-yil 1-oktabrdagi odatiy narxlarga koʻra YuPay ikkala doʻkondagi barcha paketlarda 3–8 % arzon. Midasbuy aksiyasi paytida ayrim paketlar u yerda arzonroq boʻlishi mumkin — sotib olish kuni solishtiring.'),
(gen_random_uuid(), :post_id, 'uz', 2, 'UC uchun Click yoki Payme orqali toʻlash mumkinmi?',
 'YuPay’da — ha: Click, Payme, Uzum, Paynet yoki YuPay balansi. Midasbuy Humo, Uzcard va xalqaro kartalarni qabul qiladi.'),
(gen_random_uuid(), :post_id, 'uz', 3, 'Akkaunt paroli kerakmi?',
 'Yoʻq. Bizga ham, Midasbuy’ga ham faqat oʻyinchi ID kerak. Parol va kirish kodlarini hech kimga aytmang.');

COMMIT;
