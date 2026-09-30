-- «Пополнение игр без комиссии: разбор сервиса» (Bunzy, 2026-10-01, draft, ru
-- only, slug `post-5`): review, repositioning, plus English and Uzbek.
--
-- **Repositioned.** Three published posts already own «без комиссии» —
-- `popolneniye-igr-onlayn` («Пополнение игр онлайн: быстро и без комиссии»),
-- `kupit-donat-v-uzbekistane` and `oplata-igr-v-sumah` (which has «Как
-- избежать скрытых комиссий банков»). A fourth on the same phrase would split
-- their traffic. What this draft actually argued — where overpayment hides and
-- how to catch it — is its own angle, so it now leads with «скрытые комиссии»
-- and a checklist the reader can apply anywhere, and links to the overview
-- post for the service itself.
--
-- What the review changed:
--
--   * Cut the payment-processing statistics (2.4% average, 2.5–3.5% for small
--     merchants, Clearly Payments, 2024): they describe the US card market,
--     not Uzbekistan, and read as if they did. The 3% example stays, labelled
--     as an illustration rather than a claim about anyone's fees.
--   * «Отзывы геймеров об удобстве» quoted no reviews at all. Replaced with the
--     real figure: 173 reviews, 4.96 average (GET /reviews/featured, 2026-10-01).
--   * «Цена не пересчитывается при скачках курса» was wrong — our prices follow
--     the rate. What is true: the total in soʻm is shown before payment and
--     exactly that is charged, the same for Click, Payme, Uzum, Paynet and the
--     balance (orders compute the total by currency only, not by method).
--   * Named the payment methods; «Yupay» → «YuPay»; «я показываю» → «мы»; the
--     catalogue link pointed at `/en/store` from the Russian text; slug
--     `post-5` → `skrytye-komissii-pri-donate`.
--
-- Brand `pubg-mobile`, as the three general posts above use. Cover
-- `Cover-hidden-fees`. Status stays `draft`. Idempotent.

BEGIN;

\set post_id '''01a0f061-6643-7d62-afc9-a1214093d274'''

UPDATE blog_posts
SET primary_brand_id = (SELECT id FROM brands WHERE slug = 'pubg-mobile'),
    cover_image_url = 'https://cdn.yupay.uz/blog_image/2026/09/01a0f3e8-07f5-7600-b363-9297a70dc2e7.jpg',
    updated_at = now()
WHERE id = :post_id;

DELETE FROM blog_post_translations WHERE post_id = :post_id;
DELETE FROM blog_post_faqs WHERE post_id = :post_id;

-- ---------------------------------------------------------------- Russian --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'ru', 'skrytye-komissii-pri-donate',
  'Скрытые комиссии при донате: где прячется переплата и как её заметить',
  'Где прячутся доплаты при пополнении игр — в курсе, на последнем шаге оплаты, в цене за способ оплаты — и как проверить любой сервис за минуту.',
$html$<h2>Главное</h2>
<ul>
<li>«Без комиссии» значит одно: сумма, которую вы видите до оплаты, и есть сумма списания.</li>
<li>Переплата обычно прячется в трёх местах: в курсе валюты, в сборе на последнем шаге и в разной цене для разных способов оплаты.</li>
<li>Проверить любой сервис можно за минуту — ниже короткий список.</li>
<li>На YuPay итог в сумах виден до оплаты и одинаков для Click, Payme, Uzum, Paynet и баланса.</li>
</ul>
<h2>Где прячется переплата</h2>
<p>Слово «бесплатно» на баннере и итог на экране оплаты часто расходятся. Схем немного, и все они узнаваемы.</p>
<ul>
<li><strong>Курс валюты.</strong> Цена указана в долларах или рублях, а в сумы её переводят по невыгодному курсу. Формально комиссии нет, но платите вы больше рыночного.</li>
<li><strong>Сбор на последнем шаге.</strong> На карточке товара цена одна, а «сервисный сбор» или процент за обработку платежа появляется только на финальном экране.</li>
<li><strong>Цена зависит от способа оплаты.</strong> Картой одна сумма, кошельком другая. Разница и есть переложенная на вас комиссия.</li>
<li><strong>Оплата в чужой валюте.</strong> Если платите картой в долларах или тенге, банк пересчитает по своему курсу и может добавить комиссию за конвертацию.</li>
</ul>
<h2>Как проверить сервис за минуту</h2>
<ol>
<li>Запомните цену на карточке товара и сравните с суммой на экране оплаты. Выросла — значит, есть доплата.</li>
<li>Посмотрите, в какой валюте цена. Если не в сумах — итог будет зависеть от курса вашего банка.</li>
<li>Переключите способ оплаты. Если сумма меняется, за какой-то способ вы доплачиваете.</li>
<li>После оплаты сверьте списание в приложении банка с суммой, которую вам показали.</li>
</ol>
<h2>Сколько это стоит на практике</h2>
<p>Для примера: если к пополнению на 100 000 сум добавляется 3 %, это 3 000 сум сверху. Четыре таких пополнения в месяц — 12 000 сум, за год — около 144 000 сум. Мелкая доплата на каждом чеке складывается в сумму, на которую можно было взять ещё одно пополнение.</p>
<h2>Как устроено у нас</h2>
<ul>
<li><strong>Цена в сумах сразу.</strong> Наша наценка уже в цене товара, отдельного процента за оплату нет.</li>
<li><strong>Итог виден до оплаты,</strong> и списывается ровно он.</li>
<li><strong>Одна цена для всех способов оплаты:</strong> Click, Payme, Uzum, Paynet или баланс YuPay.</li>
<li><strong>Зачисление автоматическое</strong> — по ID игрока или логину, без пароля.</li>
</ul>
<p>Цены в сумах следуют курсу, поэтому со временем могут меняться. Но в момент покупки сумма фиксирована: что показали, то и спишется.</p>
<h2>Что говорят покупатели</h2>
<p>На 1 октября 2026 года у YuPay 173 отзыва со средней оценкой 4,96 из 5. Отзывы оставляют только те, кто уже получил заказ.</p>
<h2>С чего начать</h2>
<p>Откройте нужную игру в <a href="/store">каталоге YuPay</a> и сравните итог в сумах с тем, что вы платите сейчас. Как устроено пополнение у нас, — в статье <a href="/blog/popolneniye-igr-onlayn">«Пополнение игр онлайн: быстро и без комиссии»</a>, о локальных способах оплаты — в статье <a href="/blog/oplata-igr-v-sumah">про оплату игр в сумах</a>.</p>$html$,
  'Скрытые комиссии при донате: где переплата и как её заметить',
  'Где прячутся доплаты при пополнении игр: курс валюты, сбор на последнем шаге, цена за способ оплаты. Как проверить сервис за минуту.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
(gen_random_uuid(), :post_id, 'ru', 0, 'Что значит пополнение без комиссии?',
 'Что сумма, которую вы видите до оплаты, и есть сумма списания: без процента за обработку платежа, сбора на последнем шаге или доплаты за способ оплаты.'),
(gen_random_uuid(), :post_id, 'ru', 1, 'Где чаще всего прячут комиссию?',
 'В невыгодном курсе валюты, в «сервисном сборе» на последнем экране оплаты и в разной цене для разных способов оплаты. При оплате картой в чужой валюте ещё и банк считает по своему курсу.'),
(gen_random_uuid(), :post_id, 'ru', 2, 'Зависит ли цена на YuPay от способа оплаты?',
 'Нет. Итог в сумах одинаков для Click, Payme, Uzum, Paynet и баланса YuPay, и он виден до оплаты.'),
(gen_random_uuid(), :post_id, 'ru', 3, 'Могут ли цены в сумах меняться?',
 'Да, они следуют курсу и со временем могут меняться. Но в момент покупки сумма фиксирована: списывается ровно та, что показана перед оплатой.');

-- ---------------------------------------------------------------- English --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'en', 'hidden-fees-game-top-ups',
  'Hidden fees on game top-ups: where the overpayment hides and how to spot it',
  'Where extra charges hide when you top up a game — in the exchange rate, on the last checkout step, in a price per payment method — and how to check any store in a minute.',
$html$<h2>The short version</h2>
<ul>
<li>«No fee» means one thing: the amount you see before paying is the amount charged.</li>
<li>Overpayment usually hides in three places: the exchange rate, a fee on the last step, and a different price per payment method.</li>
<li>You can check any store in a minute — a short list is below.</li>
<li>On YuPay the total in soʻm is shown before you pay and is the same for Click, Payme, Uzum, Paynet and the balance.</li>
</ul>
<h2>Where the overpayment hides</h2>
<p>«Free» on a banner and the total on the payment screen often disagree. The tricks are few and easy to recognise.</p>
<ul>
<li><strong>The exchange rate.</strong> The price is in dollars or roubles and converted to soʻm at a poor rate. Formally there is no fee, but you pay more than the market rate.</li>
<li><strong>A fee on the last step.</strong> The product card shows one price, and a «service fee» or processing percentage appears only on the final screen.</li>
<li><strong>A price per payment method.</strong> One amount by card, another by wallet. The difference is a fee passed on to you.</li>
<li><strong>Paying in a foreign currency.</strong> Pay by card in dollars or tenge and your bank converts at its own rate and may add a conversion fee.</li>
</ul>
<h2>How to check a store in a minute</h2>
<ol>
<li>Note the price on the product card and compare it with the amount on the payment screen. If it grew, there is a surcharge.</li>
<li>Check the price currency. If it is not soʻm, the total depends on your bank's rate.</li>
<li>Switch the payment method. If the amount changes, you pay extra for one of them.</li>
<li>After paying, compare the charge in your banking app with the amount you were shown.</li>
</ol>
<h2>What it costs in practice</h2>
<p>For example: add 3% to a 100,000 soʻm top-up and that is 3,000 soʻm on top. Four such top-ups a month make 12,000 soʻm, about 144,000 soʻm a year. A small surcharge on every receipt adds up to another top-up's worth.</p>
<h2>How it works on YuPay</h2>
<ul>
<li><strong>Prices in soʻm straight away.</strong> Our margin is already in the price; there is no separate payment percentage.</li>
<li><strong>The total is shown before you pay,</strong> and exactly that is charged.</li>
<li><strong>One price for every payment method:</strong> Click, Payme, Uzum, Paynet or your YuPay balance.</li>
<li><strong>Automatic delivery</strong> — by player ID or login, no password.</li>
</ul>
<p>Prices in soʻm follow the exchange rate, so they can change over time. At the moment of purchase the amount is fixed: what you are shown is what is charged.</p>
<h2>What buyers say</h2>
<p>As of 1 October 2026 YuPay has 173 reviews with an average of 4.96 out of 5. Only buyers who have received their order can leave one.</p>
<h2>Where to start</h2>
<p>Open your game in the <a href="/en/store">YuPay catalogue</a> and compare the total in soʻm with what you pay now. How top-ups work here is in <a href="/en/blog/online-game-top-ups-uzbekistan">«Online game top-ups: fast, and with no fee»</a>; local payment methods are covered in <a href="/en/blog/buy-game-top-ups-in-uzbekistan">«Buying game top-ups in Uzbekistan»</a>.</p>$html$,
  'Hidden fees on game top-ups: where they hide and how to spot them',
  'Where extra charges hide on game top-ups: the exchange rate, a last-step fee, a price per payment method. How to check any store in a minute.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
(gen_random_uuid(), :post_id, 'en', 0, 'What does a top-up with no fee mean?',
 'That the amount you see before paying is the amount charged: no processing percentage, no last-step fee, no surcharge for a payment method.'),
(gen_random_uuid(), :post_id, 'en', 1, 'Where are fees most often hidden?',
 'In a poor exchange rate, in a «service fee» on the last payment screen, and in a different price per payment method. Paying by card in a foreign currency, your bank also converts at its own rate.'),
(gen_random_uuid(), :post_id, 'en', 2, 'Does the price on YuPay depend on the payment method?',
 'No. The total in soʻm is the same for Click, Payme, Uzum, Paynet and the YuPay balance, and it is shown before you pay.'),
(gen_random_uuid(), :post_id, 'en', 3, 'Can prices in soʻm change?',
 'Yes, they follow the exchange rate and can change over time. At the moment of purchase the amount is fixed: exactly what you were shown is charged.');

-- ------------------------------------------------------------------ Uzbek --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'uz', 'donatdagi-yashirin-komissiyalar',
  'Donatdagi yashirin komissiyalar: ortiqcha toʻlov qayerda yashirinadi va uni qanday payqash mumkin',
  'Oʻyinni toʻldirishda qoʻshimcha toʻlovlar qayerda yashirinadi — valyuta kursida, toʻlovning oxirgi bosqichida, toʻlov usuliga qarab narxda — va istalgan xizmatni bir daqiqada qanday tekshirish mumkin.',
$html$<h2>Asosiysi</h2>
<ul>
<li>«Komissiyasiz» degani bitta narsa: toʻlovdan oldin koʻrgan summangiz yechiladigan summa bilan bir xil.</li>
<li>Ortiqcha toʻlov odatda uch joyda yashirinadi: valyuta kursida, oxirgi bosqichdagi yigʻimda va turli toʻlov usullari uchun turli narxda.</li>
<li>Istalgan xizmatni bir daqiqada tekshirish mumkin — quyida qisqa roʻyxat.</li>
<li>YuPay’da soʻmdagi jami toʻlovdan oldin koʻrinadi va Click, Payme, Uzum, Paynet hamda balans uchun bir xil.</li>
</ul>
<h2>Ortiqcha toʻlov qayerda yashirinadi</h2>
<p>Bannerdagi «bepul» soʻzi va toʻlov ekranidagi jami koʻpincha farq qiladi. Usullar koʻp emas va ularni oson tanish mumkin.</p>
<ul>
<li><strong>Valyuta kursi.</strong> Narx dollar yoki rublda koʻrsatilgan, soʻmga esa noqulay kursda oʻtkaziladi. Rasman komissiya yoʻq, lekin siz bozor kursidan koʻproq toʻlaysiz.</li>
<li><strong>Oxirgi bosqichdagi yigʻim.</strong> Mahsulot kartochkasida bitta narx, «xizmat yigʻimi» yoki toʻlovni qayta ishlash foizi esa faqat oxirgi ekranda paydo boʻladi.</li>
<li><strong>Narx toʻlov usuliga bogʻliq.</strong> Karta bilan bitta summa, hamyon bilan boshqa. Farq — sizga yuklangan komissiya.</li>
<li><strong>Xorijiy valyutada toʻlov.</strong> Karta bilan dollar yoki tengeda toʻlasangiz, bank oʻz kursi boʻyicha hisoblaydi va konvertatsiya uchun komissiya qoʻshishi mumkin.</li>
</ul>
<h2>Xizmatni bir daqiqada qanday tekshirish mumkin</h2>
<ol>
<li>Mahsulot kartochkasidagi narxni eslab qoling va toʻlov ekranidagi summa bilan solishtiring. Oshgan boʻlsa — qoʻshimcha toʻlov bor.</li>
<li>Narx qaysi valyutada ekanini koʻring. Soʻmda boʻlmasa — jami bankingiz kursiga bogʻliq boʻladi.</li>
<li>Toʻlov usulini almashtiring. Summa oʻzgarsa, qaysidir usul uchun ortiqcha toʻlayapsiz.</li>
<li>Toʻlovdan keyin bank ilovasidagi yechilgan summani sizga koʻrsatilgan summa bilan solishtiring.</li>
</ol>
<h2>Amalda bu qancha turadi</h2>
<p>Misol uchun: 100 000 soʻmlik toʻldirishga 3 % qoʻshilsa, bu ustiga 3 000 soʻm. Oyiga toʻrtta shunday toʻldirish — 12 000 soʻm, yiliga — taxminan 144 000 soʻm. Har bir chekdagi kichik qoʻshimcha toʻlov yana bitta toʻldirishga yetadigan summaga aylanadi.</p>
<h2>Bizda qanday ishlaydi</h2>
<ul>
<li><strong>Narx darhol soʻmda.</strong> Ustamamiz allaqachon mahsulot narxida, toʻlov uchun alohida foiz yoʻq.</li>
<li><strong>Jami toʻlovdan oldin koʻrinadi</strong> va aynan u yechiladi.</li>
<li><strong>Barcha toʻlov usullari uchun bitta narx:</strong> Click, Payme, Uzum, Paynet yoki YuPay balansi.</li>
<li><strong>Avtomatik tushadi</strong> — oʻyinchi ID yoki login orqali, parolsiz.</li>
</ul>
<p>Soʻmdagi narxlar kursga bogʻliq, shuning uchun vaqt oʻtishi bilan oʻzgarishi mumkin. Lekin xarid paytida summa qatʼiy: nima koʻrsatilgan boʻlsa, shu yechiladi.</p>
<h2>Xaridorlar nima deydi</h2>
<p>2026-yil 1-oktabr holatiga YuPay’da 173 ta sharh bor, oʻrtacha baho 5 dan 4,96. Sharhni faqat buyurtmasini olgan xaridorlar qoldiradi.</p>
<h2>Nimadan boshlash kerak</h2>
<p><a href="/uz/store">YuPay katalogida</a> kerakli oʻyinni oching va soʻmdagi jamini hozir toʻlayotganingiz bilan solishtiring. Bizda toʻldirish qanday ishlashi — <a href="/uz/blog/onlayn-oyin-toldirish">«Oʻyinlarni onlayn toʻldirish: tez va komissiyasiz»</a> maqolasida, mahalliy toʻlov usullari haqida — <a href="/uz/blog/ozbekistonda-donat-sotib-olish">«Oʻzbekistonda donat sotib olish»</a> maqolasida.</p>$html$,
  'Donatdagi yashirin komissiyalar: qayerda va qanday payqash mumkin',
  'Oʻyinni toʻldirishda qoʻshimcha toʻlovlar qayerda yashirinadi: valyuta kursi, oxirgi bosqich yigʻimi, toʻlov usuliga qarab narx. Tekshirish usuli.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
(gen_random_uuid(), :post_id, 'uz', 0, 'Komissiyasiz toʻldirish nimani anglatadi?',
 'Toʻlovdan oldin koʻrgan summangiz yechiladigan summa bilan bir xil ekanini: toʻlovni qayta ishlash foizi, oxirgi bosqich yigʻimi yoki toʻlov usuli uchun qoʻshimcha toʻlovsiz.'),
(gen_random_uuid(), :post_id, 'uz', 1, 'Komissiya koʻpincha qayerda yashiriladi?',
 'Noqulay valyuta kursida, oxirgi toʻlov ekranidagi «xizmat yigʻimi»da va turli toʻlov usullari uchun turli narxda. Karta bilan xorijiy valyutada toʻlaganda bank ham oʻz kursi boʻyicha hisoblaydi.'),
(gen_random_uuid(), :post_id, 'uz', 2, 'YuPay’da narx toʻlov usuliga bogʻliqmi?',
 'Yoʻq. Soʻmdagi jami Click, Payme, Uzum, Paynet va YuPay balansi uchun bir xil va toʻlovdan oldin koʻrinadi.'),
(gen_random_uuid(), :post_id, 'uz', 3, 'Soʻmdagi narxlar oʻzgarishi mumkinmi?',
 'Ha, ular kursga bogʻliq va vaqt oʻtishi bilan oʻzgarishi mumkin. Lekin xarid paytida summa qatʼiy: aynan toʻlovdan oldin koʻrsatilgan summa yechiladi.');

COMMIT;
