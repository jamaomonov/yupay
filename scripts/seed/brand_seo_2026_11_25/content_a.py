# ruff: noqa: C408 -- content data: keyword dicts read better than literals here
"""Storefront copy + SEO for valorant, league-of-legends, fortnite (2026-11-25).

Sources:
- Riot, Prepaid Cards, Cash Codes & Content Codes:
  https://support.riotgames.com/en-us/riot/store/prepaid-cards-cash-codes-content-codes
  (VALORANT client steps, LoL client steps, shop.riotgames.com/redeem, region lock,
  "PC only" in-game redemption, one game per code, "cash codes never expire").
- Riot VALORANT support (search snippets; the article now redirects to the support hub):
  https://support-valorant.riotgames.com/hc/en-us/articles/48753809137171-Prepaid-Cards-Cash-Codes-Content-Codes
- Epic, How to redeem a V-Bucks card (403 to direct fetch; read via search snippets):
  https://www.epicgames.com/help/fortnite-c5719335176219/billing-support-c5719343057307/how-to-redeem-a-v-bucks-card-a5720383111579
- Fortnite, Redeem your V-Bucks Card (403 to direct fetch; read via search snippets):
  https://www.fortnite.com/vbuckscard (region lock by flag, Epic or platform account
  country, Shared Wallet across PlayStation/Xbox/PC/mobile/cloud, Nintendo-only V-Bucks).

Unverified — owner to check:
1. Russian and Uzbek menu labels in the steps are our translations. Riot and Epic pages
   were read in English only, so the steps quote the English labels in brackets
   (Prepaid Cards & Codes, Redeem Codes, Get Started, Submit).
2. Valorant RU card: we call its region «Россия (СНГ)» per our DB note. Check that this
   is how a buyer recognises their account region, and that Riot still sells VP in it.
3. LoL EU card: which server it fits — EU West, EU Nordic & East, or both.
4. Fortnite: Epic says new «Fortnite Gift Cards» are replacing V-Bucks cards and use a
   different redemption flow. The steps here are for classic V-Bucks cards
   (fortnite.com/vbuckscard). Confirm our codes are V-Bucks cards, not Fortnite Gift Cards.
5. Fortnite EU card: which account countries it accepts (Epic locks by the country flag).
6. Fortnite on Nintendo: Epic's pages give the extra console step only for Xbox and
   PlayStation; whether Nintendo needs one is not confirmed. Steps say only Xbox/PS.
7. What each currency buys (VP: skins, battle pass, agents; RP: champions, skins;
   V-Bucks: outfits, emotes, battle pass) is general game knowledge, not from the
   support pages above.
"""

PAY = {
    "ru": "Оплата в сумах через Click, Payme или Uzum. Итог в сумах виден до оплаты, и списывается ровно он.",
    "en": "Pay in soʻm with Click, Payme or Uzum. You see the total in soʻm before paying, and exactly that amount is charged.",
    "uz": "Click, Payme yoki Uzum orqali soʻmda toʻlov. Soʻmdagi yakuniy summa toʻlovdan oldin koʻrinadi va aynan shu summa yechiladi.",
}
PAY_Q = {
    "ru": "Как оплатить?",
    "en": "How do I pay?",
    "uz": "Qanday toʻlash mumkin?",
}
WHERE_Q = {
    "ru": "Где мой код?",
    "en": "Where is my code?",
    "uz": "Kodim qayerda?",
}
WHERE_A = {
    "ru": "На странице заказа и в письме на почту, указанную при заказе. Если письма нет — проверьте «Спам» и «Промоакции».",
    "en": "On the order page and in an email to the address on the order. If the email is not there, check Spam and Promotions.",
    "uz": "Buyurtma sahifasida va buyurtmada koʻrsatilgan pochtaga kelgan xatda. Xat boʻlmasa — «Spam» va «Promotions» papkalarini tekshiring.",
}

B = {}

B["valorant"] = dict(
    seo_title={
        "ru": "Valorant Points (VP) — купить в Узбекистане за сумы",
        "en": "Valorant Points (VP) — buy in Uzbekistan for soʻm",
        "uz": "Valorant Points (VP) — Oʻzbekistonda soʻmga sotib olish",
    },
    seo_description={
        "ru": "Коды Valorant Points для аккаунтов Riot регионов Россия (СНГ), Турция, Европа, США и других. Код на почту после оплаты. Оплата в сумах через Click, Payme или Uzum.",
        "en": "Valorant Points codes for Riot accounts in Russia (CIS), Turkey, Europe, the US and more. Code by email after payment. Pay in soʻm with Click, Payme or Uzum.",
        "uz": "Rossiya (MDH), Turkiya, Yevropa, AQSH va boshqa mintaqalar Riot akkauntlari uchun Valorant Points kodlari. Kod toʻlovdan soʻng pochtaga. Click, Payme yoki Uzum orqali soʻmda toʻlov.",
    },
    short={
        "ru": "Коды Valorant Points для аккаунта Riot нужного региона. Код на почту, оплата в сумах.",
        "en": "Valorant Points codes for your Riot account's region. Code by email, pay in soʻm.",
        "uz": "Kerakli mintaqa Riot akkaunti uchun Valorant Points kodlari. Kod pochtaga, soʻmda toʻlov.",
    },
    desc={
        "ru": "Код Valorant Points пополняет баланс VP в аккаунте Riot. На VP покупают скины оружия, боевой пропуск и агентов.\n\nКод работает только на аккаунте своего региона: российский — на аккаунте региона Россия (СНГ), турецкий — на турецком. Выберите регион своего аккаунта в переключателе выше.\n\nКод виден на странице заказа и приходит на почту после оплаты.",
        "en": "A Valorant Points code tops up the VP balance on your Riot account. VP buys weapon skins, the battle pass and agents.\n\nA code only works on an account from its own region: a Russian code on a Russia (CIS) account, a Turkish code on a Turkish one. Pick your account's region in the switcher above.\n\nThe code shows on the order page and arrives by email after payment.",
        "uz": "Valorant Points kodi Riot akkauntidagi VP balansini toʻldiradi. VP ga qurol skinlari, jangovar propusk va agentlar olinadi.\n\nKod faqat oʻz mintaqasi akkauntida ishlaydi: rossiyacha — Rossiya (MDH) mintaqasi akkauntida, turkcha — turkcha akkauntda. Yuqoridagi tanlagichda akkauntingiz mintaqasini tanlang.\n\nKod toʻlovdan soʻng buyurtma sahifasida koʻrinadi va pochtaga keladi.",
    },
    steps={
        "ru": [
            "Войдите в клиент VALORANT и нажмите на значок VALORANT рядом с балансом VP в правом верхнем углу.",
            "Выберите раздел предоплаченных карт и кодов (Prepaid Cards & Codes).",
            "Введите код из письма без пробелов. В некоторых регионах нужно отметить галочку согласия.",
            "Нажмите Submit — VP зачислятся на аккаунт.",
            "Код можно погасить и на сайте shop.riotgames.com/redeem: войдите в аккаунт Riot, введите код и выберите VALORANT.",
        ],
        "en": [
            "Sign in to the VALORANT client and click the VALORANT icon next to your VP balance in the top right corner.",
            "Choose Prepaid Cards & Codes.",
            "Enter the code from the email with no spaces. In some regions you need to tick the consent box.",
            "Click Submit — the VP lands on your account.",
            "You can also redeem on shop.riotgames.com/redeem: sign in to your Riot account, enter the code and pick VALORANT.",
        ],
        "uz": [
            "VALORANT klientiga kiring va yuqori oʻng burchakdagi VP balansi yonidagi VALORANT belgisini bosing.",
            "Oldindan toʻlangan kartalar va kodlar boʻlimini (Prepaid Cards & Codes) tanlang.",
            "Xatdagi kodni boʻsh joysiz kiriting. Ayrim mintaqalarda rozilik belgisini qoʻyish kerak.",
            "Submit ni bosing — VP akkauntga tushadi.",
            "Kodni shop.riotgames.com/redeem saytida ham faollashtirish mumkin: Riot akkauntingizga kiring, kodni kiriting va VALORANT ni tanlang.",
        ],
    },
    faqs=[
        (
            {
                "ru": "Какой регион выбрать?",
                "en": "Which region should I pick?",
                "uz": "Qaysi mintaqani tanlash kerak?",
            },
            {
                "ru": "Регион своего аккаунта Riot. Код другого региона на аккаунте не активируется.",
                "en": "Your Riot account's region. A code from another region will not redeem on your account.",
                "uz": "Riot akkauntingiz mintaqasini. Boshqa mintaqa kodi akkauntingizda faollashmaydi.",
            },
        ),
        (PAY_Q, PAY),
        (WHERE_Q, WHERE_A),
        (
            {
                "ru": "Я играю на консоли. Как погасить код?",
                "en": "I play on console. How do I redeem the code?",
                "uz": "Konsolda oʻynayman. Kodni qanday faollashtiraman?",
            },
            {
                "ru": "Внутри игры код погашается только в ПК-версии. На консоли используйте сайт shop.riotgames.com/redeem.",
                "en": "In-game, the code redeems only in the PC version. On console, use shop.riotgames.com/redeem.",
                "uz": "Oʻyin ichida kod faqat PK versiyasida faollashadi. Konsolda shop.riotgames.com/redeem saytidan foydalaning.",
            },
        ),
    ],
)

B["league-of-legends"] = dict(
    seo_title={
        "ru": "League of Legends RP — купить в Узбекистане за сумы",
        "en": "League of Legends RP — buy in Uzbekistan for soʻm",
        "uz": "League of Legends RP — Oʻzbekistonda soʻmga sotib olish",
    },
    seo_description={
        "ru": "Коды Riot Points для League of Legends: аккаунты Европы, Турции, США, Великобритании и других регионов. Код на почту после оплаты. Оплата в сумах через Click, Payme или Uzum.",
        "en": "Riot Points codes for League of Legends: European, Turkish, US, UK and other accounts. Code by email after payment. Pay in soʻm with Click, Payme or Uzum.",
        "uz": "League of Legends uchun Riot Points kodlari: Yevropa, Turkiya, AQSH, Buyuk Britaniya va boshqa mintaqalar akkauntlari. Kod toʻlovdan soʻng pochtaga. Click, Payme yoki Uzum orqali soʻmda toʻlov.",
    },
    short={
        "ru": "Коды RP для League of Legends на аккаунт нужного региона. Код на почту, оплата в сумах.",
        "en": "RP codes for League of Legends on your account's region. Code by email, pay in soʻm.",
        "uz": "Kerakli mintaqa akkaunti uchun League of Legends RP kodlari. Kod pochtaga, soʻmda toʻlov.",
    },
    desc={
        "ru": "Код пополняет баланс Riot Points (RP) в League of Legends. На RP покупают чемпионов и образы.\n\nКод работает только на аккаунте своего региона: европейский — на европейском, турецкий — на турецком. Выберите регион своего аккаунта в переключателе выше.\n\nКод виден на странице заказа и приходит на почту после оплаты.",
        "en": "The code tops up your Riot Points (RP) balance in League of Legends. RP buys champions and skins.\n\nA code only works on an account from its own region: a European code on a European account, a Turkish code on a Turkish one. Pick your account's region in the switcher above.\n\nThe code shows on the order page and arrives by email after payment.",
        "uz": "Kod League of Legends dagi Riot Points (RP) balansini toʻldiradi. RP ga championlar va skinlar olinadi.\n\nKod faqat oʻz mintaqasi akkauntida ishlaydi: yevropacha — yevropacha akkauntda, turkcha — turkcha akkauntda. Yuqoridagi tanlagichda akkauntingiz mintaqasini tanlang.\n\nKod toʻlovdan soʻng buyurtma sahifasida koʻrinadi va pochtaga keladi.",
    },
    steps={
        "ru": [
            "Войдите в клиент League of Legends и откройте магазин.",
            "Нажмите кнопку аккаунта (Account) и выберите «Активация кодов» (Redeem Codes).",
            "Введите код из письма без пробелов и нажмите Submit — RP зачислятся на аккаунт.",
            "Код можно погасить и на сайте shop.riotgames.com/redeem: войдите в аккаунт Riot, введите код и выберите League of Legends.",
        ],
        "en": [
            "Sign in to the League of Legends client and open the store.",
            "Click the Account button and choose Redeem Codes.",
            "Enter the code from the email with no spaces and press Submit — the RP lands on your account.",
            "You can also redeem on shop.riotgames.com/redeem: sign in to your Riot account, enter the code and pick League of Legends.",
        ],
        "uz": [
            "League of Legends klientiga kiring va doʻkonni oching.",
            "Akkaunt (Account) tugmasini bosing va «Redeem Codes» ni tanlang.",
            "Xatdagi kodni boʻsh joysiz kiriting va Submit ni bosing — RP akkauntga tushadi.",
            "Kodni shop.riotgames.com/redeem saytida ham faollashtirish mumkin: Riot akkauntingizga kiring, kodni kiriting va League of Legends ni tanlang.",
        ],
    },
    faqs=[
        (
            {
                "ru": "Какой регион выбрать?",
                "en": "Which region should I pick?",
                "uz": "Qaysi mintaqani tanlash kerak?",
            },
            {
                "ru": "Регион своего аккаунта League of Legends. Код другого региона на аккаунте не активируется.",
                "en": "Your League of Legends account's region. A code from another region will not redeem on your account.",
                "uz": "League of Legends akkauntingiz mintaqasini. Boshqa mintaqa kodi akkauntingizda faollashmaydi.",
            },
        ),
        (PAY_Q, PAY),
        (WHERE_Q, WHERE_A),
        (
            {
                "ru": "У кода есть срок действия?",
                "en": "Does the code expire?",
                "uz": "Kodning amal qilish muddati bormi?",
            },
            {
                "ru": "Нет. По правилам Riot такие коды не сгорают. Вся сумма кода зачисляется в одну игру на одном аккаунте.",
                "en": "No. Under Riot's rules these codes never expire. The full amount goes to one game on one account.",
                "uz": "Yoʻq. Riot qoidalariga koʻra bunday kodlar muddati tugamaydi. Kodning butun summasi bitta akkauntdagi bitta oʻyinga tushadi.",
            },
        ),
    ],
)

B["fortnite"] = dict(
    seo_title={
        "ru": "V-Bucks для Fortnite — купить карту в Узбекистане за сумы",
        "en": "Fortnite V-Bucks cards — buy in Uzbekistan for soʻm",
        "uz": "Fortnite uchun V-Bucks — Oʻzbekistonda soʻmga karta sotib olish",
    },
    seo_description={
        "ru": "Карты V-Bucks для аккаунтов США, Европы, Великобритании, Германии и других стран. Код на почту после оплаты. Оплата в сумах через Click, Payme или Uzum.",
        "en": "V-Bucks cards for US, European, UK, German and other accounts. Code by email after payment. Pay in soʻm with Click, Payme or Uzum.",
        "uz": "AQSH, Yevropa, Buyuk Britaniya, Germaniya va boshqa davlatlar akkauntlari uchun V-Bucks kartalari. Kod toʻlovdan soʻng pochtaga. Click, Payme yoki Uzum orqali soʻmda toʻlov.",
    },
    short={
        "ru": "Карты V-Bucks для Fortnite на аккаунт нужной страны. Код на почту, оплата в сумах.",
        "en": "Fortnite V-Bucks cards for your account's country. Code by email, pay in soʻm.",
        "uz": "Kerakli davlat akkaunti uchun Fortnite V-Bucks kartalari. Kod pochtaga, soʻmda toʻlov.",
    },
    desc={
        "ru": "Карта V-Bucks пополняет баланс V-Bucks в Fortnite. На них покупают образы, эмоции и боевой пропуск.\n\nКарта привязана к стране. Она активируется, только если ваш аккаунт Epic Games или аккаунт платформы, например PlayStation Network, зарегистрирован в той же стране. Выберите страну своего аккаунта в переключателе выше.\n\nV-Bucks, погашенные на PlayStation, Xbox, ПК или мобильных устройствах, общие для этих платформ. Погашенные на Nintendo тратятся только на Nintendo.",
        "en": "A V-Bucks card tops up your V-Bucks balance in Fortnite. V-Bucks buy outfits, emotes and the battle pass.\n\nThe card is tied to a country. It redeems only if your Epic Games account, or your platform account such as PlayStation Network, is registered in that same country. Pick your account's country in the switcher above.\n\nV-Bucks redeemed on PlayStation, Xbox, PC or mobile are shared across those platforms. V-Bucks redeemed on Nintendo can only be spent on Nintendo.",
        "uz": "V-Bucks kartasi Fortnite dagi V-Bucks balansini toʻldiradi. Ularga obrazlar, emotsiyalar va jangovar propusk olinadi.\n\nKarta davlatga bogʻlangan. U faqat Epic Games akkauntingiz yoki platforma akkauntingiz, masalan PlayStation Network, xuddi shu davlatda roʻyxatdan oʻtgan boʻlsa faollashadi. Yuqoridagi tanlagichda akkauntingiz davlatini tanlang.\n\nPlayStation, Xbox, PK yoki mobil qurilmalarda faollashtirilgan V-Bucks shu platformalar uchun umumiy. Nintendo da faollashtirilganlari faqat Nintendo da sarflanadi.",
    },
    steps={
        "ru": [
            "Войдите в нужный аккаунт Epic Games.",
            "Откройте fortnite.com/vbuckscard и нажмите Get Started.",
            "Введите PIN-код из письма без дефисов.",
            "Выберите платформу, на которой играете, и подтвердите.",
            "Если выбрали Xbox или PlayStation, сайт выдаст второй код. Введите его в своём аккаунте Microsoft или Sony — после этого V-Bucks зачислятся.",
        ],
        "en": [
            "Sign in to the right Epic Games account.",
            "Open fortnite.com/vbuckscard and click Get Started.",
            "Enter the PIN from the email with no dashes.",
            "Pick the platform you play on and confirm.",
            "If you picked Xbox or PlayStation, the site gives you a second code. Enter it in your Microsoft or Sony account — then the V-Bucks arrive.",
        ],
        "uz": [
            "Kerakli Epic Games akkauntiga kiring.",
            "fortnite.com/vbuckscard ni oching va Get Started ni bosing.",
            "Xatdagi PIN-kodni defislarsiz kiriting.",
            "Oʻynaydigan platformangizni tanlang va tasdiqlang.",
            "Xbox yoki PlayStation ni tanlagan boʻlsangiz, sayt ikkinchi kod beradi. Uni Microsoft yoki Sony akkauntingizda kiriting — shundan soʻng V-Bucks tushadi.",
        ],
    },
    faqs=[
        (
            {
                "ru": "Какую страну выбрать?",
                "en": "Which country should I pick?",
                "uz": "Qaysi davlatni tanlash kerak?",
            },
            {
                "ru": "Страну, в которой зарегистрирован ваш аккаунт Epic Games, а если играете на PlayStation — аккаунт PlayStation Network. Карта другой страны не активируется.",
                "en": "The country your Epic Games account is registered in — or your PlayStation Network account, if you play on PlayStation. A card from another country will not redeem.",
                "uz": "Epic Games akkauntingiz roʻyxatdan oʻtgan davlatni, PlayStation da oʻynasangiz — PlayStation Network akkauntingiz davlatini. Boshqa davlat kartasi faollashmaydi.",
            },
        ),
        (PAY_Q, PAY),
        (
            {
                "ru": "На какой платформе будут V-Bucks?",
                "en": "Which platform will the V-Bucks be on?",
                "uz": "V-Bucks qaysi platformada boʻladi?",
            },
            {
                "ru": "V-Bucks, погашенные на PlayStation, Xbox, ПК или мобильных устройствах, общие для этих платформ. Погашенные на Nintendo тратятся только на Nintendo.",
                "en": "V-Bucks redeemed on PlayStation, Xbox, PC or mobile are shared across those platforms. V-Bucks redeemed on Nintendo can only be spent on Nintendo.",
                "uz": "PlayStation, Xbox, PK yoki mobil qurilmalarda faollashtirilgan V-Bucks shu platformalar uchun umumiy. Nintendo da faollashtirilganlari faqat Nintendo da sarflanadi.",
            },
        ),
        (WHERE_Q, WHERE_A),
    ],
)
