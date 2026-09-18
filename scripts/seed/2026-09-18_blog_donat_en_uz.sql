-- Blog post «Купить донат в Узбекистане: где выгоднее» (draft) — en + uz translations.
--
-- Post id 01a0ad07-2d2b-7a71-be53-03b7df31efa9, created in the admin as a ru-only
-- draft. This script adds the two missing locales and fixes two defects in the ru
-- row it was written with:
--
--   * the slug was the placeholder `post`, which would have shipped the URL
--     https://yupay.uz/blog/post — renamed to `kupit-donat-v-uzbekistane`.
--     Safe to rename: the post has never been published, so nothing links to it
--     and nothing is indexed.
--   * the closing call to action said "Откройте каталог Yupay" without linking
--     anywhere. Now it links to /store, per locale.
--
-- What this script deliberately does NOT do: publish. `status` stays `draft` and
-- `primary_brand_id` stays NULL — `ck_blog_posts_brand_unless_draft` requires a
-- brand before this post can leave draft, and picking the brand is the owner's
-- call (see the review notes).
--
-- Idempotent: re-running it overwrites the same three translation rows and the
-- eight en/uz FAQ rows without duplicating anything.
--
-- Apply:
--   docker exec -i yupay-prod-postgres-1 sh -lc \
--     'psql -U $POSTGRES_USER -d $POSTGRES_DB -v ON_ERROR_STOP=1' \
--     < scripts/seed/2026-09-18_blog_donat_en_uz.sql

\set post_id '''01a0ad07-2d2b-7a71-be53-03b7df31efa9'''

BEGIN;

-- ---------------------------------------------------------------- ru fixes ----

UPDATE blog_post_translations
   SET slug = 'kupit-donat-v-uzbekistane'
 WHERE post_id = :post_id
   AND locale = 'ru'
   AND slug = 'post';

UPDATE blog_post_translations
   SET body_html = replace(
         body_html,
         '<p>Откройте каталог Yupay, найдите нужную игру',
         '<p>Откройте <a href="https://yupay.uz/store">каталог Yupay</a>, найдите нужную игру'
       )
 WHERE post_id = :post_id
   AND locale = 'ru';

-- Pure navigation water: the paragraph only announces the headings that follow
-- it, which the reader can already see.
UPDATE blog_post_translations
   SET body_html = replace(
         body_html,
         '<p>Ниже разберём, что вообще такое донат, как оплатить его в сумах, почему локальные'
         || ' способы оплаты удобнее международных карт, как отсутствие комиссии влияет на цену'
         || ' и по каким признакам отличить надёжный сервис от мошеннического.</p>' || E'\n',
         ''
       )
 WHERE post_id = :post_id
   AND locale = 'ru';

-- ------------------------------------------------------------------- en ------

INSERT INTO blog_post_translations (post_id, locale, slug, title, excerpt, body_html,
                                    seo_title, seo_description)
VALUES (
  :post_id,
  'en',
  'buy-game-top-ups-in-uzbekistan',
  'Buying game top-ups in Uzbekistan: where it costs less',
  'How to buy game top-ups in Uzbekistan paying in soum, with no fee and no risk to your account. '
    || 'Local payment methods, honest pricing and the safety checks that actually matter.',
$body$<h2>The short version</h2>
<ul>
<li>Top-ups cost least in Uzbekistan when you pay in soum with a local Uzcard or Humo card, with no currency conversion.</li>
<li>No fee feeds straight into the final price: you pay for the in-game currency, not for the transfer.</li>
<li>A safe purchase never needs your game account password — your player ID is enough.</li>
<li>Automatic delivery credits the top-up within a few minutes of payment.</li>
</ul>
<p>Game top-ups in Uzbekistan are cheapest paid in soum through local cards and payment apps, with no fee and no currency conversion. A safe purchase does not need the password to your game account: your player ID is enough, and the currency is credited automatically within minutes.</p>
<h2>What a game top-up is and why players buy one</h2>
<p>A top-up means buying in-game currency or items with real money. In PUBG Mobile that is UC, in Free Fire diamonds, in Genshin Impact Genesis Crystals, in Mobile Legends diamonds again. Players spend that currency on battle passes, skins, characters and other items.</p>
<p>Mobile games have long been a mass pastime, and Uzbekistan is no exception. According to the <a href="https://datareportal.com/reports/digital-2025-uzbekistan">DataReportal Digital 2025</a> report, the country had 32.7 million internet users at the start of 2025, an online penetration of 89.0 percent. Cellular mobile connections reached 33.9 million, equal to 92.2 percent of the population. That audience, with a smartphone permanently to hand, is the base for which topping up became an ordinary expense.</p>
<p>The reasons are simple. Some players want to speed up progress instead of spending dozens of hours farming, some support a game they love, some just collect cosmetics and skins. In esports titles a top-up often unlocks seasonal rewards that cannot be earned any other way.</p>
<h2>How to buy in-game currency paying in soum</h2>
<p>Paying in soum solves the main problem local players have: no hunting for an international card and no overpaying for conversion. At any decent service the flow looks the same.</p>
<ol>
<li>Pick the game and the amount you want — a UC pack for PUBG Mobile, say, or diamonds for Free Fire.</li>
<li>Enter your player ID or login. Steam needs your login; mobile games need the numeric ID from your profile.</li>
<li>Pay with an Uzcard or Humo card, or through Click or Payme.</li>
<li>Wait for automatic delivery. The currency appears in your game account within a few minutes.</li>
</ol>
<p>On Yupay every product has its own page, where the available amounts and the price in soum are visible straight away. If you are just starting with a popular gacha title, learn the mechanics first — we cover them in <a href="https://yupay.uz/en/blog/genshin-impact">How to play Genshin Impact: a beginner's guide</a> — and buy Genesis Crystals on the game's catalogue page afterwards.</p>
<p>Steam works slightly differently: you top up the wallet, and games and in-game items are paid for from it. We wrote out the steps in <a href="https://yupay.uz/en/blog/steam">How to top up Steam in Uzbekistan</a>.</p>
<h2>What local payment methods give you</h2>
<p>Local payments in Uzbekistan are built around two card systems, Uzcard and Humo, and three large payment apps: Click, Payme and Uzum. For a player that brings several tangible benefits.</p>
<ul>
<li><strong>The price is already in soum.</strong> You see the final amount with no exchange-rate arithmetic and no hidden markup for a currency operation.</li>
<li><strong>No international card needed.</strong> You do not need a dollar Visa or Mastercard to top up a game.</li>
<li><strong>Fast confirmation.</strong> Paying through Click or Payme takes a couple of taps in an app almost everyone already has installed.</li>
<li><strong>A readable transaction history.</strong> Every purchase shows up in your usual banking app, which makes spending easy to keep track of.</li>
</ul>
<p>International payment gateways often add a cross-border fee and apply an exchange rate worse than the official one. Together those can noticeably raise the price of the very same top-up pack. Paying directly in soum removes the extra links.</p>
<h2>No fee is the difference that shows</h2>
<p>A fee is usually what separates a good buy from a bad one. Plenty of sites show an attractive base price, then add a processing charge, a payment-method charge or a conversion charge at the payment step. The amount due ends up higher than advertised.</p>
<p>Yupay works with no fee: the price you see on the product page is the amount you pay. That matters most for regular purchases. If you buy a battle pass and some in-game currency every month, even a small percentage turns into a noticeable overpayment across a year.</p>
<p>Checking it is easy. Compare the price on the product page with the final amount at the moment of payment. At an honest service the two numbers match. If the amount grows at the last step, the fee is simply hidden deeper in the process.</p>
<h2>Safety when buying a top-up</h2>
<p>Safety comes down to a few simple rules worth knowing for every player in Uzbekistan.</p>
<p><strong>Never hand over your account password.</strong> Topping up most mobile games needs only your player ID. Steam is topped up by login, without a password. Any request for your password, an SMS code or your login details is an attempt to steal the account.</p>
<p><strong>Check the payment methods.</strong> A service built for this market accepts Uzcard, Humo, Click and Payme. If a site demands foreign cards only, or a transfer to a private person's card, treat it as a warning sign.</p>
<p><strong>Look at price transparency.</strong> No hidden fees, and a clear product page with a fixed price in soum, mean the service is not trying to disguise anything.</p>
<p><strong>Watch the speed and the automation.</strong> Automatic delivery means crediting does not depend on when a seller gets round to processing the order by hand. That cuts the risk of delays and human error.</p>
<p>The caution is warranted. As online payments grow, so does the activity of fraudsters, and game accounts holding currency and rare skins have long been an attractive target. The basics stay the same for any payment: never give anyone your card details or confirmation codes, buy only from services you have checked, and always look at the site address before paying.</p>
<h2>Where to start right now</h2>
<p>Open the <a href="https://yupay.uz/en/store">Yupay catalogue</a>, find your game, and compare the price on the product page with the final amount at payment. If the numbers match, payment goes through in soum via Uzcard, Humo, Click or Payme, and all you are asked for is your player ID, you have found a cheap and safe way to buy a top-up. Start with a small pack, confirm the currency arrives automatically, and top up with confidence after that.</p>$body$,
  'Buy game top-ups in Uzbekistan: where it costs less',
  'How to buy game top-ups in Uzbekistan paying in soum, with no fee and no risk to your account. '
    || 'Local payment methods, honest pricing and the safety checks that actually matter.'
)
ON CONFLICT (post_id, locale) DO UPDATE
   SET slug = EXCLUDED.slug,
       title = EXCLUDED.title,
       excerpt = EXCLUDED.excerpt,
       body_html = EXCLUDED.body_html,
       seo_title = EXCLUDED.seo_title,
       seo_description = EXCLUDED.seo_description;

-- ------------------------------------------------------------------- uz ------

INSERT INTO blog_post_translations (post_id, locale, slug, title, excerpt, body_html,
                                    seo_title, seo_description)
VALUES (
  :post_id,
  'uz',
  'ozbekistonda-donat-sotib-olish',
  'Oʻzbekistonda donat sotib olish: qayerda arzonroq',
  'Oʻzbekistonda donatni soʻmda, komissiyasiz va xavfsiz qanday sotib olish mumkin. '
    || 'Mahalliy toʻlov usullari, halol narx va eʼtibor berish kerak boʻlgan xavfsizlik belgilari.',
$body$<h2>Asosiysi</h2>
<ul>
<li>Oʻzbekistonda donatni soʻmda, Uzcard va Humo mahalliy kartalari orqali sotib olish arzonroq — valyuta konvertatsiyasisiz.</li>
<li>Komissiyaning yoʻqligi yakuniy narxga bevosita taʼsir qiladi: siz oʻtkazma uchun emas, oʻyin valyutasi uchun toʻlaysiz.</li>
<li>Xavfsiz xarid oʻyin akkaunti parolini talab qilmaydi, oʻyin ID raqamining oʻzi yetarli.</li>
<li>Avtomatik yetkazib berish toʻlovdan keyin bir necha daqiqada donatni hisobga oʻtkazadi.</li>
</ul>
<p>Oʻzbekistonda donatni eng arzon tarzda soʻmda, mahalliy kartalar va toʻlov ilovalari orqali, komissiyasiz va valyuta konvertatsiyasisiz sotib olasiz. Xavfsiz xarid esa oʻyin akkauntingiz parolini talab qilmaydi: oʻyin ID raqami yetarli, valyuta esa bir necha daqiqada avtomatik hisobga oʻtadi.</p>
<h2>Donat nima va u nima uchun kerak</h2>
<p>Donat deb oʻyin ichidagi valyuta yoki buyumlarni haqiqiy pulga sotib olish aytiladi. PUBG Mobileda bu UC, Free Fireda olmoslar, Genshin Impactda Yaratilish Kristallari, Mobile Legendsda yana olmoslar. Oʻyinchilar bu valyutaga jangovar propusklar, skinlar, qahramonlar va boshqa buyumlarni oladi.</p>
<p>Mobil oʻyinlar allaqachon ommaviy mashgʻulotga aylangan va Oʻzbekiston bundan mustasno emas. <a href="https://datareportal.com/reports/digital-2025-uzbekistan">DataReportal Digital 2025</a> hisobotiga koʻra, 2025 yil boshida mamlakatda 32,7 million internet foydalanuvchisi boʻlgan, bu internetdan foydalanish darajasining 89,0 foiziga toʻgʻri keladi. Mobil ulanishlar soni esa 33,9 millionga yetgan, yaʼni aholining 92,2 foizi. Smartfoni doim yonida boʻlgan ana shu auditoriya uchun donat oddiy xarajatga aylangan.</p>
<p>Sabablari oddiy. Kimdir farmga oʻnlab soat sarflamay, oʻsishini tezlashtirmoqchi, kimdir sevimli oʻyinini qoʻllab-quvvatlaydi, kimdir shunchaki kosmetika va skinlar yigʻadi. Kibersport oʻyinlarida donat koʻpincha boshqa yoʻl bilan olib boʻlmaydigan mavsumiy mukofotlarni ochadi.</p>
<h2>Oʻyin valyutasini soʻmda qanday sotib olish mumkin</h2>
<p>Soʻmda toʻlash mahalliy oʻyinchilarning asosiy muammosini hal qiladi: xalqaro karta izlash va konvertatsiya uchun ortiqcha toʻlash shart emas. Har qanday normal servisda xarid tartibi bir xil koʻrinadi.</p>
<ol>
<li>Oʻyinni va kerakli donat nominalini tanlang, masalan PUBG Mobile uchun UC paketi yoki Free Fire uchun olmoslar.</li>
<li>Oʻyin ID raqami yoki loginini kiriting. Steam uchun login, mobil oʻyinlar uchun profildagi raqamli ID kerak boʻladi.</li>
<li>Buyurtmani Uzcard yoki Humo kartasi bilan, yoxud Click yoki Payme orqali toʻlang.</li>
<li>Avtomatik hisobga oʻtishini kuting. Valyuta oʻyin hisobingizda bir necha daqiqada paydo boʻladi.</li>
</ol>
<p>Yupayda har bir mahsulot alohida sahifada joylashgan, u yerda nominallar va soʻmdagi narx darhol koʻrinadi. Agar mashhur gacha oʻyinini endi boshlayotgan boʻlsangiz, avval mexanikasini tushunib olgan maʼqul: bu haqda <a href="https://yupay.uz/uz/blog/genshin-impact">Genshin Impactda qanday oʻynash kerak: yangi boshlovchilar uchun qoʻllanma</a> materialimiz bor, keyin katalogdagi oʻyin sahifasidan Yaratilish Kristallarini sotib olsa boʻladi.</p>
<p>Steamdagi xaridlar mantigʻi biroz boshqacha: u yerda hamyon toʻldiriladi, keyin undan oʻyinlar va oʻyin ichidagi buyumlar uchun toʻlanadi. Batafsil ketma-ketlikni <a href="https://yupay.uz/uz/blog/steam">Oʻzbekistonda Steamni qanday toʻldirish</a> koʻrsatmasida yozganmiz.</p>
<h2>Mahalliy toʻlov usullarining afzalliklari</h2>
<p>Oʻzbekistondagi mahalliy toʻlov usullari ikkita karta tizimi — Uzcard va Humo — hamda uchta yirik toʻlov ilovasi: Click, Payme va Uzum atrofida qurilgan. Oʻyinchi uchun bu bir nechta sezilarli qulaylik beradi.</p>
<ul>
<li><strong>Narx darhol soʻmda.</strong> Yakuniy summani kurs boʻyicha qayta hisoblashsiz va valyuta amaliyoti uchun yashirin ustamasiz koʻrasiz.</li>
<li><strong>Xalqaro kartalar kerak emas.</strong> Oʻyinni toʻldirish uchun dollardagi Visa yoki Mastercard shart emas.</li>
<li><strong>Tez tasdiqlash.</strong> Click yoki Payme orqali toʻlov deyarli hammada oʻrnatilgan ilovada bir necha teginishda oʻtadi.</li>
<li><strong>Tushunarli amaliyotlar tarixi.</strong> Barcha xarajatlar odatdagi bank ilovasida koʻrinadi, bu xarajatlarni nazorat qilishga qulay.</li>
</ul>
<p>Xalqaro toʻlov shlyuzlari koʻpincha chegara ortidagi toʻlov uchun komissiya qoʻshadi va rasmiydan yomonroq konvertatsiya kursini qoʻllaydi. Natijada xuddi oʻsha donat paketining narxi sezilarli oshishi mumkin. Toʻgʻridan-toʻgʻri soʻmda toʻlash bu ortiqcha bosqichlarni olib tashlaydi.</p>
<h2>Komissiyaning yoʻqligi — asosiy farq</h2>
<p>Koʻpincha aynan komissiya foydali xaridni foydasizidan ajratadi. Koʻp saytlar jozibali asosiy narxni koʻrsatadi, ammo toʻlov bosqichida toʻlovni qayta ishlash, toʻlov usuli yoki konvertatsiya uchun yigʻim qoʻshadi. Natijada toʻlanadigan summa eʼlon qilinganidan yuqori chiqadi.</p>
<p>Yupay komissiyasiz ishlaydi: mahsulot sahifasida koʻrgan narxingiz — aynan siz toʻlaydigan summa. Bu muntazam xaridlar uchun ayniqsa muhim. Agar har oy jangovar propusk va bir oz oʻyin valyutasi olsangiz, hatto kichik foizli komissiya ham yil davomida sezilarli ortiqcha toʻlovga aylanadi.</p>
<p>Buni tekshirish oson. Mahsulot sahifasidagi narxni toʻlov paytidagi yakuniy summa bilan solishtiring. Halol servisda bu ikki raqam mos keladi. Agar oxirgi qadamda summa oshsa, demak komissiya jarayonning ichiga yashirilgan.</p>
<h2>Donat sotib olishda xavfsizlik</h2>
<p>Xavfsizlik Oʻzbekistondagi har bir oʻyinchi bilishi kerak boʻlgan bir nechta oddiy qoidaga borib taqaladi.</p>
<p><strong>Akkaunt parolini bermang.</strong> Koʻpchilik mobil oʻyinlarni toʻldirish uchun faqat oʻyin ID raqami kerak. Steam parolsiz, login boʻyicha toʻldiriladi. Parol, SMSdagi kod yoki kirish maʼlumotlarini soʻrash — akkauntni oʻgʻirlashga urinish demakdir.</p>
<p><strong>Toʻlov usullarini tekshiring.</strong> Mahalliy bozor uchun ishonchli servis Uzcard, Humo, Click va Paymeni qabul qiladi. Agar sayt faqat xorijiy kartalar bilan yoki jismoniy shaxsning shaxsiy kartasiga oʻtkazma orqali toʻlashni talab qilsa, bu xavotirli belgi.</p>
<p><strong>Narx shaffofligiga qarang.</strong> Yashirin komissiyalarning yoʻqligi va soʻmdagi qatʼiy narx koʻrsatilgan tushunarli mahsulot sahifasi servis nimanidir yashirmayotganini bildiradi.</p>
<p><strong>Tezlik va avtomatlashtirishga eʼtibor bering.</strong> Avtomatik yetkazib berish hisobga oʻtish sotuvchi buyurtmani qachon qoʻlda koʻrib chiqishiga bogʻliq emasligini anglatadi. Bu kechikish va inson xatosi xavfini kamaytiradi.</p>
<p>Bu yerda ehtiyotkorlik oʻrinli. Onlayn toʻlovlar koʻpaygani sari firibgarlar faolligi ham ortadi, toʻplangan valyuta va nodir skinlarga ega oʻyin akkauntlari esa allaqachon jozibali nishonga aylangan. Himoyaning asosiy tamoyillari har qanday toʻlov uchun bir xil: karta rekvizitlari va tasdiqlash kodlarini hech kimga aytmang, faqat tekshirilgan saytlarda xarid qiling va toʻlovdan oldin sayt manzilini doim solishtiring.</p>
<h2>Hoziroq nimadan boshlash kerak</h2>
<p><a href="https://yupay.uz/uz/store">Yupay katalogini</a> oching, kerakli oʻyinni toping va mahsulot sahifasidagi narxni toʻlovdagi yakuniy summa bilan solishtiring. Agar raqamlar mos kelsa, toʻlov soʻmda Uzcard, Humo, Click yoki Payme orqali oʻtsa va hisobga oʻtkazish uchun faqat oʻyin ID raqami soʻralsa, demak siz donat sotib olishning arzon va xavfsiz yoʻlini topdingiz. Kichik paketdan boshlang, valyuta avtomatik kelganiga ishonch hosil qiling va keyin xotirjam toʻldiravering.</p>$body$,
  'Oʻzbekistonda donat sotib olish: qayerda arzonroq',
  'Oʻzbekistonda donatni soʻmda, komissiyasiz va xavfsiz qanday sotib olish mumkin. '
    || 'Mahalliy toʻlov usullari, halol narx va xavfsizlik belgilari — batafsil qoʻllanma.'
)
ON CONFLICT (post_id, locale) DO UPDATE
   SET slug = EXCLUDED.slug,
       title = EXCLUDED.title,
       excerpt = EXCLUDED.excerpt,
       body_html = EXCLUDED.body_html,
       seo_title = EXCLUDED.seo_title,
       seo_description = EXCLUDED.seo_description;

-- ----------------------------------------------------------------- FAQs ------
-- The visible Q/A block also feeds FAQPage JSON-LD, so each locale needs its own
-- rows or the markup falls back to nothing. Replaced wholesale on every run:
-- `(post_id, locale, sort_order)` is unique, so re-running with edited copy would
-- otherwise collide.

DELETE FROM blog_post_faqs WHERE post_id = :post_id AND locale IN ('en', 'uz');

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer)
VALUES
  (gen_random_uuid(), :post_id, 'en', 0,
   'Can I buy game top-ups in Uzbekistan paying in soum?',
   'Yes. Services such as Yupay accept Uzcard and Humo cards as well as Click and Payme, so the '
   || 'price is quoted in soum from the start, with no conversion.'),
  (gen_random_uuid(), :post_id, 'en', 1,
   'Do I need my game account password to buy a top-up?',
   'No. For most games your player ID or login is enough. If a service asks for your account '
   || 'password, that is a sign of fraud.'),
  (gen_random_uuid(), :post_id, 'en', 2,
   'Why is a top-up with no fee cheaper?',
   'A fee is added on top of the base price and raises the final amount. Without one you pay only '
   || 'for the in-game currency itself.'),
  (gen_random_uuid(), :post_id, 'en', 3,
   'How quickly does a top-up arrive after payment?',
   'With automatic delivery, crediting usually takes from a few seconds to a few minutes after the '
   || 'payment is confirmed.'),
  (gen_random_uuid(), :post_id, 'uz', 0,
   'Oʻzbekistonda donatni soʻmda toʻlab sotib olish mumkinmi?',
   'Ha. Yupay kabi servislar Uzcard va Humo kartalarini, shuningdek Click va Payme toʻlovlarini '
   || 'qabul qiladi, shuning uchun narx darhol soʻmda, konvertatsiyasiz koʻrsatiladi.'),
  (gen_random_uuid(), :post_id, 'uz', 1,
   'Donat sotib olish uchun oʻyin akkaunti paroli kerakmi?',
   'Yoʻq. Koʻpchilik oʻyinlar uchun oʻyin ID raqami yoki login yetarli. Agar servis akkaunt '
   || 'parolini soʻrasa, bu firibgarlik belgisi.'),
  (gen_random_uuid(), :post_id, 'uz', 2,
   'Nega komissiyasiz donat foydaliroq?',
   'Komissiya asosiy narx ustiga qoʻshiladi va yakuniy summani oshiradi. Usiz siz faqat oʻyin '
   || 'valyutasining oʻzi uchun toʻlaysiz.'),
  (gen_random_uuid(), :post_id, 'uz', 3,
   'Toʻlovdan keyin donat qanchalik tez keladi?',
   'Avtomatik yetkazib berishda hisobga oʻtish toʻlov tasdiqlangach odatda bir necha soniyadan bir '
   || 'necha daqiqagacha vaqt oladi.');

COMMIT;
