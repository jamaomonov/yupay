"""«Как покупать игры в PS Store из Узбекистана» (batch 2026-11-25, key `psn`).

Sources / facts used:

* An account's country/region cannot be changed after the account is created;
  a PS Store voucher works only on an account of the same country —
  https://www.playstation.com/en-us/support/account/check-account-country-region/
* Wallet funds stay in the account's own currency; another region's funds
  cannot be used. Players keep a second account for another country and switch
  users on the console (PS5: PS button → Control Center → switch user) — same
  PlayStation support source, as given in the batch brief.
* Turkish PS Store charges in Turkish lira; Sony raised prices there several
  times (PS Plus +55 % in 2025). No exact prices quoted.
* GTA 6 on PS5: codes are region-locked to the account's region group, so the
  safe path is a card of your account's country —
  https://sixhype.com/blog/gta-6-region-locked-ps5-codes-explained/
* YuPay catalogue (prod, 2026-11-25): `/store/playstation`, one page with a
  country switcher, 43 countries incl. tr, us, ae, uk, pl, in. Codes are
  delivered on the order page and by e-mail after payment (no time promised).

Unverified — owner to check:

* Whether PSN accepts Uzbekistan as an account country. The post says only that
  players in Uzbekistan usually use an account of another country (Turkey, UAE,
  USA, Poland…).
* Exact redeem paths: PS5 «PlayStation Store → «…» → Погасить код» and the web
  path «store.playstation.com → аватар → Погасить коды». Not in the brief's
  verified facts; menu labels may differ by firmware/locale.
* That PS Plus can be bought with wallet funds topped up from a gift card
  (phrased cautiously in the post as "the wallet pays for games and PS Plus").
* That a new PSN account needs its own e-mail address (common knowledge,
  not sourced).
"""

from __future__ import annotations

POST = {
    "post_id": "01a21022-13a8-76b1-905f-268d1d1b651a",
    "brand_slug": "playstation",
    "kind": "guide",
    "cover": "https://cdn.yupay.uz/blog_image/2026/11/01a2102c-2cf1-7110-9c95-a6bf0cff0979.jpg",
    "ru": {
        "slug": "kak-pokupat-igry-v-ps-store-iz-uzbekistana",
        "title": "Как покупать игры в PS Store из Узбекистана",
        "excerpt": "Какую страну выбрать для аккаунта PSN, почему её нельзя сменить, какая карта PS Store подойдёт и как её погасить на PS5 и на сайте.",
        "seo_title": "Как купить игру в PS Store в Узбекистане — карты PSN",
        "seo_description": "Как покупать игры и PS Plus в PS Store из Узбекистана: страна аккаунта, карта PSN нужной страны (Турция, США, ОАЭ), активация на PS5 и частые ошибки.",
        "body": """
Чтобы покупать игры в PS Store из Узбекистана, нужен аккаунт PSN определённой страны и подарочная карта PS Store той же страны. Карта пополняет кошелёк аккаунта, а с кошелька оплачиваются игры и PS Plus.

## Главное

- Страну аккаунта PSN выбирают один раз при регистрации. Потом её не сменить.
- Карта PS Store работает только на аккаунте той же страны. Турецкая карта — для турецкого аккаунта, американская — для американского.
- Деньги в кошельке хранятся в валюте страны аккаунта и в другой регион не переносятся.
- Нужен магазин другой страны — заводят второй аккаунт и переключаются между пользователями на PS5.
- В YuPay карты PSN 43 стран на одной странице. Оплата в сумах через Click, Payme или Uzum: итог в сумах виден до оплаты, и списывается ровно он.

## Какую страну выбрать для аккаунта

Игроки в Узбекистане обычно используют аккаунт другой страны: Турции, ОАЭ, США, Польши и других.

От страны зависят три вещи:

- **валюта и цены** — в турецком магазине цены в лирах, в американском в долларах;
- **ассортимент и язык** — каталог и локализация игр отличаются по регионам;
- **какие карты подойдут** — только карты этой же страны.

Турецкий PS Store популярен из-за цен. Но Sony несколько раз их поднимала: только PS Plus в 2025 году подорожал на 55 %. Сравнивайте цену нужной игры в разных регионах сами, перед регистрацией, а не после.

Если у вас уже есть аккаунт с покупками и трофеями, обычно проще остаться на нём. Узнать его страну можно в настройках аккаунта на консоли или на сайте PlayStation.

## Почему страну нельзя сменить

Sony прямо пишет: страну или регион аккаунта после создания изменить нельзя. Это касается и кошелька: деньги остаются в валюте аккаунта, а средства другого региона использовать нельзя.

Практический вывод простой. Ошиблись со страной — придётся создавать новый аккаунт. Купленные игры и подписка на старом аккаунте останутся там.

## Второй аккаунт и переключение пользователей

Многие держат два аккаунта: основной и, например, турецкий для покупок по местным ценам. Для нового аккаунта понадобится отдельная почта.

На PS5 переключаться между ними просто:

1. Нажмите кнопку PS на геймпаде.
2. Откройте Пункт управления.
3. Выберите смену пользователя и войдите во второй аккаунт.

Карту пополнения активируйте на том аккаунте, страна которого с ней совпадает. Кошельки у аккаунтов раздельные.

## Как погасить карту PSN на PS5

1. Войдите в аккаунт нужной страны.
2. Откройте PlayStation Store.
3. Нажмите «…» в верхней части магазина и выберите «Погасить код».
4. Введите код с карты и подтвердите.

Сумма появится в кошельке аккаунта. После этого игру или PS Plus можно оплатить обычным способом.

Код не принимается? Сначала проверьте, на какой аккаунт вы вошли и совпадает ли его страна со страной карты. Затем сверьте сам код: лишний пробел или перепутанная буква дают ту же ошибку.

## Как погасить карту на сайте

1. Откройте store.playstation.com и войдите в тот же аккаунт.
2. Нажмите на аватар и выберите «Погасить коды».
3. Введите код и подтвердите.

Так удобно пополнить кошелёк заранее, не включая консоль.

## Что проверить перед покупкой

- **Страна аккаунта.** Посмотрите её в настройках до покупки карты, а не по памяти.
- **Страна карты.** Должна совпадать со страной аккаунта.
- **Номинал.** Хватит ли его на игру с учётом цены в местной валюте. Не хватает — возьмите две карты или карту крупнее.
- **PS Plus.** Подписку оплачивают с кошелька того аккаунта, на котором она будет. Значит, и карта нужна страны этого аккаунта.
- **Регион игры.** Некоторые игры привязаны к региону. Например, коды [GTA 6 для PS5](/blog/kak-kupit-gta-6-v-uzbekistane) работают только на аккаунте подходящего региона. Безопасный путь — покупать игру в магазине своего аккаунта.

## Частые ошибки

- **Карта не той страны.** Самая частая. Турецкий аккаунт не примет американскую карту, и наоборот. Код при этом не испортится, но на этот аккаунт его не зачислить.
- **Попытка сменить страну аккаунта.** Это невозможно. Выход один — второй аккаунт.
- **Карта активирована не на том пользователе.** На консоли с двумя аккаунтами проверьте, кто сейчас вошёл.
- **Ожидание, что деньги «переедут».** Средства одного региона в другом не работают.

## Как купить карту PSN в YuPay

1. Откройте [PlayStation Store в каталоге YuPay](/store/playstation).
2. Выберите страну своего аккаунта, например [Турцию](/store/playstation?region=tr) или [США](/store/playstation?region=us).
3. Выберите номинал.
4. Оплатите в сумах через Click, Payme или Uzum.
5. Код придёт на страницу заказа и на e-mail.

Играете и на Xbox? Там правила другие: страну аккаунта Microsoft можно сменить, но с ограничениями. Подробно — в гайде [как пополнить Xbox из Узбекистана](/blog/kak-popolnit-xbox-iz-uzbekistana).

Знаете страну своего аккаунта? Откройте [карты PlayStation Store](/store/playstation), выберите эту страну и номинал под нужную игру.
""",
        "faqs": [
            (
                "Можно ли сменить страну аккаунта PSN?",
                "Нет. Sony не позволяет менять страну или регион аккаунта после создания. Нужен другой регион — создают второй аккаунт.",
            ),
            (
                "Подойдёт ли турецкая карта PSN к американскому аккаунту?",
                "Нет. Карта PS Store работает только на аккаунте той же страны. Для турецкого аккаунта нужна турецкая карта.",
            ),
            (
                "Как активировать карту PSN на PS5?",
                "Войдите в аккаунт нужной страны, откройте PlayStation Store, нажмите «…» и выберите «Погасить код». Сумма зачислится в кошелёк аккаунта.",
            ),
            (
                "Можно ли перенести деньги из кошелька одного региона в другой?",
                "Нет. Деньги хранятся в валюте страны аккаунта, и средства другого региона использовать нельзя.",
            ),
            (
                "Как оплатить карту PSN в YuPay?",
                "В сумах через Click, Payme или Uzum. Итог в сумах виден до оплаты, а код приходит на страницу заказа и на e-mail.",
            ),
        ],
    },
    "en": {
        "slug": "how-to-buy-ps-store-games-from-uzbekistan",
        "title": "How to buy PS Store games from Uzbekistan",
        "excerpt": "Which country to pick for your PSN account, why it cannot be changed, which PS Store card fits and how to redeem it on PS5 and on the web.",
        "seo_title": "How to buy PS Store games in Uzbekistan — PSN gift cards",
        "seo_description": "Buying games and PS Plus in PS Store from Uzbekistan: account country, a PSN card of the right country (Turkey, USA, UAE), redeeming on PS5, common mistakes.",
        "body": """
To buy games in PS Store from Uzbekistan, you need a PSN account of a specific country and a PS Store gift card of that same country. The card tops up the account wallet, and the wallet pays for games and PS Plus.

## Key takeaways

- You choose your PSN account country once, at sign-up. It cannot be changed later.
- A PS Store card works only on an account of the same country. A Turkish card is for a Turkish account, a US card for a US account.
- Wallet funds are held in the account country's currency and do not move to another region.
- Need another country's store? Players create a second account and switch users on the PS5.
- YuPay has PSN cards for 43 countries on one page. Pay in soʻm with Click, Payme or Uzum: the total in soʻm is shown before payment, and that is exactly what is charged.

## Which country to pick for your account

Players in Uzbekistan usually use an account of another country: Turkey, the UAE, the USA, Poland and others.

The country decides three things:

- **currency and prices** — the Turkish store prices in lira, the US store in dollars;
- **catalogue and language** — the game list and localisation differ by region;
- **which cards work** — only cards of that same country.

The Turkish PS Store is popular for its prices. But Sony has raised them several times: PS Plus alone went up 55 % in 2025. Compare the price of the game you want across regions yourself, before you sign up, not after.

If you already have an account with purchases and trophies, staying on it is usually simpler. You can see its country in the account settings on the console or on the PlayStation website.

## Why the country cannot be changed

Sony says it plainly: an account's country or region cannot be changed after the account is created. The same goes for the wallet: funds stay in the account's currency, and another region's funds cannot be used.

The practical conclusion is simple. Picked the wrong country — you will need a new account. Games and subscriptions bought on the old account stay there.

## A second account and switching users

Many players keep two accounts: a main one and, say, a Turkish one for local prices. A new account needs its own e-mail address.

Switching between them on the PS5 is easy:

1. Press the PS button on the controller.
2. Open the Control Center.
3. Choose switch user and sign in to the second account.

Redeem a card on the account whose country matches it. Each account has its own wallet.

## How to redeem a PSN card on PS5

1. Sign in to the account of the right country.
2. Open PlayStation Store.
3. Select «…» at the top of the store and choose Redeem Code.
4. Enter the code from the card and confirm.

The amount appears in the account wallet. Then pay for the game or PS Plus as usual.

Code not accepted? First check which account you are signed in to and whether its country matches the card's. Then check the code itself: an extra space or a mixed-up letter gives the same error.

## How to redeem a card on the web

1. Open store.playstation.com and sign in to the same account.
2. Click your avatar and choose Redeem Codes.
3. Enter the code and confirm.

This is handy for topping up the wallet in advance without turning on the console.

## What to check before you buy

- **Account country.** Look it up in the settings before buying a card, not from memory.
- **Card country.** It must match the account country.
- **Face value.** Will it cover the game at its local price? If not, take two cards or a bigger one.
- **PS Plus.** The subscription is paid from the wallet of the account it will be on. So the card must be of that account's country too.
- **Game region.** Some games are region-locked. For example, [GTA 6 codes for PS5](/blog/how-to-buy-gta-6-in-uzbekistan) work only on an account of the matching region. The safe path is to buy the game in your own account's store.

## Common mistakes

- **A card from the wrong country.** The most common one. A Turkish account will not accept a US card, and the other way round. The code is not ruined, but it cannot be credited to that account.
- **Trying to change the account country.** It is not possible. The only way out is a second account.
- **Redeeming on the wrong user.** On a console with two accounts, check who is signed in.
- **Expecting the money to "move".** One region's funds do not work in another.

## How to buy a PSN card on YuPay

1. Open [PlayStation Store on YuPay](/store/playstation).
2. Choose your account's country, for example [Turkey](/store/playstation?region=tr) or the [USA](/store/playstation?region=us).
3. Choose a face value.
4. Pay in soʻm with Click, Payme or Uzum.
5. The code arrives on the order page and by e-mail.

Play on Xbox too? The rules there are different: a Microsoft account country can be changed, with limits. Details in our guide on [how to top up Xbox from Uzbekistan](/blog/how-to-top-up-xbox-from-uzbekistan).

Know your account's country? Open [PlayStation Store cards](/store/playstation), pick that country and a face value for the game you want.
""",
        "faqs": [
            (
                "Can I change my PSN account country?",
                "No. Sony does not allow changing an account's country or region after it is created. If you need another region, create a second account.",
            ),
            (
                "Will a Turkish PSN card work on a US account?",
                "No. A PS Store card works only on an account of the same country. A Turkish account needs a Turkish card.",
            ),
            (
                "How do I redeem a PSN card on PS5?",
                "Sign in to the account of the right country, open PlayStation Store, select «…» and choose Redeem Code. The amount is added to the account wallet.",
            ),
            (
                "Can I move wallet funds from one region to another?",
                "No. Funds are held in the account country's currency, and another region's funds cannot be used.",
            ),
            (
                "How do I pay for a PSN card on YuPay?",
                "In soʻm with Click, Payme or Uzum. The total in soʻm is shown before payment, and the code arrives on the order page and by e-mail.",
            ),
        ],
    },
    "uz": {
        "slug": "ps-store-dan-oyin-sotib-olish",
        "title": "Oʻzbekistondan PS Store’da oʻyin qanday sotib olinadi",
        "excerpt": "PSN akkaunti uchun qaysi davlatni tanlash, nega uni oʻzgartirib boʻlmaydi, qaysi PS Store kartasi mos keladi va uni PS5 hamda saytda qanday faollashtirish.",
        "seo_title": "Oʻzbekistonda PS Store’dan oʻyin sotib olish — PSN kartalari",
        "seo_description": "Oʻzbekistondan PS Store’da oʻyin va PS Plus sotib olish: akkaunt davlati, kerakli davlatning PSN kartasi (Turkiya, AQSh, BAA), PS5’da faollashtirish va xatolar.",
        "body": """
Oʻzbekistondan PS Store’da oʻyin sotib olish uchun maʼlum bir davlatning PSN akkaunti va aynan shu davlatning PS Store sovgʻa kartasi kerak. Karta akkaunt hamyonini toʻldiradi, hamyondan esa oʻyinlar va PS Plus toʻlanadi.

## Asosiysi

- PSN akkaunti davlati roʻyxatdan oʻtishda bir marta tanlanadi. Keyin uni oʻzgartirib boʻlmaydi.
- PS Store kartasi faqat shu davlat akkauntida ishlaydi. Turk kartasi — turk akkaunti uchun, Amerika kartasi — Amerika akkaunti uchun.
- Hamyondagi pul akkaunt davlati valyutasida saqlanadi va boshqa regionga oʻtmaydi.
- Boshqa davlat doʻkoni kerak boʻlsa, ikkinchi akkaunt ochiladi va PS5’da foydalanuvchilar almashtiriladi.
- YuPay’da 43 davlatning PSN kartalari bitta sahifada. Toʻlov soʻmda, Click, Payme yoki Uzum orqali: soʻmdagi yakuniy summa toʻlovdan oldin koʻrinadi va aynan u yechiladi.

## Akkaunt uchun qaysi davlatni tanlash

Oʻzbekistondagi oʻyinchilar odatda boshqa davlat akkauntidan foydalanadi: Turkiya, BAA, AQSh, Polsha va boshqalar.

Davlat uch narsani belgilaydi:

- **valyuta va narxlar** — turk doʻkonida narxlar lirada, Amerika doʻkonida dollarda;
- **katalog va til** — oʻyinlar roʻyxati va lokalizatsiya regionga qarab farq qiladi;
- **qaysi kartalar mos keladi** — faqat shu davlat kartalari.

Turk PS Store narxlari tufayli mashhur. Lekin Sony ularni bir necha marta oshirgan: faqat PS Plus 2025-yilda 55 % qimmatlashdi. Kerakli oʻyin narxini turli regionlarda oʻzingiz solishtiring — roʻyxatdan oʻtishdan oldin, keyin emas.

Agar xaridlar va kuboklar bor akkauntingiz boʻlsa, odatda unda qolish osonroq. Uning davlatini konsoldagi yoki PlayStation saytidagi akkaunt sozlamalarida koʻrish mumkin.

## Nega davlatni oʻzgartirib boʻlmaydi

Sony buni ochiq yozadi: akkaunt yaratilgandan keyin uning davlati yoki regionini oʻzgartirib boʻlmaydi. Hamyon ham shunday: pul akkaunt valyutasida qoladi, boshqa region mablagʻidan foydalanib boʻlmaydi.

Amaliy xulosa oddiy. Davlatni xato tanlasangiz, yangi akkaunt ochishga toʻgʻri keladi. Eski akkauntda olingan oʻyinlar va obuna oʻsha yerda qoladi.

## Ikkinchi akkaunt va foydalanuvchini almashtirish

Koʻpchilik ikkita akkaunt yuritadi: asosiysi va, masalan, mahalliy narxlarda xarid qilish uchun turk akkaunti. Yangi akkaunt uchun alohida pochta kerak boʻladi.

PS5’da ular orasida almashish oson:

1. Geympaddagi PS tugmasini bosing.
2. Boshqaruv markazini oching.
3. Foydalanuvchini almashtirishni tanlang va ikkinchi akkauntga kiring.

Kartani davlati unga mos keladigan akkauntda faollashtiring. Har bir akkauntning hamyoni alohida.

## PSN kartasini PS5’da qanday faollashtirish

1. Kerakli davlat akkauntiga kiring.
2. PlayStation Store’ni oching.
3. Doʻkonning yuqori qismidagi «…» tugmasini bosing va kodni faollashtirishni tanlang.
4. Kartadagi kodni kiriting va tasdiqlang.

Summa akkaunt hamyoniga tushadi. Shundan soʻng oʻyin yoki PS Plus’ni odatdagidek toʻlash mumkin.

Kod qabul qilinmayaptimi? Avval qaysi akkauntga kirganingizni va uning davlati karta davlati bilan mos kelishini tekshiring. Soʻng kodning oʻzini solishtiring: ortiqcha boʻsh joy yoki adashtirilgan harf ham xuddi shu xatoni beradi.

## Kartani saytda qanday faollashtirish

1. store.playstation.com’ni oching va oʻsha akkauntga kiring.
2. Avatarni bosing va kodlarni faollashtirishni tanlang.
3. Kodni kiriting va tasdiqlang.

Bu konsolni yoqmasdan hamyonni oldindan toʻldirish uchun qulay.

## Xariddan oldin nimani tekshirish kerak

- **Akkaunt davlati.** Uni karta olishdan oldin sozlamalarda koʻring, xotiraga tayanmang.
- **Karta davlati.** Akkaunt davlati bilan bir xil boʻlishi kerak.
- **Nominal.** Mahalliy valyutadagi narxni hisobga olganda oʻyinga yetadimi? Yetmasa, ikkita karta yoki kattaroq karta oling.
- **PS Plus.** Obuna u boʻladigan akkaunt hamyonidan toʻlanadi. Demak, karta ham shu akkaunt davlatiniki boʻlishi kerak.
- **Oʻyin regioni.** Baʼzi oʻyinlar regionga bogʻlangan. Masalan, [PS5 uchun GTA 6 kodlari](/blog/gta-6-ni-ozbekistonda-sotib-olish) faqat mos region akkauntida ishlaydi. Xavfsiz yoʻl — oʻyinni oʻz akkauntingiz doʻkonidan olish.

## Koʻp uchraydigan xatolar

- **Boshqa davlat kartasi.** Eng koʻp uchraydigani. Turk akkaunti Amerika kartasini qabul qilmaydi va aksincha. Kod buzilmaydi, lekin bu akkauntga tushmaydi.
- **Akkaunt davlatini oʻzgartirishga urinish.** Bu mumkin emas. Yagona yoʻl — ikkinchi akkaunt.
- **Karta boshqa foydalanuvchida faollashtirilgan.** Ikkita akkauntli konsolda hozir kim kirganini tekshiring.
- **Pul «koʻchib oʻtadi» deb kutish.** Bir region mablagʻi boshqasida ishlamaydi.

## YuPay’da PSN kartasini qanday sotib olish

1. YuPay katalogida [PlayStation Store](/store/playstation) sahifasini oching.
2. Akkauntingiz davlatini tanlang, masalan [Turkiya](/store/playstation?region=tr) yoki [AQSh](/store/playstation?region=us).
3. Nominalni tanlang.
4. Click, Payme yoki Uzum orqali soʻmda toʻlang.
5. Kod buyurtma sahifasiga va e-mail’ga keladi.

Xbox’da ham oʻynaysizmi? U yerda qoidalar boshqacha: Microsoft akkaunti davlatini oʻzgartirish mumkin, lekin cheklovlar bilan. Batafsil — [Xbox hisobini Oʻzbekistondan toʻldirish](/blog/xbox-hisobini-toldirish) qoʻllanmasida.

Akkauntingiz davlatini bilasizmi? [PlayStation Store kartalari](/store/playstation) sahifasini oching, shu davlatni va kerakli oʻyinga yetadigan nominalni tanlang.
""",
        "faqs": [
            (
                "PSN akkaunti davlatini oʻzgartirish mumkinmi?",
                "Yoʻq. Sony akkaunt yaratilgandan keyin uning davlati yoki regionini oʻzgartirishga ruxsat bermaydi. Boshqa region kerak boʻlsa, ikkinchi akkaunt ochiladi.",
            ),
            (
                "Turk PSN kartasi Amerika akkauntiga mos keladimi?",
                "Yoʻq. PS Store kartasi faqat shu davlat akkauntida ishlaydi. Turk akkauntiga turk kartasi kerak.",
            ),
            (
                "PSN kartasini PS5’da qanday faollashtirish mumkin?",
                "Kerakli davlat akkauntiga kiring, PlayStation Store’ni oching, «…» tugmasini bosing va kodni faollashtirishni tanlang. Summa akkaunt hamyoniga tushadi.",
            ),
            (
                "Hamyondagi pulni bir regiondan boshqasiga oʻtkazish mumkinmi?",
                "Yoʻq. Pul akkaunt davlati valyutasida saqlanadi, boshqa region mablagʻidan foydalanib boʻlmaydi.",
            ),
            (
                "YuPay’da PSN kartasini qanday toʻlash mumkin?",
                "Soʻmda, Click, Payme yoki Uzum orqali. Soʻmdagi yakuniy summa toʻlovdan oldin koʻrinadi, kod esa buyurtma sahifasiga va e-mail’ga keladi.",
            ),
        ],
    },
}
