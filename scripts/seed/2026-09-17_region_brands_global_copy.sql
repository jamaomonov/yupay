-- scripts/seed/2026-09-17_region_brands_global_copy.sql
--
-- The global Mobile Legends and Magic Chess: Go Go pages after the region
-- split (ADR-0079, seed 2026-09-16_region_brands.sql). Their description,
-- short description and two of their FAQs were written for the old layout —
-- two products, "Алмазы — глобальный аккаунт" vs the RU one, "switch to the
-- other product" — and still said so after the split moved the RU product to
-- its own brand page. This rewrites exactly those passages to point at the
-- RU page instead; the rest of the copy and the other FAQs are untouched.
--
-- Idempotent: plain UPDATEs keyed by brand slug + locale (translations) and by
-- the FAQ's question text (answers), so a re-run rewrites the same rows to the
-- same values. A no-op on a database that lacks these brands or FAQs.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Descriptions and short descriptions of the two GLOBAL brands. The first
--    two paragraphs of each description are kept verbatim; only the closing
--    "one thing to know" paragraph changes, and the short description names
--    the region and the sibling page.
-- ---------------------------------------------------------------------------

UPDATE brand_translations t SET
    short_description = $c$Пополнение Mobile Legends (глобальный аккаунт) — алмазы по ID игрока и ID сервера, оплата в сумах, без пароля. Для российского аккаунта — страница Mobile Legends RU.$c$,
    description = $c$Mobile Legends: Bang Bang (MLBB) — мобильная MOBA от Moonton, где команды 5 на 5 сражаются на трёх линиях. Алмазы служат внутриигровой валютой: за них открывают героев и скины, покупают Starlight-подписку, боевой пропуск сезона и наборы событий.

YuPay пополняет аккаунт по публичному игровому ID и ID сервера — пароль и вход в аккаунт не нужны. Перед оплатой мы проверяем связку ID и сервера и показываем ник, который к ней привязан, чтобы алмазы не ушли чужому игроку. Оплатить можно в сумах картами Uzcard и Humo через Click, Payme или Uzum; курс виден до оплаты, а алмазы зачисляются автоматически после подтверждения платежа.

Важно: у Mobile Legends есть отдельный российский регион и глобальный. Регион задаётся при создании аккаунта и не меняется, поэтому пополнения между регионами не переходят. Эта страница — для глобального аккаунта; для российского аккаунта есть отдельная страница Mobile Legends RU — ссылка на неё над списком пакетов.$c$
FROM brands b WHERE b.id = t.brand_id AND b.slug = 'mobile-legends' AND t.locale = 'ru';

UPDATE brand_translations t SET
    short_description = $c$Top up Mobile Legends (global account) — diamonds by player ID and server ID, pay in sum, no password. Russian accounts: the Mobile Legends RU page.$c$,
    description = $c$Mobile Legends: Bang Bang (MLBB) is a mobile MOBA by Moonton where teams of five fight across three lanes. Diamonds are the in-game currency: they unlock heroes and skins, and buy the Starlight membership, the seasonal battle pass and event bundles.

YuPay tops up your account by its public player ID and server ID — no password and no account login needed. Before you pay we verify the ID and server pair and show you the nickname attached to it, so diamonds never land on a stranger's account. You can pay in Uzbek sum with Uzcard and Humo cards via Click, Payme or Uzum; the rate is shown before you pay, and diamonds are credited automatically once your payment is confirmed.

One thing to know: Mobile Legends has a separate Russian region alongside the global one. The region is fixed when an account is created and cannot be changed, so top-ups do not cross between them. This page is for a global account; a Russian account has its own page, Mobile Legends RU — the link is above the package list.$c$
FROM brands b WHERE b.id = t.brand_id AND b.slug = 'mobile-legends' AND t.locale = 'en';

UPDATE brand_translations t SET
    short_description = $c$Mobile Legends toʻldirish (global akkaunt) — olmoslar oʻyinchi ID va server ID orqali, soʻmda toʻlov, parolsiz. Rossiya akkaunti uchun — Mobile Legends RU sahifasi.$c$,
    description = $c$Mobile Legends: Bang Bang (MLBB) — Moonton kompaniyasining mobil MOBA oʻyini, unda jamoalar uch yoʻlakda 5 ga 5 jang qiladi. Olmoslar oʻyin ichidagi valyuta hisoblanadi: ularga qahramonlar va skinlar ochiladi, Starlight obunasi, mavsumiy jangovar pass va tadbir toʻplamlari sotib olinadi.

YuPay hisobingizni ochiq oʻyin ID va server ID orqali toʻldiradi — parol va akkauntga kirish talab qilinmaydi. Toʻlovdan oldin biz ID va server juftligini tekshirib, unga bogʻlangan nikni koʻrsatamiz, shunda olmoslar begona oʻyinchiga tushmaydi. Toʻlovni soʻmda Uzcard va Humo kartalari bilan Click, Payme yoki Uzum orqali amalga oshirishingiz mumkin; kurs toʻlovdan oldin koʻrinadi, olmoslar esa toʻlov tasdiqlangach avtomatik tushadi.

Muhim: Mobile Legends oʻyinida global regiondan tashqari alohida Rossiya regioni ham bor. Region akkaunt yaratilganda belgilanadi va oʻzgarmaydi, shuning uchun toʻldirishlar regionlar oʻrtasida oʻtmaydi. Bu sahifa global akkaunt uchun; Rossiya akkaunti uchun alohida Mobile Legends RU sahifasi bor — havola paketlar roʻyxati ustida.$c$
FROM brands b WHERE b.id = t.brand_id AND b.slug = 'mobile-legends' AND t.locale = 'uz';

UPDATE brand_translations t SET
    short_description = $c$Пополнение Magic Chess: Go Go (глобальный аккаунт) — алмазы по ID игрока и ID сервера, оплата в сумах, без пароля. Для российского аккаунта — страница Magic Chess: Go Go RU.$c$,
    description = $c$Magic Chess: Go Go (MCGG) — мобильный автобаттлер от Moonton по вселенной Mobile Legends: вы не управляете боем напрямую, а собираете состав и расставляете фигуры, а дальше раунд идёт сам. Алмазы служат внутриигровой валютой: за них открывают облики и скины, покупают наборы событий и сезонные пропуска.

YuPay пополняет аккаунт по публичному ID игрока и ID сервера — пароль и вход в аккаунт не нужны. Перед оплатой мы проверяем связку ID и сервера и показываем привязанный к ней ник, чтобы алмазы не ушли чужому игроку. Оплатить можно в сумах картами Uzcard и Humo через Click, Payme или Uzum; курс виден до оплаты, а алмазы зачисляются автоматически после подтверждения платежа.

Важно: у Magic Chess: Go Go есть отдельный российский регион и глобальный, и пополнения между ними не переходят. Эта страница — для глобального аккаунта; для российского аккаунта есть отдельная страница Magic Chess: Go Go RU — ссылка на неё над списком пакетов.$c$
FROM brands b WHERE b.id = t.brand_id AND b.slug = 'magic-chess-gogo' AND t.locale = 'ru';

UPDATE brand_translations t SET
    short_description = $c$Top up Magic Chess: Go Go (global account) — diamonds by player ID and server ID, pay in sum, no password. Russian accounts: the Magic Chess: Go Go RU page.$c$,
    description = $c$Magic Chess: Go Go (MCGG) is a mobile auto battler by Moonton set in the Mobile Legends universe: you do not control the fight directly, you assemble a line-up and place your pieces, and the round plays itself out. Diamonds are the in-game currency — they unlock looks and skins, and buy event bundles and seasonal passes.

YuPay tops up your account by its public player ID and server ID — no password and no account login needed. Before you pay we verify the ID and server pair and show you the nickname attached to it, so diamonds never land on a stranger's account. You can pay in Uzbek sum with Uzcard and Humo cards via Click, Payme or Uzum; the rate is shown before you pay, and diamonds are credited automatically once your payment is confirmed.

One thing to know: Magic Chess: Go Go has a separate Russian region alongside the global one, and top-ups do not cross between them. This page is for a global account; a Russian account has its own page, Magic Chess: Go Go RU — the link is above the package list.$c$
FROM brands b WHERE b.id = t.brand_id AND b.slug = 'magic-chess-gogo' AND t.locale = 'en';

UPDATE brand_translations t SET
    short_description = $c$Magic Chess: Go Go toʻldirish (global akkaunt) — olmoslar oʻyinchi ID va server ID orqali, soʻmda toʻlov, parolsiz. Rossiya akkaunti uchun — Magic Chess: Go Go RU sahifasi.$c$,
    description = $c$Magic Chess: Go Go (MCGG) — Moonton kompaniyasining Mobile Legends olamida qurilgan mobil avtobattleri: siz jangni bevosita boshqarmaysiz, balki tarkib toʻplab, figuralarni joylashtirasiz, raund esa oʻzi oʻtadi. Olmoslar oʻyin ichidagi valyuta hisoblanadi: ularga koʻrinishlar va skinlar ochiladi, tadbir toʻplamlari va mavsumiy passlar sotib olinadi.

YuPay hisobingizni ochiq oʻyinchi ID va server ID orqali toʻldiradi — parol va akkauntga kirish talab qilinmaydi. Toʻlovdan oldin biz ID va server juftligini tekshirib, unga bogʻlangan nikni koʻrsatamiz, shunda olmoslar begona oʻyinchiga tushmaydi. Toʻlovni soʻmda Uzcard va Humo kartalari bilan Click, Payme yoki Uzum orqali amalga oshirishingiz mumkin; kurs toʻlovdan oldin koʻrinadi, olmoslar esa toʻlov tasdiqlangach avtomatik tushadi.

Muhim: Magic Chess: Go Go oʻyinida global regiondan tashqari alohida Rossiya regioni bor va toʻldirishlar ular oʻrtasida oʻtmaydi. Bu sahifa global akkaunt uchun; Rossiya akkaunti uchun alohida Magic Chess: Go Go RU sahifasi bor — havola paketlar roʻyxati ustida.$c$
FROM brands b WHERE b.id = t.brand_id AND b.slug = 'magic-chess-gogo' AND t.locale = 'uz';

-- ---------------------------------------------------------------------------
-- 2. The two FAQs that told the customer to pick "the other product". Matched
--    by their question text (stable), not by sort_order (shifted once already).
-- ---------------------------------------------------------------------------

-- «Что выбрать — глобальный или российский аккаунт?» — Mobile Legends
UPDATE brand_faq_translations ft SET answer = $a$Если вы играете в Узбекистане или другой стране СНГ и скачали игру в обычном Google Play или App Store, у вас глобальный аккаунт — вы на нужной странице. Российский регион у Mobile Legends отдельный: он нужен тем, кто играет в российской версии игры (цены в игре в рублях). Регион задаётся при создании аккаунта и не меняется, поэтому пополнения между регионами не переходят. Для российского аккаунта откройте страницу Mobile Legends RU — ссылка над списком пакетов. Самый надёжный способ проверить — ввести ID игрока и ID сервера: мы покажем ник до оплаты, а если ник не находится, значит нужна страница другого региона.$a$
FROM brand_faqs f JOIN brands b ON b.id = f.brand_id
WHERE ft.brand_faq_id = f.id AND b.slug = 'mobile-legends' AND ft.locale = 'ru'
  AND ft.question = $q$Что выбрать — глобальный или российский аккаунт?$q$;

UPDATE brand_faq_translations ft SET answer = $a$If you play in Uzbekistan or another CIS country and installed the game from the ordinary Google Play or App Store, your account is global — you are on the right page. Mobile Legends runs a separate Russian region for players on the Russian version of the game (rouble prices in-game). The region is fixed when the account is created and cannot be changed, so top-ups do not cross between regions. For a Russian account open the Mobile Legends RU page — the link is above the package list. The surest way to check is to enter your player ID and server ID: we show the nickname before payment, and if no nickname is found you need the other region's page.$a$
FROM brand_faqs f JOIN brands b ON b.id = f.brand_id
WHERE ft.brand_faq_id = f.id AND b.slug = 'mobile-legends' AND ft.locale = 'en'
  AND ft.question = $q$Global or Russian account — which do I pick?$q$;

UPDATE brand_faq_translations ft SET answer = $a$Agar Oʻzbekistonda yoki boshqa MDH davlatida oʻynasangiz va oʻyinni oddiy Google Play yoki App Store'dan yuklagan boʻlsangiz, akkauntingiz global — siz kerakli sahifadasiz. Mobile Legends oʻyinining rus versiyasida oʻynaydiganlar uchun (oʻyindagi narxlar rublda) alohida Rossiya regioni bor. Region akkaunt yaratilganda belgilanadi va oʻzgarmaydi, shuning uchun toʻldirishlar regionlar oʻrtasida oʻtmaydi. Rossiya akkaunti uchun Mobile Legends RU sahifasini oching — havola paketlar roʻyxati ustida. Eng ishonchli usul — oʻyinchi ID va server ID kiritish: nikni toʻlovdan oldin koʻrsatamiz, agar nik topilmasa, boshqa region sahifasi kerak.$a$
FROM brand_faqs f JOIN brands b ON b.id = f.brand_id
WHERE ft.brand_faq_id = f.id AND b.slug = 'mobile-legends' AND ft.locale = 'uz'
  AND ft.question = $q$Global yoki Rossiya akkaunti — qaysi birini tanlash kerak?$q$;

-- «Что выбрать — глобальный или российский аккаунт?» — Magic Chess: Go Go
UPDATE brand_faq_translations ft SET answer = $a$Если вы играете в Узбекистане или другой стране СНГ и скачали игру в обычном Google Play или App Store, у вас глобальный аккаунт — вы на нужной странице. Российский регион у Magic Chess: Go Go отдельный: он нужен тем, кто играет в российской версии игры (цены в игре в рублях). Пополнения между регионами не переходят. Для российского аккаунта откройте страницу Magic Chess: Go Go RU — ссылка над списком пакетов. Самый надёжный способ проверить — ввести ID игрока и ID сервера: мы покажем ник до оплаты, а если ник не находится, значит нужна страница другого региона.$a$
FROM brand_faqs f JOIN brands b ON b.id = f.brand_id
WHERE ft.brand_faq_id = f.id AND b.slug = 'magic-chess-gogo' AND ft.locale = 'ru'
  AND ft.question = $q$Что выбрать — глобальный или российский аккаунт?$q$;

UPDATE brand_faq_translations ft SET answer = $a$If you play in Uzbekistan or another CIS country and installed the game from the ordinary Google Play or App Store, your account is global — you are on the right page. Magic Chess: Go Go runs a separate Russian region for players on the Russian version of the game (rouble prices in-game). Top-ups do not cross between regions. For a Russian account open the Magic Chess: Go Go RU page — the link is above the package list. The surest way to check is to enter your player ID and server ID: we show the nickname before payment, and if no nickname is found you need the other region's page.$a$
FROM brand_faqs f JOIN brands b ON b.id = f.brand_id
WHERE ft.brand_faq_id = f.id AND b.slug = 'magic-chess-gogo' AND ft.locale = 'en'
  AND ft.question = $q$Global or Russian account — which do I pick?$q$;

UPDATE brand_faq_translations ft SET answer = $a$Agar Oʻzbekistonda yoki boshqa MDH davlatida oʻynasangiz va oʻyinni oddiy Google Play yoki App Store'dan yuklagan boʻlsangiz, akkauntingiz global — siz kerakli sahifadasiz. Magic Chess: Go Go oʻyinining rus versiyasida oʻynaydiganlar uchun (oʻyindagi narxlar rublda) alohida Rossiya regioni bor. Toʻldirishlar regionlar oʻrtasida oʻtmaydi. Rossiya akkaunti uchun Magic Chess: Go Go RU sahifasini oching — havola paketlar roʻyxati ustida. Eng ishonchli usul — oʻyinchi ID va server ID kiritish: nikni toʻlovdan oldin koʻrsatamiz, agar nik topilmasa, boshqa region sahifasi kerak.$a$
FROM brand_faqs f JOIN brands b ON b.id = f.brand_id
WHERE ft.brand_faq_id = f.id AND b.slug = 'magic-chess-gogo' AND ft.locale = 'uz'
  AND ft.question = $q$Global yoki Rossiya akkaunti — qaysi birini tanlash kerak?$q$;

-- «Что будет, если выбрать не тот регион?» — identical text on both brands
UPDATE brand_faq_translations ft SET answer = $a$До оплаты — ничего: проверка просто не найдёт ник по вашей связке ID и сервера, и под полем появится подсказка перейти на страницу другого региона. Именно поэтому мы показываем ник перед оплатой. Если ник не находится ни на одной из двух страниц, проверьте, что ID и сервер скопированы полностью и без пробелов, и напишите в поддержку — разберёмся до того, как вы заплатите.$a$
FROM brand_faqs f JOIN brands b ON b.id = f.brand_id
WHERE ft.brand_faq_id = f.id AND b.slug IN ('mobile-legends', 'magic-chess-gogo') AND ft.locale = 'ru'
  AND ft.question = $q$Что будет, если выбрать не тот регион?$q$;

UPDATE brand_faq_translations ft SET answer = $a$Before payment, nothing: the check simply will not find a nickname for your ID and server pair, and a hint under the field points you to the other region's page. That is exactly why we show the nickname before you pay. If neither page finds a nickname, check that the ID and server were copied in full with no spaces, and message support — we will sort it out before you pay anything.$a$
FROM brand_faqs f JOIN brands b ON b.id = f.brand_id
WHERE ft.brand_faq_id = f.id AND b.slug IN ('mobile-legends', 'magic-chess-gogo') AND ft.locale = 'en'
  AND ft.question = $q$What happens if I pick the wrong region?$q$;

UPDATE brand_faq_translations ft SET answer = $a$Toʻlovdan oldin — hech nima: tekshiruv sizning ID va server juftligingiz boʻyicha nikni topa olmaydi va maydon ostida boshqa region sahifasiga oʻtish uchun koʻrsatma chiqadi. Aynan shuning uchun nikni toʻlovdan oldin koʻrsatamiz. Agar ikkala sahifada ham nik topilmasa, ID va server toʻliq, boʻshliqsiz nusxalanganini tekshiring va qoʻllab-quvvatlashga yozing — toʻlovdan oldin hal qilamiz.$a$
FROM brand_faqs f JOIN brands b ON b.id = f.brand_id
WHERE ft.brand_faq_id = f.id AND b.slug IN ('mobile-legends', 'magic-chess-gogo') AND ft.locale = 'uz'
  AND ft.question = $q$Notoʻgʻri region tanlansa nima boʻladi?$q$;

COMMIT;
