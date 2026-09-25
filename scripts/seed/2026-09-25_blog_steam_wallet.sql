-- Steam wallet guide: review of the Russian original, plus English and Uzbek.
--
-- Arrived from Bunzy on 2026-09-25 as a draft with slug `steam-2` (`steam`
-- belongs to the existing top-up guide). What the review changed in Russian:
--
--   * The closing store link pointed at `/en/store/steam` — the locale bug
--     seen in the Genshin post, again. Now `/store/steam`.
--   * Nothing said what our own Steam card says: the amount is in dollars,
--     $1–$300; it is the *login*, not the profile name; it works for CIS
--     accounts only (UZ, KZ, RU, BY); an Uzbek account's wallet is in USD.
--   * It sold the wallet for Community Market purchases without saying the
--     market stays shut until the account has spent $5 and has had Steam
--     Guard on for 15 days.
--   * It steered "gifting" towards Steam gift cards, which we do not sell.
--     Kept as the explanation it is, then pointed at gifting a game through
--     «Steam Игры» and its guide.
--   * The top-up steps now defer to the full guide (`/blog/steam`) rather
--     than repeat it, and two paragraphs of filler went.
--
-- Links carry a locale prefix. `oplata-igr-v-sumah` exists only in Russian,
-- so en/uz point at `buy-game-top-ups-in-uzbekistan` /
-- `ozbekistonda-donat-sotib-olish`, as the Genshin translations did.
--
-- Also sets the brand (publish refuses without one) and the cover, rendered
-- in yupay-motion (`Cover-steam-wallet`) and uploaded through the admin
-- presign path. Leaves the status alone: publishing is a person pressing
-- «Опубликовать».
--
-- Idempotent: re-running rewrites all three translations and FAQ sets.

BEGIN;

\set post_id '''01a0d6aa-5498-7901-8ee7-729baee8643c'''

UPDATE blog_posts
SET primary_brand_id = (SELECT id FROM brands WHERE slug = 'steam'),
    cover_image_url = 'https://cdn.yupay.uz/blog_image/2026/09/01a0d6e8-7e08-7ce2-afdd-e00ae3794b36.jpg',
    updated_at = now()
WHERE id = :post_id;

DELETE FROM blog_post_translations WHERE post_id = :post_id;
DELETE FROM blog_post_faqs WHERE post_id = :post_id;

-- ---------------------------------------------------------------- Russian --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'ru', 'steam-koshelek',
  'Steam-кошелёк: как пополнить и на что тратить',
  'Как пополнить Steam-кошелёк в Узбекистане в сумах без комиссии, на что тратить баланс, чем он отличается от подарочной карты и как подготовиться к распродажам.',
$html$<h2>Главное</h2>
<ul>
<li>Баланс Steam-кошелька тратится на игры, DLC, внутриигровые покупки и предметы на торговой площадке Steam.</li>
<li>В Узбекистане его удобно пополнять в сумах через YuPay: нужен только логин Steam, сумма — от $1 до $300, комиссии сверху нет.</li>
<li>Прямое пополнение и подарочная карта дают один и тот же баланс, но карта — это код, который удобно подарить.</li>
<li>Кошелёк привязан к валюте региона аккаунта: потратить средства в другой валюте не получится.</li>
<li>Самые большие скидки — на летней и зимней распродажах Steam, и они же длятся дольше остальных.</li>
</ul>
<p>Пополнить Steam-кошелёк проще всего локальным платежом в сумах: вы указываете логин аккаунта, оплачиваете через Click, Payme или Uzum, и баланс автоматически появляется в клиенте, обычно за пару минут. Дальше эти деньги работают как внутренняя валюта Steam: ими оплачивают игры, дополнения, внутриигровые покупки и предметы на торговой площадке, не вводя карту при каждой покупке.</p>
<p>Ниже — на что реально тратится баланс, как пополнить его в сумах, чем пополнение отличается от подарочной карты, какие правила Steam действуют по регионам и валютам и как с толком пройти сезонные распродажи.</p>
<h2>Что можно купить за средства в Steam-кошельке</h2>
<p>Valve описывает кошелёк предельно широко: деньги на нём можно использовать для покупки любой игры в Steam или внутри игры, которая поддерживает транзакции Steam (<a href="https://store.steampowered.com/steamaccount/addfunds/">Steam Add Funds</a>).</p>
<p>С баланса обычно оплачивают:</p>
<ul>
<li>игры и издания в магазине Steam;</li>
<li>дополнения и DLC к уже купленным играм;</li>
<li>внутриигровые покупки в проектах, которые принимают оплату через Steam;</li>
<li>предметы на торговой площадке — скины и коллекционные карточки;</li>
<li>игры в подарок другим игрокам прямо из магазина.</li>
</ul>
<p>С торговой площадкой есть нюанс: она открывается не сразу. Аккаунт не должен быть ограниченным — для этого в Steam нужно потратить от $5, и пополнение кошелька на эту сумму тоже считается. Кроме того, мобильный Steam Guard должен быть включён не меньше 15 дней.</p>
<p>Главное удобство баланса — скорость. Не нужно каждый раз вводить реквизиты карты и ждать подтверждения банка, и в дни распродаж, когда скидка держится ограниченное время, это особенно заметно.</p>
<h2>Как пополнить баланс в сумах</h2>
<p>Для игрока из Узбекистана главный вопрос — как положить деньги на кошелёк без валютной карты и без переплаты за конвертацию. Магазин Steam не принимает карты Uzcard и Humo напрямую, а банковские переводы добавляют скрытые расходы.</p>
<p>Через YuPay это четыре шага:</p>
<ol>
<li>Откройте страницу <a href="https://yupay.uz/store/steam">пополнения Steam</a>.</li>
<li>Введите логин Steam — имя, под которым вы входите в аккаунт, а не отображаемое имя профиля. Пароль не нужен.</li>
<li>Укажите сумму в долларах — от $1 до $300. Итог в сумах виден сразу.</li>
<li>Оплатите картой Uzcard или Humo через Click, Payme или Uzum — баланс пополнится автоматически.</li>
</ol>
<p>Комиссии сверху нет: сколько долларов вы указали, столько и придёт на кошелёк, а сумма в сумах на экране — это и есть сумма платежа. Подробная инструкция с разбором частых ошибок — в статье <a href="https://yupay.uz/blog/steam">Как пополнить Steam в Узбекистане</a>, а обо всех локальных способах оплаты мы писали в материале <a href="https://yupay.uz/blog/oplata-igr-v-sumah">Оплата игр в сумах: локальные методы Узбекистана</a>.</p>
<h2>Чем пополнение кошелька отличается от подарочной карты</h2>
<p>Начинающие игроки часто путают два способа положить деньги в Steam: прямое пополнение и подарочную карту. Итог одинаковый — баланс кошелька, разница только в форме.</p>
<p>Прямое пополнение сразу увеличивает баланс конкретного аккаунта: вы указываете логин, оплачиваете, и деньги появляются именно там.</p>
<p>Подарочная карта — это код на определённую сумму. Активировать его может игрок в своём аккаунте, поэтому карта удобна как подарок: код можно отправить другу, и он сам решит, когда его ввести. У карт бывают региональные ограничения, так что перед покупкой проверьте, подойдёт ли код для региона получателя.</p>
<p>Практический вывод: свой аккаунт удобнее пополнять напрямую. А если хочется подарить другу конкретную игру, её можно купить подарком через «Steam Игры» — как это устроено, мы разобрали в гайде <a href="https://yupay.uz/blog/kak-kupit-igru-v-steam-iz-uzbekistana">Как купить игру в Steam из Узбекистана</a>.</p>
<h2>Правила Steam по регионам и валютам</h2>
<p>У кошелька есть ограничение, о которое спотыкаются те, кто меняет регион аккаунта: баланс привязан к валюте региона Steam. Если валюта покупки не совпадает с валютой средств, Steam не даст завершить оплату и прямо напишет, что валюта кошелька не совпадает с валютой покупки. Деньги, добавленные в одном регионе, нельзя потратить в другом.</p>
<p>Пополнение через YuPay работает для аккаунтов из СНГ — Узбекистана, Казахстана, России и Беларуси. Сумму вы задаёте в долларах, а на кошелёк она зачисляется в его валюте. У аккаунтов, зарегистрированных в Узбекистане, это доллар США.</p>
<p>Что из этого следует:</p>
<ul>
<li>пополняйте кошелёк того аккаунта и в том регионе, где собираетесь покупать;</li>
<li>не меняйте страну магазина без необходимости, если на балансе уже есть деньги;</li>
<li>пополняйте под конкретные покупки, а не про запас.</li>
</ul>
<h2>Как использовать сезонные распродажи</h2>
<p>Заранее пополненный кошелёк особенно выгоден на крупных распродажах: цены на популярные игры падают, а скидка действует ограниченное время. С деньгами на балансе заказ оформляется сразу, без ожидания банка.</p>
<p>Крупнейшие распродажи года проходят летом и зимой, и они же обычно длятся дольше остальных. Весенние и осенние короче — это скорее дополнительный повод обновить библиотеку.</p>
<p>Несколько приёмов:</p>
<ul>
<li>соберите список желаемого заранее — Steam пришлёт письмо, когда игра из него подешевеет;</li>
<li>пополните кошелёк до старта распродажи, чтобы не терять время в первый день;</li>
<li>сверяйте цену с историей скидок: если игра часто уходит в акции, «рекордная» скидка может оказаться обычной;</li>
<li>при ограниченном бюджете берите несколько небольших покупок вместо одной крупной.</li>
</ul>
<p>Готовы к ближайшей распродаже? Откройте <a href="https://yupay.uz/store/steam">Steam на YuPay</a>, укажите сумму и пополните кошелёк заранее, чтобы купить нужные игры, пока действует скидка.</p>$html$,
  'Steam-кошелёк: как пополнить в сумах и на что тратить',
  'Как пополнить Steam-кошелёк в Узбекистане в сумах без комиссии: логин, сумма от $1 до $300, оплата через Click, Payme или Uzum. На что тратить баланс и как его планировать под распродажи.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
  (gen_random_uuid(), :post_id, 'ru', 0,
   'Можно ли пополнить Steam-кошелёк в сумах без комиссии?',
   'Да. Через YuPay достаточно указать логин Steam и сумму от $1 до $300 и оплатить через Click, Payme или Uzum. Комиссии сверху нет: сколько долларов указали, столько и зачислится.'),
  (gen_random_uuid(), :post_id, 'ru', 1,
   'На что можно потратить деньги со Steam-кошелька?',
   'На игры и дополнения в магазине Steam, внутриигровые покупки в поддерживаемых играх, предметы на торговой площадке и игры в подарок другим игрокам.'),
  (gen_random_uuid(), :post_id, 'ru', 2,
   'Чем пополнение кошелька отличается от подарочной карты Steam?',
   'Оба способа дают один и тот же баланс. Пополнение сразу зачисляет деньги на указанный аккаунт, а подарочная карта — это код, который удобно подарить другому игроку.'),
  (gen_random_uuid(), :post_id, 'ru', 3,
   'Почему Steam пишет, что валюта средств не совпадает с покупкой?',
   'Кошелёк привязан к валюте региона аккаунта. Если регион или валюта покупки отличаются, оплатить этими средствами не получится.'),
  (gen_random_uuid(), :post_id, 'ru', 4,
   'Для каких аккаунтов работает пополнение через YuPay?',
   'Для аккаунтов Steam из СНГ: Узбекистана, Казахстана, России и Беларуси. Деньги зачисляются в валюте вашего кошелька.');

-- ---------------------------------------------------------------- English --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'en', 'steam-wallet-top-up-and-spend',
  'Steam Wallet: how to top it up and what to spend it on',
  'How to top up your Steam Wallet from Uzbekistan in soʻm with no fee on top, what the balance buys, how it differs from a gift card, and how to get ready for the big sales.',
$html$<h2>The short version</h2>
<ul>
<li>Steam Wallet funds pay for games, DLC, in-game purchases and items on the Steam Community Market.</li>
<li>From Uzbekistan the easy way to add funds is in soʻm through YuPay: all it needs is your Steam login, any amount from $1 to $300, and there is no fee on top.</li>
<li>A direct top-up and a gift card end up as the same balance, but a gift card is a code, which makes it easy to give away.</li>
<li>Your wallet is tied to your account region's currency, so the funds cannot pay for a purchase in another one.</li>
<li>The deepest discounts come in the Summer and Winter Sales, which also run longer than the others.</li>
</ul>
<p>The simplest way to top up a Steam Wallet is a local payment in soʻm: you enter your account login, pay through Click, Payme or Uzum, and the balance appears in the client automatically, usually within a couple of minutes. From then on it works as Steam's own currency — games, add-ons, in-game purchases and Market items, without typing in a card every time.</p>
<p>Below: what the balance actually gets spent on, how to top it up in soʻm, how a top-up differs from a gift card, which regional and currency rules Steam applies, and how to make the most of the seasonal sales.</p>
<h2>What Steam Wallet funds can buy</h2>
<p>Valve describes the wallet very broadly: the funds can be used to buy any game on Steam or inside a game that supports Steam transactions (<a href="https://store.steampowered.com/steamaccount/addfunds/">Steam Add Funds</a>).</p>
<p>What people usually pay for from the balance:</p>
<ul>
<li>games and editions in the Steam store;</li>
<li>add-ons and DLC for games they already own;</li>
<li>in-game purchases in titles that take payment through Steam;</li>
<li>Community Market items — skins and trading cards;</li>
<li>games bought as gifts for other players, straight from the store.</li>
</ul>
<p>The Market comes with a catch: it does not open straight away. The account must not be limited — which takes $5 spent on Steam, and adding $5 to the wallet counts — and the Steam Guard Mobile Authenticator must have been on for at least 15 days.</p>
<p>The main convenience of a balance is speed. No re-entering card details and no waiting for the bank to confirm, which matters most during a sale, when a discount only lasts so long.</p>
<h2>How to top up in soʻm</h2>
<p>For a player in Uzbekistan the real question is how to get money into the wallet without a foreign-currency card and without losing on conversion. The Steam store does not take Uzcard or Humo directly, and bank transfers add costs you do not see up front.</p>
<p>With YuPay it is four steps:</p>
<ol>
<li>Open the <a href="https://yupay.uz/en/store/steam">Steam top-up page</a>.</li>
<li>Enter your Steam login — the name you sign in with, not your profile's display name. No password is needed.</li>
<li>Enter an amount in dollars, from $1 to $300. The total in soʻm shows immediately.</li>
<li>Pay with an Uzcard or Humo card through Click, Payme or Uzum, and the balance tops up automatically.</li>
</ol>
<p>There is no fee on top: the dollars you enter are the dollars that reach the wallet, and the soʻm amount on screen is the amount you pay. A full walkthrough with the common mistakes is in <a href="https://yupay.uz/en/blog/steam">How to top up Steam in Uzbekistan</a>, and the local payment methods themselves are covered in <a href="https://yupay.uz/en/blog/buy-game-top-ups-in-uzbekistan">a separate article</a>.</p>
<h2>A wallet top-up versus a gift card</h2>
<p>New players often mix up the two ways of putting money into Steam: a direct top-up and a gift card. Both end as wallet balance; only the form differs.</p>
<p>A direct top-up raises the balance of one specific account straight away: you give the login, you pay, and the money lands there.</p>
<p>A gift card is a code for a set amount that a player redeems on their own account, which makes it a good present: you send the code and your friend decides when to enter it. Cards can carry regional restrictions, so check that the code will work in the recipient's region before buying.</p>
<p>The practical rule: top up your own account directly. And if you want to give a friend one particular game, you can buy it as a gift through YuPay — we explain how in <a href="https://yupay.uz/en/blog/how-to-buy-steam-games-from-uzbekistan">How to buy Steam games from Uzbekistan</a>.</p>
<h2>Steam's rules on regions and currencies</h2>
<p>The wallet has one limit that trips up people who change their account region: the balance is tied to the currency of the Steam region. If a purchase is in a different currency from the funds, Steam will not complete it and says outright that the wallet currency does not match the purchase. Money added in one region cannot be spent in another.</p>
<p>A top-up through YuPay works for accounts in the CIS — Uzbekistan, Kazakhstan, Russia and Belarus. You set the amount in dollars and it is credited in your wallet's currency; for an account registered in Uzbekistan that is the US dollar.</p>
<p>What that means in practice:</p>
<ul>
<li>top up the account, and the region, you intend to buy in;</li>
<li>do not switch the store country without a reason while there is money on the balance;</li>
<li>top up for specific purchases rather than stockpiling.</li>
</ul>
<h2>Making the most of the seasonal sales</h2>
<p>A wallet funded in advance pays off most during the big sales: popular games drop in price and the discount only lasts a limited time. With money already on the balance, checkout is immediate — no waiting on the bank.</p>
<p>The year's largest sales run in summer and winter, and they usually last longer than the rest. The spring and autumn sales are shorter — more of an extra excuse to refresh your library.</p>
<p>A few habits that help:</p>
<ul>
<li>build your wishlist early — Steam emails you when something on it goes on sale;</li>
<li>top up before the sale starts so you do not lose time on day one;</li>
<li>check a price against its discount history: if a game is on sale often, a "record" discount may be its usual one;</li>
<li>on a tight budget, several small purchases beat one big one.</li>
</ul>
<p>Ready for the next sale? Open <a href="https://yupay.uz/en/store/steam">Steam on YuPay</a>, enter an amount and top up your wallet in advance, so you can buy the games you want while the discount lasts.</p>$html$,
  'Steam Wallet: top it up in soʻm and what to spend it on',
  'How to top up a Steam Wallet from Uzbekistan in soʻm with no fee on top: your login, $1 to $300, paid through Click, Payme or Uzum. What the balance buys and how to plan it around the sales.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
  (gen_random_uuid(), :post_id, 'en', 0,
   'Can I top up a Steam Wallet in soʻm with no fee?',
   'Yes. With YuPay you enter your Steam login and an amount from $1 to $300, and pay through Click, Payme or Uzum. There is no fee on top: the dollars you enter are the dollars credited.'),
  (gen_random_uuid(), :post_id, 'en', 1,
   'What can Steam Wallet funds be spent on?',
   'Games and add-ons in the Steam store, in-game purchases in supported games, Community Market items, and games bought as gifts for other players.'),
  (gen_random_uuid(), :post_id, 'en', 2,
   'How is a wallet top-up different from a Steam gift card?',
   'Both end as the same balance. A top-up credits a specific account straight away; a gift card is a code that is easy to give to another player.'),
  (gen_random_uuid(), :post_id, 'en', 3,
   'Why does Steam say my wallet currency does not match the purchase?',
   'The wallet is tied to your account region''s currency. If the purchase is in another region or currency, those funds cannot pay for it.'),
  (gen_random_uuid(), :post_id, 'en', 4,
   'Which accounts can be topped up through YuPay?',
   'Steam accounts in the CIS: Uzbekistan, Kazakhstan, Russia and Belarus. The money is credited in your wallet''s currency.');

-- ----------------------------------------------------------------- Uzbek ---

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'uz', 'steam-hamyoni',
  'Steam hamyoni: qanday toʻldirish va nimaga sarflash',
  'Oʻzbekistondan Steam hamyonini soʻmda, ustama komissiyasiz qanday toʻldirish, balansni nimaga sarflash, u sovgʻa kartasidan nimasi bilan farq qilishi va chegirmalarga qanday tayyorlanish.',
$html$<h2>Asosiysi</h2>
<ul>
<li>Steam hamyonidagi pul oʻyinlar, DLC, oʻyin ichidagi xaridlar va Steam savdo maydonchasidagi buyumlarga sarflanadi.</li>
<li>Oʻzbekistonda uni YuPay orqali soʻmda toʻldirish qulay: faqat Steam logini kerak, summa $1 dan $300 gacha, ustama komissiya yoʻq.</li>
<li>Toʻgʻridan-toʻgʻri toʻldirish ham, sovgʻa kartasi ham bir xil balans beradi, lekin karta — bu kod, uni sovgʻa qilish qulay.</li>
<li>Hamyon akkaunt mintaqasining valyutasiga bogʻlangan: boshqa valyutadagi xaridni undagi pul bilan toʻlab boʻlmaydi.</li>
<li>Eng katta chegirmalar Steam’ning yozgi va qishki savdolarida boʻladi, ular boshqalaridan uzoqroq ham davom etadi.</li>
</ul>
<p>Steam hamyonini toʻldirishning eng oson yoʻli — soʻmda mahalliy toʻlov: akkaunt loginini kiritasiz, Click, Payme yoki Uzum orqali toʻlaysiz, balans esa klientda avtomatik, odatda bir-ikki daqiqada paydo boʻladi. Shundan keyin bu pul Steam’ning ichki valyutasi boʻlib ishlaydi: har safar karta kiritmasdan oʻyinlar, qoʻshimchalar, oʻyin ichidagi xaridlar va savdo maydonchasidagi buyumlar uchun toʻlaysiz.</p>
<p>Quyida — balans aslida nimaga sarflanishi, uni soʻmda qanday toʻldirish, toʻldirish sovgʻa kartasidan nimasi bilan farq qilishi, Steam mintaqa va valyutalar boʻyicha qanday qoidalarni qoʻllashi va mavsumiy savdolardan qanday foydalanish haqida.</p>
<h2>Steam hamyonidagi pulga nima sotib olish mumkin</h2>
<p>Valve hamyonni juda keng taʼriflaydi: undagi pulni Steam’dagi istalgan oʻyinni yoki Steam tranzaksiyalarini qoʻllab-quvvatlaydigan oʻyin ichidagi xaridni toʻlashga ishlatish mumkin (<a href="https://store.steampowered.com/steamaccount/addfunds/">Steam Add Funds</a>).</p>
<p>Balansdan odatda quyidagilar toʻlanadi:</p>
<ul>
<li>Steam doʻkonidagi oʻyinlar va nashrlar;</li>
<li>allaqachon sotib olingan oʻyinlarga qoʻshimchalar va DLC;</li>
<li>Steam orqali toʻlov qabul qiladigan oʻyinlardagi oʻyin ichidagi xaridlar;</li>
<li>savdo maydonchasidagi buyumlar — skinlar va kolleksiya kartochkalari;</li>
<li>doʻkondan toʻgʻridan-toʻgʻri boshqa oʻyinchilarga sovgʻa qilinadigan oʻyinlar.</li>
</ul>
<p>Savdo maydonchasining bir nozik jihati bor: u darhol ochilmaydi. Akkaunt cheklangan boʻlmasligi kerak — buning uchun Steam’da kamida $5 sarflash kerak, hamyonni shu summaga toʻldirish ham hisobga olinadi. Bundan tashqari, mobil Steam Guard kamida 15 kun yoqilgan boʻlishi kerak.</p>
<p>Balansning asosiy qulayligi — tezlik. Har safar karta maʼlumotlarini kiritish va bank tasdigʻini kutish shart emas, bu esa chegirma cheklangan vaqt amal qiladigan savdo kunlarida ayniqsa sezilarli.</p>
<h2>Balansni soʻmda qanday toʻldirish</h2>
<p>Oʻzbekistondagi oʻyinchi uchun asosiy savol — valyuta kartasisiz va konvertatsiya uchun ortiqcha toʻlamasdan hamyonga qanday pul tushirish. Steam doʻkoni Uzcard va Humo kartalarini toʻgʻridan-toʻgʻri qabul qilmaydi, bank oʻtkazmalari esa yashirin xarajatlar qoʻshadi.</p>
<p>YuPay orqali bu toʻrt qadam:</p>
<ol>
<li><a href="https://yupay.uz/uz/store/steam">Steam’ni toʻldirish</a> sahifasini oching.</li>
<li>Steam loginini kiriting — bu akkauntga kiradigan nomingiz, profilda koʻrinadigan ism emas. Parol kerak emas.</li>
<li>Summani dollarda kiriting — $1 dan $300 gacha. Soʻmdagi jami darhol koʻrinadi.</li>
<li>Uzcard yoki Humo kartasi bilan Click, Payme yoki Uzum orqali toʻlang — balans avtomatik toʻldiriladi.</li>
</ol>
<p>Ustama komissiya yoʻq: qancha dollar kiritsangiz, hamyonga shuncha tushadi, ekrandagi soʻmdagi summa esa toʻlov summasining oʻzi. Koʻp uchraydigan xatolar tahlili bilan batafsil yoʻriqnoma — <a href="https://yupay.uz/uz/blog/steam">Oʻzbekistonda Steam’ni qanday toʻldirish</a> maqolasida, mahalliy toʻlov usullari haqida esa <a href="https://yupay.uz/uz/blog/ozbekistonda-donat-sotib-olish">alohida maqolada</a> yozganmiz.</p>
<h2>Hamyonni toʻldirish sovgʻa kartasidan nimasi bilan farq qiladi</h2>
<p>Yangi oʻyinchilar Steam’ga pul tushirishning ikki usulini koʻpincha adashtiradi: toʻgʻridan-toʻgʻri toʻldirish va sovgʻa kartasi. Natija bir xil — hamyon balansi, farq faqat shaklda.</p>
<p>Toʻgʻridan-toʻgʻri toʻldirish muayyan akkauntning balansini darhol oshiradi: loginni kiritasiz, toʻlaysiz va pul aynan oʻsha yerda paydo boʻladi.</p>
<p>Sovgʻa kartasi — bu maʼlum summaga kod, uni oʻyinchi oʻz akkauntida faollashtiradi. Shuning uchun karta sovgʻa sifatida qulay: kodni doʻstingizga yuborasiz, uni qachon kiritishni u oʻzi hal qiladi. Kartalarda mintaqaviy cheklovlar boʻlishi mumkin, shuning uchun sotib olishdan oldin kod qabul qiluvchining mintaqasiga mos kelishini tekshiring.</p>
<p>Amaliy xulosa: oʻz akkauntingizni toʻgʻridan-toʻgʻri toʻldirish qulayroq. Doʻstingizga aniq bir oʻyinni sovgʻa qilmoqchi boʻlsangiz, uni YuPay orqali sovgʻa sifatida sotib olish mumkin — bu qanday ishlashini <a href="https://yupay.uz/uz/blog/ozbekistondan-steam-oyin-sotib-olish">Oʻzbekistondan Steam oʻyinini qanday sotib olish</a> qoʻllanmasida tushuntirganmiz.</p>
<h2>Steam’ning mintaqa va valyuta qoidalari</h2>
<p>Hamyonning akkaunt mintaqasini almashtiradiganlar duch keladigan bitta cheklovi bor: balans Steam mintaqasining valyutasiga bogʻlangan. Xarid valyutasi hamyondagi pul valyutasiga mos kelmasa, Steam toʻlovni yakunlashga ruxsat bermaydi va hamyon valyutasi xarid valyutasiga mos emasligini ochiq yozadi. Bir mintaqada qoʻshilgan pulni boshqasida sarflab boʻlmaydi.</p>
<p>YuPay orqali toʻldirish MDH akkauntlari uchun ishlaydi — Oʻzbekiston, Qozogʻiston, Rossiya va Belarus. Summani dollarda kiritasiz, hamyonga esa u hamyon valyutasida tushadi. Oʻzbekistonda roʻyxatdan oʻtgan akkauntlar uchun bu AQSh dollari.</p>
<p>Bundan nima kelib chiqadi:</p>
<ul>
<li>xarid qilmoqchi boʻlgan akkaunt va mintaqadagi hamyonni toʻldiring;</li>
<li>balansda pul boʻlsa, doʻkon mamlakatini sababsiz almashtirmang;</li>
<li>zaxira uchun emas, aniq xaridlar uchun toʻldiring.</li>
</ul>
<h2>Mavsumiy savdolardan qanday foydalanish</h2>
<p>Oldindan toʻldirilgan hamyon katta savdolarda ayniqsa foydali: mashhur oʻyinlar arzonlashadi, chegirma esa cheklangan vaqt amal qiladi. Balansda pul boʻlsa, buyurtma bankni kutmasdan darhol rasmiylashtiriladi.</p>
<p>Yilning eng katta savdolari yozda va qishda boʻlib oʻtadi va odatda boshqalaridan uzoqroq davom etadi. Bahorgi va kuzgi savdolar qisqaroq — ular koʻproq kutubxonani yangilash uchun qoʻshimcha bahona.</p>
<p>Bir nechta foydali odat:</p>
<ul>
<li>istaklar roʻyxatini oldindan tuzing — undagi oʻyin arzonlashganda Steam xat yuboradi;</li>
<li>birinchi kuni vaqt yoʻqotmaslik uchun hamyonni savdo boshlanishidan oldin toʻldiring;</li>
<li>narxni chegirmalar tarixi bilan solishtiring: oʻyin tez-tez aksiyaga tushsa, «rekord» chegirma uning odatiy chegirmasi boʻlib chiqishi mumkin;</li>
<li>byudjet cheklangan boʻlsa, bitta katta xarid oʻrniga bir nechta kichik xarid qiling.</li>
</ul>
<p>Navbatdagi savdoga tayyormisiz? <a href="https://yupay.uz/uz/store/steam">YuPay’dagi Steam</a> sahifasini oching, summani kiriting va chegirma amal qilayotganda kerakli oʻyinlarni sotib olish uchun hamyonni oldindan toʻldiring.</p>$html$,
  'Steam hamyoni: soʻmda toʻldirish va nimaga sarflash',
  'Oʻzbekistondan Steam hamyonini soʻmda, ustama komissiyasiz toʻldirish: login, $1 dan $300 gacha, Click, Payme yoki Uzum orqali toʻlov. Balansni nimaga sarflash va savdolarga qanday rejalashtirish.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
  (gen_random_uuid(), :post_id, 'uz', 0,
   'Steam hamyonini soʻmda komissiyasiz toʻldirish mumkinmi?',
   'Ha. YuPay orqali Steam logini va $1 dan $300 gacha summani kiritib, Click, Payme yoki Uzum orqali toʻlash kifoya. Ustama komissiya yoʻq: qancha dollar kiritsangiz, shuncha tushadi.'),
  (gen_random_uuid(), :post_id, 'uz', 1,
   'Steam hamyonidagi pulni nimaga sarflash mumkin?',
   'Steam doʻkonidagi oʻyinlar va qoʻshimchalarga, qoʻllab-quvvatlanadigan oʻyinlardagi xaridlarga, savdo maydonchasidagi buyumlarga va boshqa oʻyinchilarga sovgʻa qilinadigan oʻyinlarga.'),
  (gen_random_uuid(), :post_id, 'uz', 2,
   'Hamyonni toʻldirish Steam sovgʻa kartasidan nimasi bilan farq qiladi?',
   'Ikkalasi ham bir xil balans beradi. Toʻldirish pulni koʻrsatilgan akkauntga darhol tushiradi, sovgʻa kartasi esa boshqa oʻyinchiga sovgʻa qilish qulay boʻlgan kod.'),
  (gen_random_uuid(), :post_id, 'uz', 3,
   'Nega Steam hamyon valyutasi xaridga mos emasligini yozadi?',
   'Hamyon akkaunt mintaqasining valyutasiga bogʻlangan. Xarid boshqa mintaqa yoki valyutada boʻlsa, bu pul bilan toʻlab boʻlmaydi.'),
  (gen_random_uuid(), :post_id, 'uz', 4,
   'YuPay orqali qaysi akkauntlarni toʻldirish mumkin?',
   'MDH’dagi Steam akkauntlarini: Oʻzbekiston, Qozogʻiston, Rossiya va Belarus. Pul hamyoningiz valyutasida tushadi.');

COMMIT;
