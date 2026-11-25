# ruff: noqa: C408 -- content data: keyword dicts read better than literals here
"""Storefront copy + SEO for call-of-duty-mobile, ea-sports-fc-26, pubg-battlegrounds (2026-11-25).

Sources:
- Activision, Call of Duty: Mobile Promotions (where the UID is: tap your nickname at the
  top left of the home screen, open the second tab; the UID is a ~20-digit number under
  the nickname):
  https://support.activision.com/cod-mobile/articles/call-of-duty-mobile-promotions
- Activision, Managing your Account and Friends in Call of Duty: Mobile (second tab =
  Player Profile; read via search snippet):
  https://support.activision.com/content/atvi/support/web/en/cod-mobile/articles/managing-your-account-and-friends-in-call-of-duty-mobile.html
- EA Help, How to redeem your product and promotional codes (EA app: launch, log in,
  My Library → Redeem Code; ea.com/redeem: Redeem button for PC codes; virtual currency
  codes "can be redeemed at the URL in your code's instructions"):
  https://help.ea.com/en/articles/orders-and-rewards/redeem-product-and-promo-codes/
- EA Forums, FC 26 Ultimate Team, FC Points (EA community manager: points redeemed on a
  PC account cannot be used on PlayStation — points stay on their platform):
  https://forums.ea.com/discussions/fc-26-ultimate-team-en/fc-points/13426571
- PUBG Support, What is G-COIN? (G-COIN buys in-game items in the Store; paid / free /
  timed free G-Coin):
  https://support.pubg.com/hc/en-us/articles/900003190826-What-is-G-COIN
- PUBG Support, What is KRAFTON Player Account? (the account is used to "redeem codes"):
  https://support.pubg.com/hc/en-us/articles/11495102737305-What-is-KRAFTON-Player-Account
- pubg.com/en/events/redeem — official «Use redeem code» page (KRAFTON Player Account
  sign-in; does not mention G-Coin).

Unverified — owner to check:
1. EA SPORTS FC 26 Points: which platform OUR codes are for. EA does not say on a page we
   could read, and the supplier labels only say «EA points». The copy assumes PC codes
   redeemed in the EA app or at ea.com/redeem. If they are PlayStation or Xbox codes,
   the steps, desc, short and FAQ 1 must change.
2. FC Points: whether the codes are region-locked to the EA account's country. Resellers
   say some are; EA does not say. The copy does not mention a region.
3. PUBG G-Coin: no official PUBG/Krafton page with redeem steps was found. Resellers
   describe the lobby Store → «Add Bonus/Gift Code» (label varies) or the web page
   pubg.com/en/events/redeem. The steps are kept generic («в магазине лобби найдите пункт
   ввода кода»). Confirm the real path on one code before launch.
4. PUBG G-Coin: whether the codes work only on the Steam version or also on Epic Games.
   The copy says «ПК-версия» and «не для консолей и не для PUBG Mobile» only.
5. Call of Duty: Mobile: whether the region in the switcher (KZ, US, CA, IN, SA) must
   match anything on the player's account. Activision accounts are global; the copy only
   says it is for the Activision version (not Garena), per our regions seed note, and
   does not claim a region lock.
6. CoD Mobile in-game menu labels in RU/UZ are our translations of Activision's English
   («nickname», «second tab»).
7. What each currency buys (CP: battle pass, weapon blueprints, characters; FC Points:
   Ultimate Team packs; G-Coin: skins, Survivor Pass) is general game knowledge, except
   «G-COIN buys in-game items in the Store», which PUBG Support states.
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

B["call-of-duty-mobile"] = dict(
    seo_title={
        "ru": "Call of Duty: Mobile CP — пополнить по UID в Узбекистане за сумы",
        "en": "Call of Duty: Mobile CP — top up by UID in Uzbekistan for soʻm",
        "uz": "Call of Duty: Mobile CP — Oʻzbekistonda UID orqali soʻmga toʻldirish",
    },
    seo_description={
        "ru": "Пополнение CP в Call of Duty: Mobile по UID игрока, без пароля. Версия Activision: Казахстан, США, Канада, Индия, Саудовская Аравия. Оплата в сумах через Click, Payme или Uzum.",
        "en": "Call of Duty: Mobile CP top-up by Player UID, no password. Activision version: Kazakhstan, US, Canada, India, Saudi Arabia. Pay in soʻm with Click, Payme or Uzum.",
        "uz": "Call of Duty: Mobile da CP ni oʻyinchi UID si orqali toʻldirish, parolsiz. Activision versiyasi: Qozogʻiston, AQSH, Kanada, Hindiston, Saudiya Arabistoni. Click, Payme yoki Uzum orqali soʻmda toʻlov.",
    },
    short={
        "ru": "CP для Call of Duty: Mobile по UID игрока. Пароль не нужен, оплата в сумах.",
        "en": "CP for Call of Duty: Mobile by Player UID. No password, pay in soʻm.",
        "uz": "Call of Duty: Mobile uchun oʻyinchi UID si orqali CP. Parol kerak emas, soʻmda toʻlov.",
    },
    desc={
        "ru": "CP (COD Points) — валюта Call of Duty: Mobile. На неё покупают боевой пропуск, оружие и персонажей.\n\nПополнение идёт по UID игрока. Код вводить не нужно, пароль не нужен. Подходит для версии игры от Activision.\n\nВыберите регион и сумму, укажите UID и оплатите. CP придут на аккаунт после оплаты.",
        "en": "CP (COD Points) is the currency of Call of Duty: Mobile. It buys the battle pass, weapons and characters.\n\nThe top-up goes by Player UID. No code to enter, no password. It is for the Activision version of the game.\n\nPick a region and amount, enter your UID and pay. The CP arrives on the account after payment.",
        "uz": "CP (COD Points) — Call of Duty: Mobile valyutasi. Unga jangovar propusk, qurollar va personajlar olinadi.\n\nToʻldirish oʻyinchi UID si orqali. Kod kiritish shart emas, parol kerak emas. Oʻyinning Activision versiyasi uchun.\n\nMintaqa va summani tanlang, UID ni kiriting va toʻlang. CP toʻlovdan soʻng akkauntga tushadi.",
    },
    steps={
        "ru": [
            "В игре на главном экране нажмите на свой никнейм в левом верхнем углу и откройте вторую вкладку — профиль.",
            "Скопируйте UID — длинное число (около 20 цифр) под никнеймом.",
            "Выберите регион и сумму CP выше и вставьте UID.",
            "Оплатите заказ и перезайдите в игру.",
        ],
        "en": [
            "In the game, on the home screen, tap your nickname at the top left and open the second tab — your profile.",
            "Copy your UID — the long number (about 20 digits) under your nickname.",
            "Pick a region and CP amount above and paste the UID.",
            "Pay for the order and restart the game.",
        ],
        "uz": [
            "Oʻyinda bosh ekranda yuqori chap burchakdagi nikneymingizni bosing va ikkinchi tabni — profilni oching.",
            "UID ni nusxalang — nikneym ostidagi uzun raqam (taxminan 20 ta raqam).",
            "Yuqorida mintaqa va CP summasini tanlang, UID ni kiriting.",
            "Buyurtmani toʻlang va oʻyinga qayta kiring.",
        ],
    },
    faqs=[
        (
            {
                "ru": "Где найти UID?",
                "en": "Where do I find my UID?",
                "uz": "UID ni qayerdan topaman?",
            },
            {
                "ru": "В игре нажмите на свой никнейм в левом верхнем углу главного экрана и откройте вторую вкладку. UID — длинное число под никнеймом. Проверьте его перед оплатой: CP придут на тот аккаунт, чей UID указан.",
                "en": "In the game, tap your nickname at the top left of the home screen and open the second tab. The UID is the long number under your nickname. Check it before paying: the CP goes to the account whose UID you entered.",
                "uz": "Oʻyinda bosh ekranning yuqori chap burchagidagi nikneymingizni bosing va ikkinchi tabni oching. UID — nikneym ostidagi uzun raqam. Toʻlashdan oldin tekshiring: CP UID si kiritilgan akkauntga tushadi.",
            },
        ),
        (
            {
                "ru": "Какая версия игры подходит?",
                "en": "Which version of the game does this fit?",
                "uz": "Oʻyinning qaysi versiyasiga mos?",
            },
            {
                "ru": "Версия от Activision. Версии Garena для Юго-Восточной Азии здесь не пополняются.",
                "en": "The Activision version. Garena versions for Southeast Asia cannot be topped up here.",
                "uz": "Activision versiyasi. Janubi-Sharqiy Osiyo uchun Garena versiyalari bu yerda toʻldirilmaydi.",
            },
        ),
        (
            {
                "ru": "Нужен ли пароль от аккаунта?",
                "en": "Do you need my account password?",
                "uz": "Akkaunt paroli kerakmi?",
            },
            {
                "ru": "Нет. Нужен только UID. Никому не сообщайте пароль.",
                "en": "No. Only the UID. Never share your password with anyone.",
                "uz": "Yoʻq. Faqat UID kerak. Parolingizni hech kimga bermang.",
            },
        ),
        (PAY_Q, PAY),
    ],
)

B["ea-sports-fc-26"] = dict(
    seo_title={
        "ru": "EA SPORTS FC 26 Points — купить в Узбекистане за сумы",
        "en": "EA SPORTS FC 26 Points — buy in Uzbekistan for soʻm",
        "uz": "EA SPORTS FC 26 Points — Oʻzbekistonda soʻmga sotib olish",
    },
    seo_description={
        "ru": "Коды FC Points для EA SPORTS FC 26 на ПК: 1050, 2800, 5900, 12000 и 18500 очков. Код на почту после оплаты. Оплата в сумах через Click, Payme или Uzum.",
        "en": "FC Points codes for EA SPORTS FC 26 on PC: 1050, 2800, 5900, 12000 and 18500 points. Code by email after payment. Pay in soʻm with Click, Payme or Uzum.",
        "uz": "PK dagi EA SPORTS FC 26 uchun FC Points kodlari: 1050, 2800, 5900, 12000 va 18500 ochko. Kod toʻlovdan soʻng pochtaga. Click, Payme yoki Uzum orqali soʻmda toʻlov.",
    },
    short={
        "ru": "Коды FC Points для EA SPORTS FC 26 на ПК. Код на почту, оплата в сумах.",
        "en": "FC Points codes for EA SPORTS FC 26 on PC. Code by email, pay in soʻm.",
        "uz": "PK dagi EA SPORTS FC 26 uchun FC Points kodlari. Kod pochtaga, soʻmda toʻlov.",
    },
    desc={
        "ru": "FC Points — валюта EA SPORTS FC 26. На неё покупают наборы в Ultimate Team.\n\nКод для ПК-версии. Он погашается на аккаунте EA, с которого вы играете. Очки остаются на своей платформе: на PlayStation или Xbox их не перенести.\n\nКод виден на странице заказа и приходит на почту после оплаты.",
        "en": "FC Points are the currency of EA SPORTS FC 26. They buy packs in Ultimate Team.\n\nThe code is for the PC version. Redeem it on the EA account you play on. Points stay on their platform: they cannot be moved to PlayStation or Xbox.\n\nThe code shows on the order page and arrives by email after payment.",
        "uz": "FC Points — EA SPORTS FC 26 valyutasi. Unga Ultimate Team da toʻplamlar olinadi.\n\nKod PK versiyasi uchun. U siz oʻynaydigan EA akkauntida faollashtiriladi. Ochkolar oʻz platformasida qoladi: PlayStation yoki Xbox ga oʻtkazib boʻlmaydi.\n\nKod toʻlovdan soʻng buyurtma sahifasida koʻrinadi va pochtaga keladi.",
    },
    steps={
        "ru": [
            "Запустите EA app и войдите в аккаунт EA, с которого играете в FC 26.",
            "Откройте «Моя библиотека» (My Library) и выберите «Активировать код» (Redeem Code).",
            "Введите код из письма и подтвердите.",
            "Или откройте ea.com/redeem, нажмите Redeem для ПК-кодов и введите код.",
            "Запустите FC 26 и войдите в Ultimate Team — очки будут на балансе.",
        ],
        "en": [
            "Launch the EA app and sign in to the EA account you play FC 26 on.",
            "Open My Library and choose Redeem Code.",
            "Enter the code from the email and confirm.",
            "Or open ea.com/redeem, click Redeem for PC codes and enter the code.",
            "Launch FC 26 and enter Ultimate Team — the points are on your balance.",
        ],
        "uz": [
            "EA app ni ishga tushiring va FC 26 oʻynaydigan EA akkauntingizga kiring.",
            "«My Library» ni oching va «Redeem Code» ni tanlang.",
            "Xatdagi kodni kiriting va tasdiqlang.",
            "Yoki ea.com/redeem ni oching, PK kodlari uchun Redeem ni bosing va kodni kiriting.",
            "FC 26 ni ishga tushiring va Ultimate Team ga kiring — ochkolar balansda boʻladi.",
        ],
    },
    faqs=[
        (
            {
                "ru": "Код подойдёт для PlayStation или Xbox?",
                "en": "Will the code work on PlayStation or Xbox?",
                "uz": "Kod PlayStation yoki Xbox uchun mos keladimi?",
            },
            {
                "ru": "Нет. Код для ПК-версии FC 26. Очки, погашенные на ПК, на консоли не переносятся.",
                "en": "No. The code is for the PC version of FC 26. Points redeemed on PC cannot be moved to a console.",
                "uz": "Yoʻq. Kod FC 26 ning PK versiyasi uchun. PK da faollashtirilgan ochkolar konsolga oʻtkazilmaydi.",
            },
        ),
        (PAY_Q, PAY),
        (WHERE_Q, WHERE_A),
        (
            {
                "ru": "Я погасил код, а очков в игре нет. Что делать?",
                "en": "I redeemed the code but see no points in the game. What now?",
                "uz": "Kodni faollashtirdim, lekin oʻyinda ochko yoʻq. Nima qilish kerak?",
            },
            {
                "ru": "Проверьте, что код погашен на том аккаунте EA, с которого вы играете. Затем перезапустите игру и снова войдите в Ultimate Team.",
                "en": "Check that you redeemed the code on the EA account you play on. Then restart the game and enter Ultimate Team again.",
                "uz": "Kod siz oʻynaydigan EA akkauntida faollashtirilganini tekshiring. Soʻng oʻyinni qayta ishga tushiring va Ultimate Team ga qayta kiring.",
            },
        ),
    ],
)

B["pubg-battlegrounds"] = dict(
    seo_title={
        "ru": "PUBG: BATTLEGROUNDS G-Coin — купить в Узбекистане за сумы",
        "en": "PUBG: BATTLEGROUNDS G-Coin — buy in Uzbekistan for soʻm",
        "uz": "PUBG: BATTLEGROUNDS G-Coin — Oʻzbekistonda soʻmga sotib olish",
    },
    seo_description={
        "ru": "Коды G-Coin для PUBG: BATTLEGROUNDS на ПК: от 100 до 11200 G-Coin. Код на почту после оплаты. Оплата в сумах через Click, Payme или Uzum.",
        "en": "G-Coin codes for PUBG: BATTLEGROUNDS on PC: 100 to 11200 G-Coin. Code by email after payment. Pay in soʻm with Click, Payme or Uzum.",
        "uz": "PK dagi PUBG: BATTLEGROUNDS uchun G-Coin kodlari: 100 dan 11200 G-Coin gacha. Kod toʻlovdan soʻng pochtaga. Click, Payme yoki Uzum orqali soʻmda toʻlov.",
    },
    short={
        "ru": "Коды G-Coin для PUBG: BATTLEGROUNDS на ПК. Код на почту, оплата в сумах.",
        "en": "G-Coin codes for PUBG: BATTLEGROUNDS on PC. Code by email, pay in soʻm.",
        "uz": "PK dagi PUBG: BATTLEGROUNDS uchun G-Coin kodlari. Kod pochtaga, soʻmda toʻlov.",
    },
    desc={
        "ru": "G-Coin — валюта PUBG: BATTLEGROUNDS. На неё покупают предметы в игровом магазине: скины, наборы, Survivor Pass.\n\nКод для ПК-версии игры. Для консолей и PUBG Mobile он не подходит.\n\nКод виден на странице заказа и приходит на почту после оплаты.",
        "en": "G-Coin is the currency of PUBG: BATTLEGROUNDS. It buys items in the in-game Store: skins, bundles, the Survivor Pass.\n\nThe code is for the PC version of the game. It does not fit consoles or PUBG Mobile.\n\nThe code shows on the order page and arrives by email after payment.",
        "uz": "G-Coin — PUBG: BATTLEGROUNDS valyutasi. Unga oʻyin doʻkonidagi buyumlar olinadi: skinlar, toʻplamlar, Survivor Pass.\n\nKod oʻyinning PK versiyasi uchun. Konsollar va PUBG Mobile uchun mos emas.\n\nKod toʻlovdan soʻng buyurtma sahifasida koʻrinadi va pochtaga keladi.",
    },
    steps={
        "ru": [
            "Запустите PUBG: BATTLEGROUNDS на ПК и войдите в свой аккаунт.",
            "В лобби откройте магазин (Store) и найдите пункт ввода кода.",
            "Введите код из письма и подтвердите.",
            "G-Coin зачислятся на баланс — его видно в магазине.",
        ],
        "en": [
            "Launch PUBG: BATTLEGROUNDS on PC and sign in to your account.",
            "In the lobby, open the Store and find the option to enter a code.",
            "Enter the code from the email and confirm.",
            "The G-Coin lands on your balance — you can see it in the Store.",
        ],
        "uz": [
            "PK da PUBG: BATTLEGROUNDS ni ishga tushiring va akkauntingizga kiring.",
            "Lobbida doʻkonni (Store) oching va kod kiritish boʻlimini toping.",
            "Xatdagi kodni kiriting va tasdiqlang.",
            "G-Coin balansga tushadi — uni doʻkonda koʻrasiz.",
        ],
    },
    faqs=[
        (
            {
                "ru": "Подойдёт ли код для PUBG Mobile или консоли?",
                "en": "Will the code work for PUBG Mobile or a console?",
                "uz": "Kod PUBG Mobile yoki konsol uchun mos keladimi?",
            },
            {
                "ru": "Нет. Код только для PUBG: BATTLEGROUNDS на ПК. PUBG Mobile — другая игра со своей валютой (UC).",
                "en": "No. The code is only for PUBG: BATTLEGROUNDS on PC. PUBG Mobile is a different game with its own currency (UC).",
                "uz": "Yoʻq. Kod faqat PK dagi PUBG: BATTLEGROUNDS uchun. PUBG Mobile — oʻz valyutasi (UC) bor boshqa oʻyin.",
            },
        ),
        (PAY_Q, PAY),
        (WHERE_Q, WHERE_A),
        (
            {
                "ru": "Что купить на G-Coin?",
                "en": "What can I buy with G-Coin?",
                "uz": "G-Coin ga nima olish mumkin?",
            },
            {
                "ru": "Предметы в игровом магазине PUBG: BATTLEGROUNDS — скины, наборы и Survivor Pass.",
                "en": "Items in the PUBG: BATTLEGROUNDS in-game Store — skins, bundles and the Survivor Pass.",
                "uz": "PUBG: BATTLEGROUNDS oʻyin doʻkonidagi buyumlar — skinlar, toʻplamlar va Survivor Pass.",
            },
        ),
    ],
)
