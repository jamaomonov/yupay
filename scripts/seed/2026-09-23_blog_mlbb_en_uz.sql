-- Mobile Legends diamonds guide: the English and Uzbek translations.
--
-- The Russian original arrived from Bunzy on 2026-09-23, was reviewed, edited
-- and published the same day. Bunzy sends one locale; every other post on the
-- blog carries all three, so these two are written here rather than imported.
--
-- Two things worth knowing before editing:
--
--   * Links carry a locale prefix — `/blog/x` in Russian, `/en/blog/x` and
--     `/uz/blog/x` in the other two. A prefix-less link inside a translated
--     post drops the reader back into Russian.
--   * The Russian text links to `oplata-igr-v-sumah`, which exists **only in
--     Russian**. Linking it from here would do exactly that. Both translations
--     point at `kupit-donat-v-uzbekistane` instead — the nearest article that
--     does exist in all three locales, and about the same thing: paying for
--     game top-ups from Uzbekistan.
--
-- Idempotent: re-running replaces both translations and their FAQ rows,
-- leaving the Russian original and the post's own row untouched.

BEGIN;

\set post_id '''01a0cc50-d79c-7370-afee-fbcf83db958a'''

DELETE FROM blog_post_translations WHERE post_id = :post_id AND locale IN ('en', 'uz');
DELETE FROM blog_post_faqs WHERE post_id = :post_id AND locale IN ('en', 'uz');

-- ---------------------------------------------------------------- English --

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'en', 'how-to-top-up-mobile-legends',
  'How to top up Mobile Legends: buying diamonds',
  'How to top up Mobile Legends with diamonds from Uzbekistan: paying in soʻm, finding your game ID, and buying safely.',
$html$<h2>The short version</h2>
<ul>
<li>Diamonds in Mobile Legends buy skins, heroes, emblems and the Starlight pass — they do not decide a match for you</li>
<li>From Uzbekistan you top up by game ID and pay in soʻm with local methods, no foreign card needed</li>
<li>Your ID sits in your profile as a number with the server in brackets, like 123456789 (12345)</li>
<li>The ID is enough to buy: no honest service ever asks for your game password</li>
<li>Russian and global accounts are topped up on different pages — check your region before paying</li>
</ul>
<p>To top up Mobile Legends with diamonds from Uzbekistan you need three things: your game ID, your server number, and a way to pay in soʻm. Your account password is not one of them. Below: what diamonds are for, which routes exist, how to find your ID, and how to pick a safe one.</p>
<p>Diamonds are the premium currency of Mobile Legends: Bang Bang, bought with real money and spent on cosmetics and convenience. It is worth understanding the process once — after that a top-up takes two minutes.</p>
<h2>What diamonds actually do in Mobile Legends: Bang Bang</h2>
<p>Diamonds unlock most of the game's premium content: hero skins, buying characters outright, upgrading emblems, the Starlight subscription and event draws. The developer reports 1.5 billion installs and 110 million monthly players (<a href="https://en.moonton.com/about/index.html">Moonton</a>, 2025) — an audience that explains how developed the in-game economy is.</p>
<p>Diamonds usually go on:</p>
<ul>
<li>Hero skins, from basic ones to collector editions</li>
<li>Unlocking new heroes without grinding Battle Points for weeks</li>
<li>The Starlight subscription and its monthly rewards</li>
<li>Upgrading emblems, which give small combat bonuses</li>
<li>Event passes, draws and name changes</li>
</ul>
<p>Skins and most purchases are cosmetic. They change how a hero looks, not how hard they hit. Buying diamonds buys comfort and identity; the match is still decided by skill and by how your team plays.</p>
<p>Starlight is the exception worth singling out. It gives an exclusive skin every month, extra rewards for playing, and progression bonuses. For someone who plays regularly it is often the most rational way to spend diamonds, because the value is spread across a month instead of going into one item.</p>
<p>Emblems work differently. They give small passive bonuses in combat — damage, defence — and can be levelled without spending anything, though diamonds speed it up noticeably. The honest caveat: the difference shows at high ranks and is barely felt early on, so new players have no reason to rush it.</p>
<h2>How to top up from Uzbekistan</h2>
<p>The easiest route from Uzbekistan is a service that takes local payment methods in soʻm. That removes both the foreign card and the currency conversion. The player base here is large and demand for local payment is steady.</p>
<p>Players usually have three options:</p>
<ol>
<li>The in-game store. It works, but payment is usually tied to international cards or app-store billing.</li>
<li>Local top-up services. They take soʻm and credit diamonds by game ID.</li>
<li>Resale marketplaces. Cheaper on paper, with a higher chance of delays and fraud.</li>
</ol>
<p>The local route is normally the most direct one. On Yupay you pick Mobile Legends, enter your ID and pay in soʻm the way you usually pay, with no commission on top. We covered the wider picture of paying for top-ups from Uzbekistan in a <a href="https://yupay.uz/en/blog/buy-game-top-ups-in-uzbekistan">separate article</a>.</p>
<p>Each option has its own logic. The official store is reliable but wants a card that clears international payments, which is the main barrier for many players here. Resale marketplaces sometimes quote a lower price, but that is where delayed delivery and outright scams live. A local service removes both problems: payment in soʻm, and a process that asks only for a game ID.</p>
<p>Speed matters too. With automatic processing diamonds arrive almost immediately after payment, because the order never waits for an operator to look at it. In practice that means you can still buy an event pass on the last day of the event without gambling on the timing.</p>
<h2>Finding your ID so the diamonds land in the right place</h2>
<p>Your game ID is the key to the whole thing: it is how a service knows which account to credit. Finding it takes seconds, and no password is involved.</p>
<p>Here is where to look:</p>
<ol>
<li>Open Mobile Legends.</li>
<li>Tap your profile avatar in the top-left corner.</li>
<li>Under your nickname there is a number and a server code in brackets — 123456789 (12345).</li>
<li>The first number is your ID; the one in brackets is your server.</li>
</ol>
<p>You need both. An ID without the server can send diamonds somewhere else or fail the payment outright. Check the digits once more before you pay — a mistyped one is the single most common reason a top-up stalls.</p>
<p>A small habit helps if you top up regularly: copy your ID and server into your phone's notes once, and from then on you paste them in a second with nothing to get wrong. It also helps when someone else is buying for you — you send them two numbers, and access to the account stays entirely yours.</p>
<p>If you have more than one account, watch the server carefully. The same nickname on two servers is two different accounts with different progress, and a wrong server code sends the diamonds to an empty profile.</p>
<p>One more difference is the account region. Russian Mobile Legends accounts live separately from global ones and are topped up on different pages: <a href="https://yupay.uz/en/store/mobile-legends">the global account</a> and <a href="https://yupay.uz/en/store/mobile-legends-ru">the Russian one</a>. Open the wrong page and the payment either fails or credits the wrong profile. Check your region before paying.</p>
<h2>Comparing diamond packs on price</h2>
<p>Diamond packs almost always follow one rule: the bigger the pack, the less each diamond costs. Small packs suit a one-off skin; large ones pay off for anyone playing regularly.</p>
<p>Three things to compare:</p>
<ul>
<li>Price per diamond, not just the total. Larger packs often add bonus diamonds on top.</li>
<li>The first-purchase bonus. Many packs double your diamonds on the first buy of the month.</li>
<li>The final price in soʻm including commission. Hidden fees can eat the whole advantage of a bigger pack.</li>
</ul>
<p>The practical logic is simple. Want one particular skin? Take the pack just above its price. Planning Starlight and events? A large pack with a bonus works out cheaper per diamond. Services without commission, like Yupay, make this easier to compare: the price you see in soʻm is the price you pay. The same reasoning applies to <a href="https://yupay.uz/en/blog/online-game-top-ups-uzbekistan">online game top-ups</a> generally.</p>
<p>The first-purchase bonus deserves its own thought. It usually doubles the diamonds on your first top-up in a given month, which means splitting a monthly budget across several small payments is the wrong move — the bonus fires once. Better to gather the amount and make a single purchase, so the doubling lands on the larger number.</p>
<p>It is easier to count towards a specific goal. If you know what a skin costs in diamonds, take the nearest pack that covers it with a little to spare, and you avoid paying for diamonds that then sit unused. For bigger goals — a collector skin, a Starlight season — the reverse holds: a large pack is worth it for the better unit price.</p>
<h2>Buying safely</h2>
<p>Safe buying rests on one rule: topping up by ID needs the ID and the server, and nothing else. No honest service asks for your password, an SMS code or your login details. If someone does, it is a scam.</p>
<p>A few markers:</p>
<ul>
<li>Never hand over your account password or a confirmation code.</li>
<li>Check the ID and server before paying — one wrong digit is a different account.</li>
<li>Prefer services that quote a clear price in soʻm with no hidden fees.</li>
<li>Keep the payment confirmation until the diamonds actually arrive.</li>
<li>Treat prices well below the market with suspicion.</li>
</ul>
<p>Automatic delivery also cuts out human error: the order is processed against the ID you entered, with nobody retyping it. That saves time and makes the purchase predictable.</p>
<p>The other marker is where you buy. The official store and established local services work to rules you can point at, so a dispute has somewhere to go. A stranger in a chat or on a forum offers no such thing: if the diamonds never arrive, there is nobody to ask. A couple of percent off is not worth losing the whole amount.</p>
<p>If you have your ID and you know which pack you want, the rest is short: open <a href="https://yupay.uz/en/store/mobile-legends">Mobile Legends</a>, enter your ID with the server, and pay in soʻm however suits you. Start with a small pack to see how fast delivery is, then move up to the larger, better-value ones.</p>$html$,
  'How to top up Mobile Legends: buying diamonds',
  'How to top up Mobile Legends with diamonds from Uzbekistan: paying in soʻm, finding your game ID, and buying safely.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
  (gen_random_uuid(), :post_id, 'en', 0,
   'What do diamonds do in Mobile Legends?',
   'Diamonds unlock hero skins, buying heroes outright, emblem upgrades, the Starlight subscription, events and draws. They are the game''s premium currency.'),
  (gen_random_uuid(), :post_id, 'en', 1,
   'How do I find my Mobile Legends ID?',
   'Open the game and tap your avatar in the top-left corner. Under your nickname is a number with a server code in brackets, like 123456789 (12345). You need both to top up.'),
  (gen_random_uuid(), :post_id, 'en', 2,
   'Can I top up Mobile Legends in soʻm?',
   'Yes. From Uzbekistan the top-up goes through services that take local payment methods in soʻm, so no foreign card is required.'),
  (gen_random_uuid(), :post_id, 'en', 3,
   'Does topping up by ID need my account password?',
   'No. Crediting diamonds needs only the game ID and the server. Nobody should ever be told your password or login code — being asked for one is a sign of fraud.');

-- ----------------------------------------------------------------- Uzbek ---

INSERT INTO blog_post_translations
  (post_id, locale, slug, title, excerpt, body_html, seo_title, seo_description)
VALUES (
  :post_id, 'uz', 'mobile-legends-toldirish',
  'Mobile Legends qanday toʻldiriladi: olmos sotib olish',
  'Oʻzbekistonda Mobile Legends ni olmoslar bilan toʻldirish: soʻmda toʻlov, oʻyin ID sini topish va xavfsiz xarid.',
$html$<h2>Asosiysi</h2>
<ul>
<li>Mobile Legendsda olmoslar skinlar, qahramonlar, emblemalar va Starlight obunasi uchun kerak — lekin jang natijasini ular hal qilmaydi</li>
<li>Oʻzbekistondan hisobni oʻyin ID si orqali toʻldirib, soʻmda mahalliy usullar bilan toʻlash mumkin, valyuta kartasi shart emas</li>
<li>ID profilda raqam va qavs ichidagi server kodi koʻrinishida turadi, masalan 123456789 (12345)</li>
<li>Xarid uchun ID yetarli: hech bir halol xizmat oʻyin parolini soʻramaydi</li>
<li>Rossiya va global akkauntlar turli sahifalarda toʻldiriladi — toʻlovdan oldin hududni tekshiring</li>
</ul>
<p>Oʻzbekistondan Mobile Legends ni olmoslar bilan toʻldirish uchun uch narsa kerak: oʻyin ID si, server raqami va soʻmda toʻlash imkoniyati. Akkaunt paroli ularning orasida yoʻq. Quyida: olmoslar nimaga kerak, qanday yoʻllar bor, ID ni qayerdan topish va xavfsiz variantni qanday tanlash.</p>
<p>Olmos — Mobile Legends: Bang Bang oʻyinining premium valyutasi. Uni haqiqiy pulga olib, oʻyin ichidagi koʻrinish va qulayliklarga sarflashadi. Jarayonni bir marta tushunib olish kifoya, keyin toʻldirish ikki daqiqa vaqt oladi.</p>
<h2>Olmoslar Mobile Legends: Bang Bangda nima beradi</h2>
<p>Olmoslar oʻyinning deyarli barcha premium qismini ochadi: qahramon skinlari, qahramonni toʻgʻridan-toʻgʻri sotib olish, emblemalarni kuchaytirish, Starlight obunasi va tanlovlarda qatnashish. Ishlab chiquvchi maʼlumotiga koʻra, oʻyin 1,5 milliard marta oʻrnatilgan va oyiga 110 million oʻyinchi kiradi (<a href="https://en.moonton.com/about/index.html">Moonton</a>, 2025) — shuncha auditoriya oʻyin iqtisodiyoti nega bunchalik rivojlanganini tushuntiradi.</p>
<p>Olmoslar odatda shularga ketadi:</p>
<ul>
<li>Qahramon skinlari, oddiysidan kolleksion nashrigacha</li>
<li>Yangi qahramonlarni Battle Points yigʻmasdan ochish</li>
<li>Starlight obunasi va uning oylik mukofotlari</li>
<li>Jangda kichik bonus beradigan emblemalarni kuchaytirish</li>
<li>Tadbir passlari, tanlovlar va nik almashtirish</li>
</ul>
<p>Skinlar va xaridlarning koʻpi — koʻrinish masalasi. Ular qahramonning tashqi qiyofasini oʻzgartiradi, kuchini emas. Olmos qulaylik va oʻziga xoslik beradi, jang natijasini esa baribir mahorat va jamoa oʻyini hal qiladi.</p>
<p>Starlight alohida turadi. U har oy eksklyuziv skin, oʻyinlar uchun qoʻshimcha mukofot va progress bonuslarini beradi. Muntazam oʻynaydigan odam uchun bu koʻpincha olmosni sarflashning eng oqilona yoʻli, chunki qiymat bitta buyumga emas, butun oyga taqsimlanadi.</p>
<p>Emblemalar boshqacha ishlaydi. Ular jangda kichik passiv bonus beradi — masalan, zarar yoki himoyaga — va ularni olmossiz ham oshirish mumkin, olmos faqat jarayonni tezlashtiradi. Bu yerda halol ogohlantirish bor: farq yuqori ranglarda seziladi, boshlanishida esa deyarli bilinmaydi, shuning uchun yangi oʻyinchilarga shoshilishning hojati yoʻq.</p>
<h2>Oʻzbekistonda hisobni toʻldirish yoʻllari</h2>
<p>Oʻzbekistonda eng qulayi — soʻmda mahalliy usullarni qabul qiladigan xizmat. Bu valyuta kartasidan ham, ortiqcha konvertatsiyadan ham xalos qiladi. Mamlakatda oʻyinchilar koʻp, mahalliy toʻlovga talab esa barqaror.</p>
<p>Odatda uchta yoʻl boʻladi:</p>
<ol>
<li>Oʻyin ichidagi rasmiy doʻkon. Ishlaydi, lekin toʻlov koʻpincha xalqaro kartalar yoki ilovalar doʻkoniga bogʻlangan.</li>
<li>Mahalliy toʻldirish xizmatlari. Soʻmni qabul qiladi va olmosni oʻyin ID si boʻyicha oʻtkazadi.</li>
<li>Qayta sotuv maydonchalari. Qogʻozda arzonroq, lekin kechikish va firibgarlik xavfi yuqori.</li>
</ol>
<p>Mahalliy yoʻl odatda eng toʻgʻridan-toʻgʻri boʻladi. Yupayda Mobile Legends ni tanlab, ID ni kiritib, odatdagi usul bilan soʻmda toʻlaysiz, ustiga komissiya qoʻshilmaydi. Oʻzbekistondan oʻyin toʻldirish uchun toʻlash mavzusini <a href="https://yupay.uz/uz/blog/ozbekistonda-donat-sotib-olish">alohida maqolada</a> batafsil koʻrib chiqqanmiz.</p>
<p>Har bir variantning oʻz mantigʻi bor. Rasmiy doʻkon ishonchli, lekin xalqaro toʻlovlardan oʻtadigan karta talab qiladi — bu yerdagi koʻp oʻyinchi uchun asosiy toʻsiq shu. Qayta sotuv maydonchalari baʼzan past narx taklif qiladi, ammo kechikish va aldov aynan oʻsha yerda. Mahalliy xizmat ikkala muammoni ham olib tashlaydi: soʻmda toʻlov va faqat oʻyin ID si soʻraladigan tushunarli jarayon.</p>
<p>Tezlik ham muhim. Avtomatik qayta ishlashda olmos toʻlovdan keyin deyarli darhol tushadi, chunki buyurtma operator koʻrigini kutib turmaydi. Amalda bu shuni anglatadiki, tadbir passini uning oxirgi kunida ham ulgurib olish mumkin.</p>
<h2>Olmos toʻgʻri joyga tushishi uchun ID ni qanday bilish kerak</h2>
<p>Oʻyin ID si — butun jarayonning kaliti: xizmat aynan shu orqali qaysi akkauntga olmos oʻtkazishni biladi. Uni topish bir necha soniya vaqt oladi va parol umuman kerak emas.</p>
<p>Qayerga qarash kerak:</p>
<ol>
<li>Mobile Legends ni oching.</li>
<li>Chap yuqoridagi profil avatarini bosing.</li>
<li>Nik ostida raqam va qavs ichida server kodi turadi — 123456789 (12345).</li>
<li>Birinchi raqam — ID, qavs ichidagisi — server.</li>
</ol>
<p>Ikkalasi ham kerak. Serversiz ID bilan olmos boshqa joyga ketishi yoki toʻlov oʻtmasligi mumkin. Toʻlashdan oldin raqamlarni yana bir bor solishtiring — xato terilgan raqam toʻldirish kechikishining eng koʻp uchraydigan sababi.</p>
<p>Muntazam toʻldiradiganlar uchun kichik odat foyda beradi: ID va serverni telefon eslatmalariga bir marta koʻchirib qoʻying, keyin ularni bir soniyada qoʻyasiz va adashish imkoni qolmaydi. Bu xaridni doʻst yoki qarindosh qilib berayotganda ham asqotadi: ularga ikkita raqam yuborasiz, akkauntga kirish esa faqat sizda qoladi.</p>
<p>Agar akkauntingiz bir nechta boʻlsa, serverga ehtiyot boʻling. Bitta nik ikki serverda — bu progressi har xil ikki alohida akkaunt, server kodidagi xato esa olmosni boʻsh profilga yuboradi.</p>
<p>Yana bir farq — akkaunt hududi. Rossiya Mobile Legends akkauntlari global akkauntlardan alohida yashaydi va turli sahifalarda toʻldiriladi: <a href="https://yupay.uz/uz/store/mobile-legends">global akkaunt</a> va <a href="https://yupay.uz/uz/store/mobile-legends-ru">rossiyalik akkaunt</a>. Notoʻgʻri sahifani ochsangiz, toʻlov oʻtmaydi yoki olmos boshqa profilga tushadi. Toʻlovdan oldin hududni tekshiring.</p>
<h2>Olmos paketlarini narx boʻyicha solishtirish</h2>
<p>Olmos paketlari deyarli har doim bitta qoidaga boʻysunadi: paket qancha katta boʻlsa, bitta olmos shuncha arzon tushadi. Kichik paketlar bitta skin uchun qulay, kattalari esa muntazam oʻynaydiganlarga foydali.</p>
<p>Solishtirishda uch narsaga qarang:</p>
<ul>
<li>Umumiy summa emas, bitta olmos narxi. Katta paketlar koʻpincha ustiga bonus olmos qoʻshadi.</li>
<li>Birinchi xarid bonusi. Koʻp paketlar oydagi birinchi xaridda olmosni ikki baravar qiladi.</li>
<li>Komissiya bilan birga soʻmdagi yakuniy narx. Yashirin toʻlovlar katta paketning butun foydasini yeb qoʻyishi mumkin.</li>
</ul>
<p>Amaliy mantiq oddiy. Bitta aniq skin kerakmi — narxidan sal yuqori paketni oling. Starlight va tadbirlarni rejalashtiryapsizmi — bonusli katta paket bitta olmos hisobida arzonroq chiqadi. Yupay kabi komissiyasiz xizmatlar solishtirishni osonlashtiradi: soʻmda koʻrgan narxingiz — yakuniy narx. Xuddi shu mantiq umuman <a href="https://yupay.uz/uz/blog/onlayn-oyin-toldirish">onlayn oʻyin toʻldirish</a> uchun ham ishlaydi.</p>
<p>Birinchi xarid bonusini alohida hisobga olish kerak. U odatda oydagi birinchi toʻldirishda olmosni ikki baravar qiladi — demak, oylik byudjetni bir nechta kichik toʻlovga boʻlish foydasiz, chunki bonus faqat bir marta ishlaydi. Kerakli summani yigʻib, bitta xarid qilgan maʼqul, shunda ikkilantirish kattaroq hajmga tushadi.</p>
<p>Aniq maqsadga qarab hisoblash qulayroq. Agar kerakli skin necha olmos turishini bilsangiz, uni sal zaxira bilan qoplaydigan eng yaqin paketni tanlang — shunda keyin ishlatilmay yotadigan olmosga ortiqcha pul toʻlamaysiz. Kolleksion skin yoki Starlight mavsumi kabi katta maqsadlarda esa aksincha: bitta olmos narxi arzonroq boʻlgani uchun katta paket maʼqul.</p>
<h2>Xavfsiz xarid boʻyicha maslahatlar</h2>
<p>Xavfsiz xarid bitta qoidaga tayanadi: ID orqali toʻldirish uchun faqat ID va server raqami kerak, boshqa hech narsa emas. Hech bir halol xizmat parol, SMS kodi yoki kirish maʼlumotlarini soʻramaydi. Soʻrashsa — bu firibgarlik.</p>
<p>Bir nechta mezon:</p>
<ul>
<li>Akkaunt parolini yoki tasdiqlash kodini hech qachon bermang.</li>
<li>Toʻlashdan oldin ID va serverni tekshiring — bitta xato raqam boshqa akkaunt degani.</li>
<li>Soʻmda aniq narx beradigan va yashirin komissiyasi yoʻq xizmatlarni tanlang.</li>
<li>Olmos tushgunicha toʻlov tasdigʻini saqlab turing.</li>
<li>Bozordan sezilarli past narxga ehtiyotkorlik bilan qarang.</li>
</ul>
<p>Avtomatik oʻtkazish inson xatosini ham kamaytiradi: buyurtma siz kiritgan ID boʻyicha qayta terilmasdan qayta ishlanadi. Bu vaqtni tejaydi va xaridni oldindan bashorat qilinadigan qiladi.</p>
<p>Yana bir mezon — qayerdan sotib olayotganingiz. Rasmiy doʻkon va tekshirilgan mahalliy xizmatlar aniq qoidalar boʻyicha ishlaydi, shuning uchun bahsli holatni hal qilsa boʻladi. Messenjerdagi yoki forumdagi tasodifiy sotuvchida bunday tayanch yoʻq: olmos kelmasa, murojaat qiladigan joy qolmaydi. Bir-ikki foiz farq butun summani yoʻqotishga arzimaydi.</p>
<p>Agar ID ni topgan va paketni tanlagan boʻlsangiz, qolgani qisqa: <a href="https://yupay.uz/uz/store/mobile-legends">Mobile Legends</a> sahifasini oching, ID ni server bilan kiriting va oʻzingizga qulay usulda soʻmda toʻlang. Avval kichik paketdan boshlab yetkazish tezligiga ishonch hosil qiling, keyin foydaliroq katta paketlarga oʻting.</p>$html$,
  'Mobile Legends qanday toʻldiriladi: olmos sotib olish',
  'Oʻzbekistonda Mobile Legends ni olmoslar bilan toʻldirish: soʻmda toʻlov, oʻyin ID sini topish va xavfsiz xarid.'
);

INSERT INTO blog_post_faqs (id, post_id, locale, sort_order, question, answer) VALUES
  (gen_random_uuid(), :post_id, 'uz', 0,
   'Mobile Legendsda olmoslar nima beradi?',
   'Olmoslar qahramon skinlari, qahramonni sotib olish, emblemalarni kuchaytirish, Starlight obunasi, tadbirlar va tanlovlarni ochadi. Bu oʻyinning premium valyutasi.'),
  (gen_random_uuid(), :post_id, 'uz', 1,
   'Mobile Legendsda oʻz ID mni qanday bilaman?',
   'Oʻyinni oching va chap yuqoridagi avatarni bosing. Nik ostida raqam va qavs ichida server kodi turadi, masalan 123456789 (12345). Toʻldirish uchun ikkalasi ham kerak.'),
  (gen_random_uuid(), :post_id, 'uz', 2,
   'Mobile Legends ni soʻmda toʻldirish mumkinmi?',
   'Ha. Oʻzbekistonda toʻldirish soʻmda mahalliy usullarni qabul qiladigan xizmatlar orqali oʻtadi, shuning uchun valyuta kartasi talab qilinmaydi.'),
  (gen_random_uuid(), :post_id, 'uz', 3,
   'ID orqali toʻldirish uchun akkaunt paroli kerakmi?',
   'Yoʻq. Olmos oʻtkazish uchun faqat oʻyin ID si va server yetarli. Parol yoki kirish kodini hech kimga aytish kerak emas — uni soʻrashsa, bu firibgarlik belgisi.');

COMMIT;
