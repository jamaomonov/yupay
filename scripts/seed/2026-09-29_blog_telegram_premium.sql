-- Telegram Premium guide: review of the Russian original, plus English and
-- Uzbek.
--
-- Arrived from Bunzy on 2026-09-29 as a draft with slug `telegram-premium`.
-- What the review changed in Russian:
--
--   * The store link pointed at `/en/store/telegram-premium` from the Russian
--     text — the same locale bug earlier posts had. «Yupay» → «YuPay».
--   * Renewal advice was wrong for us: it said to buy the next period a few
--     days before the end. Our brand FAQ is right — paid months are added to
--     the current term, so renewing early loses nothing. Rewritten around it.
--   * The steps now say what the storefront does: the username is checked
--     before payment, and «@» may be typed or left out (the field accepts
--     both, `^@?[A-Za-z]…`).
--   * «Годовой вариант выгоднее» became a number: per month, 12 months costs
--     about 40% less than 3 (≈34k vs ≈58k soʻm at today's prices). No soʻm
--     prices in the text — they move with the rate.
--   * Dropped the «десятки миллионов подписчиков» figure, a speculative
--     «удерживается дополнительная комиссия» about foreign cards, and three
--     paragraphs that repeated the renewal and gift sections.
--   * Added: we never ask for a password or a login code — the one thing a
--     buyer of a Telegram product most needs to hear.
--
-- Links carry a locale prefix. `oplata-igr-v-sumah` exists only in Russian,
-- so en/uz point at `buy-game-top-ups-in-uzbekistan` /
-- `ozbekistonda-donat-sotib-olish`.
--
-- Also sets the brand (publish refuses without one) and the cover, rendered
-- in yupay-motion (`Cover-telegram-premium`) and uploaded through the admin
-- presign path. Leaves the status alone: publishing is a person pressing
-- «Опубликовать».
--
-- Idempotent: re-running rewrites all three translations and FAQ sets.

BEGIN;

\set post_id '''01a0eb01-2c8b-79e2-b5fb-b5b6dba6b77b'''

UPDATE blog_posts
SET primary_brand_id = (SELECT id FROM brands WHERE slug = 'telegram-premium'),
    cover_image_url = 'https://cdn.yupay.uz/blog_image/2026/09/01a0ed4b-1cd4-7803-b156-a8e760dc9931.jpg',
    updated_at = now()
WHERE id = :post_id;

DELETE FROM blog_post_translations WHERE post_id = :post_id;
DELETE FROM blog_post_faqs WHERE post_id = :post_id;

-- ---------------------------------------------------------------- Russian --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'ru', 'telegram-premium',
  'Telegram Premium в Узбекистане: оплата в сумах',
  'Как купить Telegram Premium в Узбекистане без иностранной карты: оплата в сумах через Click, Payme или Uzum, по username, на 3, 6 или 12 месяцев — себе или в подарок.',
$html$<h2>Главное</h2>
<ul>
<li>Premium даёт файлы до 4 ГБ, отключение рекламы, расшифровку голосовых, перевод чатов и вдвое больше лимитов.</li>
<li>Из Узбекистана подписку удобно оплатить в сумах через Click, Payme или Uzum — без иностранной карты и магазина приложений.</li>
<li>Нужен только username в Telegram. Пароль и код входа не нужны — мы их никогда не спрашиваем.</li>
<li>Сроки: 3, 6 или 12 месяцев. В пересчёте на месяц год примерно на 40% дешевле трёх месяцев.</li>
<li>Premium можно подарить: достаточно указать username получателя.</li>
</ul>
<p>Купить Telegram Premium в Узбекистане проще всего по username с оплатой в сумах: выбираете срок, вводите имя пользователя, платите картой Uzcard или Humo — и подписка активируется на аккаунте. Ниже — что даёт Premium, почему напрямую его оплатить сложно и как оформить подписку себе или в подарок.</p>
<h2>Что даёт Telegram Premium</h2>
<p>По <a href="https://telegram.org/faq_premium">официальному FAQ Telegram</a>, подписка включает:</p>
<ul>
<li>загрузку файлов до 4 ГБ вместо 2 ГБ и скачивание на максимальной скорости;</li>
<li>отключение рекламы в публичных каналах;</li>
<li>расшифровку голосовых и видеосообщений в текст;</li>
<li>перевод целых чатов;</li>
<li>премиальные стикеры, реакции, анимированные аватарки и значок Premium;</li>
<li>вдвое больше лимитов: до 1000 каналов и групп, 20 папок, больше закреплённых чатов.</li>
</ul>
<p>Тарифов с разным набором функций нет: Premium везде одинаковый, отличается только срок. Чем он длиннее, тем дешевле месяц.</p>
<h2>Почему напрямую оплатить сложно</h2>
<p>Telegram продаёт Premium через App Store, Google Play и бота @PremiumBot. Магазинам приложений нужна карта, которую они принимают, а карты Uzcard и Humo там не работают. С международной картой платёж проходит не всегда, а цену меняют курс и комиссия банка.</p>
<p>Оплата по username обходится без этого: платите в сумах привычной картой, а подписку оформляем мы.</p>
<h2>Как оформить Premium в сумах</h2>
<ol>
<li>Откройте <a href="https://yupay.uz/store/telegram-premium">страницу Telegram Premium в каталоге YuPay</a> и выберите срок: 3, 6 или 12 месяцев.</li>
<li>Введите username в Telegram — с «@» или без. Перед оплатой мы проверим, что такой аккаунт существует.</li>
<li>Оплатите через Click, Payme или Uzum. Итог в сумах виден до оплаты, комиссии сверху нет.</li>
<li>Premium активируется автоматически после подтверждения оплаты — обычно за несколько минут.</li>
</ol>
<p>Где найти username: откройте Telegram → Настройки → «Имя пользователя». Если поле пустое, придумайте имя латиницей и сохраните — без него подписку не к чему привязать.</p>
<p>Так же, в сумах и без иностранной карты, оплачиваются игры — подробнее в материале про <a href="https://yupay.uz/blog/oplata-igr-v-sumah">оплату игр в сумах</a>.</p>
<h2>Premium в подарок</h2>
<p>Чтобы подарить подписку, введите username получателя вместо своего — больше ничего делать не нужно. Premium активируется на его аккаунте, уведомление придёт ему в Telegram.</p>
<ul>
<li>Спросите у друга именно username, а не номер телефона.</li>
<li>Убедитесь, что username у него задан.</li>
<li>Сверьте написание перед оплатой.</li>
</ul>
<h2>Продление и окончание срока</h2>
<p>Подписка, оплаченная у нас, не продлевается сама: деньги не спишутся неожиданно. Если Premium уже активен, оплаченные месяцы добавятся к текущему сроку, а не начнутся заново, — поэтому продлевать можно заранее, ничего не сгорит.</p>
<p>Когда срок заканчивается, аккаунт возвращается к бесплатной версии. Чаты, файлы и каналы остаются на месте — отключаются только возможности Premium.</p>
<h2>Как не попасться мошенникам</h2>
<ul>
<li><strong>Никому не сообщайте код входа и облачный пароль.</strong> Для оформления Premium они не нужны. Если их просят — это мошенники.</li>
<li><strong>Проверяйте цену до оплаты.</strong> Итоговая сумма должна быть видна сразу, без доплат на последнем шаге.</li>
<li><strong>Не верьте «Premium за полцены».</strong> Цена сильно ниже рынка обычно означает, что подписки не будет.</li>
</ul>$html$,
  'Telegram Premium в Узбекистане: как оплатить в сумах',
  'Telegram Premium из Узбекистана без иностранной карты: по username, оплата в сумах через Click, Payme или Uzum, на 3, 6 или 12 месяцев. Себе или в подарок, продление без сгорания срока.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
  (gen_random_uuid(), :post_id, 'ru', 0,
   'Как купить Telegram Premium в Узбекистане в сумах?',
   'Выберите срок на странице Telegram Premium в каталоге YuPay, введите username и оплатите через Click, Payme или Uzum картой Uzcard или Humo. Подписка активируется автоматически.'),
  (gen_random_uuid(), :post_id, 'ru', 1,
   'Нужен ли пароль или код из Telegram?',
   'Нет. Нужен только username — имя после «@» из профиля. Пароль, облачный пароль и код входа мы не спрашиваем никогда. Если их просят — это мошенники.'),
  (gen_random_uuid(), :post_id, 'ru', 2,
   'Почему не получается оплатить Premium напрямую?',
   'Telegram продаёт Premium через App Store, Google Play и @PremiumBot. Магазины приложений не принимают карты Uzcard и Humo, а с международной картой платёж проходит не всегда.'),
  (gen_random_uuid(), :post_id, 'ru', 3,
   'Можно ли подарить Telegram Premium?',
   'Да. Введите username получателя вместо своего: подписка активируется на его аккаунте, уведомление придёт ему в Telegram.'),
  (gen_random_uuid(), :post_id, 'ru', 4,
   'Что будет, если Premium уже активен?',
   'Оплаченные месяцы добавятся к текущему сроку — подписка продлится, а не начнётся заново. Поэтому продлевать можно заранее.');

-- ---------------------------------------------------------------- English --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'en', 'telegram-premium',
  'Telegram Premium in Uzbekistan: pay in soʻm',
  'How to buy Telegram Premium in Uzbekistan without a foreign card: pay in soʻm with Click, Payme or Uzum, by username, for 3, 6 or 12 months — for yourself or as a gift.',
$html$<h2>Key points</h2>
<ul>
<li>Premium gives you 4 GB uploads, no ads, voice-to-text, chat translation and double the limits.</li>
<li>From Uzbekistan it is easiest to pay in soʻm with Click, Payme or Uzum — no foreign card, no app store.</li>
<li>All we need is your Telegram username. No password or login code — we never ask for them.</li>
<li>Terms: 3, 6 or 12 months. Per month, a year costs about 40% less than three months.</li>
<li>Premium can be a gift: just enter the recipient's username.</li>
</ul>
<p>The simplest way to buy Telegram Premium in Uzbekistan is by username, paying in soʻm: pick a term, enter the username, pay with an Uzcard or Humo card — and the subscription turns on for that account. Below: what Premium gives you, why paying for it directly is hard, and how to get it for yourself or as a gift.</p>
<h2>What Telegram Premium gives you</h2>
<p>According to <a href="https://telegram.org/faq_premium">Telegram's official FAQ</a>, the subscription includes:</p>
<ul>
<li>uploads up to 4 GB instead of 2 GB, and downloads at full speed;</li>
<li>no ads in public channels;</li>
<li>voice and video messages transcribed to text;</li>
<li>translation of whole chats;</li>
<li>premium stickers, reactions, animated profile pictures and the Premium badge;</li>
<li>double the limits: up to 1,000 channels and groups, 20 folders, more pinned chats.</li>
</ul>
<p>There are no tiers with different features: Premium is the same everywhere, only the term differs. The longer it is, the cheaper each month.</p>
<h2>Why paying directly is hard</h2>
<p>Telegram sells Premium through the App Store, Google Play and the @PremiumBot bot. App stores need a card they accept, and Uzcard and Humo cards do not work there. An international card does not always go through, and the exchange rate and bank fees change the price.</p>
<p>Paying by username avoids all that: you pay in soʻm with your usual card, and we arrange the subscription.</p>
<h2>How to get Premium in soʻm</h2>
<ol>
<li>Open the <a href="https://yupay.uz/en/store/telegram-premium">Telegram Premium page on YuPay</a> and choose a term: 3, 6 or 12 months.</li>
<li>Enter your Telegram username — with or without the «@». Before you pay, we check that the account exists.</li>
<li>Pay with Click, Payme or Uzum. The total in soʻm is shown before you pay, with no fee on top.</li>
<li>Premium turns on automatically once the payment is confirmed — usually within minutes.</li>
</ol>
<p>Where to find your username: open Telegram → Settings → Username. If it is empty, choose a name in Latin letters and save it — without one there is nothing to attach the subscription to.</p>
<p>Games are paid the same way, in soʻm and without a foreign card — see our guide to <a href="https://yupay.uz/en/blog/buy-game-top-ups-in-uzbekistan">buying game top-ups in Uzbekistan</a>.</p>
<h2>Premium as a gift</h2>
<p>To give the subscription, enter the recipient's username instead of yours — nothing else is needed. Premium turns on for their account, and they get a notification in Telegram.</p>
<ul>
<li>Ask your friend for their username, not their phone number.</li>
<li>Make sure they have a username set.</li>
<li>Check the spelling before you pay.</li>
</ul>
<h2>Renewal and when the term ends</h2>
<p>A subscription paid through us does not renew by itself: no money leaves your card unexpectedly. If Premium is already active, the months you pay for are added to the current term rather than starting over — so you can renew early and lose nothing.</p>
<p>When the term ends, the account goes back to the free version. Chats, files and channels stay where they are — only the Premium features switch off.</p>
<h2>How to avoid scams</h2>
<ul>
<li><strong>Never share your login code or cloud password.</strong> Premium does not need them. Anyone asking for them is a scammer.</li>
<li><strong>Check the price before paying.</strong> The total should be visible right away, with nothing added at the last step.</li>
<li><strong>Do not trust «Premium at half price».</strong> A price far below the market usually means there will be no subscription.</li>
</ul>$html$,
  'Telegram Premium in Uzbekistan: how to pay in soʻm',
  'Telegram Premium from Uzbekistan without a foreign card: by username, paid in soʻm with Click, Payme or Uzum, for 3, 6 or 12 months. For yourself or as a gift; early renewal loses nothing.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
  (gen_random_uuid(), :post_id, 'en', 0,
   'How do I buy Telegram Premium in Uzbekistan in soʻm?',
   'Choose a term on the Telegram Premium page on YuPay, enter your username and pay with Click, Payme or Uzum using an Uzcard or Humo card. The subscription turns on automatically.'),
  (gen_random_uuid(), :post_id, 'en', 1,
   'Do you need my password or a Telegram code?',
   'No. Only your username — the name after «@» in your profile. We never ask for your password, cloud password or login code. Anyone asking for them is a scammer.'),
  (gen_random_uuid(), :post_id, 'en', 2,
   'Why can''t I pay for Premium directly?',
   'Telegram sells Premium through the App Store, Google Play and @PremiumBot. App stores do not accept Uzcard and Humo cards, and an international card does not always go through.'),
  (gen_random_uuid(), :post_id, 'en', 3,
   'Can I give Telegram Premium as a gift?',
   'Yes. Enter the recipient''s username instead of yours: the subscription turns on for their account, and they get a notification in Telegram.'),
  (gen_random_uuid(), :post_id, 'en', 4,
   'What if Premium is already active?',
   'The months you pay for are added to the current term — the subscription is extended, not restarted. So you can renew early.');

-- ----------------------------------------------------------------- Uzbek --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'uz', 'telegram-premium',
  'Oʻzbekistonda Telegram Premium: soʻmda toʻlov',
  'Oʻzbekistonda Telegram Premium’ni xorijiy kartasiz qanday sotib olish: Click, Payme yoki Uzum orqali soʻmda, username boʻyicha, 3, 6 yoki 12 oyga — oʻzingizga yoki sovgʻaga.',
$html$<h2>Asosiysi</h2>
<ul>
<li>Premium 4 GB gacha fayllar, reklamasiz kanallar, ovozli xabarlarni matnga oʻgirish, chatlarni tarjima qilish va ikki barobar koʻp limitlar beradi.</li>
<li>Oʻzbekistondan obunani Click, Payme yoki Uzum orqali soʻmda toʻlash qulay — xorijiy karta va ilovalar doʻkonisiz.</li>
<li>Faqat Telegram username kerak. Parol va kirish kodi kerak emas — biz ularni hech qachon soʻramaymiz.</li>
<li>Muddatlar: 3, 6 yoki 12 oy. Oyiga hisoblaganda bir yillik obuna uch oylikdan taxminan 40% arzon.</li>
<li>Premium’ni sovgʻa qilish mumkin: qabul qiluvchining username’ini kiritish kifoya.</li>
</ul>
<p>Oʻzbekistonda Telegram Premium’ni username boʻyicha soʻmda toʻlab sotib olish eng oson: muddatni tanlaysiz, username’ni kiritasiz, Uzcard yoki Humo kartasi bilan toʻlaysiz — obuna akkauntda faollashadi. Quyida — Premium nima beradi, uni toʻgʻridan-toʻgʻri toʻlash nega qiyin va obunani oʻzingizga yoki sovgʻaga qanday rasmiylashtirish.</p>
<h2>Telegram Premium nima beradi</h2>
<p><a href="https://telegram.org/faq_premium">Telegram’ning rasmiy FAQ</a>’iga koʻra, obunaga quyidagilar kiradi:</p>
<ul>
<li>2 GB oʻrniga 4 GB gacha fayl yuklash va maksimal tezlikda yuklab olish;</li>
<li>ommaviy kanallarda reklamani oʻchirish;</li>
<li>ovozli va video xabarlarni matnga oʻgirish;</li>
<li>butun chatlarni tarjima qilish;</li>
<li>premium stikerlar, reaksiyalar, animatsion avatarlar va Premium belgisi;</li>
<li>ikki barobar koʻp limitlar: 1000 tagacha kanal va guruh, 20 ta papka, koʻproq qadalgan chatlar.</li>
</ul>
<p>Turli funksiyali tariflar yoʻq: Premium hamma joyda bir xil, faqat muddati farq qiladi. Muddat qancha uzun boʻlsa, bir oy shuncha arzon.</p>
<h2>Nega toʻgʻridan-toʻgʻri toʻlash qiyin</h2>
<p>Telegram Premium’ni App Store, Google Play va @PremiumBot orqali sotadi. Ilovalar doʻkonlariga ular qabul qiladigan karta kerak, Uzcard va Humo kartalari esa u yerda ishlamaydi. Xalqaro karta bilan toʻlov har doim ham oʻtmaydi, narxni esa kurs va bank komissiyasi oʻzgartiradi.</p>
<p>Username boʻyicha toʻlov bularsiz oʻtadi: odatdagi kartangiz bilan soʻmda toʻlaysiz, obunani esa biz rasmiylashtiramiz.</p>
<h2>Premium’ni soʻmda qanday rasmiylashtirish</h2>
<ol>
<li><a href="https://yupay.uz/uz/store/telegram-premium">YuPay’dagi Telegram Premium</a> sahifasini oching va muddatni tanlang: 3, 6 yoki 12 oy.</li>
<li>Telegram username’ingizni kiriting — «@» bilan yoki usiz. Toʻlovdan oldin bunday akkaunt mavjudligini tekshiramiz.</li>
<li>Click, Payme yoki Uzum orqali toʻlang. Soʻmdagi yakuniy summa toʻlovdan oldin koʻrinadi, ustama komissiya yoʻq.</li>
<li>Toʻlov tasdiqlangach, Premium avtomatik faollashadi — odatda bir necha daqiqada.</li>
</ol>
<p>Username qayerda: Telegram → Sozlamalar → «Foydalanuvchi nomi». Agar maydon boʻsh boʻlsa, lotin harflarida nom oʻylab toping va saqlang — usiz obunani biriktirishga joy yoʻq.</p>
<p>Oʻyinlar ham xuddi shunday — soʻmda va xorijiy kartasiz toʻlanadi. Batafsil — <a href="https://yupay.uz/uz/blog/ozbekistonda-donat-sotib-olish">Oʻzbekistonda donat sotib olish</a> boʻyicha qoʻllanmada.</p>
<h2>Premium sovgʻa sifatida</h2>
<p>Obunani sovgʻa qilish uchun oʻzingizniki oʻrniga qabul qiluvchining username’ini kiriting — boshqa hech narsa kerak emas. Premium uning akkauntida faollashadi, xabarnoma unga Telegram’da keladi.</p>
<ul>
<li>Doʻstingizdan telefon raqamini emas, aynan username’ini soʻrang.</li>
<li>Unda username oʻrnatilganiga ishonch hosil qiling.</li>
<li>Toʻlovdan oldin yozilishini tekshiring.</li>
</ul>
<h2>Uzaytirish va muddat tugashi</h2>
<p>Bizda toʻlangan obuna oʻzi uzaymaydi: pul kutilmaganda yechilmaydi. Agar Premium allaqachon faol boʻlsa, toʻlangan oylar joriy muddatga qoʻshiladi, qaytadan boshlanmaydi — shuning uchun oldindan uzaytirish mumkin, hech narsa kuymaydi.</p>
<p>Muddat tugagach, akkaunt bepul versiyaga qaytadi. Chatlar, fayllar va kanallar joyida qoladi — faqat Premium imkoniyatlari oʻchadi.</p>
<h2>Firibgarlarga qanday aldanmaslik</h2>
<ul>
<li><strong>Kirish kodi va bulutli parolni hech kimga aytmang.</strong> Premium uchun ular kerak emas. Ularni soʻrashsa — bu firibgarlar.</li>
<li><strong>Narxni toʻlovdan oldin tekshiring.</strong> Yakuniy summa oxirgi qadamda qoʻshimchalarsiz, darhol koʻrinishi kerak.</li>
<li><strong>«Yarim narxdagi Premium»ga ishonmang.</strong> Bozordan ancha past narx koʻpincha obuna boʻlmasligini bildiradi.</li>
</ul>$html$,
  'Oʻzbekistonda Telegram Premium: soʻmda qanday toʻlash',
  'Oʻzbekistondan Telegram Premium xorijiy kartasiz: username boʻyicha, Click, Payme yoki Uzum orqali soʻmda, 3, 6 yoki 12 oyga. Oʻzingizga yoki sovgʻaga, oldindan uzaytirishda hech narsa kuymaydi.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
  (gen_random_uuid(), :post_id, 'uz', 0,
   'Oʻzbekistonda Telegram Premium’ni soʻmda qanday sotib olish mumkin?',
   'YuPay’dagi Telegram Premium sahifasida muddatni tanlang, username’ni kiriting va Uzcard yoki Humo kartasi bilan Click, Payme yoki Uzum orqali toʻlang. Obuna avtomatik faollashadi.'),
  (gen_random_uuid(), :post_id, 'uz', 1,
   'Parol yoki Telegram kodi kerakmi?',
   'Yoʻq. Faqat username — profildagi «@» dan keyingi nom. Parol, bulutli parol va kirish kodini hech qachon soʻramaymiz. Ularni soʻrashsa — bu firibgarlar.'),
  (gen_random_uuid(), :post_id, 'uz', 2,
   'Nega Premium’ni toʻgʻridan-toʻgʻri toʻlab boʻlmaydi?',
   'Telegram Premium’ni App Store, Google Play va @PremiumBot orqali sotadi. Ilovalar doʻkonlari Uzcard va Humo kartalarini qabul qilmaydi, xalqaro karta bilan esa toʻlov har doim ham oʻtmaydi.'),
  (gen_random_uuid(), :post_id, 'uz', 3,
   'Telegram Premium’ni sovgʻa qilish mumkinmi?',
   'Ha. Oʻzingizniki oʻrniga qabul qiluvchining username’ini kiriting: obuna uning akkauntida faollashadi, xabarnoma unga Telegram’da keladi.'),
  (gen_random_uuid(), :post_id, 'uz', 4,
   'Premium allaqachon faol boʻlsa-chi?',
   'Toʻlangan oylar joriy muddatga qoʻshiladi — obuna uzayadi, qaytadan boshlanmaydi. Shuning uchun oldindan uzaytirish mumkin.');

COMMIT;
