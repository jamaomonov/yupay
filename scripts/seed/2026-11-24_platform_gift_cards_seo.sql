-- SEO and activation content for the platform gift-card pages and Roblox's
-- regions (follows 2026-11-24_roblox_regions.sql and
-- 2026-11-24_platform_gift_card_regions.sql — run those first).
--
-- The one thing every platform page has to say: a card only redeems on an
-- account from its own country (Sony states it outright; Microsoft, Nintendo,
-- Apple and Google work the same way, and Roblox locks regional cards to the
-- account's currency). So the description ends on «pick your account's
-- country», the first FAQ says where to look the country up, and the second
-- answers the Uzbekistan question plainly.
--
-- Also renames the regional products «PlayStation (TR)» → «PlayStation · Турция»
-- to match their brands, and tells Roblox's page about its country cards.
--
-- Idempotent: translations are UPDATEd in place; the platforms' FAQs are
-- rebuilt; Roblox's country FAQ (sort 8) is replaced.
--
--   docker exec -i yupay-prod-postgres-1 psql -U yupay_app -d yupay -v ON_ERROR_STOP=1 \
--     < scripts/seed/2026-11-24_platform_gift_cards_seo.sql

BEGIN;

-- PlayStation Store (playstation)
UPDATE brand_translations SET
    seo_title = $c$Карты PlayStation Store (PSN) — купить в Узбекистане за сумы$c$,
    seo_description = $c$Подарочные карты PSN для аккаунтов США, Турции, Великобритании, Германии и других стран. Код приходит на почту сразу после оплаты. Оплата в сумах через Click, Payme или Uzum.$c$,
    short_description = $c$Подарочные карты PlayStation Store для аккаунта нужной страны. Код на почту, оплата в сумах.$c$,
    description = $c$Карта PlayStation Store пополняет кошелёк аккаунта PSN. На эти деньги покупают игры и дополнения, внутриигровую валюту и подписку PS Plus.

Карта работает только на аккаунте своей страны: американская — на американском, турецкая — на турецком. Выберите страну своего аккаунта в переключателе выше.$c$,
    instructions = $c$Как активировать код PlayStation Store:

1. На PS5 откройте PlayStation Store, нажмите «…» вверху и выберите «Активировать код». На PS4 — пункт «Активировать коды» в меню магазина. С компьютера — store.playstation.com, меню аватара → «Активировать код».
2. Введите 12-значный код из письма.
3. Подтвердите — сумма сразу зачислится на кошелёк.

Перед вводом проверьте, что вошли в аккаунт PSN той страны, карту которой купили. Код приходит на почту, указанную при заказе, сразу после оплаты. Если письма нет — проверьте «Спам» и «Промоакции».$c$,
    highlights = $c$["Оплата в сумах", "Код на почту", "Страна на выбор", "Без пароля"]$c$::json
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'playstation') AND locale = 'ru';
UPDATE brand_translations SET
    seo_title = $c$PlayStation Store (PSN) gift cards — buy in Uzbekistan for soʻm$c$,
    seo_description = $c$PSN gift cards for US, Turkish, UK, German and other accounts. The code arrives by email right after payment. Pay in soʻm with Click, Payme or Uzum.$c$,
    short_description = $c$PlayStation Store gift cards for your account's country. Code by email, pay in soʻm.$c$,
    description = $c$A PlayStation Store card tops up your PSN wallet. The balance buys games and add-ons, in-game currency and PS Plus.

A card only works on an account from its own country: a US card on a US account, a Turkish card on a Turkish one. Pick your account's country in the switcher above.$c$,
    instructions = $c$How to redeem your PlayStation Store code:

1. On PS5 open PlayStation Store, press «…» at the top and choose Redeem Code. On PS4 use Redeem Codes in the store menu. On a computer go to store.playstation.com, avatar menu → Redeem Code.
2. Enter the 12-character code from the email.
3. Confirm — the amount lands in your wallet at once.

Before entering it, make sure you are signed in to the PSN account from the card's country. The code is emailed to the address on the order right after payment. If it has not arrived, check Spam and Promotions.$c$,
    highlights = $c$["Pay in UZS", "Code by email", "Pick your country", "No password"]$c$::json
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'playstation') AND locale = 'en';
UPDATE brand_translations SET
    seo_title = $c$PlayStation Store (PSN) kartalari — Oʻzbekistonda soʻmga sotib olish$c$,
    seo_description = $c$AQSH, Turkiya, Buyuk Britaniya, Germaniya va boshqa davlatlar akkauntlari uchun PSN kartalari. Kod toʻlovdan soʻng darhol pochtaga keladi. Click, Payme yoki Uzum orqali soʻmda toʻlov.$c$,
    short_description = $c$Kerakli davlat akkaunti uchun PlayStation Store sovgʻa kartalari. Kod pochtaga, soʻmda toʻlov.$c$,
    description = $c$PlayStation Store kartasi PSN akkaunti hamyonini toʻldiradi. Bu pulga oʻyinlar va qoʻshimchalar, oʻyin valyutasi va PS Plus obunasi olinadi.

Karta faqat oʻz davlati akkauntida ishlaydi: amerikacha — amerikacha akkauntda, turkcha — turkcha akkauntda. Yuqoridagi tanlagichda akkauntingiz davlatini tanlang.$c$,
    instructions = $c$PlayStation Store kodini qanday faollashtirish:

1. PS5 da PlayStation Store ni oching, yuqoridagi «…» ni bosing va «Redeem Code» ni tanlang. PS4 da — doʻkon menyusidagi «Redeem Codes». Kompyuterda — store.playstation.com, avatar menyusi → «Redeem Code».
2. Xatdagi 12 belgili kodni kiriting.
3. Tasdiqlang — summa darhol hamyonga tushadi.

Kiritishdan oldin karta davlatidagi PSN akkauntiga kirganingizni tekshiring. Kod toʻlovdan soʻng darhol buyurtmadagi pochtaga keladi. Xat kelmasa — «Spam» va «Promotions» papkalarini tekshiring.$c$,
    highlights = $c$["Soʻmda toʻlov", "Kod pochtaga", "Davlatni tanlang", "Parolsiz"]$c$::json
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'playstation') AND locale = 'uz';
DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'playstation');
WITH nf AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), b.id, v.so, true
      FROM brands b, (VALUES (1), (2), (3), (4)) AS v(so)
     WHERE b.slug = 'playstation'
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
  FROM nf JOIN (VALUES
    (1, 'ru', $q$Карту какой страны выбрать?$q$, $a$Той, в которой зарегистрирован ваш аккаунт: карта другой страны не активируется. Страну аккаунта PSN видно в настройках консоли: «Пользователи и учётные записи» → «Учётная запись» → «Профиль». Её задают при регистрации, сменить потом нельзя.$a$),
    (1, 'en', $q$Which country's card do I need?$q$, $a$The country your account is registered in: a card from another country will not redeem. Your PSN account's country is in the console settings: Users and Accounts → Account → Profile. It is set at sign-up and cannot be changed later.$a$),
    (1, 'uz', $q$Qaysi davlat kartasini tanlash kerak?$q$, $a$Akkauntingiz roʻyxatdan oʻtgan davlatnikini: boshqa davlat kartasi faollashmaydi. PSN akkaunti davlati konsol sozlamalarida: «Users and Accounts» → «Account» → «Profile». U roʻyxatdan oʻtishda belgilanadi va keyin oʻzgartirib boʻlmaydi.$a$),
    (2, 'ru', $q$Подойдёт ли карта для аккаунта из Узбекистана?$q$, $a$Нет: карта работает только на аккаунте своей страны, а карт для Узбекистана нет. Подойдёт аккаунт одной из стран в переключателе — например, США или Турции.$a$),
    (2, 'en', $q$Will a card work on an account from Uzbekistan?$q$, $a$No: a card only works on an account from its own country, and there are no cards for Uzbekistan. You need an account from one of the countries in the switcher, such as the US or Turkey.$a$),
    (2, 'uz', $q$Karta Oʻzbekiston akkauntiga mos keladimi?$q$, $a$Yoʻq: karta faqat oʻz davlati akkauntida ishlaydi, Oʻzbekiston uchun esa karta yoʻq. Tanlagichdagi davlatlardan birining akkaunti kerak — masalan, AQSH yoki Turkiya.$a$),
    (3, 'ru', $q$Когда придёт код?$q$, $a$Код приходит на почту, указанную при заказе, сразу после оплаты. Если письма нет — проверьте «Спам» и «Промоакции».$a$),
    (3, 'en', $q$When will I get the code?$q$, $a$The code is emailed to the address on the order right after payment. If it has not arrived, check Spam and Promotions.$a$),
    (3, 'uz', $q$Kod qachon keladi?$q$, $a$Kod toʻlovdan soʻng darhol buyurtmadagi pochtaga keladi. Xat kelmasa — «Spam» va «Promotions» papkalarini tekshiring.$a$),
    (4, 'ru', $q$Как оплатить карту PlayStation Store?$q$, $a$Оплата в сумах через Click, Payme или Uzum. Итог в сумах виден до подтверждения, комиссии сверху нет.$a$),
    (4, 'en', $q$How do I pay for a PlayStation Store card?$q$, $a$Pay in soʻm with Click, Payme or Uzum. The total in soʻm is shown before you confirm, with no extra fee.$a$),
    (4, 'uz', $q$PlayStation Store kartasini qanday toʻlash mumkin?$q$, $a$Click, Payme yoki Uzum orqali soʻmda toʻlov. Yakuniy summa soʻmda tasdiqlashdan oldin koʻrinadi, ustiga komissiya yoʻq.$a$)
) AS t(so, locale, question, answer) ON t.so = nf.sort_order;

-- Xbox (xbox)
UPDATE brand_translations SET
    seo_title = $c$Карты Xbox — купить подарочную карту в Узбекистане за сумы$c$,
    seo_description = $c$Подарочные карты Xbox для аккаунтов Microsoft США, Турции, Европы, Великобритании и других стран. Код на почту сразу после оплаты. Оплата в сумах через Click, Payme или Uzum.$c$,
    short_description = $c$Подарочные карты Xbox для аккаунта Microsoft нужной страны. Код на почту, оплата в сумах.$c$,
    description = $c$Карта Xbox пополняет баланс аккаунта Microsoft. На него покупают игры и дополнения в Microsoft Store на Xbox и Windows, внутриигровую валюту и подписки.

Карта работает только на аккаунте своей страны. Выберите страну своего аккаунта в переключателе выше.$c$,
    instructions = $c$Как активировать код Xbox:

1. Откройте redeem.microsoft.com и войдите в свой аккаунт Microsoft. На консоли — Microsoft Store → «Использовать код».
2. Введите 25-значный код из письма.
3. Подтвердите — сумма зачислится на баланс аккаунта.

Перед вводом проверьте, что вошли в аккаунт Microsoft той страны, карту которой купили. Код приходит на почту, указанную при заказе, сразу после оплаты. Если письма нет — проверьте «Спам» и «Промоакции».$c$,
    highlights = $c$["Оплата в сумах", "Код на почту", "Страна на выбор", "Без пароля"]$c$::json
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'xbox') AND locale = 'ru';
UPDATE brand_translations SET
    seo_title = $c$Xbox gift cards — buy in Uzbekistan for soʻm$c$,
    seo_description = $c$Xbox gift cards for Microsoft accounts in the US, Turkey, Europe, the UK and more. Code by email right after payment. Pay in soʻm with Click, Payme or Uzum.$c$,
    short_description = $c$Xbox gift cards for your Microsoft account's country. Code by email, pay in soʻm.$c$,
    description = $c$An Xbox card tops up your Microsoft account balance. It buys games and add-ons in the Microsoft Store on Xbox and Windows, in-game currency and subscriptions.

A card only works on an account from its own country. Pick your account's country in the switcher above.$c$,
    instructions = $c$How to redeem your Xbox code:

1. Open redeem.microsoft.com and sign in to your Microsoft account. On the console: Microsoft Store → Redeem.
2. Enter the 25-character code from the email.
3. Confirm — the amount lands on your account balance.

Before entering it, make sure you are signed in to the Microsoft account from the card's country. The code is emailed to the address on the order right after payment. If it has not arrived, check Spam and Promotions.$c$,
    highlights = $c$["Pay in UZS", "Code by email", "Pick your country", "No password"]$c$::json
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'xbox') AND locale = 'en';
UPDATE brand_translations SET
    seo_title = $c$Xbox sovgʻa kartalari — Oʻzbekistonda soʻmga sotib olish$c$,
    seo_description = $c$AQSH, Turkiya, Yevropa, Buyuk Britaniya va boshqa davlatlar Microsoft akkauntlari uchun Xbox kartalari. Kod toʻlovdan soʻng pochtaga. Click, Payme yoki Uzum orqali soʻmda toʻlov.$c$,
    short_description = $c$Kerakli davlat Microsoft akkaunti uchun Xbox kartalari. Kod pochtaga, soʻmda toʻlov.$c$,
    description = $c$Xbox kartasi Microsoft akkaunti balansini toʻldiradi. Unga Xbox va Windows dagi Microsoft Store da oʻyinlar va qoʻshimchalar, oʻyin valyutasi va obunalar olinadi.

Karta faqat oʻz davlati akkauntida ishlaydi. Yuqoridagi tanlagichda akkauntingiz davlatini tanlang.$c$,
    instructions = $c$Xbox kodini qanday faollashtirish:

1. redeem.microsoft.com ni oching va Microsoft akkauntingizga kiring. Konsolda — Microsoft Store → «Redeem».
2. Xatdagi 25 belgili kodni kiriting.
3. Tasdiqlang — summa akkaunt balansiga tushadi.

Kiritishdan oldin karta davlatidagi Microsoft akkauntiga kirganingizni tekshiring. Kod toʻlovdan soʻng darhol buyurtmadagi pochtaga keladi. Xat kelmasa — «Spam» va «Promotions» papkalarini tekshiring.$c$,
    highlights = $c$["Soʻmda toʻlov", "Kod pochtaga", "Davlatni tanlang", "Parolsiz"]$c$::json
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'xbox') AND locale = 'uz';
DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'xbox');
WITH nf AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), b.id, v.so, true
      FROM brands b, (VALUES (1), (2), (3), (4)) AS v(so)
     WHERE b.slug = 'xbox'
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
  FROM nf JOIN (VALUES
    (1, 'ru', $q$Карту какой страны выбрать?$q$, $a$Той, в которой зарегистрирован ваш аккаунт: карта другой страны не активируется. Страну аккаунта видно на account.microsoft.com в разделе «Ваши сведения» → «Страна или регион».$a$),
    (1, 'en', $q$Which country's card do I need?$q$, $a$The country your account is registered in: a card from another country will not redeem. Your account's country is on account.microsoft.com under Your info → Country or region.$a$),
    (1, 'uz', $q$Qaysi davlat kartasini tanlash kerak?$q$, $a$Akkauntingiz roʻyxatdan oʻtgan davlatnikini: boshqa davlat kartasi faollashmaydi. Akkaunt davlati account.microsoft.com da «Your info» → «Country or region» boʻlimida.$a$),
    (2, 'ru', $q$Подойдёт ли карта для аккаунта из Узбекистана?$q$, $a$Нет: карта работает только на аккаунте своей страны, а карт для Узбекистана нет. Подойдёт аккаунт одной из стран в переключателе — например, США или Турции.$a$),
    (2, 'en', $q$Will a card work on an account from Uzbekistan?$q$, $a$No: a card only works on an account from its own country, and there are no cards for Uzbekistan. You need an account from one of the countries in the switcher, such as the US or Turkey.$a$),
    (2, 'uz', $q$Karta Oʻzbekiston akkauntiga mos keladimi?$q$, $a$Yoʻq: karta faqat oʻz davlati akkauntida ishlaydi, Oʻzbekiston uchun esa karta yoʻq. Tanlagichdagi davlatlardan birining akkaunti kerak — masalan, AQSH yoki Turkiya.$a$),
    (3, 'ru', $q$Когда придёт код?$q$, $a$Код приходит на почту, указанную при заказе, сразу после оплаты. Если письма нет — проверьте «Спам» и «Промоакции».$a$),
    (3, 'en', $q$When will I get the code?$q$, $a$The code is emailed to the address on the order right after payment. If it has not arrived, check Spam and Promotions.$a$),
    (3, 'uz', $q$Kod qachon keladi?$q$, $a$Kod toʻlovdan soʻng darhol buyurtmadagi pochtaga keladi. Xat kelmasa — «Spam» va «Promotions» papkalarini tekshiring.$a$),
    (4, 'ru', $q$Как оплатить карту Xbox?$q$, $a$Оплата в сумах через Click, Payme или Uzum. Итог в сумах виден до подтверждения, комиссии сверху нет.$a$),
    (4, 'en', $q$How do I pay for a Xbox card?$q$, $a$Pay in soʻm with Click, Payme or Uzum. The total in soʻm is shown before you confirm, with no extra fee.$a$),
    (4, 'uz', $q$Xbox kartasini qanday toʻlash mumkin?$q$, $a$Click, Payme yoki Uzum orqali soʻmda toʻlov. Yakuniy summa soʻmda tasdiqlashdan oldin koʻrinadi, ustiga komissiya yoʻq.$a$)
) AS t(so, locale, question, answer) ON t.so = nf.sort_order;

-- Nintendo eShop (nintendo)
UPDATE brand_translations SET
    seo_title = $c$Карты Nintendo eShop — купить в Узбекистане за сумы$c$,
    seo_description = $c$Подарочные карты Nintendo eShop для Switch: аккаунты США, Европы, Великобритании, Японии и других стран. Код на почту сразу после оплаты. Оплата в сумах через Click, Payme или Uzum.$c$,
    short_description = $c$Подарочные карты Nintendo eShop для аккаунта нужной страны. Код на почту, оплата в сумах.$c$,
    description = $c$Карта Nintendo eShop пополняет баланс аккаунта Nintendo. На него покупают игры и дополнения для Nintendo Switch.

Карта работает только на аккаунте своей страны. Выберите страну своего аккаунта в переключателе выше.$c$,
    instructions = $c$Как активировать код Nintendo eShop:

1. На Switch откройте Nintendo eShop и выберите свой профиль.
2. Слева выберите «Активировать код» и введите 16-значный код из письма.
3. Подтвердите — сумма зачислится на баланс eShop.

Перед вводом проверьте, что вошли в аккаунт Nintendo той страны, карту которой купили. Код приходит на почту, указанную при заказе, сразу после оплаты. Если письма нет — проверьте «Спам» и «Промоакции».$c$,
    highlights = $c$["Оплата в сумах", "Код на почту", "Страна на выбор", "Без пароля"]$c$::json
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'nintendo') AND locale = 'ru';
UPDATE brand_translations SET
    seo_title = $c$Nintendo eShop gift cards — buy in Uzbekistan for soʻm$c$,
    seo_description = $c$Nintendo eShop gift cards for Switch: US, European, UK, Japanese and other accounts. Code by email right after payment. Pay in soʻm with Click, Payme or Uzum.$c$,
    short_description = $c$Nintendo eShop gift cards for your account's country. Code by email, pay in soʻm.$c$,
    description = $c$A Nintendo eShop card tops up your Nintendo Account balance. It buys games and add-ons for Nintendo Switch.

A card only works on an account from its own country. Pick your account's country in the switcher above.$c$,
    instructions = $c$How to redeem your Nintendo eShop code:

1. On Switch open Nintendo eShop and pick your profile.
2. Choose Redeem Code on the left and enter the 16-character code from the email.
3. Confirm — the amount lands on your eShop balance.

Before entering it, make sure you are signed in to the Nintendo Account from the card's country. The code is emailed to the address on the order right after payment. If it has not arrived, check Spam and Promotions.$c$,
    highlights = $c$["Pay in UZS", "Code by email", "Pick your country", "No password"]$c$::json
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'nintendo') AND locale = 'en';
UPDATE brand_translations SET
    seo_title = $c$Nintendo eShop kartalari — Oʻzbekistonda soʻmga sotib olish$c$,
    seo_description = $c$Switch uchun Nintendo eShop kartalari: AQSH, Yevropa, Buyuk Britaniya, Yaponiya va boshqa akkauntlar. Kod toʻlovdan soʻng pochtaga. Click, Payme yoki Uzum orqali soʻmda toʻlov.$c$,
    short_description = $c$Kerakli davlat akkaunti uchun Nintendo eShop kartalari. Kod pochtaga, soʻmda toʻlov.$c$,
    description = $c$Nintendo eShop kartasi Nintendo akkaunti balansini toʻldiradi. Unga Nintendo Switch uchun oʻyinlar va qoʻshimchalar olinadi.

Karta faqat oʻz davlati akkauntida ishlaydi. Yuqoridagi tanlagichda akkauntingiz davlatini tanlang.$c$,
    instructions = $c$Nintendo eShop kodini qanday faollashtirish:

1. Switch da Nintendo eShop ni oching va profilingizni tanlang.
2. Chapda «Redeem Code» ni tanlang va xatdagi 16 belgili kodni kiriting.
3. Tasdiqlang — summa eShop balansiga tushadi.

Kiritishdan oldin karta davlatidagi Nintendo akkauntiga kirganingizni tekshiring. Kod toʻlovdan soʻng darhol buyurtmadagi pochtaga keladi. Xat kelmasa — «Spam» va «Promotions» papkalarini tekshiring.$c$,
    highlights = $c$["Soʻmda toʻlov", "Kod pochtaga", "Davlatni tanlang", "Parolsiz"]$c$::json
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'nintendo') AND locale = 'uz';
DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'nintendo');
WITH nf AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), b.id, v.so, true
      FROM brands b, (VALUES (1), (2), (3), (4)) AS v(so)
     WHERE b.slug = 'nintendo'
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
  FROM nf JOIN (VALUES
    (1, 'ru', $q$Карту какой страны выбрать?$q$, $a$Той, в которой зарегистрирован ваш аккаунт: карта другой страны не активируется. Страну аккаунта видно на accounts.nintendo.com в разделе «Информация о пользователе» → «Страна/регион проживания».$a$),
    (1, 'en', $q$Which country's card do I need?$q$, $a$The country your account is registered in: a card from another country will not redeem. Your account's country is on accounts.nintendo.com under User info → Country/region of residence.$a$),
    (1, 'uz', $q$Qaysi davlat kartasini tanlash kerak?$q$, $a$Akkauntingiz roʻyxatdan oʻtgan davlatnikini: boshqa davlat kartasi faollashmaydi. Akkaunt davlati accounts.nintendo.com da «User info» → «Country/region of residence» boʻlimida.$a$),
    (2, 'ru', $q$Подойдёт ли карта для аккаунта из Узбекистана?$q$, $a$Нет: карта работает только на аккаунте своей страны, а карт для Узбекистана нет. Подойдёт аккаунт одной из стран в переключателе — например, США или Турции.$a$),
    (2, 'en', $q$Will a card work on an account from Uzbekistan?$q$, $a$No: a card only works on an account from its own country, and there are no cards for Uzbekistan. You need an account from one of the countries in the switcher, such as the US or Turkey.$a$),
    (2, 'uz', $q$Karta Oʻzbekiston akkauntiga mos keladimi?$q$, $a$Yoʻq: karta faqat oʻz davlati akkauntida ishlaydi, Oʻzbekiston uchun esa karta yoʻq. Tanlagichdagi davlatlardan birining akkaunti kerak — masalan, AQSH yoki Turkiya.$a$),
    (3, 'ru', $q$Когда придёт код?$q$, $a$Код приходит на почту, указанную при заказе, сразу после оплаты. Если письма нет — проверьте «Спам» и «Промоакции».$a$),
    (3, 'en', $q$When will I get the code?$q$, $a$The code is emailed to the address on the order right after payment. If it has not arrived, check Spam and Promotions.$a$),
    (3, 'uz', $q$Kod qachon keladi?$q$, $a$Kod toʻlovdan soʻng darhol buyurtmadagi pochtaga keladi. Xat kelmasa — «Spam» va «Promotions» papkalarini tekshiring.$a$),
    (4, 'ru', $q$Как оплатить карту Nintendo eShop?$q$, $a$Оплата в сумах через Click, Payme или Uzum. Итог в сумах виден до подтверждения, комиссии сверху нет.$a$),
    (4, 'en', $q$How do I pay for a Nintendo eShop card?$q$, $a$Pay in soʻm with Click, Payme or Uzum. The total in soʻm is shown before you confirm, with no extra fee.$a$),
    (4, 'uz', $q$Nintendo eShop kartasini qanday toʻlash mumkin?$q$, $a$Click, Payme yoki Uzum orqali soʻmda toʻlov. Yakuniy summa soʻmda tasdiqlashdan oldin koʻrinadi, ustiga komissiya yoʻq.$a$)
) AS t(so, locale, question, answer) ON t.so = nf.sort_order;

-- App Store & iTunes (app-store)
UPDATE brand_translations SET
    seo_title = $c$Пополнить Apple ID — подарочные карты App Store в Узбекистане$c$,
    seo_description = $c$Подарочные карты App Store & iTunes для Apple ID США, Турции, Великобритании и других стран. Для приложений, подписок и iCloud+. Код на почту, оплата в сумах через Click, Payme или Uzum.$c$,
    short_description = $c$Подарочные карты App Store & iTunes для Apple ID нужной страны. Код на почту, оплата в сумах.$c$,
    description = $c$Карта App Store & iTunes пополняет баланс Apple ID. С него оплачивают приложения и игры, покупки внутри них, подписки Apple Music, iCloud+ и другие.

Карта работает только на Apple ID своей страны. Выберите страну своего Apple ID в переключателе выше.$c$,
    instructions = $c$Как активировать код App Store & iTunes:

1. На iPhone или iPad откройте App Store и нажмите на фото профиля вверху.
2. Выберите «Погасить подарочную карту или код» → «Ввести код вручную» и введите код из письма.
3. Сумма сразу зачислится на баланс Apple ID.

Перед вводом проверьте, что вошли в Apple ID той страны, карту которой купили. Код приходит на почту, указанную при заказе, сразу после оплаты. Если письма нет — проверьте «Спам» и «Промоакции».$c$,
    highlights = $c$["Оплата в сумах", "Код на почту", "Страна на выбор", "Без пароля"]$c$::json
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'app-store') AND locale = 'ru';
UPDATE brand_translations SET
    seo_title = $c$Top up your Apple Account — App Store gift cards in Uzbekistan$c$,
    seo_description = $c$App Store & iTunes gift cards for US, Turkish, UK and other Apple Accounts. For apps, subscriptions and iCloud+. Code by email, pay in soʻm with Click, Payme or Uzum.$c$,
    short_description = $c$App Store & iTunes gift cards for your Apple Account's country. Code by email, pay in soʻm.$c$,
    description = $c$An App Store & iTunes card tops up your Apple Account balance. It pays for apps and games, in-app purchases, and subscriptions such as Apple Music and iCloud+.

A card only works on an Apple Account from its own country. Pick your account's country in the switcher above.$c$,
    instructions = $c$How to redeem your App Store & iTunes code:

1. On iPhone or iPad open the App Store and tap your profile photo at the top.
2. Choose Redeem Gift Card or Code → Enter Code Manually and type the code from the email.
3. The amount lands on your Apple Account balance at once.

Before entering it, make sure you are signed in to the Apple Account from the card's country. The code is emailed to the address on the order right after payment. If it has not arrived, check Spam and Promotions.$c$,
    highlights = $c$["Pay in UZS", "Code by email", "Pick your country", "No password"]$c$::json
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'app-store') AND locale = 'en';
UPDATE brand_translations SET
    seo_title = $c$Apple ID ni toʻldirish — Oʻzbekistonda App Store kartalari$c$,
    seo_description = $c$AQSH, Turkiya, Buyuk Britaniya va boshqa davlatlar Apple ID lari uchun App Store & iTunes kartalari. Ilovalar, obunalar va iCloud+ uchun. Kod pochtaga, Click, Payme yoki Uzum orqali soʻmda toʻlov.$c$,
    short_description = $c$Kerakli davlat Apple ID si uchun App Store & iTunes kartalari. Kod pochtaga, soʻmda toʻlov.$c$,
    description = $c$App Store & iTunes kartasi Apple ID balansini toʻldiradi. Undan ilovalar va oʻyinlar, ular ichidagi xaridlar, Apple Music, iCloud+ va boshqa obunalar toʻlanadi.

Karta faqat oʻz davlati Apple ID sida ishlaydi. Yuqoridagi tanlagichda Apple ID davlatini tanlang.$c$,
    instructions = $c$App Store & iTunes kodini qanday faollashtirish:

1. iPhone yoki iPad da App Store ni oching va yuqoridagi profil rasmini bosing.
2. «Redeem Gift Card or Code» → «Enter Code Manually» ni tanlang va xatdagi kodni kiriting.
3. Summa darhol Apple ID balansiga tushadi.

Kiritishdan oldin karta davlatidagi Apple IDga kirganingizni tekshiring. Kod toʻlovdan soʻng darhol buyurtmadagi pochtaga keladi. Xat kelmasa — «Spam» va «Promotions» papkalarini tekshiring.$c$,
    highlights = $c$["Soʻmda toʻlov", "Kod pochtaga", "Davlatni tanlang", "Parolsiz"]$c$::json
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'app-store') AND locale = 'uz';
DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'app-store');
WITH nf AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), b.id, v.so, true
      FROM brands b, (VALUES (1), (2), (3), (4)) AS v(so)
     WHERE b.slug = 'app-store'
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
  FROM nf JOIN (VALUES
    (1, 'ru', $q$Карту какой страны выбрать?$q$, $a$Той, в которой зарегистрирован ваш аккаунт: карта другой страны не активируется. Страну Apple ID видно в «Настройки» → ваше имя → «Медиаматериалы и покупки» → «Просмотреть» → «Страна или регион».$a$),
    (1, 'en', $q$Which country's card do I need?$q$, $a$The country your account is registered in: a card from another country will not redeem. Your Apple Account's country is in Settings → your name → Media & Purchases → View Account → Country/Region.$a$),
    (1, 'uz', $q$Qaysi davlat kartasini tanlash kerak?$q$, $a$Akkauntingiz roʻyxatdan oʻtgan davlatnikini: boshqa davlat kartasi faollashmaydi. Apple ID davlati «Settings» → ismingiz → «Media & Purchases» → «View Account» → «Country/Region» da.$a$),
    (2, 'ru', $q$Подойдёт ли карта для аккаунта из Узбекистана?$q$, $a$Нет: карта работает только на аккаунте своей страны, а карт для Узбекистана нет. Подойдёт аккаунт одной из стран в переключателе — например, США или Турции.$a$),
    (2, 'en', $q$Will a card work on an account from Uzbekistan?$q$, $a$No: a card only works on an account from its own country, and there are no cards for Uzbekistan. You need an account from one of the countries in the switcher, such as the US or Turkey.$a$),
    (2, 'uz', $q$Karta Oʻzbekiston akkauntiga mos keladimi?$q$, $a$Yoʻq: karta faqat oʻz davlati akkauntida ishlaydi, Oʻzbekiston uchun esa karta yoʻq. Tanlagichdagi davlatlardan birining akkaunti kerak — masalan, AQSH yoki Turkiya.$a$),
    (3, 'ru', $q$Когда придёт код?$q$, $a$Код приходит на почту, указанную при заказе, сразу после оплаты. Если письма нет — проверьте «Спам» и «Промоакции».$a$),
    (3, 'en', $q$When will I get the code?$q$, $a$The code is emailed to the address on the order right after payment. If it has not arrived, check Spam and Promotions.$a$),
    (3, 'uz', $q$Kod qachon keladi?$q$, $a$Kod toʻlovdan soʻng darhol buyurtmadagi pochtaga keladi. Xat kelmasa — «Spam» va «Promotions» papkalarini tekshiring.$a$),
    (4, 'ru', $q$Как оплатить карту App Store & iTunes?$q$, $a$Оплата в сумах через Click, Payme или Uzum. Итог в сумах виден до подтверждения, комиссии сверху нет.$a$),
    (4, 'en', $q$How do I pay for a App Store & iTunes card?$q$, $a$Pay in soʻm with Click, Payme or Uzum. The total in soʻm is shown before you confirm, with no extra fee.$a$),
    (4, 'uz', $q$App Store & iTunes kartasini qanday toʻlash mumkin?$q$, $a$Click, Payme yoki Uzum orqali soʻmda toʻlov. Yakuniy summa soʻmda tasdiqlashdan oldin koʻrinadi, ustiga komissiya yoʻq.$a$)
) AS t(so, locale, question, answer) ON t.so = nf.sort_order;

-- Google Play (google-play)
UPDATE brand_translations SET
    seo_title = $c$Карты Google Play — пополнить аккаунт в Узбекистане за сумы$c$,
    seo_description = $c$Подарочные карты Google Play для аккаунтов США, Турции, Великобритании, Германии и других стран. Для игр, приложений и подписок. Код на почту, оплата в сумах через Click, Payme или Uzum.$c$,
    short_description = $c$Подарочные карты Google Play для аккаунта нужной страны. Код на почту, оплата в сумах.$c$,
    description = $c$Карта Google Play пополняет баланс аккаунта Google. С него оплачивают игры и приложения, покупки внутри них и подписки в Google Play.

Карта работает только на аккаунте своей страны. Выберите страну своего аккаунта в переключателе выше.$c$,
    instructions = $c$Как активировать код Google Play:

1. Откройте play.google.com/redeem или приложение Google Play → фото профиля → «Платежи и подписки» → «Активировать подарочный код».
2. Введите код из письма.
3. Подтвердите — сумма зачислится на баланс Google Play.

Перед вводом проверьте, что вошли в аккаунт Google той страны, карту которой купили. Код приходит на почту, указанную при заказе, сразу после оплаты. Если письма нет — проверьте «Спам» и «Промоакции».$c$,
    highlights = $c$["Оплата в сумах", "Код на почту", "Страна на выбор", "Без пароля"]$c$::json
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'google-play') AND locale = 'ru';
UPDATE brand_translations SET
    seo_title = $c$Google Play gift cards — top up in Uzbekistan for soʻm$c$,
    seo_description = $c$Google Play gift cards for US, Turkish, UK, German and other accounts. For games, apps and subscriptions. Code by email, pay in soʻm with Click, Payme or Uzum.$c$,
    short_description = $c$Google Play gift cards for your account's country. Code by email, pay in soʻm.$c$,
    description = $c$A Google Play card tops up your Google account balance. It pays for games and apps, in-app purchases and subscriptions on Google Play.

A card only works on an account from its own country. Pick your account's country in the switcher above.$c$,
    instructions = $c$How to redeem your Google Play code:

1. Open play.google.com/redeem, or the Google Play app → profile photo → Payments & subscriptions → Redeem gift code.
2. Enter the code from the email.
3. Confirm — the amount lands on your Google Play balance.

Before entering it, make sure you are signed in to the Google account from the card's country. The code is emailed to the address on the order right after payment. If it has not arrived, check Spam and Promotions.$c$,
    highlights = $c$["Pay in UZS", "Code by email", "Pick your country", "No password"]$c$::json
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'google-play') AND locale = 'en';
UPDATE brand_translations SET
    seo_title = $c$Google Play kartalari — Oʻzbekistonda soʻmga toʻldirish$c$,
    seo_description = $c$AQSH, Turkiya, Buyuk Britaniya, Germaniya va boshqa davlatlar akkauntlari uchun Google Play kartalari. Oʻyinlar, ilovalar va obunalar uchun. Kod pochtaga, Click, Payme yoki Uzum orqali soʻmda toʻlov.$c$,
    short_description = $c$Kerakli davlat akkaunti uchun Google Play kartalari. Kod pochtaga, soʻmda toʻlov.$c$,
    description = $c$Google Play kartasi Google akkaunti balansini toʻldiradi. Undan Google Play dagi oʻyinlar va ilovalar, ular ichidagi xaridlar va obunalar toʻlanadi.

Karta faqat oʻz davlati akkauntida ishlaydi. Yuqoridagi tanlagichda akkauntingiz davlatini tanlang.$c$,
    instructions = $c$Google Play kodini qanday faollashtirish:

1. play.google.com/redeem ni yoki Google Play ilovasini oching → profil rasmi → «Payments & subscriptions» → «Redeem gift code».
2. Xatdagi kodni kiriting.
3. Tasdiqlang — summa Google Play balansiga tushadi.

Kiritishdan oldin karta davlatidagi Google akkauntiga kirganingizni tekshiring. Kod toʻlovdan soʻng darhol buyurtmadagi pochtaga keladi. Xat kelmasa — «Spam» va «Promotions» papkalarini tekshiring.$c$,
    highlights = $c$["Soʻmda toʻlov", "Kod pochtaga", "Davlatni tanlang", "Parolsiz"]$c$::json
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'google-play') AND locale = 'uz';
DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'google-play');
WITH nf AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), b.id, v.so, true
      FROM brands b, (VALUES (1), (2), (3), (4)) AS v(so)
     WHERE b.slug = 'google-play'
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
  FROM nf JOIN (VALUES
    (1, 'ru', $q$Карту какой страны выбрать?$q$, $a$Той, в которой зарегистрирован ваш аккаунт: карта другой страны не активируется. Страну аккаунта видно в Google Play: фото профиля → «Настройки» → «Общие» → «Настройки аккаунта и устройства» → «Страна и профили».$a$),
    (1, 'en', $q$Which country's card do I need?$q$, $a$The country your account is registered in: a card from another country will not redeem. Your account's country is in Google Play: profile photo → Settings → General → Account and device preferences → Country and profiles.$a$),
    (1, 'uz', $q$Qaysi davlat kartasini tanlash kerak?$q$, $a$Akkauntingiz roʻyxatdan oʻtgan davlatnikini: boshqa davlat kartasi faollashmaydi. Akkaunt davlati Google Play da: profil rasmi → «Settings» → «General» → «Account and device preferences» → «Country and profiles».$a$),
    (2, 'ru', $q$Подойдёт ли карта для аккаунта из Узбекистана?$q$, $a$Нет: карта работает только на аккаунте своей страны, а карт для Узбекистана нет. Подойдёт аккаунт одной из стран в переключателе — например, США или Турции.$a$),
    (2, 'en', $q$Will a card work on an account from Uzbekistan?$q$, $a$No: a card only works on an account from its own country, and there are no cards for Uzbekistan. You need an account from one of the countries in the switcher, such as the US or Turkey.$a$),
    (2, 'uz', $q$Karta Oʻzbekiston akkauntiga mos keladimi?$q$, $a$Yoʻq: karta faqat oʻz davlati akkauntida ishlaydi, Oʻzbekiston uchun esa karta yoʻq. Tanlagichdagi davlatlardan birining akkaunti kerak — masalan, AQSH yoki Turkiya.$a$),
    (3, 'ru', $q$Когда придёт код?$q$, $a$Код приходит на почту, указанную при заказе, сразу после оплаты. Если письма нет — проверьте «Спам» и «Промоакции».$a$),
    (3, 'en', $q$When will I get the code?$q$, $a$The code is emailed to the address on the order right after payment. If it has not arrived, check Spam and Promotions.$a$),
    (3, 'uz', $q$Kod qachon keladi?$q$, $a$Kod toʻlovdan soʻng darhol buyurtmadagi pochtaga keladi. Xat kelmasa — «Spam» va «Promotions» papkalarini tekshiring.$a$),
    (4, 'ru', $q$Как оплатить карту Google Play?$q$, $a$Оплата в сумах через Click, Payme или Uzum. Итог в сумах виден до подтверждения, комиссии сверху нет.$a$),
    (4, 'en', $q$How do I pay for a Google Play card?$q$, $a$Pay in soʻm with Click, Payme or Uzum. The total in soʻm is shown before you confirm, with no extra fee.$a$),
    (4, 'uz', $q$Google Play kartasini qanday toʻlash mumkin?$q$, $a$Click, Payme yoki Uzum orqali soʻmda toʻlov. Yakuniy summa soʻmda tasdiqlashdan oldin koʻrinadi, ustiga komissiya yoʻq.$a$)
) AS t(so, locale, question, answer) ON t.so = nf.sort_order;

-- Roblox: the page now has country cards too.
UPDATE brand_translations SET description = replace(description, $c$YuPay продаёт глобальные подарочные карты Roblox.$c$, $c$YuPay продаёт глобальные подарочные карты Roblox и карты 25 стран в их валюте — для аккаунтов, зарегистрированных в этих странах.$c$)
 WHERE brand_id = (SELECT id FROM brands WHERE slug = 'roblox') AND locale = 'ru' AND position($c$YuPay продаёт глобальные подарочные карты Roblox и карты 25 стран в их валюте — для аккаунтов, зарегистрированных в этих странах.$c$ in description) = 0;
UPDATE brand_translations SET description = replace(description, $c$YuPay sells global Roblox gift cards.$c$, $c$YuPay sells global Roblox gift cards, and cards from 25 countries in their own currency for accounts registered there.$c$)
 WHERE brand_id = (SELECT id FROM brands WHERE slug = 'roblox') AND locale = 'en' AND position($c$YuPay sells global Roblox gift cards, and cards from 25 countries in their own currency for accounts registered there.$c$ in description) = 0;
UPDATE brand_translations SET description = replace(description, $c$YuPay global Roblox sovgʻa kartalarini sotadi.$c$, $c$YuPay global Roblox sovgʻa kartalarini va 25 davlatning oʻz valyutasidagi kartalarini sotadi — shu davlatlarda roʻyxatdan oʻtgan akkauntlar uchun.$c$)
 WHERE brand_id = (SELECT id FROM brands WHERE slug = 'roblox') AND locale = 'uz' AND position($c$YuPay global Roblox sovgʻa kartalarini va 25 davlatning oʻz valyutasidagi kartalarini sotadi — shu davlatlarda roʻyxatdan oʻtgan akkauntlar uchun.$c$ in description) = 0;
DELETE FROM brand_faqs WHERE sort_order = 8 AND brand_id = (SELECT id FROM brands WHERE slug = 'roblox');
WITH nf AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), id, 8, true FROM brands WHERE slug = 'roblox'
    RETURNING id
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer FROM nf, (VALUES
    ('ru', $q$Какую карту Roblox выбрать — глобальную или страны?$q$, $a$Глобальную, если не уверены: она подходит аккаунтам из Узбекистана. Карта страны — в валюте этой страны и активируется только на аккаунте, зарегистрированном в ней.$a$),
    ('en', $q$Which Roblox card do I need — global or a country's?$q$, $a$The global one if you are unsure: it works on accounts from Uzbekistan. A country card is in that country's currency and redeems only on an account registered there.$a$),
    ('uz', $q$Qaysi Roblox kartasini tanlash kerak — global yoki davlat kartasini?$q$, $a$Ishonchingiz komil boʻlmasa — globalini: u Oʻzbekiston akkauntlariga mos keladi. Davlat kartasi shu davlat valyutasida va faqat u yerda roʻyxatdan oʻtgan akkauntda faollashadi.$a$)
) AS t(locale, question, answer);

-- Regional products read like their brands: «PlayStation (TR)» → «PlayStation · Турция».
UPDATE product_translations pt
   SET name = bt.name
  FROM products p
  JOIN brands c ON c.id = p.brand_id
  JOIN brands m ON m.id = c.region_parent_id
  JOIN brand_translations bt ON bt.brand_id = c.id
 WHERE pt.product_id = p.id
   AND bt.locale = pt.locale
   AND m.slug IN ('roblox', 'playstation', 'xbox', 'nintendo', 'app-store', 'google-play')
   AND p.slug = c.slug || '-cards';

SELECT b.slug, t.locale, t.seo_title,
       (SELECT count(*) FROM brand_faqs f WHERE f.brand_id = b.id) AS faqs
  FROM brands b JOIN brand_translations t ON t.brand_id = b.id
 WHERE b.slug IN ('roblox', 'playstation', 'xbox', 'nintendo', 'app-store', 'google-play')
 ORDER BY 1, 2;

COMMIT;
