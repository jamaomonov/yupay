-- Blog post «Топ-10 мобильных игр для геймеров Узбекистана в 2026» (draft).
--
-- Post id 01a0b23f-a34c-78d0-835c-bb8ef0aa9420, written in the admin as a ru-only
-- draft. This script rewrites the ru body, adds en + uz, and gives every locale
-- its own four FAQ rows.
--
-- What changed in ru, and why:
--
--   * The post names ten games and tells the reader they can top them up with
--     us — and linked to the catalogue exactly zero times. Every one of the ten
--     is a brand we actually sell, so each now carries one line naming what we
--     sell for it, by its real product name, linked to that brand page. The
--     names come from the live catalogue, not from the games' wikis: Standoff 2
--     is Gold delivered as a promo code (no player ID), Roblox is Robux on
--     global gift cards, PUBG Mobile has WOW Coins beside UC. Mobile Legends
--     also points at the separate RU-region page, because topping up the wrong
--     region is the one mistake that cannot be undone after payment.
--   * `<a href="https://yupay.uz/blog/post">` was already a 404 — that post's
--     placeholder slug was renamed to `kupit-donat-v-uzbekistane` when it was
--     published. Fixed.
--   * The slug was `10-2026`, which reads as a date, not a page. Renamed to
--     `top-10-mobilnyh-igr-2026`. Safe: never published, nothing indexed.
--   * "В каталоге есть готовые страницы для популярных проектов: …" listed five
--     games as plain text. Linked, and corrected to say all ten are covered.
--
-- The two cited statistics were checked against the source and are accurate:
-- $82bn mobile IAP revenue in 2025 and 95,000 mobile game downloads per minute
-- (Sensor Tower, State of Gaming 2025).
--
-- Does NOT publish. `status` stays `draft` and `primary_brand_id` stays NULL —
-- `ck_blog_posts_brand_unless_draft` needs a brand before this can leave draft,
-- and with `show_buy_card` on, that brand also picks the buy card under the
-- text. A ten-game round-up has no single obvious brand: that is the owner's
-- call.
--
-- Idempotent: re-running replaces the same three translation rows and twelve
-- FAQ rows.
--
-- Apply:
--   docker exec -i yupay-prod-postgres-1 sh -lc \
--     'psql -U $POSTGRES_USER -d $POSTGRES_DB -v ON_ERROR_STOP=1' \
--     < scripts/seed/2026-09-18_blog_top10_mobile_games.sql

\set post_id '''01a0b23f-a34c-78d0-835c-bb8ef0aa9420'''

BEGIN;

-- ------------------------------------------------------------------- ru ------

UPDATE blog_post_translations SET
  slug = 'top-10-mobilnyh-igr-2026',
  body_html = $body$<h2>Главное</h2>
<ul>
<li>Лучшие мобильные игры 2026 в Узбекистане это PUBG Mobile, Free Fire, Genshin Impact, Mobile Legends и Standoff 2</li>
<li>Мировой мобильный гейминг принёс 82 миллиарда долларов от внутриигровых покупок в 2025 году (Sensor Tower)</li>
<li>Для большинства топовых игр хватает бюджетного смартфона с 4-6 ГБ оперативной памяти и стабильного интернета</li>
<li>Все десять игр из списка можно пополнить у нас в сумах и без комиссии за пару минут</li>
</ul>
<p>Лучшие мобильные игры 2026 для геймеров Узбекистана это PUBG Mobile, Free Fire, Standoff 2, Mobile Legends и Genshin Impact. Ниже разбираем десять проектов, которые реально популярны внутри страны, их требования к устройствам и то, как быстро добавить в них внутриигровую валюту в сумах.</p>
<p>Мобильный гейминг перестал быть развлечением на пять минут в очереди. В 2025 году игры на смартфонах принесли 82 миллиарда долларов дохода только от внутриигровых покупок, а скачивалось около 95 000 мобильных игр каждую минуту (<a href="https://www.prnewswire.com/news-releases/sensor-tower-state-of-gaming-gaming-drove-94-billion-in-revenue-in-2025-downloads-reached-52-billion-302696284.html">Sensor Tower, State of Gaming 2025</a>, 2026). Узбекистан внутри этой волны: недорогие смартфоны, доступный мобильный интернет и большое молодое сообщество игроков.</p>
<h2>Лучшие мобильные игры 2026 среди узбекских игроков</h2>
<p>Топ узбекского гейминга держат бесплатные онлайн-проекты с быстрыми матчами и низкими требованиями к железу. По объёму аудитории и активности внутри страны на первый план выходят PUBG Mobile, Free Fire и Standoff 2. Они запускаются даже на бюджетных телефонах и не требуют дорогого оборудования.</p>
<p>Причина проста. Игроку нужен телефон, который уже есть в кармане, и матч, который начинается за несколько секунд. Соревновательные шутеры и MOBA дают и то, и другое. Одиночные и полу-одиночные RPG вроде Genshin Impact собирают отдельную, но очень преданную аудиторию, готовую вкладываться в развитие персонажей.</p>
<p>Если коротко, узбекский игрок 2026 года ценит три вещи: бесплатный вход, работу на доступном устройстве и активное местное комьюнити.</p>
<h2>Краткий обзор каждого проекта и его особенностей</h2>
<p>Ниже десять игр, которые стоит держать на радаре в 2026 году. Для каждой указана суть геймплея, чем она цепляет аудиторию и что именно можно пополнить у нас.</p>
<h3>1. PUBG Mobile</h3>
<p>Королевская битва, которая во многом задала стандарт жанра на мобильных. Матч на 100 игроков, сужающаяся зона, реалистичная стрельба. PUBG Mobile остаётся одним из самых массовых мобильных шутеров в мире с аудиторией в десятки миллионов активных игроков ежемесячно. В Узбекистане это фактически игра по умолчанию для командных катка с друзьями.</p>
<p><strong>Пополнить у нас:</strong> <a href="https://yupay.uz/store/pubg-mobile">UC, Royal Pass, Prime и WOW Coins</a> — по игровому ID, пароль не нужен.</p>
<h3>2. Free Fire</h3>
<p>Более лёгкая и быстрая королевская битва. Матчи короче, требования к устройству ниже, а на старте всего 50 игроков вместо сотни. Именно за счёт скромных системных требований Free Fire стал хитом на бюджетных смартфонах, которых в регионе большинство.</p>
<p><strong>Пополнить у нас:</strong> <a href="https://yupay.uz/store/free-fire">алмазы, наборы и подписку</a> — по игровому ID.</p>
<h3>3. Standoff 2</h3>
<p>Динамичный командный шутер в духе классических тактических перестрелок. Формат 5 на 5, закладка бомбы, экономика раундов. Standoff 2 особенно любят за скины и активную торговлю ими, а также за то, что игра идёт плавно даже на среднем железе.</p>
<p><strong>Пополнить у нас:</strong> <a href="https://yupay.uz/store/standoff-2">Gold</a> — приходит промокодом, игровой ID указывать не нужно.</p>
<h3>4. Mobile Legends: Bang Bang</h3>
<p>MOBA в формате 5 на 5 с матчами примерно по 10-15 минут. Понятная для новичков, но с высоким потолком мастерства. Mobile Legends собирает большие турниры в Юго-Восточной Азии, и этот соревновательный дух хорошо чувствуется в узбекском сообществе.</p>
<p><strong>Пополнить у нас:</strong> <a href="https://yupay.uz/store/mobile-legends">алмазы, пропуски и наборы</a> по игровому ID. Если аккаунт российского региона, берите <a href="https://yupay.uz/store/mobile-legends-ru">страницу MLBB RU</a>: регион выбирается до оплаты и после неё уже не меняется.</p>
<h3>5. Genshin Impact</h3>
<p>Открытый мир, аниме-стилистика и система развития персонажей через гача-механику. Genshin Impact остаётся одним из самых прибыльных мобильных проектов в мире и собрал многомиллиардную аудиторию, готовую вкладываться в новых персонажей. Для новичков у нас есть отдельный разбор в <a href="https://yupay.uz/blog/genshin-impact">гайде по Genshin Impact</a>.</p>
<p><strong>Пополнить у нас:</strong> <a href="https://yupay.uz/store/genshin-impact">Кристаллы Сотворения и Благословение полой луны</a>.</p>
<h3>6. Honkai: Star Rail</h3>
<p>Пошаговая RPG от создателей Genshin с упором на сюжет и коллекционирование героев. Требует более мощного устройства, но вознаграждает кинематографичной подачей и глубокой системой команд. Хороший выбор для тех, кто любит вдумчивый геймплей без постоянного онлайн-стресса.</p>
<p><strong>Пополнить у нас:</strong> <a href="https://yupay.uz/store/honkai-star-rail">Сущность древних снов и Экспресс-снабжение</a>.</p>
<h3>7. Roblox</h3>
<p>Не столько игра, сколько платформа с миллионами пользовательских миров: от гонок до симуляторов и хорроров. Roblox особенно популярен у младшей аудитории и держится за счёт бесконечного потока нового контента от самих игроков.</p>
<p><strong>Пополнить у нас:</strong> <a href="https://yupay.uz/store/roblox">Robux глобальными картами пополнения</a> — код активируется на своём аккаунте.</p>
<h3>8. Delta Force</h3>
<p>Современный тактический шутер с масштабными боями и режимами в духе больших военных операций. Delta Force привлекает тех, кто вырос на классических командных шутерах и хочет более серьёзной, чем королевские битвы, тактики.</p>
<p><strong>Пополнить у нас:</strong> <a href="https://yupay.uz/store/delta-force">Delta Coins и Season Pass</a>.</p>
<h3>9. Arena Breakout</h3>
<p>Хардкорный шутер-экстракшн: заходишь в зону, собираешь лут и пытаешься выбраться живым, рискуя потерять всё снаряжение. Arena Breakout ценят за реализм оружия и напряжение, которого нет в обычных аркадных перестрелках.</p>
<p><strong>Пополнить у нас:</strong> <a href="https://yupay.uz/store/arena-breakout">Bonds, Battle Pass и наборы</a>. У версии для ПК отдельная страница — <a href="https://yupay.uz/store/arena-breakout-infinite">Arena Breakout: Infinite</a>.</p>
<h3>10. Blood Strike</h3>
<p>Быстрый и лёгкий шутер, объединяющий королевскую битву и командные режимы. Blood Strike сделан так, чтобы запускаться на широком спектре устройств и не требовать долгой загрузки, что делает его удобным для коротких сессий.</p>
<p><strong>Пополнить у нас:</strong> <a href="https://yupay.uz/store/blood-strike">золото и пропуска</a>.</p>
<h2>Игры с системой доната и внутриигровой валютой</h2>
<p>Почти все проекты из списка бесплатны на входе и зарабатывают на внутриигровых покупках. Это не случайность: именно модель free-to-play с донатом принесла мобильному геймингу основную часть его годового дохода, о котором мы говорили выше.</p>
<p>Внутриигровая валюта у каждой игры своя. В PUBG Mobile это UC, во Free Fire алмазы, в Mobile Legends алмазы, в Genshin Impact и Honkai: Star Rail кристаллы для гача-крутки, в Roblox робуксы. За эту валюту покупают скины, боевые пропуски, новых персонажей и косметику.</p>
<p>Важно понимать разницу между двумя типами трат. В шутерах донат чаще косметический и почти не влияет на баланс. В гача-играх вроде Genshin валюта нужна, чтобы получать новых героев и оружие, поэтому здесь покупки ощущаются заметнее. Если хочется разобраться, где выгоднее покупать валюту, посмотрите наш разбор в статье <a href="https://yupay.uz/blog/kupit-donat-v-uzbekistane">где выгоднее купить донат в Узбекистане</a>.</p>
<h2>Требования к устройствам и интернету</h2>
<p>Хорошая новость для узбекских игроков: большинство топовых игр нетребовательны. Для соревновательных шутеров вроде PUBG Mobile, Free Fire и Standoff 2 достаточно смартфона с 4-6 ГБ оперативной памяти и средним процессором. Free Fire специально оптимизирован под слабые телефоны, поэтому идёт почти на всём.</p>
<p>Более тяжёлые проекты просят больше ресурсов. Genshin Impact и Honkai: Star Rail комфортнее играть на устройстве с 6-8 ГБ оперативной памяти и хорошей графикой, иначе возможны просадки кадров в насыщенных сценах. Roblox нетребователен сам по себе, но отдельные пользовательские миры могут нагружать телефон сильнее.</p>
<p>Про интернет отдельный разговор. Для онлайн-шутеров ключевую роль играет стабильность соединения и пинг, а не только скорость закачки. Комфортная игра начинается со стабильного 4G или Wi-Fi с задержкой примерно 60-80 мс. Для одиночных RPG хватает и обычного мобильного интернета: там важна не мгновенная реакция, а просто наличие связи.</p>
<p>Короткий чек-лист перед установкой:</p>
<ul>
<li>Свободное место: от 3 до 15 ГБ в зависимости от игры.</li>
<li>Оперативная память: 4 ГБ минимум, 6-8 ГБ для тяжёлых проектов.</li>
<li>Соединение: стабильный 4G или Wi-Fi для онлайн-режимов.</li>
<li>Зарядка: тяжёлые игры быстро сажают батарею, держите повербанк под рукой.</li>
</ul>
<h2>Как быстро пополнить любимую игру</h2>
<p>Самый удобный способ добавить внутриигровую валюту в Узбекистане это оплата в сумах местными методами без комиссии. Именно так работает Yupay: вы выбираете игру, указываете нужный пакет валюты и подтверждаете платёж, а зачисление проходит автоматически за пару минут.</p>
<p>Это снимает две привычные головные боли. Первая: не нужно искать зарубежную карту или обходные пути для оплаты в долларах. Вторая: не нужно вручную ждать продавца, потому что процесс автоматизирован. Страницы есть у всех десяти игр из этого списка: <a href="https://yupay.uz/store/pubg-mobile">PUBG Mobile</a>, <a href="https://yupay.uz/store/free-fire">Free Fire</a>, <a href="https://yupay.uz/store/standoff-2">Standoff 2</a>, <a href="https://yupay.uz/store/mobile-legends">Mobile Legends</a>, <a href="https://yupay.uz/store/genshin-impact">Genshin Impact</a>, <a href="https://yupay.uz/store/honkai-star-rail">Honkai: Star Rail</a>, <a href="https://yupay.uz/store/roblox">Roblox</a>, <a href="https://yupay.uz/store/delta-force">Delta Force</a>, <a href="https://yupay.uz/store/arena-breakout">Arena Breakout</a> и <a href="https://yupay.uz/store/blood-strike">Blood Strike</a>.</p>
<p>Порядок действий предельно простой:</p>
<ol>
<li>Откройте страницу нужной игры в <a href="https://yupay.uz/store">каталоге</a>.</li>
<li>Выберите пакет валюты или подписку.</li>
<li>Укажите игровой ID, если он требуется.</li>
<li>Оплатите в сумах привычным способом.</li>
<li>Дождитесь автоматического зачисления.</li>
</ol>
<p>Если вы только выбираете, во что вложить свободный вечер, начните с любого бесплатного шутера из списка: скачивание ничего не стоит, а разобраться в основах можно за один матч. А когда захочется прокачать персонажа или взять новый скин, пополнить баланс в сумах займёт меньше времени, чем сам матч.</p>$body$
WHERE post_id = :post_id AND locale = 'ru';

-- ------------------------------------------------------------------- en ------

INSERT INTO blog_post_translations (post_id, locale, slug, title, excerpt, body_html,
                                    seo_title, seo_description)
VALUES (
  :post_id,
  'en',
  'top-10-mobile-games-uzbekistan-2026',
  'Top 10 mobile games for players in Uzbekistan in 2026',
  'The best mobile games of 2026 for players in Uzbekistan: what each one is, what device it needs, '
    || 'and the fast way to top it up in soum.',
$body$<h2>The short version</h2>
<ul>
<li>The best mobile games of 2026 in Uzbekistan are PUBG Mobile, Free Fire, Genshin Impact, Mobile Legends and Standoff 2</li>
<li>Mobile gaming worldwide brought in 82 billion dollars from in-app purchases in 2025 (Sensor Tower)</li>
<li>Most of the top games run on a budget phone with 4-6 GB of RAM and a stable connection</li>
<li>All ten games on this list can be topped up with us, in soum, with no fee, in a couple of minutes</li>
</ul>
<p>The best mobile games of 2026 for players in Uzbekistan are PUBG Mobile, Free Fire, Standoff 2, Mobile Legends and Genshin Impact. Below are ten titles that are genuinely popular inside the country, what device each one needs, and how to add in-game currency to them in soum.</p>
<p>Mobile gaming stopped being a five-minute distraction in a queue a long time ago. In 2025, games on smartphones earned 82 billion dollars from in-app purchases alone, and roughly 95,000 mobile games were downloaded every minute (<a href="https://www.prnewswire.com/news-releases/sensor-tower-state-of-gaming-gaming-drove-94-billion-in-revenue-in-2025-downloads-reached-52-billion-302696284.html">Sensor Tower, State of Gaming 2025</a>, 2026). Uzbekistan sits inside that wave: affordable smartphones, affordable mobile internet and a large young community of players.</p>
<h2>The 2026 favourites among players in Uzbekistan</h2>
<p>The top of gaming in Uzbekistan is held by free online titles with fast matches and low hardware demands. By audience size and in-country activity, PUBG Mobile, Free Fire and Standoff 2 come first. They run on budget phones and need no expensive equipment.</p>
<p>The reason is simple. A player needs the phone already in their pocket and a match that starts in a few seconds. Competitive shooters and MOBAs give both. Single-player and semi-single-player RPGs like Genshin Impact gather a separate but very loyal audience, ready to invest in developing their characters.</p>
<p>In short, the Uzbek player of 2026 values three things: free entry, working on an affordable device, and an active local community.</p>
<h2>A short look at each title</h2>
<p>Ten games worth keeping on the radar in 2026. For each one: what the gameplay is, what hooks the audience, and exactly what you can top up with us.</p>
<h3>1. PUBG Mobile</h3>
<p>The battle royale that largely set the standard for the genre on mobile. A hundred players per match, a shrinking zone, realistic gunplay. PUBG Mobile remains one of the most played mobile shooters in the world, with tens of millions of monthly active players. In Uzbekistan it is effectively the default game for a squad session with friends.</p>
<p><strong>Top up with us:</strong> <a href="https://yupay.uz/en/store/pubg-mobile">UC, Royal Pass, Prime and WOW Coins</a> — by player ID, no password needed.</p>
<h3>2. Free Fire</h3>
<p>A lighter, faster battle royale. Matches are shorter, the device requirements lower, and a round starts with 50 players instead of a hundred. Those modest system requirements are exactly why Free Fire became a hit on the budget smartphones that make up most of the region.</p>
<p><strong>Top up with us:</strong> <a href="https://yupay.uz/en/store/free-fire">diamonds, bundles and the subscription</a> — by player ID.</p>
<h3>3. Standoff 2</h3>
<p>A fast team shooter in the spirit of classic tactical firefights. Five on five, bomb plants, round economy. Standoff 2 is loved for its skins and the busy trading around them, and for running smoothly even on mid-range hardware.</p>
<p><strong>Top up with us:</strong> <a href="https://yupay.uz/en/store/standoff-2">Gold</a> — delivered as a promo code, so no player ID is needed.</p>
<h3>4. Mobile Legends: Bang Bang</h3>
<p>A five-on-five MOBA with matches of roughly 10-15 minutes. Approachable for beginners, with a high skill ceiling. Mobile Legends draws large tournaments in Southeast Asia, and that competitive spirit is clearly felt in the Uzbek community.</p>
<p><strong>Top up with us:</strong> <a href="https://yupay.uz/en/store/mobile-legends">diamonds, passes and bundles</a> by player ID. For an account on the Russian region, use the <a href="https://yupay.uz/en/store/mobile-legends-ru">MLBB RU page</a>: the region is chosen before payment and cannot be changed afterwards.</p>
<h3>5. Genshin Impact</h3>
<p>An open world, anime art direction and character progression built on gacha mechanics. Genshin Impact remains one of the most profitable mobile titles in the world, with a multi-billion-dollar audience willing to invest in new characters. For beginners we have a separate walkthrough in our <a href="https://yupay.uz/en/blog/genshin-impact">Genshin Impact guide</a>.</p>
<p><strong>Top up with us:</strong> <a href="https://yupay.uz/en/store/genshin-impact">Genesis Crystals and the Blessing of the Welkin Moon</a>.</p>
<h3>6. Honkai: Star Rail</h3>
<p>A turn-based RPG from the makers of Genshin, focused on story and collecting characters. It asks for a stronger device, but rewards you with cinematic presentation and a deep team system. A good pick for anyone who likes considered gameplay without constant online pressure.</p>
<p><strong>Top up with us:</strong> <a href="https://yupay.uz/en/store/honkai-star-rail">Oneiric Shards and the Express Supply Pass</a>.</p>
<h3>7. Roblox</h3>
<p>Less a game than a platform with millions of user-made worlds: racing, simulators, horror. Roblox is especially popular with a younger audience and runs on an endless stream of new content from the players themselves.</p>
<p><strong>Top up with us:</strong> <a href="https://yupay.uz/en/store/roblox">Robux on global gift cards</a> — you redeem the code on your own account.</p>
<h3>8. Delta Force</h3>
<p>A modern tactical shooter with large-scale battles and modes in the spirit of big military operations. Delta Force appeals to players who grew up on classic team shooters and want tactics more serious than a battle royale.</p>
<p><strong>Top up with us:</strong> <a href="https://yupay.uz/en/store/delta-force">Delta Coins and the Season Pass</a>.</p>
<h3>9. Arena Breakout</h3>
<p>A hardcore extraction shooter: you enter the zone, gather loot and try to get out alive, risking all your gear. Arena Breakout is valued for its weapon realism and a tension ordinary arcade firefights do not have.</p>
<p><strong>Top up with us:</strong> <a href="https://yupay.uz/en/store/arena-breakout">Bonds, Battle Pass and bundles</a>. The PC version has its own page — <a href="https://yupay.uz/en/store/arena-breakout-infinite">Arena Breakout: Infinite</a>.</p>
<h3>10. Blood Strike</h3>
<p>A fast, light shooter combining battle royale with team modes. Blood Strike is built to launch on a wide range of devices without a long load, which makes it convenient for short sessions.</p>
<p><strong>Top up with us:</strong> <a href="https://yupay.uz/en/store/blood-strike">gold and passes</a>.</p>
<h2>The games with top-ups and in-game currency</h2>
<p>Almost every title on the list is free to enter and earns from in-app purchases. That is no accident: the free-to-play model with top-ups is what brought mobile gaming most of the annual revenue mentioned above.</p>
<p>Each game has its own currency. In PUBG Mobile it is UC, in Free Fire diamonds, in Mobile Legends diamonds, in Genshin Impact and Honkai: Star Rail the crystals used for gacha pulls, in Roblox Robux. That currency buys skins, battle passes, new characters and cosmetics.</p>
<p>It is worth understanding the difference between two kinds of spending. In shooters a top-up is usually cosmetic and barely affects balance. In gacha games like Genshin the currency is what gets you new characters and weapons, so purchases feel more consequential. If you want to work out where the currency is cheapest, read our breakdown in <a href="https://yupay.uz/en/blog/buy-game-top-ups-in-uzbekistan">buying game top-ups in Uzbekistan</a>.</p>
<h2>Device and internet requirements</h2>
<p>Good news for players in Uzbekistan: most top games are undemanding. For competitive shooters like PUBG Mobile, Free Fire and Standoff 2, a phone with 4-6 GB of RAM and a mid-range processor is enough. Free Fire is deliberately optimised for weaker phones, so it runs on almost anything.</p>
<p>Heavier titles ask for more. Genshin Impact and Honkai: Star Rail are more comfortable on a device with 6-8 GB of RAM and decent graphics, otherwise frames can drop in busy scenes. Roblox is undemanding in itself, but individual user-made worlds can load a phone much harder.</p>
<p>The internet is a separate conversation. For online shooters, connection stability and ping matter more than download speed alone. Comfortable play starts at a stable 4G or Wi-Fi with about 60-80 ms of latency. For single-player RPGs ordinary mobile internet is enough: what matters there is having a connection, not instant reaction.</p>
<p>A short checklist before installing:</p>
<ul>
<li>Free space: 3 to 15 GB depending on the game.</li>
<li>RAM: 4 GB minimum, 6-8 GB for heavier titles.</li>
<li>Connection: stable 4G or Wi-Fi for online modes.</li>
<li>Power: heavy games drain a battery fast, keep a power bank to hand.</li>
</ul>
<h2>How to top up your game quickly</h2>
<p>The most convenient way to add in-game currency in Uzbekistan is paying in soum by local methods with no fee. That is how Yupay works: you pick the game, choose the pack you want and confirm the payment, and crediting happens automatically within a couple of minutes.</p>
<p>That removes two familiar headaches. First, no hunting for a foreign card or a workaround to pay in dollars. Second, no waiting on a seller by hand, because the process is automated. All ten games on this list have a page: <a href="https://yupay.uz/en/store/pubg-mobile">PUBG Mobile</a>, <a href="https://yupay.uz/en/store/free-fire">Free Fire</a>, <a href="https://yupay.uz/en/store/standoff-2">Standoff 2</a>, <a href="https://yupay.uz/en/store/mobile-legends">Mobile Legends</a>, <a href="https://yupay.uz/en/store/genshin-impact">Genshin Impact</a>, <a href="https://yupay.uz/en/store/honkai-star-rail">Honkai: Star Rail</a>, <a href="https://yupay.uz/en/store/roblox">Roblox</a>, <a href="https://yupay.uz/en/store/delta-force">Delta Force</a>, <a href="https://yupay.uz/en/store/arena-breakout">Arena Breakout</a> and <a href="https://yupay.uz/en/store/blood-strike">Blood Strike</a>.</p>
<p>The steps could not be simpler:</p>
<ol>
<li>Open the page for your game in the <a href="https://yupay.uz/en/store">catalogue</a>.</li>
<li>Pick the currency pack or the subscription.</li>
<li>Enter your player ID, if the game needs one.</li>
<li>Pay in soum the way you usually do.</li>
<li>Wait for automatic delivery.</li>
</ol>
<p>If you are still choosing what to spend a free evening on, start with any free shooter from the list: downloading costs nothing, and one match is enough to learn the basics. And when you feel like levelling up a character or picking up a new skin, topping up in soum takes less time than the match itself.</p>$body$,
  'Top 10 mobile games for players in Uzbekistan in 2026',
  'The best mobile games of 2026 for players in Uzbekistan: what each one is, what device it needs, '
    || 'and the fast way to top it up in soum with no fee.'
)
ON CONFLICT (post_id, locale) DO UPDATE
   SET slug = EXCLUDED.slug, title = EXCLUDED.title, excerpt = EXCLUDED.excerpt,
       body_html = EXCLUDED.body_html, seo_title = EXCLUDED.seo_title,
       seo_description = EXCLUDED.seo_description;

-- ------------------------------------------------------------------- uz ------

INSERT INTO blog_post_translations (post_id, locale, slug, title, excerpt, body_html,
                                    seo_title, seo_description)
VALUES (
  :post_id,
  'uz',
  'ozbekiston-uchun-top-10-mobil-oyin-2026',
  'Oʻzbekiston oʻyinchilari uchun 2026 yilning eng yaxshi 10 ta mobil oʻyini',
  '2026 yilning eng yaxshi mobil oʻyinlari: har biri nima haqda, qanday qurilma talab qiladi va '
    || 'ularni soʻmda qanday qilib tez toʻldirish mumkin.',
$body$<h2>Asosiysi</h2>
<ul>
<li>Oʻzbekistonda 2026 yilning eng yaxshi mobil oʻyinlari — PUBG Mobile, Free Fire, Genshin Impact, Mobile Legends va Standoff 2</li>
<li>Jahon mobil geymingi 2025 yilda oʻyin ichidagi xaridlardan 82 milliard dollar keltirdi (Sensor Tower)</li>
<li>Koʻpchilik top oʻyinlar uchun 4-6 GB operativ xotirali arzon smartfon va barqaror internet yetarli</li>
<li>Roʻyxatdagi oʻnta oʻyinning hammasini bizda soʻmda, komissiyasiz, bir necha daqiqada toʻldirish mumkin</li>
</ul>
<p>Oʻzbekiston oʻyinchilari uchun 2026 yilning eng yaxshi mobil oʻyinlari — PUBG Mobile, Free Fire, Standoff 2, Mobile Legends va Genshin Impact. Quyida mamlakat ichida haqiqatan mashhur boʻlgan oʻnta loyiha, ularning qurilmaga talablari va ularga oʻyin valyutasini soʻmda qanday tez qoʻshish mumkinligi koʻrib chiqiladi.</p>
<p>Mobil geyming allaqachon navbatda turgandagi besh daqiqalik ermak boʻlishdan chiqdi. 2025 yilda smartfondagi oʻyinlar faqat oʻyin ichidagi xaridlardan 82 milliard dollar daromad keltirdi, har daqiqada esa taxminan 95 000 ta mobil oʻyin yuklab olindi (<a href="https://www.prnewswire.com/news-releases/sensor-tower-state-of-gaming-gaming-drove-94-billion-in-revenue-in-2025-downloads-reached-52-billion-302696284.html">Sensor Tower, State of Gaming 2025</a>, 2026). Oʻzbekiston ham shu toʻlqin ichida: arzon smartfonlar, hamyonbop mobil internet va katta yosh oʻyinchilar jamoasi.</p>
<h2>Oʻzbek oʻyinchilari orasida 2026 yilning yetakchilari</h2>
<p>Oʻzbek geymingining choʻqqisini tez matchli va qurilmaga talabi past boʻlgan bepul onlayn loyihalar ushlab turibdi. Auditoriya hajmi va mamlakat ichidagi faollik boʻyicha birinchi oʻringa PUBG Mobile, Free Fire va Standoff 2 chiqadi. Ular hatto arzon telefonlarda ham ishlaydi va qimmat jihoz talab qilmaydi.</p>
<p>Sababi oddiy. Oʻyinchiga choʻntagida allaqachon bor telefon va bir necha soniyada boshlanadigan match kerak. Raqobatli shuterlar va MOBA shularning ikkalasini beradi. Genshin Impact kabi yakka tartibdagi RPGlar esa alohida, ammo juda sodiq auditoriyani yigʻadi — qahramonlarni rivojlantirishga sarflashga tayyor auditoriyani.</p>
<p>Qisqasi, 2026 yilning oʻzbek oʻyinchisi uch narsani qadrlaydi: bepul kirish, hamyonbop qurilmada ishlash va faol mahalliy jamoa.</p>
<h2>Har bir loyihaning qisqacha sharhi</h2>
<p>Quyida 2026 yilda eʼtiborda tutishga arziydigan oʻnta oʻyin. Har biri uchun: geympleyning mohiyati, auditoriyani nimasi bilan ushlab turishi va bizda aynan nimani toʻldirish mumkinligi.</p>
<h3>1. PUBG Mobile</h3>
<p>Mobil qurilmalarda janr standartini koʻp jihatdan belgilab bergan battle royale. 100 oʻyinchilik match, torayib boruvchi zona, realistik otishma. PUBG Mobile dunyodagi eng ommaviy mobil shuterlardan biri boʻlib qolmoqda, oyiga oʻnlab million faol oʻyinchi. Oʻzbekistonda bu doʻstlar bilan jamoaviy oʻynash uchun deyarli sukut boʻyicha tanlanadigan oʻyin.</p>
<p><strong>Bizda toʻldirish mumkin:</strong> <a href="https://yupay.uz/uz/store/pubg-mobile">UC, Royal Pass, Prime va WOW Coins</a> — oʻyin ID raqami boʻyicha, parol kerak emas.</p>
<h3>2. Free Fire</h3>
<p>Yengilroq va tezroq battle royale. Matchlar qisqaroq, qurilmaga talablar pastroq, boshida esa yuz emas, atigi 50 oʻyinchi. Aynan kamtarona tizim talablari tufayli Free Fire mintaqada koʻpchilikni tashkil qiladigan arzon smartfonlarda xit boʻldi.</p>
<p><strong>Bizda toʻldirish mumkin:</strong> <a href="https://yupay.uz/uz/store/free-fire">olmoslar, toʻplamlar va obuna</a> — oʻyin ID raqami boʻyicha.</p>
<h3>3. Standoff 2</h3>
<p>Klassik taktik otishmalar ruhidagi dinamik jamoaviy shuter. 5 ga 5 format, bomba qoʻyish, raundlar iqtisodi. Standoff 2 ayniqsa skinlari va ular atrofidagi faol savdo uchun, shuningdek oʻrtacha jihozda ham ravon ishlagani uchun yoqtiriladi.</p>
<p><strong>Bizda toʻldirish mumkin:</strong> <a href="https://yupay.uz/uz/store/standoff-2">Gold</a> — promokod tarzida keladi, oʻyin ID raqamini koʻrsatish shart emas.</p>
<h3>4. Mobile Legends: Bang Bang</h3>
<p>Taxminan 10-15 daqiqalik matchlarga ega 5 ga 5 formatidagi MOBA. Yangi boshlovchilar uchun tushunarli, ammo mahorat shifti baland. Mobile Legends Janubi-Sharqiy Osiyoda yirik turnirlar yigʻadi va bu raqobat ruhi oʻzbek jamoasida ham yaxshi seziladi.</p>
<p><strong>Bizda toʻldirish mumkin:</strong> <a href="https://yupay.uz/uz/store/mobile-legends">olmoslar, propusklar va toʻplamlar</a> — oʻyin ID raqami boʻyicha. Agar akkaunt rossiya regionida boʻlsa, <a href="https://yupay.uz/uz/store/mobile-legends-ru">MLBB RU sahifasini</a> tanlang: region toʻlovdan oldin tanlanadi va keyin oʻzgartirilmaydi.</p>
<h3>5. Genshin Impact</h3>
<p>Ochiq dunyo, anime uslubi va gacha mexanikasi orqali qahramonlarni rivojlantirish tizimi. Genshin Impact dunyodagi eng daromadli mobil loyihalardan biri boʻlib qolmoqda va yangi qahramonlarga sarflashga tayyor koʻp millionlik auditoriya yigʻgan. Yangi boshlovchilar uchun alohida <a href="https://yupay.uz/uz/blog/genshin-impact">Genshin Impact qoʻllanmamiz</a> bor.</p>
<p><strong>Bizda toʻldirish mumkin:</strong> <a href="https://yupay.uz/uz/store/genshin-impact">Yaratilish Kristallari va Boʻsh oy marhamati</a>.</p>
<h3>6. Honkai: Star Rail</h3>
<p>Genshin ijodkorlaridan syujet va qahramon toʻplashga urgʻu bergan navbatma-navbat RPG. Kuchliroq qurilma talab qiladi, ammo kinematografik taqdimot va chuqur jamoa tizimi bilan mukofotlaydi. Doimiy onlayn taranglikdan holi, oʻylab oʻynashni yoqtiradiganlar uchun yaxshi tanlov.</p>
<p><strong>Bizda toʻldirish mumkin:</strong> <a href="https://yupay.uz/uz/store/honkai-star-rail">Qadimgi tushlar mohiyati va Ekspress-taʼminot</a>.</p>
<h3>7. Roblox</h3>
<p>Bu oʻyindan koʻra millionlab foydalanuvchi olamlariga ega platforma: poygalardan simulyatorlar va xorrorlargacha. Roblox ayniqsa yosh auditoriya orasida mashhur va oʻyinchilarning oʻzi yaratadigan cheksiz yangi kontent hisobiga ushlanib turadi.</p>
<p><strong>Bizda toʻldirish mumkin:</strong> <a href="https://yupay.uz/uz/store/roblox">Robux global toʻldirish kartalari bilan</a> — kod oʻz akkauntingizda faollashtiriladi.</p>
<h3>8. Delta Force</h3>
<p>Keng koʻlamli janglar va yirik harbiy operatsiyalar ruhidagi rejimlarga ega zamonaviy taktik shuter. Delta Force klassik jamoaviy shuterlarda oʻsgan va battle royaledan koʻra jiddiyroq taktikani istaydiganlarni jalb qiladi.</p>
<p><strong>Bizda toʻldirish mumkin:</strong> <a href="https://yupay.uz/uz/store/delta-force">Delta Coins va Season Pass</a>.</p>
<h3>9. Arena Breakout</h3>
<p>Qattiqqoʻl ekstrakshn-shuter: zonaga kirasiz, lut yigʻasiz va butun jihozingizni yoʻqotish xavfi ostida tirik chiqishga harakat qilasiz. Arena Breakout qurol realizmi va oddiy arkada otishmalarda boʻlmagan taranglik uchun qadrlanadi.</p>
<p><strong>Bizda toʻldirish mumkin:</strong> <a href="https://yupay.uz/uz/store/arena-breakout">Bonds, Battle Pass va toʻplamlar</a>. PC versiyasining alohida sahifasi bor — <a href="https://yupay.uz/uz/store/arena-breakout-infinite">Arena Breakout: Infinite</a>.</p>
<h3>10. Blood Strike</h3>
<p>Battle royale va jamoaviy rejimlarni birlashtirgan tez va yengil shuter. Blood Strike keng doiradagi qurilmalarda uzoq yuklanishsiz ishga tushadigan qilib yaratilgan, bu esa uni qisqa sessiyalar uchun qulay qiladi.</p>
<p><strong>Bizda toʻldirish mumkin:</strong> <a href="https://yupay.uz/uz/store/blood-strike">oltin va propusklar</a>.</p>
<h2>Donat tizimi va oʻyin ichidagi valyutaga ega oʻyinlar</h2>
<p>Roʻyxatdagi deyarli barcha loyihalar kirishda bepul va oʻyin ichidagi xaridlardan daromad qiladi. Bu tasodif emas: aynan donatli free-to-play modeli mobil geymingga yuqorida aytilgan yillik daromadning asosiy qismini keltirgan.</p>
<p>Har bir oʻyinning oʻz valyutasi bor. PUBG Mobileda bu UC, Free Fireda olmoslar, Mobile Legendsda olmoslar, Genshin Impact va Honkai: Star Railda gacha aylantirish uchun kristallar, Robloxda robukslar. Bu valyutaga skinlar, jangovar propusklar, yangi qahramonlar va kosmetika sotib olinadi.</p>
<p>Ikki xil xarajat orasidagi farqni tushunish muhim. Shuterlarda donat koʻpincha kosmetik boʻlib, balansga deyarli taʼsir qilmaydi. Genshin kabi gacha oʻyinlarida esa valyuta yangi qahramon va qurol olish uchun kerak, shuning uchun bu yerda xaridlar sezilarliroq. Valyutani qayerdan olish foydaliroq ekanini bilmoqchi boʻlsangiz, <a href="https://yupay.uz/uz/blog/ozbekistonda-donat-sotib-olish">Oʻzbekistonda donat sotib olish</a> maqolamizni oʻqing.</p>
<h2>Qurilma va internetga talablar</h2>
<p>Oʻzbek oʻyinchilari uchun yaxshi xabar: top oʻyinlarning koʻpchiligi talabchan emas. PUBG Mobile, Free Fire va Standoff 2 kabi raqobatli shuterlar uchun 4-6 GB operativ xotira va oʻrtacha protsessorli smartfon yetarli. Free Fire kuchsiz telefonlar uchun maxsus optimallashtirilgan, shuning uchun deyarli hamma qurilmada ishlaydi.</p>
<p>Ogʻirroq loyihalar koʻproq resurs soʻraydi. Genshin Impact va Honkai: Star Railni 6-8 GB operativ xotira va yaxshi grafikali qurilmada oʻynash qulayroq, aks holda boy sahnalarda kadrlar tushishi mumkin. Roblox oʻzi talabchan emas, ammo ayrim foydalanuvchi olamlari telefonni kuchliroq yuklashi mumkin.</p>
<p>Internet haqida alohida gap. Onlayn shuterlar uchun yuklab olish tezligidan koʻra ulanish barqarorligi va ping muhim. Qulay oʻyin taxminan 60-80 ms kechikishli barqaror 4G yoki Wi-Fidan boshlanadi. Yakka tartibdagi RPGlarga oddiy mobil internet ham yetarli: u yerda bir zumlik reaksiya emas, aloqaning oʻzi muhim.</p>
<p>Oʻrnatishdan oldingi qisqa roʻyxat:</p>
<ul>
<li>Boʻsh joy: oʻyinga qarab 3 dan 15 GB gacha.</li>
<li>Operativ xotira: kamida 4 GB, ogʻir loyihalar uchun 6-8 GB.</li>
<li>Ulanish: onlayn rejimlar uchun barqaror 4G yoki Wi-Fi.</li>
<li>Quvvat: ogʻir oʻyinlar batareyani tez tugatadi, powerbank yoningizda boʻlsin.</li>
</ul>
<h2>Sevimli oʻyiningizni qanday tez toʻldirish mumkin</h2>
<p>Oʻzbekistonda oʻyin valyutasini qoʻshishning eng qulay yoʻli — mahalliy usullar bilan soʻmda, komissiyasiz toʻlash. Yupay aynan shunday ishlaydi: oʻyinni tanlaysiz, kerakli valyuta paketini koʻrsatasiz va toʻlovni tasdiqlaysiz, hisobga oʻtish esa bir necha daqiqada avtomatik boʻladi.</p>
<p>Bu ikkita odatiy bosh ogʻriqni olib tashlaydi. Birinchisi: dollarda toʻlash uchun xorijiy karta yoki aylanma yoʻllar izlash shart emas. Ikkinchisi: sotuvchini qoʻlda kutish kerak emas, chunki jarayon avtomatlashtirilgan. Bu roʻyxatdagi oʻnta oʻyinning hammasida sahifa bor: <a href="https://yupay.uz/uz/store/pubg-mobile">PUBG Mobile</a>, <a href="https://yupay.uz/uz/store/free-fire">Free Fire</a>, <a href="https://yupay.uz/uz/store/standoff-2">Standoff 2</a>, <a href="https://yupay.uz/uz/store/mobile-legends">Mobile Legends</a>, <a href="https://yupay.uz/uz/store/genshin-impact">Genshin Impact</a>, <a href="https://yupay.uz/uz/store/honkai-star-rail">Honkai: Star Rail</a>, <a href="https://yupay.uz/uz/store/roblox">Roblox</a>, <a href="https://yupay.uz/uz/store/delta-force">Delta Force</a>, <a href="https://yupay.uz/uz/store/arena-breakout">Arena Breakout</a> va <a href="https://yupay.uz/uz/store/blood-strike">Blood Strike</a>.</p>
<p>Amallar tartibi juda oddiy:</p>
<ol>
<li>Kerakli oʻyin sahifasini <a href="https://yupay.uz/uz/store">katalogdan</a> oching.</li>
<li>Valyuta paketini yoki obunani tanlang.</li>
<li>Agar talab qilinsa, oʻyin ID raqamini kiriting.</li>
<li>Odatdagi usulda soʻmda toʻlang.</li>
<li>Avtomatik hisobga oʻtishini kuting.</li>
</ol>
<p>Agar boʻsh oqshomni nimaga sarflashni endi tanlayotgan boʻlsangiz, roʻyxatdagi istalgan bepul shuterdan boshlang: yuklab olish hech narsa turmaydi, asoslarini esa bitta matchda tushunib olish mumkin. Qahramonni kuchaytirish yoki yangi skin olish istagi paydo boʻlganda esa, soʻmda toʻldirish matchning oʻzidan kamroq vaqt oladi.</p>$body$,
  'Oʻzbekiston uchun 2026 yilning eng yaxshi 10 ta mobil oʻyini',
  '2026 yilning eng yaxshi mobil oʻyinlari: har biri nima haqda, qanday qurilma talab qiladi va '
    || 'ularni soʻmda komissiyasiz qanday tez toʻldirish mumkin.'
)
ON CONFLICT (post_id, locale) DO UPDATE
   SET slug = EXCLUDED.slug, title = EXCLUDED.title, excerpt = EXCLUDED.excerpt,
       body_html = EXCLUDED.body_html, seo_title = EXCLUDED.seo_title,
       seo_description = EXCLUDED.seo_description;

-- ----------------------------------------------------------------- FAQs ------

DELETE FROM blog_post_faqs WHERE post_id = :post_id AND locale IN ('en', 'uz');

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer)
VALUES
  (gen_random_uuid(), :post_id, 'en', 0,
   'Which mobile games are most popular in Uzbekistan in 2026?',
   'PUBG Mobile, Free Fire, Standoff 2, Mobile Legends and Genshin Impact lead among Uzbek players. '
   || 'They are free to enter, run on weaker devices and have an active community inside the country.'),
  (gen_random_uuid(), :post_id, 'en', 1,
   'What phone do modern mobile games need?',
   'For shooters like PUBG Mobile and Standoff 2, a phone with 4-6 GB of RAM is enough. For heavier '
   || 'titles like Genshin Impact and Honkai: Star Rail, aim for 6-8 GB and a strong processor.'),
  (gen_random_uuid(), :post_id, 'en', 2,
   'How do I top up a mobile game in Uzbekistan?',
   'Through Yupay you can pay for in-game currency in soum by local payment methods, with no fee. '
   || 'Pick the game, choose the pack and confirm the payment; crediting happens automatically.'),
  (gen_random_uuid(), :post_id, 'en', 3,
   'Do mobile games need fast internet?',
   'For online shooters, connection stability matters more than speed alone. Comfortable play starts '
   || 'at a stable 4G or Wi-Fi with 60-80 ms ping. Single-player RPGs run fine on ordinary mobile internet.'),
  (gen_random_uuid(), :post_id, 'uz', 0,
   'Oʻzbekistonda 2026 yilda qaysi mobil oʻyinlar eng mashhur?',
   'Oʻzbek oʻyinchilari orasida PUBG Mobile, Free Fire, Standoff 2, Mobile Legends va Genshin Impact '
   || 'yetakchilik qiladi. Ular bepul, kuchsiz qurilmalarni qoʻllab-quvvatlaydi va mamlakat ichida '
   || 'faol jamoaga ega.'),
  (gen_random_uuid(), :post_id, 'uz', 1,
   'Zamonaviy mobil oʻyinlar uchun qanday smartfon kerak?',
   'PUBG Mobile va Standoff 2 kabi shuterlar uchun 4-6 GB operativ xotirali telefon yetarli. Genshin '
   || 'Impact va Honkai: Star Rail kabi ogʻir loyihalar uchun 6-8 GB va kuchli protsessor maʼqul.'),
  (gen_random_uuid(), :post_id, 'uz', 2,
   'Oʻzbekistonda mobil oʻyinni qanday toʻldirish mumkin?',
   'Yupay orqali oʻyin valyutasini mahalliy toʻlov usullari bilan soʻmda, komissiyasiz toʻlash mumkin. '
   || 'Oʻyinni tanlab, kerakli paketni koʻrsatib, toʻlovni tasdiqlash yetarli — hisobga oʻtish avtomatik.'),
  (gen_random_uuid(), :post_id, 'uz', 3,
   'Mobil oʻyinlar uchun tezkor internet kerakmi?',
   'Onlayn shuterlar uchun tezlikdan koʻra ulanish barqarorligi muhim. Qulay oʻyin 60-80 ms pingli '
   || 'barqaror 4G yoki Wi-Fidan boshlanadi. Yakka RPGlarga oddiy mobil internet ham yetadi.');

COMMIT;
