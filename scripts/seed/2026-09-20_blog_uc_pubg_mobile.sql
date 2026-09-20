-- Blog post «Как получить UC в PUBG Mobile: способы для игроков» (draft) —
-- ru corrections + en and uz translations with their FAQs.
--
-- Post id 01a0bc89-ede3-7d01-a812-5d812f2975bd, slug `uc-pubg-mobile`,
-- imported from Bunzy 2026-09-20 with ru only.
--
-- **The package table listed packs that do not exist.** It printed
-- "60 / 300 (+бонус) / 600 (+бонус) / 1500 (+бонус) / 3000 (+бонус) /
-- 6000 (+бонус) UC" with qualitative columns ("небольшой", "средний",
-- "заметный"). Those are the *base* amounts the game prints on the tile; the
-- amount that actually lands on the account is base + bonus. Our own live
-- ladder — 60, 325, 660, 985, 1320, 1800, 2460, 3850, 5650, 8100, 11950,
-- 16200 UC — is the totals, so a reader comparing the article against the
-- store page finds not one matching number above 60. The table is replaced
-- with base / bonus / total, which is both correct and the thing that
-- explains the discrepancy a reader will otherwise hit. Bonuses are the
-- official ladder: 300+25, 600+60, 1500+300, 3000+850, 6000+2100.
--
-- Two smaller corrections:
--
--   * "оплачиваете привычным способом" names no method. Production answers
--     click, click_miniapp, payme, uzum, paynet and wallet on
--     `GET /api/v1/payments/providers`, all `active` — so the article says
--     Click, Payme, Uzum, Paynet, as the other blog posts do.
--   * The post linked two blog articles but never the page it is about.
--     `yupay.uz/store/pubg-mobile` is live; it is now linked from the price
--     section and from the closing paragraph.
--
-- All four link targets were checked (200) in every locale used below.
--
-- Idempotent: the ru updates are regexp replacements that no longer match
-- once applied, and the inserts are ON CONFLICT DO UPDATE.
--
-- Apply:
--   docker exec -i yupay-prod-postgres-1 sh -lc \
--     'psql -U $POSTGRES_USER -d $POSTGRES_DB -v ON_ERROR_STOP=1' \
--     < scripts/seed/2026-09-20_blog_uc_pubg_mobile.sql

\set post_id '''01a0bc89-ede3-7d01-a812-5d812f2975bd'''

BEGIN;

-- --------------------------------------------------------------- ru body ----

-- The lead-in promised "примерно так", which is what a table of invented
-- numbers has to say. With real numbers it can say what it actually is, and
-- name the base/total split the reader is about to see.
UPDATE blog_post_translations
   SET body_html = replace(
         body_html,
         '<p>Пакеты UC устроены по принципу лестницы: чем больше объём, тем выше бонус сверху '
         || 'базовой суммы. Структура выглядит примерно так:</p>',
         '<p>Пакеты UC устроены по принципу лестницы: чем больше объём, тем выше бонус сверху '
         || 'базовой суммы. В игре и на Midasbuy пакет подписан базовой суммой, а бонус '
         || 'добавляется при зачислении — на счёт приходит итог:</p>')
 WHERE post_id = :post_id AND locale = 'ru';

UPDATE blog_post_translations
   SET body_html = regexp_replace(body_html, '<table>.*</table>', $html$<table>
<thead>
<tr>
<th>Пакет в игре</th>
<th>Бонус</th>
<th>Придёт на счёт</th>
</tr>
</thead>
<tbody>
<tr>
<td>60 UC</td>
<td>нет</td>
<td>60 UC</td>
</tr>
<tr>
<td>300 UC</td>
<td>+25</td>
<td>325 UC</td>
</tr>
<tr>
<td>600 UC</td>
<td>+60</td>
<td>660 UC</td>
</tr>
<tr>
<td>1500 UC</td>
<td>+300</td>
<td>1800 UC</td>
</tr>
<tr>
<td>3000 UC</td>
<td>+850</td>
<td>3850 UC</td>
</tr>
<tr>
<td>6000 UC</td>
<td>+2100</td>
<td>8100 UC</td>
</tr>
</tbody>
</table>$html$, 'gs')
 WHERE post_id = :post_id AND locale = 'ru';

UPDATE blog_post_translations
   SET body_html = replace(
         body_html,
         '<p>Точный размер бонуса и цена меняются в зависимости от региона, акций и текущего '
         || 'сезона, поэтому конкретные проценты лучше проверять в момент покупки. Общий принцип '
         || 'стабилен: единица UC в крупном пакете обходится дешевле, чем в мелком.</p>',
         '<p>Бонус растёт вместе с объёмом: у пакета на 300 UC это +8%, у 1500 UC уже +20%, '
         || 'а у 6000 UC — +35%. Поэтому единица UC в крупном пакете обходится дешевле, чем в '
         || 'мелком. Цена зависит от региона и акций, так что её стоит сверять в момент покупки: '
         || 'актуальные номиналы и цены в сумах видно на '
         || '<a href="https://yupay.uz/store/pubg-mobile">странице пополнения PUBG Mobile</a>. '
         || 'Кроме базовой лестницы там есть промежуточные пакеты 985, 1320, 2460, 5650, 11950 '
         || 'и 16200 UC.</p>')
 WHERE post_id = :post_id AND locale = 'ru';

UPDATE blog_post_translations
   SET body_html = replace(
         body_html,
         'выбираете пакет UC и оплачиваете привычным способом.',
         'выбираете пакет UC и оплачиваете через Click, Payme, Uzum или Paynet — картой Uzcard '
         || 'или Humo.')
 WHERE post_id = :post_id AND locale = 'ru';

UPDATE blog_post_translations
   SET body_html = replace(
         body_html,
         'самый быстрый путь это оплата в сумах по игровому ID через Yupay, без комиссии и без '
         || 'передачи пароля от аккаунта.',
         'самый быстрый путь это оплата в сумах по игровому ID на '
         || '<a href="https://yupay.uz/store/pubg-mobile">странице пополнения PUBG Mobile</a>, '
         || 'без комиссии и без передачи пароля от аккаунта.')
 WHERE post_id = :post_id AND locale = 'ru';

-- ---------------------------------------------------------------------- en ---

INSERT INTO blog_post_translations (post_id, locale, slug, title, excerpt, body_html,
                                    seo_title, seo_description)
VALUES (
  :post_id,
  'en',
  'how-to-get-uc-pubg-mobile',
  'How to get UC in PUBG Mobile: the routes that are safe',
  'How to get UC in PUBG Mobile safely: the official top-up routes, what the packs really '
    || 'contain, how to keep the account out of trouble and where the savings are.',
$body$<h2>The short version</h2>
<ul>
<li>UC (Unknown Cash) is PUBG Mobile's premium currency. You cannot earn it in a match — it is only ever bought with real money.</li>
<li>The official routes are the in-game shop and Tencent's own Midasbuy platform, alongside a trusted local service such as Yupay.</li>
<li>Bigger packs carry a bigger bonus per unit, so one large pack beats a handful of small ones.</li>
<li>Buying UC from unauthorised resellers risks losing the currency and the account, under PUBG Mobile's own rules.</li>
</ul>
<p>UC cannot be earned in PUBG Mobile: the currency is bought with real money through the in-game shop, the official Midasbuy platform or a trusted local service. Below: what UC is, how to get UC in PUBG Mobile without putting the account at risk, how the packs differ and how not to overpay.</p>
<p>This is an explainer, not a pitch. If you play from Uzbekistan, there is a practical note on paying in soum at the end.</p>
<h2>What UC is and what it buys</h2>
<p>UC stands for Unknown Cash. It is PUBG Mobile's premium currency, and no amount of ordinary matches or daily missions will accumulate it. The only way to get UC is to buy it.</p>
<p>UC goes on cosmetics and seasonal content:</p>
<ul>
<li><strong>Royale Pass (Elite Pass)</strong> — the seasonal pass, with its own rewards, missions and outfits.</li>
<li><strong>Skins</strong> for weapons, characters, vehicles and parachutes.</li>
<li><strong>Crates and draws</strong> — premium crates and lucky spins for rare items.</li>
<li><strong>Utility items</strong> — rename cards, room cards and bundles.</li>
</ul>
<p>Worth stating plainly: UC buys no combat advantage. Everything it unlocks affects how things look and how convenient they are, never damage or stats. Getting UC is a question of style and collecting, not of winning the match.</p>
<p>PUBG Mobile remains one of the largest mobile games in the world. Udonis puts it at more than <a href="https://www.blog.udonis.co/mobile-marketing/mobile-games/pubg-mobile-player-count">1.2 billion downloads and around 112.9 million monthly active players</a> as of mid-2025. An audience that size is why safe UC top-ups matter to millions of people, Central Asia included.</p>
<h2>How to get UC in PUBG Mobile: the official routes</h2>
<p>There are two official channels, plus one convenient local option for Uzbekistan.</p>
<h3>The in-game shop</h3>
<p>The obvious route is the purchase section inside the game. Payment runs through Google Play, the App Store or whatever your device has built in. It is simple; the catch is that not every international card and payment method works in Uzbekistan, and the price is not shown in soum.</p>
<h3>The Midasbuy platform</h3>
<p>Midasbuy is the official top-up platform run by Tencent and Level Infinite. It is linked from the game's own purchase screen, so it is not a third-party middleman. You enter your player ID, pick a UC pack and pay. The UC lands on the account without you handing over a login or a password.</p>
<h3>Paying locally, in soum</h3>
<p>Players in Uzbekistan would usually rather pay by local methods and see the price in soum, with no conversion and no hidden fees. That is where Yupay helps: you enter your PUBG Mobile player ID, pick a UC pack and pay through Click, Payme, Uzum or Paynet — with an Uzcard or Humo card. The top-up runs by ID and never asks for the account password, so access to your profile stays yours alone. How fast, fee-free game top-ups work in general is covered in a <a href="https://yupay.uz/en/blog/online-game-top-ups-uzbekistan">separate article on online game top-ups</a>.</p>
<p>One safety rule covers every route: a legitimate service works from your player ID and never asks for a login and password.</p>
<h2>What the UC packs actually contain</h2>
<p>UC packs work as a ladder: the larger the pack, the bigger the bonus on top of the base amount. In the game and on Midasbuy the tile is labelled with the base amount, and the bonus is added on delivery — what reaches the account is the total:</p>
<table>
<thead>
<tr>
<th>Pack in game</th>
<th>Bonus</th>
<th>Lands on the account</th>
</tr>
</thead>
<tbody>
<tr>
<td>60 UC</td>
<td>none</td>
<td>60 UC</td>
</tr>
<tr>
<td>300 UC</td>
<td>+25</td>
<td>325 UC</td>
</tr>
<tr>
<td>600 UC</td>
<td>+60</td>
<td>660 UC</td>
</tr>
<tr>
<td>1500 UC</td>
<td>+300</td>
<td>1800 UC</td>
</tr>
<tr>
<td>3000 UC</td>
<td>+850</td>
<td>3850 UC</td>
</tr>
<tr>
<td>6000 UC</td>
<td>+2100</td>
<td>8100 UC</td>
</tr>
</tbody>
</table>
<p>The bonus grows with the volume: +8% on the 300 UC pack, +20% by 1500 UC, +35% at 6000 UC. That is why a unit of UC costs less in a large pack than in a small one. Prices move with the region and with promotions, so they are worth checking at the moment of purchase — the current denominations and their prices in soum are on the <a href="https://yupay.uz/en/store/pubg-mobile">PUBG Mobile top-up page</a>. Besides the base ladder it carries the in-between packs: 985, 1320, 2460, 5650, 11950 and 16200 UC.</p>
<p>If you are comparing services and want to know where a top-up works out cheaper for Uzbekistan, there is a separate breakdown in the article on <a href="https://yupay.uz/en/blog/buy-game-top-ups-in-uzbekistan">buying game top-ups in Uzbekistan</a>.</p>
<h2>How to keep the account from being banned</h2>
<p>The biggest risk in buying UC is not the price, it is unauthorised resellers — sellers who promise cheap UC but obtain it illegitimately, or ask you for your account credentials.</p>
<p>Under PUBG Mobile's own rules the game authorises no private individuals and no third-party platforms as intermediaries. The penalties are hard: currency and items obtained illegitimately are confiscated, and the offending account is banned. Repeat offences are punished harder.</p>
<p>Plain fraud is its own risk. An unofficial seller can:</p>
<ul>
<li>take the payment and deliver no UC;</li>
<li>take over the account, if you handed over a login and password;</li>
<li>compromise your card details.</li>
</ul>
<p>Three rules keep you out of it:</p>
<ol>
<li>Buy only through the official shop, Midasbuy or a trusted local service that works from your player ID.</li>
<li>Never hand over your account login and password for a top-up.</li>
<li>Steer clear of offers priced well below the official rate: UC that cheap usually has an illegitimate source.</li>
</ol>
<h2>Where the savings actually are</h2>
<p>Saving on UC is not about hunting suspicious discounts; it is about picking the right pack at the right moment.</p>
<ul>
<li><strong>Take the Royale Pass if you play regularly.</strong> The Elite Pass returns part of its cost in rewards and in-game currency, so for an active player it pays for itself better than one-off skin purchases.</li>
<li><strong>Buy large packs if you plan to spend.</strong> The bonus per unit grows with volume, so one big pack usually beats several small ones.</li>
<li><strong>Wait for seasonal events.</strong> Anniversaries and holiday promotions often add bonus UC on top of the usual packs.</li>
<li><strong>Pay in your own currency.</strong> Paying in soum through a local service removes the quiet losses to conversion and international payment fees.</li>
</ul>
<p>If PUBG Mobile is not your only game, the same principles carry over: a larger pack, a seasonal pass and payment in your own currency save money in most mobile games.</p>
<h2>Where to start</h2>
<p>Work out how much UC you actually need for the coming season — the Royale Pass alone, or skins and crates as well. Then pick one official or trusted local channel, enter your player ID and buy the pack that covers the plan. For players in Uzbekistan the fastest route is paying in soum by player ID on the <a href="https://yupay.uz/en/store/pubg-mobile">PUBG Mobile top-up page</a>, with no fee and no account password to hand over.</p>$body$,
  'How to get UC in PUBG Mobile: the routes that are safe',
  'How to get UC in PUBG Mobile safely: the official top-up routes, what the packs really '
    || 'contain, how to keep the account out of trouble and where the savings are.'
)
ON CONFLICT (post_id, locale) DO UPDATE
   SET slug = EXCLUDED.slug,
       title = EXCLUDED.title,
       excerpt = EXCLUDED.excerpt,
       body_html = EXCLUDED.body_html,
       seo_title = EXCLUDED.seo_title,
       seo_description = EXCLUDED.seo_description;

-- ---------------------------------------------------------------------- uz ---

INSERT INTO blog_post_translations (post_id, locale, slug, title, excerpt, body_html,
                                    seo_title, seo_description)
VALUES (
  :post_id,
  'uz',
  'pubg-mobile-uc-olish',
  'PUBG Mobileda UC qanday olinadi: oʻyinchilar uchun yoʻllar',
  'PUBG Mobileda UC ni xavfsiz olish: rasmiy toʻldirish yoʻllari, paketlar tarkibi, akkauntni '
    || 'himoya qilish va tejash boʻyicha maslahatlar.',
$body$<h2>Asosiysi</h2>
<ul>
<li>UC (Unknown Cash) — PUBG Mobilening premium valyutasi. Uni jangda ishlab topib boʻlmaydi, faqat haqiqiy pulga sotib olinadi.</li>
<li>Rasmiy yoʻllar — oʻyin ichidagi doʻkon va Tencentning Midasbuy platformasi, shuningdek Yupay kabi ishonchli mahalliy servis.</li>
<li>Yirik paketlarda birlikka tushadigan bonus koʻproq, shuning uchun bitta katta paket bir nechta kichigidan foydaliroq.</li>
<li>UC ni ruxsatsiz vositachilardan sotib olish valyutani yoʻqotish va PUBG Mobile qoidalari boʻyicha akkaunt bloklanishi bilan tugashi mumkin.</li>
</ul>
<p>PUBG Mobileda UC ni jangda ishlab topib boʻlmaydi: bu valyuta faqat haqiqiy pulga — oʻyin ichidagi doʻkon, rasmiy Midasbuy platformasi yoki ishonchli mahalliy servis orqali sotib olinadi. Quyida UC nima ekanini, akkauntni xavf ostiga qoʻymasdan uni qanday olishni, paketlar farqini va ortiqcha toʻlamaslik yoʻlini koʻrib chiqamiz.</p>
<p>Maqola axborot xarakterida. Biz mexanikani tushuntiramiz, xarid qilishga undamaymiz. Agar Oʻzbekistondan oʻynasangiz, oxirida soʻmda toʻlash boʻyicha amaliy maslahat bor.</p>
<h2>UC nima va u nimaga sarflanadi</h2>
<p>UC — Unknown Cash soʻzlarining qisqartmasi. Bu PUBG Mobilening premium valyutasi boʻlib, uni oddiy matchlar yoki kunlik topshiriqlar hisobiga toʻplab boʻlmaydi. UC ni olishning yagona yoʻli — haqiqiy pulga sotib olish.</p>
<p>UC kosmetika va mavsumiy kontentga sarflanadi:</p>
<ul>
<li><strong>Royale Pass (Elite Pass)</strong> — eksklyuziv mukofotlar, missiyalar va obrazlar bilan mavsumiy propusk.</li>
<li><strong>Skinlar</strong> — qurol, personaj, transport va parashyutlar uchun.</li>
<li><strong>Keyslar va oʻyinlar</strong> — nodir buyumlar uchun premium quticha va omad gʻildiraklari.</li>
<li><strong>Xizmat buyumlari</strong> — nomni oʻzgartirish kartalari, xona kartalari va toʻplamlar.</li>
</ul>
<p>Muhim jihat: UC jangovar ustunlik bermaydi. Bu valyutaga olinadigan hamma narsa faqat tashqi koʻrinish va qulaylikka taʼsir qiladi, zarar yoki xarakteristikalarga emas. Shuning uchun UC olish — uslub va kolleksiya masalasi, matchda gʻalaba masalasi emas.</p>
<p>PUBG Mobile dunyodagi eng ommaviy mobil oʻyinlardan biri boʻlib qolmoqda. Udonis tahliliga koʻra, 2025-yil oʻrtalarida oʻyinning <a href="https://www.blog.udonis.co/mobile-marketing/mobile-games/pubg-mobile-player-count">1,2 milliarddan ortiq yuklab olinishi va oyiga taxminan 112,9 million faol oʻyinchisi</a> bor. Shunday auditoriya UC ni xavfsiz toʻldirish savoli nega millionlab odamni, jumladan Markaziy Osiyodagilarni ham qiziqtirishini tushuntiradi.</p>
<h2>PUBG Mobileda UC qanday olinadi: rasmiy yoʻllar</h2>
<p>Ikkita rasmiy kanal va Oʻzbekiston uchun bitta qulay mahalliy variant bor.</p>
<h3>Oʻyin ichidagi doʻkon</h3>
<p>Eng koʻrinarli yoʻl — toʻgʻridan-toʻgʻri oʻyindagi xaridlar boʻlimi. Toʻlov Google Play, App Store yoki qurilmaning ichki toʻlov usullari orqali oʻtadi. Ustunligi — soddaligi, kamchiligi — Oʻzbekistonda hamma xalqaro karta va toʻlov usuli ishlamaydi, narx esa soʻmda koʻrsatilmaydi.</p>
<h3>Midasbuy platformasi</h3>
<p>Midasbuy — Tencent va Level Infinitening rasmiy toʻldirish platformasi. U oʻyinning xaridlar oynasida koʻrsatilgan, yaʼni begona vositachi emas. Siz oʻyin ID raqamingizni kiritasiz, UC paketini tanlaysiz va toʻlaysiz. UC login va parolni bermasdan hisobga tushadi.</p>
<h3>Soʻmda mahalliy toʻldirish</h3>
<p>Oʻzbekistondagi oʻyinchilar uchun mahalliy usullar bilan toʻlash va narxni darhol soʻmda koʻrish qulayroq — konvertatsiyasiz va yashirin komissiyasiz. Bunda Yupay yordam beradi: PUBG Mobile oʻyin ID raqamini koʻrsatasiz, UC paketini tanlaysiz va Click, Payme, Uzum yoki Paynet orqali — Uzcard yoki Humo kartasi bilan toʻlaysiz. Toʻldirish ID boʻyicha avtomatik oʻtadi, akkaunt paroli soʻralmaydi, shuning uchun profilingizga kirish faqat sizda qoladi. Oʻyinlarni tez va komissiyasiz toʻldirish umuman qanday ishlashi haqida alohida <a href="https://yupay.uz/uz/blog/onlayn-oyin-toldirish">oʻyinlarni onlayn toʻldirish maqolasida</a> batafsil yozganmiz.</p>
<p>Xavfsizlikning asosiy qoidasi hamma yoʻl uchun bir xil: qonuniy servis oʻyin ID boʻyicha ishlaydi va hech qachon login bilan parolni soʻramaydi.</p>
<h2>UC paketlari tarkibida nima bor</h2>
<p>UC paketlari zinapoya tamoyili boʻyicha tuzilgan: hajm qancha katta boʻlsa, asosiy summa ustiga qoʻshiladigan bonus shuncha koʻp. Oʻyinda va Midasbuyda paket asosiy summa bilan nomlanadi, bonus esa hisobga oʻtkazishda qoʻshiladi — hisobga yakuniy miqdor tushadi:</p>
<table>
<thead>
<tr>
<th>Oʻyindagi paket</th>
<th>Bonus</th>
<th>Hisobga tushadi</th>
</tr>
</thead>
<tbody>
<tr>
<td>60 UC</td>
<td>yoʻq</td>
<td>60 UC</td>
</tr>
<tr>
<td>300 UC</td>
<td>+25</td>
<td>325 UC</td>
</tr>
<tr>
<td>600 UC</td>
<td>+60</td>
<td>660 UC</td>
</tr>
<tr>
<td>1500 UC</td>
<td>+300</td>
<td>1800 UC</td>
</tr>
<tr>
<td>3000 UC</td>
<td>+850</td>
<td>3850 UC</td>
</tr>
<tr>
<td>6000 UC</td>
<td>+2100</td>
<td>8100 UC</td>
</tr>
</tbody>
</table>
<p>Bonus hajm bilan birga oʻsadi: 300 UC paketida u +8%, 1500 UC da allaqachon +20%, 6000 UC da esa +35%. Shuning uchun yirik paketda bir birlik UC kichigiga qaraganda arzonroq tushadi. Narx mintaqa va aksiyalarga bogʻliq, shuning uchun uni xarid paytida tekshirgan maʼqul: joriy nominallar va soʻmdagi narxlar <a href="https://yupay.uz/uz/store/pubg-mobile">PUBG Mobile toʻldirish sahifasida</a> koʻrinadi. Asosiy zinapoyadan tashqari u yerda oraliq paketlar ham bor: 985, 1320, 2460, 5650, 11950 va 16200 UC.</p>
<p>Agar turli platformalarni solishtirib, Oʻzbekiston uchun donat qayerda foydaliroq chiqishini bilmoqchi boʻlsangiz, alohida tahlil <a href="https://yupay.uz/uz/blog/ozbekistonda-donat-sotib-olish">Oʻzbekistonda donat sotib olish haqidagi maqolada</a> bor.</p>
<h2>Akkaunt bloklanishidan qanday qochish kerak</h2>
<p>UC sotib olishdagi eng katta xavf — narx emas, ruxsatsiz vositachilar. Gap arzon UC vaʼda qiladigan, lekin valyutani noqonuniy yoʻl bilan oladigan yoki sizdan akkauntga kirish maʼlumotlarini soʻraydigan sotuvchilar haqida.</p>
<p>PUBG Mobilening rasmiy qoidalariga koʻra oʻyin oraliq xaridlar uchun jismoniy shaxslarni ham, begona platformalarni ham vakil qilib tayinlamaydi. Qoidabuzarlik uchun choralar qattiq: noqonuniy yoʻl bilan olingan valyuta va buyumlar musodara qilinadi, qoidabuzarning akkaunti esa bloklanadi. Takroriy holatlarda jazo ogʻirlashadi.</p>
<p>Firibgarlikni ham alohida yodda tutish kerak. Norasmiy sotuvchilar:</p>
<ul>
<li>toʻlovni olib, UC ni oʻtkazmasligi;</li>
<li>agar login va parolni bergan boʻlsangiz, akkauntga kirib olishi;</li>
<li>bank kartasi maʼlumotlarini oshkor qilishi mumkin.</li>
</ul>
<p>Blokka tushmaslik va akkauntni yoʻqotmaslik uchun uchta qoidaga amal qiling:</p>
<ol>
<li>Faqat rasmiy doʻkon, Midasbuy yoki oʻyin ID boʻyicha ishlaydigan ishonchli mahalliy servis orqali sotib oling.</li>
<li>Toʻldirish uchun akkaunt login va parolini hech qachon bermang.</li>
<li>Narxi rasmiysidan sezilarli past takliflardan qoching: haddan tashqari arzon UC odatda noqonuniy manbani anglatadi.</li>
</ol>
<h2>Xarid qilishda tejash boʻyicha maslahatlar</h2>
<p>UC da tejash — shubhali chegirmalar izlash emas, balki paketni va xarid paytini toʻgʻri tanlash.</p>
<ul>
<li><strong>Muntazam oʻynasangiz, Royale Pass oling.</strong> Elite Pass qiymatining bir qismini mukofot va oʻyin ichidagi valyuta bilan qaytaradi, shuning uchun faol oʻyinchida u bir martalik skin xaridlaridan koʻra tezroq oʻzini oqlaydi.</li>
<li><strong>Koʻp sarflashni rejalashtirsangiz, yirik paket oling.</strong> Bir birlik UC ga tushadigan bonus hajm bilan oʻsadi, shuning uchun bitta katta paket odatda bir nechta kichigidan foydaliroq.</li>
<li><strong>Mavsumiy tadbirlarni kuting.</strong> Oʻyin yilligi va bayram aksiyalari odatdagi paketlarga koʻpincha bonus UC qoʻshadi.</li>
<li><strong>Oʻz valyutangizda toʻlang.</strong> Mahalliy servis orqali darhol soʻmda toʻlash konvertatsiya va xalqaro toʻlov komissiyalaridagi yashirin yoʻqotishlardan xalos qiladi.</li>
</ul>
<p>Agar PUBG Mobile yagona oʻyiningiz boʻlmasa, xuddi shu tamoyillar boshqa taytllarda ham ishlaydi: yirik paket tanlash, mavsumiy propusk olish va oʻz valyutangizda toʻlash aksariyat mobil oʻyinlarda bir xil tejaydi.</p>
<h2>Nimadan boshlash kerak</h2>
<p>Yaqin mavsumga sizga qancha UC kerakligini aniqlang: faqat Royale Passmi yoki skin va keyslar hammi. Soʻngra bitta rasmiy yoki ishonchli mahalliy kanalni tanlang, oʻyin ID raqamini kiriting va rejangizni qoplaydigan paketni sotib oling. Oʻzbekistondagi oʻyinchilar uchun eng tez yoʻl — <a href="https://yupay.uz/uz/store/pubg-mobile">PUBG Mobile toʻldirish sahifasida</a> oʻyin ID boʻyicha soʻmda toʻlash, komissiyasiz va akkaunt parolini bermasdan.</p>$body$,
  'PUBG Mobileda UC qanday olinadi: oʻyinchilar uchun yoʻllar',
  'PUBG Mobileda UC ni xavfsiz olish: rasmiy toʻldirish yoʻllari, paketlar tarkibi, akkauntni '
    || 'himoya qilish va tejash boʻyicha maslahatlar.'
)
ON CONFLICT (post_id, locale) DO UPDATE
   SET slug = EXCLUDED.slug,
       title = EXCLUDED.title,
       excerpt = EXCLUDED.excerpt,
       body_html = EXCLUDED.body_html,
       seo_title = EXCLUDED.seo_title,
       seo_description = EXCLUDED.seo_description;

-- ------------------------------------------------------------------- FAQs ---

DELETE FROM blog_post_faqs WHERE post_id = :post_id AND locale IN ('en', 'uz');

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer)
VALUES
  (gen_random_uuid(), :post_id, 'en', 0,
   'Can you get UC in PUBG Mobile for free?',
   'No. UC cannot be earned in matches or missions; the currency is sold only for real money, '
   || 'through the official shop or an authorised platform.'),
  (gen_random_uuid(), :post_id, 'en', 1,
   'Is it safe to buy UC from a reseller in Uzbekistan?',
   'It is safe if the reseller works from your player ID and through official top-up channels, '
   || 'rather than from your account login and password. Yupay tops up UC by player ID and never '
   || 'asks for your credentials.'),
  (gen_random_uuid(), :post_id, 'en', 2,
   'Which UC pack is the better buy?',
   'The larger the pack, the bigger the bonus per unit: the 300 UC pack delivers 325, and the '
   || '6000 UC pack delivers 8100. If you buy the Royale Pass and items regularly, one large '
   || 'pack usually beats several small ones.'),
  (gen_random_uuid(), :post_id, 'en', 3,
   'What gets an account banned when buying UC?',
   'Buying UC through unauthorised resellers who obtain the currency illegitimately. PUBG '
   || 'Mobile''s rules allow that currency to be confiscated and the account banned.'),
  (gen_random_uuid(), :post_id, 'uz', 0,
   'PUBG Mobileda UC ni bepul olish mumkinmi?',
   'Yoʻq. UC ni matchlar yoki topshiriqlarda ishlab topib boʻlmaydi, bu valyuta faqat haqiqiy '
   || 'pulga — rasmiy doʻkon yoki vakolatli platformalar orqali sotiladi.'),
  (gen_random_uuid(), :post_id, 'uz', 1,
   'Oʻzbekistonda vositachilardan UC sotib olish xavfsizmi?',
   'Agar vositachi akkaunt login va parolidan emas, sizning oʻyin ID raqamingiz va rasmiy '
   || 'toʻldirish kanallaridan foydalansa — xavfsiz. Yupay UC ni oʻyin ID boʻyicha toʻldiradi va '
   || 'kirish maʼlumotlarini soʻramaydi.'),
  (gen_random_uuid(), :post_id, 'uz', 2,
   'Qaysi UC paketini olish foydaliroq?',
   'Paket qancha yirik boʻlsa, bir birlikka tushadigan bonus shuncha koʻp: 300 UC paketidan '
   || 'hisobga 325, 6000 UC paketidan esa 8100 UC tushadi. Royale Pass va buyumlarni muntazam '
   || 'olsangiz, bitta katta paket odatda bir nechta kichigidan foydaliroq.'),
  (gen_random_uuid(), :post_id, 'uz', 3,
   'UC sotib olishda akkaunt nima uchun bloklanishi mumkin?',
   'Valyutani noqonuniy yoʻl bilan oladigan ruxsatsiz vositachilardan UC sotib olgani uchun. '
   || 'PUBG Mobile qoidalari bunday valyutani musodara qilish va akkauntni bloklashga yoʻl '
   || 'qoʻyadi.');

COMMIT;
