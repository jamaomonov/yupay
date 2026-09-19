-- Blog post «Пополнение игр онлайн: быстро и без комиссии» (draft) — en + uz,
-- and two ru FAQ answers that carried the same payment error the body did.
--
-- Post id 01a0b79d-bbb8-70f0-977d-475232263c7d. The body was corrected in
-- `2026-09-19_blog_online_topup_fixes.sql`; this adds the two missing locales
-- and finishes the job that script started.
--
-- **Two ru FAQ answers were wrong in the same way the body was.** "Для оплаты
-- подойдёт Click, Payme или карта Uzcard либо Humo" repeats both mistakes at
-- once — it omits Uzum and Paynet, and it lists the card as a third channel
-- beside two apps you pay with a card inside. "Оплата проходит через Click,
-- Payme или банк" omits the same two. The FAQ block feeds `FAQPage` JSON-LD,
-- so an uncorrected answer does not merely sit on the page: it is published as
-- structured data for search engines to quote.
--
-- Production is the authority for that list, not the previous posts:
-- `GET /api/v1/payments/providers` answers click, click_miniapp, payme, uzum,
-- paynet and wallet, all `active`.
--
-- Idempotent: re-running replaces the same rows.
--
-- Apply:
--   docker exec -i yupay-prod-postgres-1 sh -lc \
--     'psql -U $POSTGRES_USER -d $POSTGRES_DB -v ON_ERROR_STOP=1' \
--     < scripts/seed/2026-09-19_blog_online_topup_en_uz.sql

\set post_id '''01a0b79d-bbb8-70f0-977d-475232263c7d'''

BEGIN;

-- ---------------------------------------------------------------- ru FAQ ----

UPDATE blog_post_faqs
   SET answer = 'Достаточно знать свой игровой ID или логин и выбрать нужный номинал. '
             || 'Оплатить можно через Click, Payme, Uzum или Paynet — картой Uzcard или Humo. '
             || 'Регистрация на стороннем сайте не требуется.'
 WHERE post_id = :post_id AND locale = 'ru'
   AND question = 'Что нужно, чтобы пополнить игровой аккаунт?';

UPDATE blog_post_faqs
   SET answer = 'Да, если вы пользуетесь проверенным сервисом с локальными платёжными методами. '
             || 'Оплата проходит через Click, Payme, Uzum или Paynet, а данные для зачисления '
             || 'передаются напрямую издателю игры.'
 WHERE post_id = :post_id AND locale = 'ru'
   AND question = 'Безопасно ли пополнять игры онлайн?';

-- ------------------------------------------------------------------- en ------

INSERT INTO blog_post_translations (post_id, locale, slug, title, excerpt, body_html,
                                    seo_title, seo_description)
VALUES (
  :post_id,
  'en',
  'online-game-top-ups-uzbekistan',
  'Online game top-ups: fast, and with no fee',
  'Online game top-ups in Uzbekistan: automatic delivery in minutes, paid in soum through '
    || 'Click, Payme, Uzum and Paynet, with no fee.',
$body$<h2>The short version</h2>
<ul>
<li>A top-up at Yupay runs itself: you enter your player ID, pay in soum, and the currency lands in your account within a few minutes.</li>
<li>You can pay through Click, Payme, Uzum or Paynet — with an Uzcard or Humo card, no fee on top and no currency exchange.</li>
<li>Uzbekistan has 33.9 million mobile connections (DataReportal, 2025), so an online top-up is within reach of almost every player with a phone.</li>
<li>Topping up online beats buying a code by hand: no hunting for a seller, no long keys to type, no reseller's markup.</li>
</ul>
<p>An online top-up works like this: you pick the game, enter your player ID, pay the order in soum, and the currency is credited to the account automatically within a few minutes. No hunting for a code seller, no long keys to type, no reseller's markup. Below we go through how it works, which games and services are covered, and why paying in soum by local methods beats buying by hand.</p>
<p>Demand for this format is growing with the market. Mobile gaming remains the largest segment of the games industry worldwide, and Uzbekistan is no exception: there are more players every year, and they need a simple way to pay in their own currency.</p>
<h2>How an online top-up works</h2>
<p>An online top-up is a direct exchange between you, the payment system and the game's publisher. You give the player identifier, pick an amount, pay, and the service sends the crediting request itself. The whole thing takes minutes and needs no extra software installed.</p>
<p>The mechanics are simple and much the same in every game:</p>
<ul>
<li>You open the game's page and choose an amount or a currency pack.</li>
<li>You enter your player ID, UID or account login.</li>
<li>You pay the order the way you prefer: Click, Payme, Uzum or Paynet.</li>
<li>The system confirms the payment and passes the data to the publisher.</li>
<li>The currency appears in your in-game balance.</li>
</ul>
<p>That removes the middlemen. A player used to have to find a seller, agree terms and wait while they sent a code by hand. Now it is automated and no person is needed in the chain. If you want to work out where in-game currency is cheapest in the first place, read our breakdown in <a href="https://yupay.uz/en/blog/buy-game-top-ups-in-uzbekistan">Buying game top-ups in Uzbekistan: where it costs less</a> — it helps to pick a service before your first purchase, not after.</p>
<h2>The games and services covered</h2>
<p>Yupay tops up around twenty popular games and services, covering nearly every genre played in Uzbekistan — mobile shooters, role-playing games, platforms and subscriptions. Each works the same way: choose the amount, enter the ID, pay in soum.</p>
<p>Games and in-game currency:</p>
<ul>
<li>PUBG Mobile (UC) and Free Fire (diamonds)</li>
<li>Genshin Impact and Honkai: Star Rail (crystals)</li>
<li>Mobile Legends, Standoff 2, Roblox (Robux)</li>
<li>Delta Force, Arena Breakout and Arena Breakout: Infinite</li>
<li>Blood Strike, Magic Chess: Go Go, Whiteout Survival, Oxide: Survival Island</li>
</ul>
<p>Wallet top-ups and subscriptions:</p>
<ul>
<li>Steam: wallet top-ups and buying games</li>
<li>Discord Nitro, Telegram Premium, Telegram Stars</li>
</ul>
<p>The full catalogue, with current amounts, lives in the Yupay store. It covers both one-off top-ups and subscriptions, so finding what you need takes a couple of minutes.</p>
<p>The selection follows what players in the region actually play. Mobile shooters like PUBG Mobile, Free Fire and Standoff 2 hold large audiences, while Genshin Impact and Honkai: Star Rail gather the people who like big role-playing worlds. Topping up works the same predictable way for each, which helps anyone playing several at once.</p>
<p>Subscriptions sit slightly apart, but the principle holds. Discord Nitro extends what you can do in voice chats, Telegram Premium lifts the messenger's limits, and Telegram Stars pay for content and services inside the platform. All of it is bought in soum and activates automatically, with no detour through a foreign payment gateway.</p>
<h2>Automatic delivery, in minutes</h2>
<p>Automatic delivery means the currency reaches the account after payment without anyone processing the order by hand. The system contacts the publisher's server itself and confirms the top-up. In most cases that takes from a few seconds to a couple of minutes, rather than hours of waiting on a seller's reply.</p>
<p>Speed is the whole point of the service. When an event is running or a battle pass is about to expire, waiting half a day is pointless. The automation runs around the clock, so you can top up at night, at the weekend or mid-session without stepping away for long.</p>
<p>It is worth understanding where a delay comes from in the rare cases it does. Usually it is on the publisher's side: the game's server can be working through a queue at peak hours. Even then it is minutes, and the order's status is on your screen. You are not left guessing whether the payment arrived.</p>
<p>The other benefit is accuracy. A person can mistype or pick the wrong amount. An automatic system passes exactly what you entered at checkout, so the odds of getting the wrong pack come close to zero — provided the player ID itself is right.</p>
<p>Why is this possible at scale? Because the infrastructure is there. Uzbekistan has 33.9 million mobile connections, 92.2 percent of the population (<a href="https://datareportal.com/reports/digital-2025-uzbekistan">DataReportal, Digital 2025: Uzbekistan</a>). Almost every player has a smartphone, and therefore instant top-ups.</p>
<h2>Paying in soum: Click, Payme, Uzum and Paynet</h2>
<p>Paying in soum removes two familiar problems: exchange-rate swings and extra fees. You see the price in Uzbek soum and pay exactly that. Yupay accepts Click, Payme, Uzum and Paynet — in each of them you pay with your own Uzcard or Humo card, so whichever app is already on your phone will do. You can also pay from your Yupay balance if you topped it up earlier.</p>
<p>Local payment methods are more familiar to an Uzbek player than any foreign one. No dollar card to find, no foreign bank's checks to pass, no currency to convert at a loss. A couple of taps in the app you already use for your phone bill or utilities.</p>
<p>The habit of paying digitally is well established here. Most people pay online regularly, and Click, Payme and Uzum have become as ordinary as cash once was. A game top-up simply slots into that habit: the same wallet, the same card, only instead of an internet bill you are paying for a pack of in-game currency.</p>
<p>A word on fees. At Yupay the catalogue price is final: the payment system does not add a percentage on top of your order. You pay what you see and get the full amount of currency in the game. That shows most on larger packs, where someone else's fee would eat a noticeable part of the sum.</p>
<h2>Why this beats buying codes by hand</h2>
<p>An online top-up wins on speed, reliability and price. A code has to be found, bought and then redeemed correctly, and every step is a chance to make a mistake or meet a reseller. Topping up directly by player ID removes those risks entirely.</p>
<p>The two approaches side by side:</p>
<ul>
<li>Speed: automatic delivery in minutes against finding a seller and waiting for a code.</li>
<li>Mistakes: one ID to enter against a long key that is easy to mistype.</li>
<li>Price: a fixed sum in soum against a reseller's markup.</li>
<li>Availability: the service runs around the clock; a live seller does not.</li>
</ul>
<p>Codes still make sense as gifts, when you are giving an amount to someone else. That is why Yupay keeps that option too — buying Steam games and gifts, for instance. But for your own account a direct top-up is almost always faster and cheaper. We wrote up one of the most common cases in <a href="https://yupay.uz/en/blog/steam">How to top up Steam in Uzbekistan</a>.</p>
<p>There is a safety question as well. Buying a code from a private seller leaves you depending on their honesty: the key may turn out to be used, or bought in a doubtful way. Topping up directly by player ID removes that, because the data goes straight to the publisher through a legitimate payment channel. You pay by a method you know and get an order confirmation, not a promise in a chat.</p>
<p>Finally, consider repetition. A player rarely tops up once: purchases repeat season after season. When the process is settled and takes a minute, the saved time adds up. Work out the checkout once and every purchase after that goes almost on autopilot.</p>
<p>Topping up online became the standard for a reason: it follows the logic of any ordinary mobile payment. Pick your game in the Yupay catalogue, enter the ID and pay in soum. Next time your in-game currency runs out mid-match, topping up will take less time than restarting the game.</p>$body$,
  'Online game top-ups in Uzbekistan: fast, and with no fee',
  'Online game top-ups in Uzbekistan: automatic delivery in minutes, paid in soum through '
    || 'Click, Payme, Uzum and Paynet, with no fee.'
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
  'onlayn-oyin-toldirish',
  'Oʻyinlarni onlayn toʻldirish: tez va komissiyasiz',
  'Oʻzbekistonda oʻyinlarni onlayn toʻldirish: bir necha daqiqada avtomatik hisobga oʻtish va '
    || 'Click, Payme, Uzum hamda Paynet orqali soʻmda toʻlov, komissiyasiz.',
$body$<h2>Asosiysi</h2>
<ul>
<li>Yupayda toʻldirish avtomatik boʻladi: oʻyin ID raqamini kiritasiz, soʻmda toʻlaysiz va valyuta bir necha daqiqada hisobingizga tushadi.</li>
<li>Toʻlovni Click, Payme, Uzum yoki Paynet orqali — Uzcard yoki Humo kartangiz bilan qilish mumkin, ustiga komissiyasiz va valyuta almashtirishsiz.</li>
<li>Oʻzbekistonda 33,9 million mobil ulanish bor (DataReportal, 2025), shuning uchun onlayn toʻldirish smartfoni bor deyarli har bir oʻyinchi uchun ochiq.</li>
<li>Onlayn toʻldirish kodni qoʻlda sotib olishdan qulayroq: sotuvchi izlash, uzun kalit kiritish yoki qayta sotuvchiga ortiqcha toʻlash kerak emas.</li>
</ul>
<p>Onlayn toʻldirish shunday ishlaydi: oʻyinni tanlaysiz, oʻyin ID raqamingizni kiritasiz, buyurtmani soʻmda toʻlaysiz va valyuta akkauntga avtomatik hisobga oʻtadi. Kod sotuvchisini izlash, uzun kalitlar kiritish yoki qayta sotuvchiga ortiqcha toʻlash shart emas. Quyida onlayn toʻldirish qanday tuzilgani, qaysi oʻyin va xizmatlar mavjudligi hamda mahalliy usullar bilan soʻmda toʻlash nega qoʻlda xariddan qulayroq ekani koʻrib chiqiladi.</p>
<p>Bunday formatga talab bozor bilan birga oʻsmoqda. Mobil geyming dunyoda oʻyin sanoatining eng yirik segmenti boʻlib qolmoqda va Oʻzbekiston bundan mustasno emas: oʻyinchilar koʻpaymoqda va ularga oʻz valyutasida toʻlashning oddiy yoʻli kerak.</p>
<h2>Onlayn toʻldirish qanday ishlaydi</h2>
<p>Onlayn toʻldirish — bu siz, toʻlov tizimi va oʻyin nashriyoti oʻrtasidagi bevosita maʼlumot almashinuvi. Siz oʻyin identifikatorini koʻrsatasiz, nominalni tanlaysiz, toʻlaysiz, xizmat esa hisobga oʻtkazish soʻrovini oʻzi yuboradi. Butun jarayon bir necha daqiqa oladi va qoʻshimcha dastur oʻrnatishni talab qilmaydi.</p>
<p>Mexanika oddiy va deyarli barcha oʻyinlarda bir xil takrorlanadi:</p>
<ul>
<li>Kerakli oʻyin sahifasini ochasiz va summa yoki valyuta paketini tanlaysiz.</li>
<li>Oʻyin ID, UID yoki akkaunt loginini kiritasiz.</li>
<li>Buyurtmani qulay usulda toʻlaysiz: Click, Payme, Uzum yoki Paynet.</li>
<li>Tizim toʻlovni tasdiqlaydi va maʼlumotni nashriyotga uzatadi.</li>
<li>Valyuta oʻyindagi hisobingizda paydo boʻladi.</li>
</ul>
<p>Bu yondashuv vositachilarni olib tashlaydi. Ilgari oʻyinchi sotuvchini izlashi, kelishishi va u kodni qoʻlda yuborguncha kutishi kerak edi. Endi hammasi avtomatlashtirilgan va zanjirda odam kerak emas. Oʻyin valyutasini umuman qayerdan olish foydaliroq ekanini bilmoqchi boʻlsangiz, <a href="https://yupay.uz/uz/blog/ozbekistonda-donat-sotib-olish">Oʻzbekistonda donat sotib olish: qayerda arzonroq</a> maqolamizni oʻqing — bu birinchi xariddan oldin servis tanlashga yordam beradi.</p>
<h2>Qoʻllab-quvvatlanadigan oʻyin va xizmatlar</h2>
<p>Yupay yigirmaga yaqin mashhur oʻyin va xizmatni toʻldiradi va Oʻzbekistonda oʻynaladigan deyarli barcha janrlarni qamrab oladi: mobil shuterlar, rolli oʻyinlar, platformalar va obunalar. Har bir pozitsiya bir xil sxema boʻyicha ishlaydi: nominalni tanlash, ID kiritish, soʻmda toʻlash.</p>
<p>Oʻyinlar va oʻyin ichidagi valyuta:</p>
<ul>
<li>PUBG Mobile (UC) va Free Fire (olmoslar)</li>
<li>Genshin Impact va Honkai: Star Rail (kristallar)</li>
<li>Mobile Legends, Standoff 2, Roblox (Robux)</li>
<li>Delta Force, Arena Breakout va Arena Breakout: Infinite</li>
<li>Blood Strike, Magic Chess: Go Go, Whiteout Survival, Oxide: Survival Island</li>
</ul>
<p>Hamyon toʻldirish va obunalar:</p>
<ul>
<li>Steam: hamyonni toʻldirish va oʻyin sotib olish</li>
<li>Discord Nitro, Telegram Premium, Telegram Stars</li>
</ul>
<p>Toʻliq katalog joriy nominallari bilan Yupay doʻkonida yigʻilgan. Roʻyxat ham bir martalik toʻldirishlarni, ham obunalarni qamraydi, shuning uchun kerakli pozitsiyani bir necha daqiqada topish mumkin.</p>
<p>Oʻyinlar toʻplami mintaqadagi oʻyinchilarning haqiqiy afzalliklariga qarab tanlangan. PUBG Mobile, Free Fire va Standoff 2 kabi mobil shuterlar katta auditoriyani ushlab turadi, Genshin Impact va Honkai: Star Rail esa keng rolli dunyolarni yoqtiradiganlarni yigʻadi. Bularning har biri uchun toʻldirish bir xil bashorat qilinadigan tarzda ishlaydi, bu bir vaqtning oʻzida bir nechta oʻyin oʻynaydiganlar uchun qulay.</p>
<p>Obunalar biroz alohida turadi, ammo tamoyil oʻsha. Discord Nitro ovozli chatlardagi imkoniyatlarni kengaytiradi, Telegram Premium messenjer cheklovlarini olib tashlaydi, Telegram Stars esa platforma ichidagi kontent va xizmatlarni toʻlaydi. Bularning bari soʻmda rasmiylashtiriladi va avtomatik faollashadi, xorijiy toʻlov shlyuzlariga oʻtishsiz.</p>
<h2>Bir necha daqiqada avtomatik hisobga oʻtish</h2>
<p>Avtomatik hisobga oʻtish degani — toʻlovdan keyin valyuta buyurtmani qoʻlda qayta ishlashsiz akkauntga tushadi. Tizim nashriyot serveri bilan oʻzi bogʻlanadi va toʻldirishni tasdiqlaydi. Koʻp hollarda bu sotuvchining javobini soatlab kutish emas, bir necha soniyadan bir necha daqiqagacha vaqt oladi.</p>
<p>Tezlik — xizmatning asosi. Iven ketayotganda yoki jangovar propusk tugayotganda yarim kun kutishning maʼnosi yoʻq. Avtomatika kechayu kunduz ishlaydi, shuning uchun akkauntni tunda ham, dam olish kunida ham, oʻyin sessiyasi orasida ham uzoq uzilmasdan toʻldirish mumkin.</p>
<p>Kamdan-kam hollarda kechikish qayerdan kelishini tushunish muhim. Odatda sabab nashriyot tomonida: oʻyin serveri pik soatlarda soʻrovlar navbatini qayta ishlayotgan boʻlishi mumkin. Hatto shunda ham gap daqiqalar haqida boradi va buyurtma holati ekraningizda koʻrinadi. Siz toʻlov yetib bordimi yoki yoʻqmi deb taxmin qilib qolmaysiz.</p>
<p>Avtomatik hisobga oʻtishning yana bir ustunligi — aniqlik. Odam qoʻlda kiritishda xato qilishi yoki nominalni adashtirishi mumkin. Avtomatik tizim maʼlumotni siz rasmiylashtirishda koʻrsatgan holatda uzatadi. Shuning uchun notoʻgʻri valyuta paketi olish ehtimoli nolga intiladi — agar oʻyin ID raqami toʻgʻri kiritilgan boʻlsa.</p>
<p>Nega bu shunday koʻlamda umuman mumkin? Chunki infratuzilma tayyor. Oʻzbekistonda 33,9 million mobil ulanish bor, bu aholining 92,2 foizi (<a href="https://datareportal.com/reports/digital-2025-uzbekistan">DataReportal, Digital 2025: Uzbekistan</a>). Deyarli har bir oʻyinchida smartfon bor, demak, bir zumda toʻldirish imkoni ham bor.</p>
<h2>Soʻmda toʻlov: Click, Payme, Uzum va Paynet</h2>
<p>Soʻmda toʻlash ikkita tez-tez uchraydigan muammoni olib tashlaydi: kurs sakrashlari va ortiqcha komissiyalar. Siz narxni oʻzbek soʻmida koʻrasiz va aynan shuni toʻlaysiz. Yupay Click, Payme, Uzum va Paynetni qabul qiladi — ularning har birida oʻz Uzcard yoki Humo kartangiz bilan toʻlaysiz, shuning uchun telefoningizda allaqachon turgan ilova toʻgʻri keladi. Agar oldindan toʻldirgan boʻlsangiz, Yupaydagi balansdan ham toʻlash mumkin.</p>
<p>Mahalliy toʻlov usullari oʻzbek oʻyinchisiga har qanday xorijiydan koʻra tanishroq. Dollarli karta izlash, xorijiy bank tekshiruvlaridan oʻtish yoki valyutani kursda yoʻqotib almashtirish shart emas. Aloqa yoki kommunal xizmatlarni toʻlaydigan ilovangizda bir necha teginish yetarli.</p>
<p>Mamlakatda raqamli toʻlovlar odati allaqachon shakllangan. Aholining koʻpchiligi muntazam onlayn toʻlaydi, Click, Payme va Uzum esa koʻpchilik uchun ilgari naqd pul qanday oddiy boʻlsa, shunday oddiy holga aylandi. Oʻyin toʻldirishlari shu odatiy stsenariyga shunchaki qoʻshiladi: oʻsha hamyon, oʻsha karta, faqat internet hisobi oʻrniga oʻyin valyutasi paketini toʻlaysiz.</p>
<p>Komissiya haqida alohida aytish kerak. Yupayda katalogdagi narx yakuniy: toʻlov tizimi buyurtma summasi ustiga foiz qoʻshmaydi. Qancha koʻrsangiz, shuncha toʻlaysiz va oʻyinda valyutaning toʻliq nominalini olasiz. Bu ayniqsa yirik paketlarda seziladi, u yerda begona komissiyalar summaning sezilarli qismini yeb qoʻygan boʻlardi.</p>
<h2>Nega bu kodlarni qoʻlda sotib olishdan qulayroq</h2>
<p>Onlayn toʻldirish tezlik, ishonchlilik va narx boʻyicha qoʻlda kod sotib olishdan ustun. Kodni qayerdandir topish, sotib olish, keyin toʻgʻri faollashtirish kerak, va har bir qadamda xato qilish yoki qayta sotuvchiga duch kelish mumkin. Oʻyin ID boʻyicha toʻgʻridan-toʻgʻri toʻldirish bu xavflarni butunlay olib tashlaydi.</p>
<p>Ikki yondashuvni asosiy jihatlar boʻyicha solishtiramiz:</p>
<ul>
<li>Tezlik: bir necha daqiqada avtomatik hisobga oʻtish — sotuvchi izlash va kodni kutishga qarshi.</li>
<li>Xatolar: bitta ID kiritish — oson adashtiriladigan uzun kalitga qarshi.</li>
<li>Narx: soʻmdagi qatʼiy summa — qayta sotuvchi ustamasiga qarshi.</li>
<li>Mavjudlik: xizmat kechayu kunduz ishlaydi, tirik sotuvchi esa yoʻq.</li>
</ul>
<p>Qoʻlda kodlar sovgʻa uchun hamon oʻrinli — nominalni boshqa odamga sovgʻa qilayotganingizda. Aynan shuning uchun Yupay bu variantni ham qoldiradi, masalan Steamda oʻyin va sovgʻalar sotib olish. Ammo oʻz akkauntingiz uchun toʻgʻridan-toʻgʻri toʻldirish deyarli doim tezroq va arzonroq. Eng koʻp uchraydigan stsenariylardan birini <a href="https://yupay.uz/uz/blog/steam">Oʻzbekistonda Steamni qanday toʻldirish</a> koʻrsatmasida batafsil yozganmiz.</p>
<p>Xavfsizlik masalasi ham bor. Kodni qoʻldan sotib olganda siz sotuvchining halolligiga bogʻliq boʻlasiz: kalit ishlatilgan yoki shubhali yoʻl bilan olingan boʻlib chiqishi mumkin. Oʻyin ID boʻyicha toʻgʻridan-toʻgʻri toʻldirish bu xavfni olib tashlaydi, chunki maʼlumotlar qonuniy toʻlov kanali orqali bevosita nashriyotga boradi. Siz tanish usulda toʻlaysiz va yozishmadagi ogʻzaki vaʼda emas, buyurtma tasdigʻini olasiz.</p>
<p>Nihoyat, takrorlanishni hisobga olish kerak. Oʻyinchi akkauntni kamdan-kam bir marta toʻldiradi: xaridlar mavsumdan mavsumga takrorlanadi. Jarayon yoʻlga qoʻyilgan va bir daqiqa oladigan boʻlsa, tejalgan vaqt toʻplanadi. Rasmiylashtirishni bir marta tushunib olsangiz, keyingi har bir xarid ortiqcha oʻylashsiz oʻtadi.</p>
<p>Onlayn toʻldirish bejiz standartga aylangani yoʻq: u har qanday mobil toʻlovning odatiy mantigʻini takrorlaydi. Yupay katalogidan kerakli oʻyinni tanlang, ID kiriting va soʻmda toʻlang. Keyingi safar oʻyin valyutasi match oʻrtasida tugaganda, toʻldirish sizdan oʻyinni qayta ishga tushirishdan kamroq vaqt oladi.</p>$body$,
  'Oʻzbekistonda oʻyinlarni onlayn toʻldirish: tez va komissiyasiz',
  'Oʻzbekistonda oʻyinlarni onlayn toʻldirish: bir necha daqiqada avtomatik hisobga oʻtish va '
    || 'Click, Payme, Uzum hamda Paynet orqali soʻmda toʻlov.'
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
   'How long does an online game top-up take?',
   'Usually from a few seconds to a few minutes. Once the payment succeeds the system passes the '
   || 'data to the publisher automatically, and the currency appears in the game account with no '
   || 'operator involved.'),
  (gen_random_uuid(), :post_id, 'en', 1,
   'Is there a fee when paying in soum?',
   'No. At Yupay the price is quoted in Uzbek soum and that is what you pay. The payment system '
   || 'adds no percentage on top of the order.'),
  (gen_random_uuid(), :post_id, 'en', 2,
   'What do I need to top up a game account?',
   'Your player ID or login, and the amount you want. You can pay through Click, Payme, Uzum or '
   || 'Paynet with an Uzcard or Humo card. No registration on a third-party site is needed.'),
  (gen_random_uuid(), :post_id, 'en', 3,
   'Which games and services can I top up?',
   'PUBG Mobile, Free Fire, Genshin Impact, Mobile Legends, Roblox, Standoff 2 and other popular '
   || 'games, plus Steam, Discord Nitro, Telegram Premium and Telegram Stars.'),
  (gen_random_uuid(), :post_id, 'en', 4,
   'Is topping up online safe?',
   'Yes, with a service you have checked that uses local payment methods. Payment goes through '
   || 'Click, Payme, Uzum or Paynet, and the crediting data goes straight to the game''s publisher.'),
  (gen_random_uuid(), :post_id, 'uz', 0,
   'Oʻyinni onlayn toʻldirish qancha vaqt oladi?',
   'Odatda bir necha soniyadan bir necha daqiqagacha. Toʻlov muvaffaqiyatli oʻtgach, tizim '
   || 'maʼlumotni nashriyotga avtomatik uzatadi va valyuta operator ishtirokisiz oʻyin hisobida '
   || 'paydo boʻladi.'),
  (gen_random_uuid(), :post_id, 'uz', 1,
   'Soʻmda toʻlashda komissiya bormi?',
   'Yoʻq. Yupayda narx oʻzbek soʻmida koʻrsatilgan va siz aynan shuni toʻlaysiz. Toʻlov tizimi '
   || 'buyurtma summasi ustiga foiz qoʻshmaydi.'),
  (gen_random_uuid(), :post_id, 'uz', 2,
   'Oʻyin akkauntini toʻldirish uchun nima kerak?',
   'Oʻyin ID raqamingiz yoki loginingiz va kerakli nominal. Toʻlovni Click, Payme, Uzum yoki '
   || 'Paynet orqali Uzcard yoki Humo kartasi bilan qilish mumkin. Begona saytda roʻyxatdan '
   || 'oʻtish talab qilinmaydi.'),
  (gen_random_uuid(), :post_id, 'uz', 3,
   'Qaysi oʻyin va xizmatlarni toʻldirish mumkin?',
   'PUBG Mobile, Free Fire, Genshin Impact, Mobile Legends, Roblox, Standoff 2 va boshqa mashhur '
   || 'oʻyinlar, shuningdek Steam, Discord Nitro, Telegram Premium va Telegram Stars.'),
  (gen_random_uuid(), :post_id, 'uz', 4,
   'Oʻyinlarni onlayn toʻldirish xavfsizmi?',
   'Ha, agar mahalliy toʻlov usullariga ega tekshirilgan servisdan foydalansangiz. Toʻlov Click, '
   || 'Payme, Uzum yoki Paynet orqali oʻtadi, hisobga oʻtkazish maʼlumotlari esa bevosita oʻyin '
   || 'nashriyotiga boradi.');

COMMIT;
