-- «Garena Shop или YuPay: алмазы Free Fire в Узбекистане» — ru, en, uz.
--
-- Written 2026-10-01 from Keyword Planner, Uzbekistan: «garena» and «garena
-- shop» are 1k–10k searches a month, «free fire diamond» / «ff diamond(s)»
-- 100–1k. shop.garena.com redirects to kzshop.garena.com — Garena Kazakhstan's
-- official top-up centre, whose footer names the CIS support desk. Its prices
-- were read off that page on 2026-10-01 with «Банковская карта» selected, in
-- tenge; its packs are «купить 100 — получить 110» etc., the same totals our
-- SKUs name. Converted at the Central Bank of Uzbekistan's rate for the day
-- (1 KZT = 26.84 UZS).
--
-- The result is close to parity — we are about 1% lower on five packs and 2.4%
-- higher on 341 — and the article says exactly that. It also says what the table
-- cannot show: a card from Uzbekistan paying in tenge is converted at the bank's
-- own rate, which is usually worse than the Central Bank's, sometimes with a
-- fee. Whether Garena KZ takes a given Uzbek card was not tested, so the text
-- says to check rather than claiming either way.
--
-- Links: the store page and the existing Free Fire guide (`free-fire` /
-- `free-fire-diamonds-top-up` / `free-fire-olmos-toldirish`). Cover
-- `Cover-ff-diamonds`. Brand `free-fire`. Status stays `draft`. Idempotent.

BEGIN;

\set post_id '''cb8e0e4d-b6ef-4366-9df2-29f14668d1f0'''

INSERT INTO blog_posts (id, kind, status, primary_brand_id, show_buy_card, pin_on_brand, cover_image_url)
SELECT :post_id, 'guide', 'draft', b.id, true, false,
       'https://cdn.yupay.uz/blog_image/2026/09/01a0f3c8-0ffc-7531-a438-095383e4fa78.jpg'
FROM brands b WHERE b.slug = 'free-fire'
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
  :post_id, 'ru', 'garena-shop-ili-yupay-free-fire',
  'Garena Shop или YuPay: алмазы Free Fire в Узбекистане',
  'Сравниваем официальный магазин Garena и YuPay: цены на алмазы Free Fire в сумах, способы оплаты и что учесть при оплате картой в тенге.',
$html$<h2>Главное</h2>
<ul>
<li>Официальный магазин Free Fire для стран СНГ — Garena Kazakhstan (kzshop.garena.com). Цены в тенге, оплата банковской картой, через QiwiKZ и казахстанских мобильных операторов.</li>
<li>YuPay — магазин в Узбекистане: алмазы по ID игрока, оплата в сумах через Click, Payme, Uzum, Paynet или с баланса YuPay.</li>
<li>По курсу ЦБ цены почти одинаковые: на пяти пакетах из шести мы дешевле примерно на 1 %, на одном — дороже на 2,4 %.</li>
</ul>
<h2>Цены на алмазы: сравнение</h2>
<p>Цены на 1 октября 2026 года. Garena — при оплате банковской картой, в тенге и в пересчёте на сумы по курсу ЦБ Узбекистана (1 тенге = 26,84 сум).</p>
<table>
<thead>
<tr><th>Алмазы</th><th>YuPay</th><th>Garena, тенге</th><th>Garena ≈ сум</th></tr>
</thead>
<tbody>
<tr><td>110</td><td>10 292</td><td>386</td><td>10 360</td></tr>
<tr><td>341</td><td>31 823</td><td>1 158</td><td>31 080</td></tr>
<tr><td>572</td><td>51 697</td><td>1 931</td><td>51 830</td></tr>
<tr><td>1166</td><td>102 803</td><td>3 867</td><td>103 790</td></tr>
<tr><td>2398</td><td>205 487</td><td>7 734</td><td>207 580</td></tr>
<tr><td>6160</td><td>515 906</td><td>19 340</td><td>519 090</td></tr>
</tbody>
</table>
<p>В Garena пакеты подписаны как «купить 100 — получить 110»: на аккаунт приходит 110 алмазов. У нас в названии сразу итог, поэтому пакеты те же.</p>
<p><strong>Что таблица не показывает.</strong> Если вы платите узбекской картой в тенге, банк пересчитает сумму по своему курсу, а он обычно хуже курса ЦБ. Некоторые банки ещё берут комиссию за оплату в другой валюте. На YuPay цена сразу в сумах: сколько на экране, столько и спишется.</p>
<h2>Чем отличаются</h2>
<table>
<thead>
<tr><th></th><th>YuPay</th><th>Garena Kazakhstan</th></tr>
</thead>
<tbody>
<tr><td>Валюта</td><td>Сумы</td><td>Тенге</td></tr>
<tr><td>Оплата</td><td>Click, Payme, Uzum, Paynet, баланс YuPay</td><td>Банковская карта, QiwiKZ, Beeline, Activ, Kcell, Tele2, Altel (Казахстан)</td></tr>
<tr><td>Что нужно</td><td>ID игрока</td><td>ID игрока или вход через игровой аккаунт</td></tr>
<tr><td>Кроме алмазов</td><td>Подписка и наборы</td><td>BP Card, недельный и месячный ваучер</td></tr>
<tr><td>Поддержка</td><td>В Telegram, на русском и узбекском</td><td>Служба поддержки Garena для СНГ</td></tr>
</tbody>
</table>
<h2>Когда что выбрать</h2>
<ul>
<li><strong>Garena</strong> — если у вас есть карта, которая спокойно платит в тенге, или нужны их специальные предложения.</li>
<li><strong>YuPay</strong> — если удобнее платить в сумах через Click, Payme или Uzum и не думать о курсе и комиссиях банка.</li>
</ul>
<p>Примет ли Garena конкретную узбекскую карту, зависит от банка и платёжной системы — если собираетесь платить там, проверьте заранее.</p>
<h2>Как купить алмазы на YuPay</h2>
<ol>
<li>Откройте <a href="/store/free-fire">пополнение Free Fire</a>.</li>
<li>Выберите пакет алмазов.</li>
<li>Введите ID игрока — он в игре, в профиле, под ником. Алмазы подходят и для Free Fire MAX: аккаунт один.</li>
<li>Оплатите в сумах. Алмазы приходят на аккаунт автоматически.</li>
</ol>
<p>Пароль не нужен ни у нас, ни в Garena. Подробнее — в <a href="/blog/free-fire">гайде по пополнению Free Fire</a>.</p>$html$,
  'Garena Shop или YuPay: алмазы Free Fire в Узбекистане',
  'Сравнение Garena Shop и YuPay: цены на алмазы Free Fire в сумах и тенге, оплата Click, Payme, Uzum или картой, что учесть.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
(gen_random_uuid(), :post_id, 'ru', 0, 'Какой официальный магазин Free Fire для Узбекистана?',
 'Для стран СНГ это Garena Kazakhstan — kzshop.garena.com. Цены там в тенге, оплата банковской картой, через QiwiKZ и казахстанских мобильных операторов.'),
(gen_random_uuid(), :post_id, 'ru', 1, 'Где дешевле алмазы Free Fire: в Garena или на YuPay?',
 'На 1 октября 2026 года по курсу ЦБ почти одинаково: на пяти пакетах из шести YuPay дешевле примерно на 1 %, на пакете 341 алмаз — дороже на 2,4 %. При оплате узбекской картой в тенге банк обычно считает по курсу хуже ЦБ.'),
(gen_random_uuid(), :post_id, 'ru', 2, 'Можно ли купить алмазы Free Fire через Click или Payme?',
 'Да, на YuPay: Click, Payme, Uzum, Paynet или баланс YuPay. Цены в сумах, алмазы приходят автоматически по ID игрока.'),
(gen_random_uuid(), :post_id, 'ru', 3, 'Подходят ли алмазы для Free Fire MAX?',
 'Да. Free Fire и Free Fire MAX используют один аккаунт, поэтому пополнение по ID игрока работает для обеих версий.');

-- ---------------------------------------------------------------- English --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'en', 'garena-shop-vs-yupay-free-fire',
  'Garena Shop or YuPay: Free Fire diamonds in Uzbekistan',
  'Comparing Garena''s official store and YuPay: Free Fire diamond prices in soʻm, payment methods, and what paying by card in tenge involves.',
$html$<h2>The short version</h2>
<ul>
<li>The official Free Fire store for CIS countries is Garena Kazakhstan (kzshop.garena.com). Prices are in tenge; it takes bank cards, QiwiKZ and Kazakh mobile operators.</li>
<li>YuPay is a store in Uzbekistan: diamonds by player ID, paid in soʻm with Click, Payme, Uzum, Paynet or your YuPay balance.</li>
<li>At the Central Bank rate prices are nearly the same: on five packs out of six we are about 1% cheaper, on one 2.4% dearer.</li>
</ul>
<h2>Diamond prices compared</h2>
<p>Prices as of 1 October 2026. Garena's are with a bank card, in tenge and converted to soʻm at the Central Bank of Uzbekistan's rate (1 tenge = 26.84 soʻm).</p>
<table>
<thead>
<tr><th>Diamonds</th><th>YuPay</th><th>Garena, tenge</th><th>Garena ≈ soʻm</th></tr>
</thead>
<tbody>
<tr><td>110</td><td>10,292</td><td>386</td><td>10,360</td></tr>
<tr><td>341</td><td>31,823</td><td>1,158</td><td>31,080</td></tr>
<tr><td>572</td><td>51,697</td><td>1,931</td><td>51,830</td></tr>
<tr><td>1166</td><td>102,803</td><td>3,867</td><td>103,790</td></tr>
<tr><td>2398</td><td>205,487</td><td>7,734</td><td>207,580</td></tr>
<tr><td>6160</td><td>515,906</td><td>19,340</td><td>519,090</td></tr>
</tbody>
</table>
<p>Garena labels its packs «buy 100 — get 110»: 110 diamonds reach the account. Our names give the total, so the packs are the same.</p>
<p><strong>What the table cannot show.</strong> Paying in tenge with a card from Uzbekistan, your bank converts at its own rate, usually worse than the Central Bank's, and some banks add a fee for paying in another currency. On YuPay the price is already in soʻm: what you see is what is charged.</p>
<h2>How they differ</h2>
<table>
<thead>
<tr><th></th><th>YuPay</th><th>Garena Kazakhstan</th></tr>
</thead>
<tbody>
<tr><td>Currency</td><td>Soʻm</td><td>Tenge</td></tr>
<tr><td>Payment</td><td>Click, Payme, Uzum, Paynet, YuPay balance</td><td>Bank card, QiwiKZ, Beeline, Activ, Kcell, Tele2, Altel (Kazakhstan)</td></tr>
<tr><td>What you need</td><td>Player ID</td><td>Player ID, or sign-in with the game account</td></tr>
<tr><td>Besides diamonds</td><td>Membership and bundles</td><td>BP Card, weekly and monthly vouchers</td></tr>
<tr><td>Support</td><td>On Telegram, in Russian and Uzbek</td><td>Garena's CIS support desk</td></tr>
</tbody>
</table>
<h2>Which to choose</h2>
<ul>
<li><strong>Garena</strong> — if you have a card that pays in tenge without trouble, or want its special offers.</li>
<li><strong>YuPay</strong> — if you would rather pay in soʻm with Click, Payme or Uzum and not think about bank rates and fees.</li>
</ul>
<p>Whether Garena accepts a particular Uzbek card depends on the bank and the card network — if you plan to pay there, check first.</p>
<h2>How to buy diamonds on YuPay</h2>
<ol>
<li>Open <a href="/en/store/free-fire">Free Fire top-up</a>.</li>
<li>Pick a diamond pack.</li>
<li>Enter your player ID — it is in the game, on your profile, under your name. The diamonds work in Free Fire MAX too: it is one account.</li>
<li>Pay in soʻm. The diamonds arrive on the account automatically.</li>
</ol>
<p>Neither we nor Garena need your password. More in our <a href="/en/blog/free-fire-diamonds-top-up">Free Fire top-up guide</a>.</p>$html$,
  'Garena Shop or YuPay: Free Fire diamonds in Uzbekistan',
  'Garena Shop vs YuPay: Free Fire diamond prices in soʻm and tenge, paying with Click, Payme, Uzum or a card, and what to watch for.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
(gen_random_uuid(), :post_id, 'en', 0, 'Which is the official Free Fire store for Uzbekistan?',
 'For CIS countries it is Garena Kazakhstan — kzshop.garena.com. Prices are in tenge; it takes bank cards, QiwiKZ and Kazakh mobile operators.'),
(gen_random_uuid(), :post_id, 'en', 1, 'Where are Free Fire diamonds cheaper, Garena or YuPay?',
 'On 1 October 2026, at the Central Bank rate, nearly the same: YuPay is about 1% cheaper on five packs out of six and 2.4% dearer on the 341-diamond pack. Paying in tenge with an Uzbek card, banks usually convert at a worse rate than the Central Bank.'),
(gen_random_uuid(), :post_id, 'en', 2, 'Can I buy Free Fire diamonds with Click or Payme?',
 'Yes, on YuPay: Click, Payme, Uzum, Paynet or your YuPay balance. Prices are in soʻm and diamonds arrive automatically by player ID.'),
(gen_random_uuid(), :post_id, 'en', 3, 'Do the diamonds work in Free Fire MAX?',
 'Yes. Free Fire and Free Fire MAX share one account, so a top-up by player ID works for both.');

-- ------------------------------------------------------------------ Uzbek --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'uz', 'garena-shop-yoki-yupay-free-fire',
  'Garena Shop yoki YuPay: Oʻzbekistonda Free Fire olmoslari',
  'Garena’ning rasmiy doʻkoni va YuPay’ni solishtiramiz: Free Fire olmoslari narxi soʻmda, toʻlov usullari va tengeda karta bilan toʻlashda nimani hisobga olish kerak.',
$html$<h2>Asosiysi</h2>
<ul>
<li>MDH davlatlari uchun Free Fire’ning rasmiy doʻkoni — Garena Kazakhstan (kzshop.garena.com). Narxlar tengeda, toʻlov bank kartasi, QiwiKZ va Qozogʻiston mobil operatorlari orqali.</li>
<li>YuPay — Oʻzbekistondagi doʻkon: olmoslar oʻyinchi ID orqali, Click, Payme, Uzum, Paynet yoki YuPay balansi orqali soʻmda toʻlov.</li>
<li>Markaziy bank kursi boʻyicha narxlar deyarli bir xil: oltita paketdan beshtasida biz taxminan 1 % arzonmiz, bittasida 2,4 % qimmatmiz.</li>
</ul>
<h2>Olmos narxlari: solishtirish</h2>
<p>Narxlar 2026-yil 1-oktabr holatiga. Garena — bank kartasi bilan toʻlaganda, tengeda va Oʻzbekiston Markaziy banki kursi boʻyicha soʻmga oʻtkazilgan (1 tenge = 26,84 soʻm).</p>
<table>
<thead>
<tr><th>Olmos</th><th>YuPay</th><th>Garena, tenge</th><th>Garena ≈ soʻm</th></tr>
</thead>
<tbody>
<tr><td>110</td><td>10 292</td><td>386</td><td>10 360</td></tr>
<tr><td>341</td><td>31 823</td><td>1 158</td><td>31 080</td></tr>
<tr><td>572</td><td>51 697</td><td>1 931</td><td>51 830</td></tr>
<tr><td>1166</td><td>102 803</td><td>3 867</td><td>103 790</td></tr>
<tr><td>2398</td><td>205 487</td><td>7 734</td><td>207 580</td></tr>
<tr><td>6160</td><td>515 906</td><td>19 340</td><td>519 090</td></tr>
</tbody>
</table>
<p>Garena paketlarni «100 ta sotib ol — 110 ta ol» deb yozadi: akkauntga 110 ta olmos tushadi. Bizda nomda darhol jami, shuning uchun paketlar bir xil.</p>
<p><strong>Jadval koʻrsatmaydigan narsa.</strong> Oʻzbekiston kartasi bilan tengeda toʻlasangiz, bank summani oʻz kursi boʻyicha hisoblaydi, u odatda Markaziy bank kursidan yomonroq. Ayrim banklar boshqa valyutada toʻlov uchun komissiya ham oladi. YuPay’da narx darhol soʻmda: ekranda qancha boʻlsa, shuncha yechiladi.</p>
<h2>Farqlari</h2>
<table>
<thead>
<tr><th></th><th>YuPay</th><th>Garena Kazakhstan</th></tr>
</thead>
<tbody>
<tr><td>Valyuta</td><td>Soʻm</td><td>Tenge</td></tr>
<tr><td>Toʻlov</td><td>Click, Payme, Uzum, Paynet, YuPay balansi</td><td>Bank kartasi, QiwiKZ, Beeline, Activ, Kcell, Tele2, Altel (Qozogʻiston)</td></tr>
<tr><td>Nima kerak</td><td>Oʻyinchi ID</td><td>Oʻyinchi ID yoki oʻyin akkaunti orqali kirish</td></tr>
<tr><td>Olmosdan tashqari</td><td>Obuna va toʻplamlar</td><td>BP Card, haftalik va oylik vaucher</td></tr>
<tr><td>Yordam</td><td>Telegram’da, rus va oʻzbek tilida</td><td>Garena’ning MDH yordam xizmati</td></tr>
</tbody>
</table>
<h2>Nimani tanlash kerak</h2>
<ul>
<li><strong>Garena</strong> — agar tengeda bemalol toʻlaydigan kartangiz boʻlsa yoki ularning maxsus takliflari kerak boʻlsa.</li>
<li><strong>YuPay</strong> — agar Click, Payme yoki Uzum orqali soʻmda toʻlash va bank kursi hamda komissiyalari haqida oʻylamaslik qulayroq boʻlsa.</li>
</ul>
<p>Garena muayyan Oʻzbekiston kartasini qabul qilishi bank va toʻlov tizimiga bogʻliq — u yerda toʻlamoqchi boʻlsangiz, oldindan tekshiring.</p>
<h2>YuPay’da olmos qanday sotib olinadi</h2>
<ol>
<li><a href="/uz/store/free-fire">Free Fire toʻldirish</a> sahifasini oching.</li>
<li>Olmos paketini tanlang.</li>
<li>Oʻyinchi ID’ni kiriting — u oʻyinda, profilda, nik ostida. Olmoslar Free Fire MAX uchun ham ishlaydi: akkaunt bitta.</li>
<li>Soʻmda toʻlang. Olmoslar akkauntga avtomatik tushadi.</li>
</ol>
<p>Bizga ham, Garena’ga ham parol kerak emas. Batafsil — <a href="/uz/blog/free-fire-olmos-toldirish">Free Fire toʻldirish qoʻllanmasida</a>.</p>$html$,
  'Garena Shop yoki YuPay: Oʻzbekistonda Free Fire olmoslari',
  'Garena Shop va YuPay solishtiruvi: Free Fire olmoslari narxi soʻm va tengeda, Click, Payme, Uzum yoki karta orqali toʻlov.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
(gen_random_uuid(), :post_id, 'uz', 0, 'Oʻzbekiston uchun Free Fire’ning rasmiy doʻkoni qaysi?',
 'MDH davlatlari uchun bu Garena Kazakhstan — kzshop.garena.com. Narxlar tengeda, toʻlov bank kartasi, QiwiKZ va Qozogʻiston mobil operatorlari orqali.'),
(gen_random_uuid(), :post_id, 'uz', 1, 'Free Fire olmoslari qayerda arzon: Garena’dami yoki YuPay’dami?',
 '2026-yil 1-oktabrda Markaziy bank kursi boʻyicha deyarli bir xil: oltita paketdan beshtasida YuPay taxminan 1 % arzon, 341 olmosli paketda 2,4 % qimmat. Oʻzbekiston kartasi bilan tengeda toʻlaganda banklar odatda Markaziy bankdan yomonroq kursda hisoblaydi.'),
(gen_random_uuid(), :post_id, 'uz', 2, 'Free Fire olmoslarini Click yoki Payme orqali sotib olish mumkinmi?',
 'Ha, YuPay’da: Click, Payme, Uzum, Paynet yoki YuPay balansi. Narxlar soʻmda, olmoslar oʻyinchi ID boʻyicha avtomatik tushadi.'),
(gen_random_uuid(), :post_id, 'uz', 3, 'Olmoslar Free Fire MAX uchun ham ishlaydimi?',
 'Ha. Free Fire va Free Fire MAX bitta akkauntdan foydalanadi, shuning uchun oʻyinchi ID boʻyicha toʻldirish ikkalasiga ham ishlaydi.');

COMMIT;
