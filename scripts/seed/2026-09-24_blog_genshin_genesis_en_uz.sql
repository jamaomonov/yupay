-- Genshin Genesis Crystals guide: the English and Uzbek translations.
--
-- The Russian original arrived from Bunzy on 2026-09-24, was reviewed, edited
-- and published the same day. Bunzy sends one locale; the blog carries three.
--
-- Three things to know before editing, the first two the same traps as the
-- Mobile Legends translations a day earlier:
--
--   * Links carry a locale prefix — `/blog/x` in Russian, `/en/blog/x` and
--     `/uz/blog/x` elsewhere. The Russian original arrived with an `/en/`
--     store link in it, which is the same bug seen from the other side.
--   * The Russian text links to `oplata-igr-v-sumah`, which exists **only in
--     Russian**. Both translations point at `kupit-donat-v-uzbekistane`
--     instead — the nearest article that exists in all three locales.
--   * The beginner's guide (`genshin-impact`) keeps the *same slug* in all
--     three locales, so that link only needs its prefix changed.
--
-- The original said Primogems buy "Originium", which is Arknights' currency
-- and does not exist in Genshin. Corrected to Original Resin in the Russian
-- and never written here.
--
-- Idempotent: re-running replaces both translations and their FAQ rows,
-- leaving the Russian original and the post's own row untouched.

BEGIN;

\set post_id '''01a0d188-d5c1-79c1-8f41-56b8fb21c4a2'''

DELETE FROM blog_post_translations WHERE post_id = :post_id AND locale IN ('en', 'uz');
DELETE FROM blog_post_faqs WHERE post_id = :post_id AND locale IN ('en', 'uz');

-- ---------------------------------------------------------------- English --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'en', 'genshin-impact-genesis-crystals',
  'Genshin Impact: buying Genesis Crystals without overpaying',
  'How to buy Genshin Impact Genesis Crystals from Uzbekistan: paying in soʻm, delivery in minutes, comparing packs and avoiding hidden costs.',
$html$<h2>The short version</h2>
<ul>
<li>Genesis Crystals convert to Primogems one for one, which is why they are the thing you actually pay money for — wishes and the Battle Pass are spent in Primogems</li>
<li>Blessing of the Welkin Moon costs $4.99 and gives 300 crystals at once plus 90 Primogems a day for 30 days</li>
<li>From Uzbekistan it is easier to pay in soʻm through local methods: the amount leaves your account in your own currency, with no exchange-rate surprise</li>
<li>Delivery is near-instant when the top-up goes by game ID — no logging in, no password</li>
<li>Besides your UID you will need your server — Europe, America, Asia or TW/HK/MO. On the wrong one the crystals will not find your account</li>
<li>Bigger packs give more crystals per unit of price, and the one-time first-purchase bonus doubles what you get</li>
</ul>
<p>The cheapest way to buy Genesis Crystals is a large pack with its first-purchase bonus, paid in Uzbek soʻm so nothing is lost to currency conversion. Below: what you are actually paying for, which packs give more crystals for the same money, and how to have them credited in minutes without handing your account to a stranger.</p>
<p>Genesis Crystals are the game's paid currency. They are what you buy when you want to speed up getting a new character or weapon, or to take out a subscription. Understanding how the packs and the payment methods work is worth real money on every purchase.</p>
<h2>What Genesis Crystals and the Welkin Moon are for</h2>
<p>Genesis Crystals do nothing in combat by themselves. Their value is that they convert to Primogems one for one, and Primogems are what pay for wishes — the system that gives you characters and weapons — for refilling Original Resin, and for the Battle Pass. In effect you buy crystals to turn them into chances at the character you want.</p>
<p>The single most discussed purchase is the Blessing of the Welkin Moon. For $4.99 it credits 300 Genesis Crystals immediately and then adds 90 Primogems every day for 30 days. For someone who logs in daily this is the cheapest steady source of wish currency, because its price per Primogem is lower than any one-off crystal pack.</p>
<p>The scale of the game explains why a whole industry of top-up services grew around it. Genshin Impact has passed 300 million registered accounts worldwide and is one of the highest-grossing games ever made (<a href="https://www.shanethegamer.com/research/genshin-impact-revenue-analysis/">STG Research, citing Niko Partners</a>). An audience that size means plenty of ways to top up, and not all of them are equally safe or equally cheap.</p>
<h2>Where to buy Genesis Crystals and pay in soʻm</h2>
<p>For a player in Uzbekistan the question that matters is which currency you pay in. The official shop prices in dollars, and paying with an international card adds your bank's conversion rate plus a possible cross-border fee, so the final cost becomes unpredictable.</p>
<p>Local services solve that by taking payment in the national currency. Yupay tops up Genesis Crystals priced directly in soʻm through local payment methods, so you see the exact amount before you confirm and the exchange rate stops mattering. There is no commission on top, so the number on the screen is the number that leaves your account.</p>
<p>If you are still working out which payment methods are available here at all, we covered them in a <a href="https://yupay.uz/en/blog/buy-game-top-ups-in-uzbekistan">separate article</a>.</p>
<h2>Getting the crystals credited straight away</h2>
<p>A top-up by game ID goes through the official mechanism: you give the UID, the payment clears, and the crystals arrive on that account automatically. Nobody asks for a password, because none is involved.</p>
<p>At Yupay the process is automated, so crystals usually appear on your balance within a few minutes of payment. That matters when a banner is running and you want to make your wishes while the event is still live. Yupay uses the same by-UID, near-instant delivery for other games too.</p>
<p>One detail worth knowing. The game does not hand you the Welkin Moon's daily reward by itself. After buying it you have to open the game each day and collect the 90 Primogems by hand; skip a day and they are gone. The subscription pays off for people who play regularly, and only for them.</p>
<h2>Comparing crystal packs</h2>
<p>Packs are built so that the bigger the purchase, the more crystals you get per unit of price. On top of that, the first time you buy any given pack the game adds a one-time bonus that roughly doubles it. The same pack is therefore much better value the first time than on any repeat.</p>
<p>The official packs and their first-purchase bonuses, approximately:</p>
<ul>
<li>60 crystals, no bonus. The minimum pack.</li>
<li>300 crystals plus 30 bonus on the first purchase.</li>
<li>980 crystals plus 110 bonus on the first purchase.</li>
<li>1980 crystals plus 260 bonus on the first purchase.</li>
<li>3280 crystals plus 600 bonus on the first purchase.</li>
<li>6480 crystals plus 1600 bonus on the first purchase.</li>
</ul>
<p>The practical conclusion is simple. If you are saving for a particular character, one large pack with its full first-purchase bonus beats several small ones. For a steady trickle of currency alongside that, keeping the Welkin Moon active is worth it, because its price per Primogem is lower than any one-off pack.</p>
<h2>Avoiding hidden costs and scams</h2>
<p>Hidden cost comes mostly from invisible currency conversion and undisclosed fees. When the price is quoted in dollars and paid with an international card, the amount that finally leaves your account in soʻm is larger than the one you agreed to. Paying in the national currency closes that gap: you see the final price before confirming.</p>
<p>The second risk is fraud, and it turns on one rule: topping up crystals by game ID does not need your account password. Any seller who asks for your login so they can "go in and add it for you" is creating a route to losing the account. Legitimate top-ups work by UID and nothing else.</p>
<p>To buy safely and without overpaying:</p>
<ul>
<li>Buy by game UID and never hand over a login and password.</li>
<li>Choose a service that prices in soʻm and shows a final total with no hidden fees.</li>
<li>Check that delivery is automatic rather than someone signing into your account.</li>
<li>Compare the price per crystal across packs, not just the totals.</li>
</ul>
<p>Knowing which characters you actually want keeps crystals from going to waste, so decide that before you open your wallet.</p>
<p>And one small thing that is worth the whole purchase: besides your UID, a top-up asks for your server — Europe, America, Asia or TW/HK/MO. It is chosen when the account is created and shown in-game next to your UID. Players in Uzbekistan and the CIS are most often on Europe, but check yours: on another server that is a different account, and the crystals go to it. If you are new to the game, we have a <a href="https://yupay.uz/en/blog/genshin-impact">beginner's guide to Genshin Impact</a>.</p>
<p>Decide on the goal before you buy: a specific character on the current banner, or a reserve for later. Then open the <a href="https://yupay.uz/en/store/genshin-impact">Genshin Impact top-up page</a>, pick a pack, enter your UID and pay in soʻm. The crystals arrive in minutes, at a price you saw in advance, with no risk to the account.</p>$html$,
  'Genshin Impact: buying Genesis Crystals without overpaying',
  'How to buy Genshin Impact Genesis Crystals from Uzbekistan: paying in soʻm, delivery in minutes, comparing packs and avoiding hidden costs.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
  (gen_random_uuid(), :post_id, 'en', 0,
   'How do Genesis Crystals differ from Primogems?',
   'Genesis Crystals are the paid currency you buy with money. They convert to Primogems one for one, and it is Primogems that pay for wishes and the Welkin Moon.'),
  (gen_random_uuid(), :post_id, 'en', 1,
   'What does the Blessing of the Welkin Moon give?',
   'It credits 300 Genesis Crystals at once and adds 90 Primogems every day for 30 days. The daily reward has to be collected by hand in-game.'),
  (gen_random_uuid(), :post_id, 'en', 2,
   'Can I top up Genshin Impact in soʻm?',
   'Yes. Through a local service like Yupay the payment goes in Uzbek soʻm by local methods, and the crystals are credited by your game ID.'),
  (gen_random_uuid(), :post_id, 'en', 3,
   'How quickly do the crystals arrive?',
   'A top-up by game UID usually lands within a few minutes, because the process is automated and never involves signing into your account.'),
  (gen_random_uuid(), :post_id, 'en', 4,
   'How do I avoid scams when buying?',
   'Never hand over your account login and password. Buy by game ID from services that price in soʻm with no hidden fees.');

-- ----------------------------------------------------------------- Uzbek ---

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'uz', 'genshin-impact-genesis-kristallari',
  'Genshin Impact: Genesis kristallarini ortiqcha toʻlovsiz sotib olish',
  'Oʻzbekistonda Genshin Impact Genesis kristallarini sotib olish: soʻmda toʻlov, bir necha daqiqada yetkazish, paketlarni solishtirish va yashirin toʻlovlardan qochish.',
$html$<h2>Asosiysi</h2>
<ul>
<li>Genesis kristallari Primogemsga bir-birga almashadi — pulga sotib olinadigani aynan shu, duolar va Battle Pass esa Primogemsga sarflanadi</li>
<li>Blessing of the Welkin Moon 4,99 dollar turadi va darrov 300 kristal, keyin 30 kun davomida har kuni 90 Primogems beradi</li>
<li>Oʻzbekistondan soʻmda mahalliy usullar bilan toʻlash qulayroq: pul oʻz valyutangizda yechiladi, kurs sakrashi sizga tegmaydi</li>
<li>Oʻyin ID si orqali toʻldirishda kristallar deyarli darhol tushadi — akkauntga kirish ham, parol ham kerak emas</li>
<li>UID dan tashqari server ham kerak — Europe, America, Asia yoki TW/HK/MO; notoʻgʻri serverda kristallar akkauntni topa olmaydi</li>
<li>Katta paketlarda bir kristal arzonroq tushadi, birinchi xarid bonusi esa miqdorni deyarli ikki baravar qiladi</li>
</ul>
<p>Genesis kristallarini eng foydali sotib olish yoʻli — birinchi xarid bonusi bilan katta paket olish va oʻzbek soʻmida toʻlash, shunda valyuta ayirboshlashga pul ketmaydi. Quyida: aslida nimaga toʻlayotganingiz, qaysi paketlar bir xil pulga koʻproq kristal berishi va akkauntni begonaga bermasdan bir necha daqiqada qanday olish mumkinligi.</p>
<p>Genesis kristallari — oʻyinning pullik valyutasi. Yangi qahramon yoki qurolni tezroq olmoqchi boʻlsangiz yoki obuna rasmiylashtirmoqchi boʻlsangiz, aynan shuni sotib olasiz. Paketlar va toʻlov usullari qanday ishlashini bir marta tushunib olish har bir xaridda haqiqiy pulni tejaydi.</p>
<h2>Genesis kristallari va Welkin Moon nimaga kerak</h2>
<p>Genesis kristallarining oʻzi jangda hech nima qilmaydi. Ularning qiymati shundaki, ular Primogemsga bir-birga almashadi, Primogems esa duolarga — qahramon va qurol beradigan tizimga, Original Resin toʻldirishga hamda Battle Passga sarflanadi. Yaʼni siz kristallarni kerakli qahramonni tortib olish imkoniga aylantirish uchun sotib olasiz.</p>
<p>Eng koʻp muhokama qilinadigan xarid — Blessing of the Welkin Moon. 4,99 dollarga u darrov 300 Genesis kristal beradi, soʻng 30 kun davomida har kuni 90 Primogems qoʻshadi. Har kuni kiradigan oʻyinchi uchun bu duo valyutasini barqaror yigʻishning eng arzon yoʻli, chunki bu yerda bitta Primogems narxi har qanday bir martalik paketdan past.</p>
<p>Oʻyin koʻlami toʻldirish xizmatlari atrofida butun bir soha oʻsganini tushuntiradi. Genshin Impact dunyo boʻylab 300 milliondan ortiq roʻyxatdan oʻtgan akkauntdan oshdi va tarixdagi eng daromadli oʻyinlardan biriga aylandi (<a href="https://www.shanethegamer.com/research/genshin-impact-revenue-analysis/">STG Research, Niko Partners maʼlumotlari asosida</a>). Bunday auditoriya toʻldirish yoʻllari koʻpligini bildiradi, va ularning hammasi ham bir xil xavfsiz yoki bir xil foydali emas.</p>
<h2>Genesis kristallarini qayerdan olish va soʻmda toʻlash</h2>
<p>Oʻzbekistondagi oʻyinchi uchun asosiy masala — qaysi valyutada toʻlash. Rasmiy doʻkon narxni dollarda koʻrsatadi, xalqaro karta bilan toʻlaganda esa ustiga bank kursi va chegaradan oʻtgan toʻlov uchun komissiya qoʻshilishi mumkin — natijada yakuniy summa oldindan bilinmaydi.</p>
<p>Mahalliy xizmatlar buni milliy valyutada toʻlovni qabul qilib hal qiladi. Yupay Genesis kristallarini toʻgʻridan-toʻgʻri soʻmdagi narx bilan va mahalliy usullar orqali toʻldiradi, shuning uchun tasdiqlashdan oldin aniq summani koʻrasiz va kursga bogʻliq boʻlmaysiz. Ustiga komissiya qoʻshilmaydi — ekranda koʻrgan raqam hisobdan yechiladigan raqamdir.</p>
<p>Agar bu yerda umuman qanday toʻlov usullari borligini endi oʻrganayotgan boʻlsangiz, buni <a href="https://yupay.uz/uz/blog/ozbekistonda-donat-sotib-olish">alohida maqolada</a> koʻrib chiqqanmiz.</p>
<h2>Kristallar hisobga darrov tushishi uchun</h2>
<p>Oʻyin ID si orqali toʻldirish rasmiy mexanizm boʻyicha ketadi: UID ni berasiz, toʻlov oʻtadi, kristallar esa oʻsha akkauntga avtomatik tushadi. Parol soʻralmaydi, chunki u umuman ishtirok etmaydi.</p>
<p>Yupayda jarayon avtomatlashtirilgan, shuning uchun kristallar odatda toʻlovdan keyin bir necha daqiqa ichida balansda paydo boʻladi. Bu banner ketayotganda va tadbir tugamasidan duo qilib ulgurmoqchi boʻlganingizda muhim. Xuddi shunday UID boʻyicha tez yetkazishni Yupay boshqa oʻyinlarda ham qoʻllaydi.</p>
<p>Bir muhim tafsilot. Welkin Moon ning kunlik mukofotini oʻyin oʻzi bermaydi. Sotib olgandan keyin har kuni oʻyinga kirib, 90 Primogemsni qoʻlda olish kerak; kunni oʻtkazib yuborsangiz, u yonib ketadi. Obuna muntazam oʻynaydiganlar uchun foydali — va faqat ular uchun.</p>
<h2>Kristal paketlarini solishtirish</h2>
<p>Paketlar shunday tuzilganki, xarid qanchalik katta boʻlsa, bir kristal shunchalik arzon tushadi. Bundan tashqari, har bir paketni birinchi marta olganingizda oʻyin bir martalik bonus qoʻshadi va bu miqdorni deyarli ikki baravar qiladi. Shuning uchun aynan bitta paket birinchi safar takroriy xariddan ancha foydaliroq.</p>
<p>Rasmiy paketlar va birinchi xarid bonusi, taxminan:</p>
<ul>
<li>60 kristal, bonussiz. Eng kichik paket.</li>
<li>300 kristal va birinchi xaridda 30 bonus.</li>
<li>980 kristal va birinchi xaridda 110 bonus.</li>
<li>1980 kristal va birinchi xaridda 260 bonus.</li>
<li>3280 kristal va birinchi xaridda 600 bonus.</li>
<li>6480 kristal va birinchi xaridda 1600 bonus.</li>
</ul>
<p>Amaliy xulosa oddiy. Aniq bir qahramonga yigʻayotgan boʻlsangiz, toʻliq birinchi xarid bonusi bilan bitta katta paket bir nechta kichigidan afzal. Yonida valyuta barqaror kelib turishi uchun Welkin Moon ni faol saqlash maʼqul, chunki undagi bitta Primogems narxi har qanday bir martalik paketdan past.</p>
<h2>Ortiqcha toʻlov va firibgarlardan qochish</h2>
<p>Ortiqcha toʻlov koʻpincha koʻrinmas valyuta ayirboshlash va aytilmagan komissiyalardan kelib chiqadi. Narx dollarda koʻrsatilib, toʻlov xalqaro karta bilan ketganda, soʻmda hisobdan yechiladigan yakuniy summa kelishilganidan katta boʻladi. Milliy valyutada toʻlash bu farqni yoʻq qiladi: yakuniy narxni tasdiqlashdan oldin koʻrasiz.</p>
<p>Ikkinchi xavf — firibgarlik, va u bitta qoidaga tayanadi: oʻyin ID si orqali kristal toʻldirish uchun akkaunt paroli kerak emas. «Kirib, oʻzim qoʻshib beraman» deb login soʻragan har qanday sotuvchi akkauntni yoʻqotish yoʻlini ochadi. Qonuniy toʻldirish faqat UID orqali ishlaydi.</p>
<p>Xavfsiz va ortiqcha toʻlovsiz sotib olish uchun:</p>
<ul>
<li>Oʻyin UID si boʻyicha oling va login bilan parolni hech qachon bermang.</li>
<li>Soʻmda narx koʻrsatadigan va yashirin toʻlovsiz yakuniy summa beradigan xizmatni tanlang.</li>
<li>Yetkazish avtomatik ekaniga ishonch hosil qiling — kimdir akkauntingizga kirmasin.</li>
<li>Faqat umumiy summani emas, paketlardagi bitta kristal narxini solishtiring.</li>
</ul>
<p>Qaysi qahramonlar sizga haqiqatan kerakligini bilish kristallarni behuda sarflashdan saqlaydi, shuning uchun buni hamyonni ochishdan oldin hal qiling.</p>
<p>Va butun xaridga arziydigan yana bir kichik narsa: UID dan tashqari toʻldirishda server ham soʻraladi — Europe, America, Asia yoki TW/HK/MO. U akkaunt yaratilganda tanlanadi va oʻyinda UID yonida koʻrinadi. Oʻzbekiston va MDH oʻyinchilari koʻpincha Europe da, lekin oʻzingiznikini tekshiring: boshqa serverda bu boshqa akkaunt va kristallar oʻsha yerga ketadi. Oʻyinni endi boshlayotgan boʻlsangiz, bizda <a href="https://yupay.uz/uz/blog/genshin-impact">Genshin Impact boʻyicha yangi boshlovchilar uchun qoʻllanma</a> bor.</p>
<p>Xaridgacha maqsadni belgilang: joriy bannerdagi aniq qahramonmi yoki kelajakka zaxirami. Soʻng <a href="https://yupay.uz/uz/store/genshin-impact">Genshin Impact toʻldirish sahifasini</a> oching, mos paketni tanlang, UID ni kiriting va soʻmda toʻlang. Shunda kristallarni bir necha daqiqada, oldindan koʻrgan narxda va akkauntga xavfsiz olasiz.</p>$html$,
  'Genshin Impact: Genesis kristallarini ortiqcha toʻlovsiz sotib olish',
  'Oʻzbekistonda Genshin Impact Genesis kristallarini sotib olish: soʻmda toʻlov, bir necha daqiqada yetkazish, paketlarni solishtirish va yashirin toʻlovlardan qochish.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
  (gen_random_uuid(), :post_id, 'uz', 0,
   'Genesis kristallari Primogemsdan nimasi bilan farq qiladi?',
   'Genesis kristallari — pulga sotib olinadigan pullik valyuta. Ular Primogemsga bir-birga almashadi, duolar va Welkin Moon esa aynan Primogemsga olinadi.'),
  (gen_random_uuid(), :post_id, 'uz', 1,
   'Blessing of the Welkin Moon nima beradi?',
   'U darrov 300 Genesis kristal beradi va 30 kun davomida har kuni 90 Primogems qoʻshadi. Kunlik mukofotni oʻyin ichida qoʻlda olish kerak.'),
  (gen_random_uuid(), :post_id, 'uz', 2,
   'Genshin Impact ni soʻmda toʻldirish mumkinmi?',
   'Ha. Yupay kabi mahalliy xizmat orqali toʻlov oʻzbek soʻmida mahalliy usullar bilan oʻtadi, kristallar esa oʻyin ID ingiz boʻyicha tushadi.'),
  (gen_random_uuid(), :post_id, 'uz', 3,
   'Kristallar toʻlovdan keyin qanchada keladi?',
   'Oʻyin UID si boʻyicha toʻldirishda odatda bir necha daqiqada tushadi, chunki jarayon avtomatlashtirilgan va akkauntga kirishni talab qilmaydi.'),
  (gen_random_uuid(), :post_id, 'uz', 4,
   'Sotib olishda firibgarlarga duch kelmaslik uchun nima qilish kerak?',
   'Akkaunt login va parolini bermang, soʻmda shaffof narx koʻrsatadigan va yashirin komissiyasi yoʻq xizmatlardan oʻyin ID si boʻyicha oling.');

COMMIT;
