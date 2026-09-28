-- Free Fire diamonds guide: review of the Russian original, plus English and
-- Uzbek.
--
-- Arrived from Bunzy on 2026-09-28 as a draft with slug `free-fire`. What the
-- review changed in Russian:
--
--   * Dropped the Sensor Tower "third by downloads in October 2025" figure:
--     it sold nothing and dates the post.
--   * "Проверьте UID дважды" was the only defence it offered. The storefront
--     checks the ID before payment and shows the account's nickname
--     (`required_fields.check`, provider g2b) — that is the check that
--     actually catches a wrong digit, so the steps say so.
--   * The package section was generic. Now it names our six diamond packs
--     (110–6160), the real per-diamond spread (about 10% between the smallest
--     and the largest — not the "почти всегда заметно выгоднее" it implied),
--     and the subscriptions, which our brand FAQ calls the better deal for
--     someone who logs in daily.
--   * "Бонусы и акции" advice about bonus diamonds on packs went: we sell the
--     amounts we list.
--   * The closing store link pointed at `/en/store/free-fire` from the
--     Russian text. Two filler paragraphs went.
--
-- Links carry a locale prefix. `oplata-igr-v-sumah` exists only in Russian,
-- so en/uz point at `buy-game-top-ups-in-uzbekistan` /
-- `ozbekistonda-donat-sotib-olish`.
--
-- Also sets the brand (publish refuses without one) and the cover, rendered
-- in yupay-motion (`Cover-free-fire`) and uploaded through the admin presign
-- path. Leaves the status alone: publishing is a person pressing
-- «Опубликовать».
--
-- Idempotent: re-running rewrites all three translations and FAQ sets.

BEGIN;

\set post_id '''01a0e5a3-e1f6-7980-907d-6445499faefd'''

UPDATE blog_posts
SET primary_brand_id = (SELECT id FROM brands WHERE slug = 'free-fire'),
    cover_image_url = 'https://cdn.yupay.uz/blog_image/2026/09/01a0e69d-e5b4-7a10-8195-301bcdafacbb.jpg',
    updated_at = now()
WHERE id = :post_id;

DELETE FROM blog_post_translations WHERE post_id = :post_id;
DELETE FROM blog_post_faqs WHERE post_id = :post_id;

-- ---------------------------------------------------------------- Russian --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'ru', 'free-fire',
  'Free Fire: как пополнить алмазы быстро и дёшево',
  'Как пополнить алмазы Free Fire в Узбекистане: оплата в сумах, зачисление по игровому ID, где найти UID, какой пакет выгоднее и когда лучше взять подписку.',
$html$<h2>Главное</h2>
<ul>
<li>Алмазы Free Fire пополняются по игровому ID (UID) — логин и пароль не нужны.</li>
<li>Из Узбекистана удобно платить в сумах через Click, Payme или Uzum: без валютной карты и конвертации.</li>
<li>Перед оплатой мы проверяем ID и показываем ник аккаунта — так ошибка в цифре видна сразу.</li>
<li>Алмазы и подписка зачисляются автоматически после оплаты.</li>
<li>Если заходите в игру каждый день, подписка выгоднее разовой покупки алмазов.</li>
</ul>
<p>Пополнить алмазы Free Fire из Узбекистана проще всего по игровому ID: вы указываете UID, выбираете пакет, платите в сумах — и алмазы приходят на аккаунт автоматически. Ниже — на что тратят алмазы, как пополнить их без зарубежной карты и как выбрать между пакетом и подпиской.</p>
<h2>На что тратят алмазы</h2>
<p>Алмазы — премиальная валюта Free Fire. Золото копится за матчи, а алмазы в основном покупают. Аккаунт у Free Fire и Free Fire MAX общий, поэтому алмазы доступны в обоих клиентах.</p>
<ul>
<li><strong>Персонажи.</strong> Многие персонажи с активными и пассивными навыками покупаются за алмазы.</li>
<li><strong>Elite Pass.</strong> Сезонный пропуск с заданиями, скинами и эмоциями.</li>
<li><strong>Скины оружия и косметика.</strong> Облики оружия, питомцев, транспорта, эмоции и наряды.</li>
<li><strong>Luck Royale.</strong> Вращения, в которых выпадают редкие бандлы и предметы.</li>
</ul>
<h2>Как пополнить алмазы в сумах</h2>
<p>Встроенный магазин Free Fire принимает оплату через Google Play или App Store. Для этого нужна карта, которую принимает магазин приложений, а с валютной картой итоговую цену меняют курс и комиссия.</p>
<p>Пополнение по ID проходит без этого:</p>
<ol>
<li>Откройте <a href="https://yupay.uz/store/free-fire">страницу Free Fire в каталоге YuPay</a> и выберите алмазы, подписку или набор.</li>
<li>Введите UID. Мы проверим его и покажем ник аккаунта — убедитесь, что он ваш.</li>
<li>Оплатите через Click, Payme или Uzum. Итог в сумах виден до оплаты, комиссии сверху нет.</li>
<li>Алмазы зачислятся на аккаунт автоматически после подтверждения оплаты.</li>
</ol>
<p>Где найти UID: откройте игру и в лобби нажмите на аватар в левом верхнем углу — ID указан под ником в профиле.</p>
<p>Как устроены локальные способы оплаты, мы разбирали в гайде про <a href="https://yupay.uz/blog/oplata-igr-v-sumah">оплату игр в сумах</a>.</p>
<h2>Пакет или подписка</h2>
<p>У нас шесть пакетов алмазов: 110, 341, 572, 1166, 2398 и 6160. Чем крупнее пакет, тем дешевле алмаз, но разница умеренная — около 10% между самым маленьким и самым большим. Поэтому крупный пакет стоит брать, когда алмазы точно понадобятся, а не ради экономии «на будущее».</p>
<p>Подписка устроена иначе. При активации вы получаете стартовые алмазы, а потом — алмазы каждый день в течение срока: 7 дней у недельной, 30 у месячной. Забирать их нужно, заходя в игру. Если играете ежедневно, подписка выходит выгоднее разовой покупки; если заходите раз в неделю, лучше взять пакет.</p>
<p>Ещё есть наборы — например, Level Up Package, — и Evo Access на 3, 7 или 30 дней. Все варианты и цены — на <a href="https://yupay.uz/store/free-fire">странице Free Fire</a>.</p>
<h2>Как покупать безопасно</h2>
<ul>
<li><strong>Не сообщайте пароль.</strong> Для пополнения по ID он не нужен. Любой запрос логина и пароля — повод уйти.</li>
<li><strong>Сверяйте ник перед оплатой.</strong> Алмазы, отправленные на чужой ID, вернуть сложно.</li>
<li><strong>Смотрите на цену до оплаты.</strong> Итог должен быть виден сразу, без комиссии на последнем шаге.</li>
<li><strong>Не верьте «алмазам за полцены».</strong> Цена сильно ниже рынка чаще всего означает, что алмазов не будет.</li>
</ul>$html$,
  'Как пополнить алмазы Free Fire в Узбекистане за сумы',
  'Алмазы Free Fire из Узбекистана: пополнение по UID за сумы через Click, Payme или Uzum, проверка ника до оплаты, автоматическое зачисление, пакеты от 110 до 6160 и подписка.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
  (gen_random_uuid(), :post_id, 'ru', 0,
   'Нужен ли пароль от аккаунта для пополнения?',
   'Нет. Достаточно игрового ID (UID). Мы не запрашиваем логин и пароль — и вам не стоит сообщать их никому.'),
  (gen_random_uuid(), :post_id, 'ru', 1,
   'Где найти игровой ID в Free Fire?',
   'Откройте игру и в лобби нажмите на аватар в левом верхнем углу. UID указан под ником в профиле.'),
  (gen_random_uuid(), :post_id, 'ru', 2,
   'Можно ли оплатить алмазы в сумах?',
   'Да. Через Click, Payme или Uzum картами Uzcard и Humo. Итоговая сумма видна до оплаты, комиссии сверху нет.'),
  (gen_random_uuid(), :post_id, 'ru', 3,
   'Как быстро приходят алмазы?',
   'Автоматически после подтверждения оплаты. Главное — правильный UID: перед оплатой сверьте ник, который мы показываем.'),
  (gen_random_uuid(), :post_id, 'ru', 4,
   'Что выгоднее — пакет алмазов или подписка?',
   'Если заходите в игру каждый день, подписка: стартовые алмазы плюс алмазы ежедневно в течение 7 или 30 дней. Если играете редко, берите пакет.');

-- ---------------------------------------------------------------- English --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'en', 'free-fire-diamonds-top-up',
  'Free Fire: how to top up diamonds fast and for less',
  'How to top up Free Fire diamonds in Uzbekistan: paying in soʻm, crediting by player ID, where to find your UID, which pack is the better deal, and when a membership pays off.',
$html$<h2>Key points</h2>
<ul>
<li>Free Fire diamonds are topped up by player ID (UID) — no login or password needed.</li>
<li>From Uzbekistan it’s easiest to pay in soʻm with Click, Payme or Uzum: no foreign-currency card, no conversion.</li>
<li>Before you pay we check the ID and show the account’s nickname — so a wrong digit shows up at once.</li>
<li>Diamonds and memberships are credited automatically after payment.</li>
<li>If you log in every day, a membership beats a one-off diamond pack.</li>
</ul>
<p>The simplest way to top up Free Fire diamonds from Uzbekistan is by player ID: enter your UID, pick a pack, pay in soʻm — and the diamonds land on the account automatically. Below: what diamonds are spent on, how to top up without a foreign card, and how to choose between a pack and a membership.</p>
<h2>What diamonds are spent on</h2>
<p>Diamonds are Free Fire’s premium currency. Gold is earned in matches; diamonds are mostly bought. Free Fire and Free Fire MAX share one account, so the diamonds work in both.</p>
<ul>
<li><strong>Characters.</strong> Many characters with active and passive skills are bought with diamonds.</li>
<li><strong>Elite Pass.</strong> The season pass with missions, skins and emotes.</li>
<li><strong>Weapon skins and cosmetics.</strong> Looks for weapons, pets and vehicles, emotes and outfits.</li>
<li><strong>Luck Royale.</strong> Spins that drop rare bundles and items.</li>
</ul>
<h2>How to top up diamonds in soʻm</h2>
<p>Free Fire’s built-in store takes payment through Google Play or the App Store. That needs a card the app store accepts, and with a foreign-currency card the final price shifts with the exchange rate and fees.</p>
<p>A top-up by ID skips all that:</p>
<ol>
<li>Open the <a href="https://yupay.uz/en/store/free-fire">Free Fire page on YuPay</a> and pick diamonds, a membership or a bundle.</li>
<li>Enter your UID. We check it and show the account’s nickname — make sure it’s yours.</li>
<li>Pay with Click, Payme or Uzum. The total in soʻm is shown before you pay, with no fee on top.</li>
<li>The diamonds are credited automatically once the payment is confirmed.</li>
</ol>
<p>Where to find your UID: open the game and, in the lobby, tap your avatar in the top-left corner — the ID is under your nickname in the profile.</p>
<p>We covered how local payment methods work in our guide to <a href="https://yupay.uz/en/blog/buy-game-top-ups-in-uzbekistan">buying game top-ups in Uzbekistan</a>.</p>
<h2>A pack or a membership</h2>
<p>We have six diamond packs: 110, 341, 572, 1166, 2398 and 6160. The bigger the pack, the cheaper the diamond, but the gap is modest — about 10% between the smallest and the largest. So buy a big pack when you’ll actually need the diamonds, not to save “for later”.</p>
<p>A membership works differently. You get starting diamonds on activation, then diamonds every day for the term: 7 days on the weekly, 30 on the monthly. You collect them by logging in. If you play daily, a membership beats a one-off purchase; if you log in once a week, take a pack.</p>
<p>There are also bundles — such as the Level Up Package — and Evo Access for 3, 7 or 30 days. Every option and price is on the <a href="https://yupay.uz/en/store/free-fire">Free Fire page</a>.</p>
<h2>How to buy safely</h2>
<ul>
<li><strong>Don’t share your password.</strong> A top-up by ID doesn’t need it. Any request for your login and password is a reason to leave.</li>
<li><strong>Check the nickname before paying.</strong> Diamonds sent to someone else’s ID are hard to get back.</li>
<li><strong>Look at the price before paying.</strong> The total should be visible up front, with no fee on the last step.</li>
<li><strong>Don’t trust “half-price diamonds”.</strong> A price far below the market usually means no diamonds at all.</li>
</ul>$html$,
  'How to top up Free Fire diamonds in Uzbekistan in soʻm',
  'Free Fire diamonds from Uzbekistan: top up by UID in soʻm with Click, Payme or Uzum, nickname check before payment, automatic crediting, packs from 110 to 6160, and memberships.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
  (gen_random_uuid(), :post_id, 'en', 0,
   'Do I need my account password to top up?',
   'No. Your player ID (UID) is enough. We never ask for your login or password — and you shouldn’t give them to anyone.'),
  (gen_random_uuid(), :post_id, 'en', 1,
   'Where do I find my Free Fire player ID?',
   'Open the game and, in the lobby, tap your avatar in the top-left corner. The UID is under your nickname in the profile.'),
  (gen_random_uuid(), :post_id, 'en', 2,
   'Can I pay for diamonds in soʻm?',
   'Yes. With Uzcard and Humo cards through Click, Payme or Uzum. The total is shown before you pay, with no fee on top.'),
  (gen_random_uuid(), :post_id, 'en', 3,
   'How fast do the diamonds arrive?',
   'Automatically once the payment is confirmed. What matters is the right UID: check the nickname we show before you pay.'),
  (gen_random_uuid(), :post_id, 'en', 4,
   'Which is better — a diamond pack or a membership?',
   'If you log in every day, a membership: starting diamonds plus diamonds daily for 7 or 30 days. If you play rarely, take a pack.');

-- ----------------------------------------------------------------- Uzbek ---

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'uz', 'free-fire-olmos-toldirish',
  'Free Fire: olmoslarni tez va arzon qanday toʻldirish',
  'Oʻzbekistonda Free Fire olmoslarini qanday toʻldirish: soʻmda toʻlov, oʻyin ID’si boʻyicha tushirish, UID qayerda, qaysi paket foydaliroq va obuna qachon oʻzini oqlaydi.',
$html$<h2>Asosiysi</h2>
<ul>
<li>Free Fire olmoslari oʻyin ID’si (UID) boʻyicha toʻldiriladi — login va parol kerak emas.</li>
<li>Oʻzbekistondan Click, Payme yoki Uzum orqali soʻmda toʻlash qulay: valyuta kartasi va konvertatsiyasiz.</li>
<li>Toʻlovdan oldin ID’ni tekshiramiz va akkaunt nikini koʻrsatamiz — raqamdagi xato darhol koʻrinadi.</li>
<li>Olmoslar va obuna toʻlovdan soʻng avtomatik tushadi.</li>
<li>Agar oʻyinga har kuni kirsangiz, obuna bir martalik olmos xarididan foydaliroq.</li>
</ul>
<p>Oʻzbekistondan Free Fire olmoslarini toʻldirishning eng oson yoʻli — oʻyin ID’si boʻyicha: UID’ni kiritasiz, paketni tanlaysiz, soʻmda toʻlaysiz — olmoslar esa akkauntga avtomatik tushadi. Quyida — olmoslar nimaga sarflanadi, xorijiy kartasiz qanday toʻldirish va paket bilan obuna orasida qanday tanlash.</p>
<h2>Olmoslar nimaga sarflanadi</h2>
<p>Olmoslar — Free Fire’ning premium valyutasi. Oltin matchlarda yigʻiladi, olmoslar esa asosan sotib olinadi. Free Fire va Free Fire MAX’da akkaunt umumiy, shuning uchun olmoslar ikkala klientda ham ishlaydi.</p>
<ul>
<li><strong>Personajlar.</strong> Faol va passiv koʻnikmali koʻplab personajlar olmosga sotib olinadi.</li>
<li><strong>Elite Pass.</strong> Topshiriqlar, skinlar va emotsiyalar bilan mavsumiy propusk.</li>
<li><strong>Qurol skinlari va kosmetika.</strong> Qurol, uy hayvonlari va transport koʻrinishlari, emotsiyalar va kiyimlar.</li>
<li><strong>Luck Royale.</strong> Nodir toʻplamlar va buyumlar tushadigan aylantirishlar.</li>
</ul>
<h2>Olmoslarni soʻmda qanday toʻldirish</h2>
<p>Free Fire’ning ichki doʻkoni toʻlovni Google Play yoki App Store orqali qabul qiladi. Buning uchun ilovalar doʻkoni qabul qiladigan karta kerak, valyuta kartasida esa yakuniy narxni kurs va komissiya oʻzgartiradi.</p>
<p>ID boʻyicha toʻldirish bularsiz oʻtadi:</p>
<ol>
<li><a href="https://yupay.uz/uz/store/free-fire">YuPay’dagi Free Fire</a> sahifasini oching va olmos, obuna yoki toʻplamni tanlang.</li>
<li>UID’ni kiriting. Biz uni tekshiramiz va akkaunt nikini koʻrsatamiz — u sizniki ekaniga ishonch hosil qiling.</li>
<li>Click, Payme yoki Uzum orqali toʻlang. Soʻmdagi yakuniy summa toʻlovdan oldin koʻrinadi, ustama komissiya yoʻq.</li>
<li>Toʻlov tasdiqlangach, olmoslar akkauntga avtomatik tushadi.</li>
</ol>
<p>UID qayerda: oʻyinni oching va lobbida chap yuqori burchakdagi avatarni bosing — ID profilda nikingiz ostida koʻrsatilgan.</p>
<p>Mahalliy toʻlov usullari qanday ishlashini <a href="https://yupay.uz/uz/blog/ozbekistonda-donat-sotib-olish">Oʻzbekistonda donat sotib olish</a> boʻyicha qoʻllanmada koʻrib chiqqanmiz.</p>
<h2>Paketmi yoki obunami</h2>
<p>Bizda oltita olmos paketi bor: 110, 341, 572, 1166, 2398 va 6160. Paket qancha katta boʻlsa, olmos shuncha arzon, lekin farq oʻrtacha — eng kichigi bilan eng kattasi orasida taxminan 10%. Shuning uchun katta paketni olmoslar aniq kerak boʻlganda oling, «keyinga» tejash uchun emas.</p>
<p>Obuna boshqacha ishlaydi. Faollashtirishda boshlangʻich olmoslarni olasiz, keyin esa muddat davomida har kuni olmos: haftalikda 7 kun, oylikda 30 kun. Ularni oʻyinga kirib olasiz. Har kuni oʻynasangiz, obuna bir martalik xariddan foydaliroq; haftada bir marta kirsangiz, paket oling.</p>
<p>Shuningdek toʻplamlar — masalan, Level Up Package — va 3, 7 yoki 30 kunlik Evo Access bor. Barcha variantlar va narxlar — <a href="https://yupay.uz/uz/store/free-fire">Free Fire sahifasida</a>.</p>
<h2>Qanday xavfsiz sotib olish</h2>
<ul>
<li><strong>Parolni aytmang.</strong> ID boʻyicha toʻldirish uchun u kerak emas. Login va parol soʻralsa — ketish uchun sabab.</li>
<li><strong>Toʻlovdan oldin nikni tekshiring.</strong> Begona ID’ga yuborilgan olmoslarni qaytarish qiyin.</li>
<li><strong>Narxni toʻlovdan oldin koʻring.</strong> Yakuniy summa oxirgi qadamda komissiyasiz, darhol koʻrinishi kerak.</li>
<li><strong>«Yarim narxdagi olmoslar»ga ishonmang.</strong> Bozordan ancha past narx koʻpincha olmos umuman boʻlmasligini bildiradi.</li>
</ul>$html$,
  'Oʻzbekistonda Free Fire olmoslarini soʻmda qanday toʻldirish',
  'Oʻzbekistondan Free Fire olmoslari: Click, Payme yoki Uzum orqali soʻmda UID boʻyicha toʻldirish, toʻlovdan oldin nik tekshiruvi, avtomatik tushish, 110 dan 6160 gacha paketlar va obuna.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
  (gen_random_uuid(), :post_id, 'uz', 0,
   'Toʻldirish uchun akkaunt paroli kerakmi?',
   'Yoʻq. Oʻyin ID’si (UID) yetarli. Biz login va parolni soʻramaymiz — ularni hech kimga aytmang.'),
  (gen_random_uuid(), :post_id, 'uz', 1,
   'Free Fire’da oʻyin ID’sini qayerdan topaman?',
   'Oʻyinni oching va lobbida chap yuqori burchakdagi avatarni bosing. UID profilda nikingiz ostida koʻrsatilgan.'),
  (gen_random_uuid(), :post_id, 'uz', 2,
   'Olmoslar uchun soʻmda toʻlash mumkinmi?',
   'Ha. Click, Payme yoki Uzum orqali Uzcard va Humo kartalari bilan. Yakuniy summa toʻlovdan oldin koʻrinadi, ustama komissiya yoʻq.'),
  (gen_random_uuid(), :post_id, 'uz', 3,
   'Olmoslar qanchalik tez keladi?',
   'Toʻlov tasdiqlangach avtomatik. Asosiysi — toʻgʻri UID: toʻlovdan oldin biz koʻrsatgan nikni tekshiring.'),
  (gen_random_uuid(), :post_id, 'uz', 4,
   'Nima foydaliroq — olmos paketimi yoki obunami?',
   'Oʻyinga har kuni kirsangiz — obuna: boshlangʻich olmoslar va 7 yoki 30 kun davomida har kuni olmos. Kamdan-kam oʻynasangiz, paket oling.');

COMMIT;
