-- Steam trade link guide: where to find it, how to copy it, what makes a trade
-- go through. Russian, English, Uzbek.
--
-- Written 2026-09-30 from search demand: «трейд ссылка стим» is 100–1k searches a
-- month in Uzbekistan's Google (Keyword Planner) and «трейд ссылка» 65k in
-- Wordstat, mostly «где найти». Every CS2 skin buyer needs one at checkout, so the
-- guide ends at the skins market.
--
-- What it says is what the product does: the checkout checks the link before
-- payment for exactly four things (not a trade link, private inventory, trade
-- ban, a hold because Steam Guard Mobile has not run 7 days), and after the
-- trade Steam protects it for a week. The screenshot is a redrawn Steam page
-- with an invented link — never a real token, which is a credential.
--
-- Cover rendered in yupay-motion (`Cover-trade-link`); cover and both schemes
-- uploaded through the storage presign path. Brand `cs2-skins`, whose buy card is
-- the skins market. Status stays `draft`: publishing is a person pressing
-- «Опубликовать».
--
-- Idempotent: the post keeps its id; re-running rewrites all three translations
-- and FAQ sets.

BEGIN;

\set post_id '''cefba719-c61c-4bd9-a450-aa6b01d1ae6e'''

INSERT INTO blog_posts (id, kind, status, primary_brand_id, show_buy_card, pin_on_brand, cover_image_url)
SELECT :post_id, 'guide', 'draft', b.id, true, false,
       'https://cdn.yupay.uz/blog_image/2026/09/01a0f391-db54-7ad2-899b-ca912fa3e008.jpg'
FROM brands b WHERE b.slug = 'cs2-skins'
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
  :post_id, 'ru', 'treyd-ssylka-steam',
  'Трейд-ссылка Steam: где найти и как скопировать',
  'Где в Steam найти трейд-ссылку, как скопировать её целиком и что проверить, чтобы обмен со скином CS2 прошёл без задержек.',
$html$<h2>Главное</h2>
<ul>
<li>Трейд-ссылка — адрес, по которому вам могут прислать предложение обмена в Steam, даже если вы не в друзьях.</li>
<li>Она нужна, чтобы купить скин CS2: по ней продавец отправляет вам обмен.</li>
<li>Найти её быстрее всего по прямой ссылке: <a href="https://steamcommunity.com/my/tradeoffers/privacy">steamcommunity.com/my/tradeoffers/privacy</a>.</li>
<li>Пароль и код Steam Guard для этого не нужны — никому их не сообщайте.</li>
</ul>
<h2>Где найти трейд-ссылку</h2>
<ol>
<li>Войдите в Steam в браузере и откройте <a href="https://steamcommunity.com/my/tradeoffers/privacy">настройки предложений обмена</a> — страница откроется в вашем аккаунте.</li>
<li>Или вручную: наведите на свой ник → «Инвентарь» → «Предложения обмена» → справа «Кто может отправлять мне предложения обмена?».</li>
<li>Внизу, в блоке «Сторонние сайты», есть поле «Ссылка на обмен». Скопируйте её целиком — от <code>https</code> до последнего символа после <code>token=</code>.</li>
</ol>
<img src="https://cdn.yupay.uz/blog_image/2026/09/01a0f391-ec35-7c10-a35e-1bd56261c1b1.jpg" alt="Страница Steam «Кто может отправлять мне предложения обмена?»: поле «Ссылка на обмен» в блоке «Сторонние сайты»">
<p>Если Steam у вас только в приложении, откройте ту же прямую ссылку в браузере и войдите в аккаунт — страница будет та же.</p>
<h2>Как выглядит правильная ссылка</h2>
<p><code>https://steamcommunity.com/tradeoffer/new/?partner=123456789&amp;token=AbCd1234</code></p>
<p>Здесь <code>partner</code> — номер вашего аккаунта, <code>token</code> — ключ, без которого обмен от незнакомого человека не придёт. Частые ошибки: вместо трейд-ссылки скопирована ссылка на профиль, или конец ссылки с токеном обрезан.</p>
<h2>Что проверить, чтобы обмен прошёл</h2>
<ul>
<li><strong>Инвентарь открыт.</strong> Профиль → «Редактировать профиль» → «Приватность» → «Инвентарь»: «Открытый» (<a href="https://steamcommunity.com/my/edit/settings">настройки приватности</a>). Со скрытым инвентарём обмены по ссылке не приходят.</li>
<li><strong>Steam Guard в телефоне работает не меньше 7 дней.</strong> Иначе Steam задержит обмен.</li>
<li><strong>На аккаунте нет запрета на обмены.</strong></li>
</ul>
<p>Когда вы покупаете скин на YuPay, мы проверяем ссылку ещё до оплаты и сразу скажем, если что-то из этого мешает.</p>
<h2>Безопасно ли давать трейд-ссылку</h2>
<p>Да, для этого она и нужна. По ссылке можно только прислать вам предложение — забрать что-то без вашего подтверждения нельзя. Но всё равно:</p>
<ul>
<li>смотрите, что вы отдаёте в предложении обмена, прежде чем его принять;</li>
<li>не сообщайте никому пароль и коды Steam Guard;</li>
<li>если ссылку стали использовать для спама, нажмите «Создать ссылку» — старая перестанет работать.</li>
</ul>
<h2>Как купить скин CS2 по трейд-ссылке</h2>
<ol>
<li>Выберите скин в <a href="/skins">каталоге скинов КС2</a>.</li>
<li>Вставьте трейд-ссылку.</li>
<li>Оплатите в сумах через Click, Payme или Uzum либо с баланса YuPay.</li>
<li>Примите обмен в Steam. Первую неделю Steam защищает обмен: скин уже ваш, но продать или передать его пока нельзя.</li>
</ol>$html$,
  'Трейд-ссылка Steam: где найти и как скопировать — YuPay',
  'Где найти трейд-ссылку в Steam, как скопировать её целиком и что проверить, чтобы обмен со скином CS2 пришёл без задержек.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
(gen_random_uuid(), :post_id, 'ru', 0, 'Где взять трейд-ссылку в Steam?',
 'Steam → «Инвентарь» → «Предложения обмена» → «Кто может отправлять мне предложения обмена?», блок «Сторонние сайты». Или сразу по адресу steamcommunity.com/my/tradeoffers/privacy.'),
(gen_random_uuid(), :post_id, 'ru', 1, 'Могут ли по трейд-ссылке украсть скины?',
 'Нет. По ссылке можно только прислать вам предложение обмена. Ничего не уйдёт, пока вы сами не примете обмен, поэтому всегда смотрите, что отдаёте.'),
(gen_random_uuid(), :post_id, 'ru', 2, 'Почему не приходит обмен по трейд-ссылке?',
 'Обычно причина одна из четырёх: инвентарь скрыт, ссылка скопирована не целиком или уже пересоздана, на аккаунте запрет на обмены, или Steam Guard в телефоне работает меньше 7 дней — тогда Steam задерживает обмен.'),
(gen_random_uuid(), :post_id, 'ru', 3, 'Что делать, если трейд-ссылка попала в чужие руки?',
 'Откройте ту же страницу и нажмите «Создать ссылку». Старая ссылка перестанет работать, а новую нужно будет указать заново там, где вы покупаете скины.');

-- ---------------------------------------------------------------- English --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'en', 'steam-trade-link',
  'Steam trade link: where to find it and how to copy it',
  'Where to find your Steam trade link, how to copy all of it, and what to check so a CS2 skin trade arrives without a hold.',
$html$<h2>The short version</h2>
<ul>
<li>A trade link is the address anyone can use to send you a Steam trade offer, even if you are not friends.</li>
<li>You need one to buy a CS2 skin: the seller sends the trade to it.</li>
<li>The fastest way to it is the direct link: <a href="https://steamcommunity.com/my/tradeoffers/privacy">steamcommunity.com/my/tradeoffers/privacy</a>.</li>
<li>No password or Steam Guard code is involved — never give those to anyone.</li>
</ul>
<h2>Where to find your trade link</h2>
<ol>
<li>Sign in to Steam in a browser and open <a href="https://steamcommunity.com/my/tradeoffers/privacy">your trade offer settings</a> — the page opens in your account.</li>
<li>Or by hand: hover over your name → Inventory → Trade Offers → on the right, «Who can send me Trade Offers?».</li>
<li>At the bottom, under «Third-Party Sites», there is the Trade URL field. Copy all of it — from <code>https</code> to the last character after <code>token=</code>.</li>
</ol>
<img src="https://cdn.yupay.uz/blog_image/2026/09/01a0f391-fc27-7391-aee7-dc33c194fab9.jpg" alt="The Steam page «Who can send me Trade Offers?»: the Trade URL field under Third-Party Sites">
<p>If you only use the Steam app, open the same direct link in a browser and sign in — it is the same page.</p>
<h2>What a correct link looks like</h2>
<p><code>https://steamcommunity.com/tradeoffer/new/?partner=123456789&amp;token=AbCd1234</code></p>
<p><code>partner</code> is your account number; <code>token</code> is the key without which a trade from a stranger will not arrive. Common mistakes: copying your profile link instead, or cutting off the end with the token.</p>
<h2>What to check so the trade goes through</h2>
<ul>
<li><strong>Your inventory is public.</strong> Profile → Edit Profile → Privacy Settings → Inventory: Public (<a href="https://steamcommunity.com/my/edit/settings">privacy settings</a>). With a private inventory, trades through the link do not arrive.</li>
<li><strong>Steam Guard Mobile has been on for at least 7 days.</strong> Otherwise Steam holds the trade.</li>
<li><strong>The account has no trade ban.</strong></li>
</ul>
<p>When you buy a skin on YuPay, we check the link before you pay and tell you straight away if any of these is in the way.</p>
<h2>Is it safe to share a trade link?</h2>
<p>Yes — that is what it is for. The link only lets someone send you an offer; nothing can be taken without your confirmation. Still:</p>
<ul>
<li>look at what you would give away before accepting an offer;</li>
<li>never share your password or Steam Guard codes;</li>
<li>if the link gets used for spam, press «Create New URL» — the old one stops working.</li>
</ul>
<h2>How to buy a CS2 skin with your trade link</h2>
<ol>
<li>Pick a skin in the <a href="/en/skins">CS2 skins market</a>.</li>
<li>Paste your trade link.</li>
<li>Pay in soʻm with Click, Payme or Uzum, or from your YuPay balance.</li>
<li>Accept the trade in Steam. For the first week Steam protects the trade: the skin is yours, but you cannot sell or pass it on yet.</li>
</ol>$html$,
  'Steam trade link: where to find it and how to copy it — YuPay',
  'Where to find your Steam trade link, how to copy all of it, and what to check so a CS2 skin trade arrives without a hold.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
(gen_random_uuid(), :post_id, 'en', 0, 'Where do I get my Steam trade link?',
 'Steam → Inventory → Trade Offers → «Who can send me Trade Offers?», under Third-Party Sites. Or go straight to steamcommunity.com/my/tradeoffers/privacy.'),
(gen_random_uuid(), :post_id, 'en', 1, 'Can someone steal my skins with my trade link?',
 'No. The link only lets someone send you a trade offer. Nothing leaves your inventory until you accept, so always check what you would give away.'),
(gen_random_uuid(), :post_id, 'en', 2, 'Why is a trade to my link not arriving?',
 'Usually one of four things: the inventory is private, the link was copied only in part or has been re-created, the account has a trade ban, or Steam Guard Mobile has been on for less than 7 days — then Steam holds the trade.'),
(gen_random_uuid(), :post_id, 'en', 3, 'What if my trade link ends up in the wrong hands?',
 'Open the same page and press «Create New URL». The old link stops working; give the new one wherever you buy skins.');

-- ------------------------------------------------------------------ Uzbek --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'uz', 'steam-treyd-havola',
  'Steam treyd havolasi: qayerdan topish va qanday nusxalash',
  'Steam’da treyd havolani qayerdan topish, uni toʻliq nusxalash va CS2 skini almashuvi kechikmasdan kelishi uchun nimalarni tekshirish kerak.',
$html$<h2>Asosiysi</h2>
<ul>
<li>Treyd havola — bu manzil, uning orqali doʻstingiz boʻlmagan odam ham sizga Steam’da almashuv taklifini yubora oladi.</li>
<li>CS2 skinini sotib olish uchun u kerak: sotuvchi almashuvni aynan shu havolaga yuboradi.</li>
<li>Eng tez yoʻl — toʻgʻridan-toʻgʻri havola: <a href="https://steamcommunity.com/my/tradeoffers/privacy">steamcommunity.com/my/tradeoffers/privacy</a>.</li>
<li>Parol va Steam Guard kodi kerak emas — ularni hech kimga aytmang.</li>
</ul>
<h2>Treyd havolani qayerdan topish mumkin</h2>
<ol>
<li>Brauzerda Steam’ga kiring va <a href="https://steamcommunity.com/my/tradeoffers/privacy">almashuv takliflari sozlamalarini</a> oching — sahifa sizning akkauntingizda ochiladi.</li>
<li>Yoki qoʻlda: nikingiz ustiga olib boring → «Inventar» → «Almashuv takliflari» → oʻngda «Kim menga almashuv takliflarini yubora oladi?» (ruscha interfeysda — «Кто может отправлять мне предложения обмена?»).</li>
<li>Pastda, «Uchinchi tomon saytlari» («Сторонние сайты») blokida «Almashuv havolasi» («Ссылка на обмен») maydoni bor. Uni toʻliq nusxalang — <code>https</code> dan <code>token=</code> dan keyingi oxirgi belgigacha.</li>
</ol>
<img src="https://cdn.yupay.uz/blog_image/2026/09/01a0f391-ec35-7c10-a35e-1bd56261c1b1.jpg" alt="Steam sahifasi: «Uchinchi tomon saytlari» blokidagi almashuv havolasi maydoni">
<p>Steam’dan faqat ilovada foydalansangiz, oʻsha havolani brauzerda oching va akkauntga kiring — sahifa bir xil.</p>
<h2>Toʻgʻri havola qanday koʻrinadi</h2>
<p><code>https://steamcommunity.com/tradeoffer/new/?partner=123456789&amp;token=AbCd1234</code></p>
<p><code>partner</code> — akkauntingiz raqami, <code>token</code> — kalit, usiz notanish odamdan almashuv kelmaydi. Koʻp uchraydigan xatolar: treyd havola oʻrniga profil havolasi nusxalangan yoki oxiridagi token kesilib qolgan.</p>
<h2>Almashuv oʻtishi uchun nimani tekshirish kerak</h2>
<ul>
<li><strong>Inventar ochiq.</strong> Profil → «Profilni tahrirlash» → «Maxfiylik» → «Inventar»: «Ochiq» (<a href="https://steamcommunity.com/my/edit/settings">maxfiylik sozlamalari</a>). Yopiq inventarga havola orqali almashuv kelmaydi.</li>
<li><strong>Telefondagi Steam Guard kamida 7 kundan beri ishlaydi.</strong> Aks holda Steam almashuvni kechiktiradi.</li>
<li><strong>Akkauntda almashuv taqiqi yoʻq.</strong></li>
</ul>
<p>YuPay’da skin sotib olayotganingizda havolani toʻlovdan oldin tekshiramiz va shulardan biri xalaqit bersa, darhol aytamiz.</p>
<h2>Treyd havolani berish xavfsizmi</h2>
<p>Ha, u aynan shuning uchun bor. Havola orqali faqat sizga taklif yuborish mumkin — sizning tasdigʻingizsiz hech narsani olib boʻlmaydi. Shunday boʻlsa ham:</p>
<ul>
<li>taklifni qabul qilishdan oldin nimani berayotganingizni koʻring;</li>
<li>parol va Steam Guard kodlarini hech kimga aytmang;</li>
<li>havola spam uchun ishlatila boshlasa, «Havola yaratish» («Создать ссылку») tugmasini bosing — eskisi ishlamay qoladi.</li>
</ul>
<h2>Treyd havola orqali CS2 skinini qanday sotib olish</h2>
<ol>
<li><a href="/uz/skins">CS2 skinlari katalogidan</a> skin tanlang.</li>
<li>Treyd havolangizni qoʻying.</li>
<li>Click, Payme yoki Uzum orqali soʻmda yoki YuPay balansidan toʻlang.</li>
<li>Steam’da almashuvni qabul qiling. Birinchi hafta Steam almashuvni himoya qiladi: skin allaqachon sizniki, lekin uni hali sotib yoki berib boʻlmaydi.</li>
</ol>$html$,
  'Steam treyd havolasi: qayerdan topish va nusxalash — YuPay',
  'Steam’da treyd havolani qayerdan topish, toʻliq nusxalash va CS2 skini almashuvi kechikmasdan kelishi uchun nimalarni tekshirish kerak.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
(gen_random_uuid(), :post_id, 'uz', 0, 'Steam’da treyd havolani qayerdan olsa boʻladi?',
 'Steam → «Inventar» → «Almashuv takliflari» → «Kim menga almashuv takliflarini yubora oladi?», «Uchinchi tomon saytlari» bloki. Yoki toʻgʻridan-toʻgʻri: steamcommunity.com/my/tradeoffers/privacy.'),
(gen_random_uuid(), :post_id, 'uz', 1, 'Treyd havola orqali skinlarni oʻgʻirlash mumkinmi?',
 'Yoʻq. Havola orqali faqat almashuv taklifini yuborish mumkin. Siz qabul qilmaguningizcha hech narsa ketmaydi, shuning uchun nimani berayotganingizni doim tekshiring.'),
(gen_random_uuid(), :post_id, 'uz', 2, 'Nega treyd havolaga almashuv kelmayapti?',
 'Odatda sabab toʻrttadan biri: inventar yopiq, havola toʻliq nusxalanmagan yoki qayta yaratilgan, akkauntda almashuv taqiqi bor, yoki telefondagi Steam Guard 7 kundan kam ishlagan — unda Steam almashuvni kechiktiradi.'),
(gen_random_uuid(), :post_id, 'uz', 3, 'Treyd havola begona qoʻlga tushsa nima qilish kerak?',
 'Oʻsha sahifani oching va «Havola yaratish»ni bosing. Eski havola ishlamay qoladi, yangisini skin sotib oladigan joyda qayta koʻrsating.');

COMMIT;
