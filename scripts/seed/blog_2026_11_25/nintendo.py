"""«Nintendo eShop из Узбекистана» (blog batch 2026-11-25, key `nintendo`).

Guide for Switch / Switch 2 owners in Uzbekistan: which country the Nintendo
Account is in, how to change it and what happens to the eShop balance, what
blocks the change, which eShop card to buy and how to redeem it. Primary
intents: «nintendo eshop узбекистан», «пополнить nintendo switch», «карта
nintendo eshop». No games, sales or prices are named on purpose.

Sources / facts used:

* Nintendo support (nintendo.com, articles on changing the Nintendo Account
  country/region; exact URLs were not in the brief):
  - the country is changed on the Nintendo Account website: User Info →
    Profile → Change (the post says «Информация о пользователе → Профиль →
    Изменить» / "User Info → Profile → Edit");
  - the eShop balance does not move to the new country: accounts in the
    Americas must spend it to 0 first; in Europe the change is possible but
    the balance is lost after a confirmation; there is a "give up balance"
    option;
  - active auto-renewals (Nintendo Switch Online) and pre-ordered DLC block
    the change;
  - eShop cards should match the account's region — kept as advice ("buy the
    card of your account's country"), not as a hard rule.
* YuPay catalogue, verified on prod 2026-11-25: `/store/nintendo` sells
  Nintendo eShop cards for 10 countries — us, eu, br, uk, ca, jp, hk, se, pl,
  de; region links as `/store/nintendo?region=<code>`. Codes are delivered on
  the order page and by e-mail after payment (no delivery time promised).
* Payment line per brief: so'm via Click, Payme or Uzum; the total in so'm is
  shown before payment and exactly that is charged.

Unverified — owner to check:

* Whether Nintendo Account / eShop accepts Uzbekistan as an account country.
  The post only says players in Uzbekistan usually keep an account of another
  country (USA, Poland, Germany, UK…), without claiming Uzbekistan is excluded.
* Redeem path on the console: Nintendo eShop → pick the user → «Ввести код» /
  "Redeem Code" in the left menu, and that the same item exists on
  Nintendo Switch 2. Also that eShop codes are 16 characters.
* Redeeming on the web: the post says there is a code-redeem page on the
  Nintendo site after signing in to the Nintendo Account. The exact page
  (and whether it exists for every region) was not checked.
* That the YuPay "eu" (Europe, euro) card fits Nintendo Accounts of euro-area
  countries. The post words this as "a euro account — the Europe card; check
  that the currency matches".
* That auto-renewal is switched off in the Nintendo Account shop settings
  (post says "в настройках Nintendo Account", no exact menu path).
* That a code which does not match the account's region is refused at
  redemption (post phrases it as "may not be accepted").
"""

from __future__ import annotations

POST = {
    "post_id": "01a21022-1547-75e0-acb5-7f1414dd88f0",
    "brand_slug": "nintendo",
    "kind": "guide",
    "cover": "https://cdn.yupay.uz/blog_image/2026/11/01a2102c-2c50-7312-9292-c6222a0062be.jpg",
    "ru": {
        "slug": "nintendo-eshop-iz-uzbekistana",
        "title": "Nintendo eShop из Узбекистана: как пополнить Switch картой своей страны",
        "excerpt": "Как пополнить Nintendo eShop из Узбекистана: в какой стране ваш Nintendo Account, что будет с балансом при смене страны, какую карту eShop взять и как ввести код.",
        "seo_title": "Nintendo eShop из Узбекистана — как пополнить Switch",
        "seo_description": "Как пополнить Nintendo Switch из Узбекистана: страна Nintendo Account, смена региона и баланс eShop, карта своей страны и ввод кода. Оплата в сумах.",
        "body": """
Пополнить Nintendo eShop из Узбекистана можно картой eShop той страны, в которой зарегистрирован ваш Nintendo Account. Сначала проверьте страну аккаунта, затем купите карту этой страны и введите код на консоли или на сайте.

## Главное

- Баланс eShop привязан к стране Nintendo Account. Карту берите той же страны.
- Страну можно сменить на сайте Nintendo Account, но баланс за вами не переедет.
- В Америке баланс сначала нужно потратить до нуля. В Европе смена возможна, но баланс сгорит после подтверждения.
- Смену страны блокируют активное автопродление Nintendo Switch Online и предзаказанные DLC.
- В YuPay карты eShop для 10 стран, оплата в сумах через Click, Payme или Uzum.

## В какой стране ваш Nintendo Account

Всё в eShop завязано на страну аккаунта: валюта баланса, цены, ассортимент и то, какая карта подойдёт. Игроки в Узбекистане обычно держат аккаунт другой страны — США, Польши, Германии, Великобритании — и пополняют его картой этой страны.

Посмотреть страну просто. Войдите на сайт Nintendo Account и откройте «Информация о пользователе». Страна указана в профиле. На консоли подсказка тоже есть: валюта баланса в eShop. Доллары США — американский аккаунт, евро — одна из стран еврозоны, фунты — Великобритания, злотые — Польша.

Если аккаунт уже есть и в нём куплены игры, страну лучше не трогать. Покупки остаются за аккаунтом, а вот с балансом и подписками при смене есть нюансы.

## Как сменить страну и что будет с балансом

Страна меняется на сайте Nintendo Account: «Информация о пользователе» → «Профиль» → «Изменить». Выберите новую страну и сохраните.

Главное здесь — деньги на балансе eShop. В новую страну они не переходят. Правило зависит от того, где аккаунт сейчас:

- **Аккаунт в странах Америки** (США, Канада, Бразилия и другие). Сменить страну можно только с нулевым балансом. Сначала потратьте всё, что лежит в eShop.
- **Аккаунт в Европе.** Сменить страну можно и с деньгами на балансе, но после подтверждения они пропадут. Nintendo прямо предлагает отказаться от баланса — это не ошибка, а условие смены.

Если на балансе есть деньги, сначала потратьте их. Не пополняйте старый регион перед переездом.

## Что блокирует смену страны

Даже с нулевым балансом смена не пройдёт, пока у аккаунта есть:

- **автопродление Nintendo Switch Online** — отключите его в настройках Nintendo Account;
- **предзаказанные DLC** — дополнения, оплаченные заранее и ещё не вышедшие. Дождитесь выхода или отмените предзаказ.

Сняли блокировки — меняйте страну. После смены пополняйте аккаунт уже картой новой страны.

## Какую карту eShop покупать

Правило одно: карта той страны, в которой Nintendo Account. Карта другой страны может не приняться при вводе кода, а валюта её номинала не совпадёт с валютой баланса.

В YuPay на странице [Nintendo eShop](/store/nintendo) есть карты 10 стран. Переключатель вверху страницы выбирает страну:

- [США](/store/nintendo?region=us) — для американского аккаунта, в долларах;
- [Европа](/store/nintendo?region=eu) — для аккаунта в стране еврозоны;
- [Германия](/store/nintendo?region=de), [Польша](/store/nintendo?region=pl), [Великобритания](/store/nintendo?region=uk), [Швеция](/store/nintendo?region=se);
- [Канада](/store/nintendo?region=ca), [Бразилия](/store/nintendo?region=br), [Япония](/store/nintendo?region=jp), [Гонконг](/store/nintendo?region=hk).

Перед оплатой сверьте две вещи: страну карты и валюту баланса в eShop. Если они совпадают, код подойдёт.

## Как купить карту в YuPay

1. Откройте [Nintendo eShop](/store/nintendo) и выберите страну своего аккаунта.
2. Выберите номинал.
3. Оплатите в сумах через Click, Payme или Uzum. Итог в сумах виден до оплаты, и списывается ровно он.
4. Код появится на странице заказа и придёт на e-mail.

## Как ввести код на Nintendo Switch и Switch 2

1. Откройте Nintendo eShop на консоли.
2. Выберите пользователя, к которому привязан нужный Nintendo Account.
3. В меню слева выберите «Ввести код».
4. Введите код с карты и подтвердите.

Сумма зачислится на баланс eShop. Тратить их можно и с консоли, и на сайте Nintendo.

Код можно ввести и без консоли: на сайте Nintendo есть страница погашения кода. Войдите в тот же Nintendo Account и введите код там. Это удобно, если консоль сейчас не под рукой.

## Частые ошибки

- **Карта не той страны.** Американская карта на европейский аккаунт — самая частая причина отказа. Сначала страна аккаунта, потом карта.
- **Пополнение перед сменой страны.** Деньги остаются в старом регионе: в Америке смена не пройдёт, в Европе баланс сгорит.
- **Не тот пользователь на консоли.** Если на Switch несколько профилей, проверьте, к какому Nintendo Account привязан выбранный.
- **Ошибка в коде.** Копируйте код со страницы заказа, а не перепечатывайте вручную. Путаются похожие символы.
- **Забытое автопродление.** Смена страны не проходит, а причина — подписка Nintendo Switch Online. Отключите автопродление заранее.

## Другие платформы

У PlayStation и Xbox правила со странами свои. У PlayStation страну аккаунта сменить нельзя совсем, у Microsoft — можно, но не чаще раза в три месяца. Подробно — в гайдах [как покупать игры в PS Store из Узбекистана](/blog/kak-pokupat-igry-v-ps-store-iz-uzbekistana) и [как пополнить Xbox из Узбекистана](/blog/kak-popolnit-xbox-iz-uzbekistana).

Проверили страну аккаунта? Откройте [Nintendo eShop в YuPay](/store/nintendo), выберите ту же страну и нужный номинал.
""",
        "faqs": [
            (
                "Можно ли пополнить Nintendo eShop из Узбекистана?",
                "Да. Купите карту eShop той страны, в которой зарегистрирован ваш Nintendo Account, и введите код на консоли или на сайте Nintendo.",
            ),
            (
                "Сохранится ли баланс eShop при смене страны аккаунта?",
                "Нет. В Америке баланс нужно потратить до нуля, иначе страна не сменится. В Европе смена возможна, но баланс пропадёт после подтверждения.",
            ),
            (
                "Почему не получается сменить страну Nintendo Account?",
                "Чаще всего мешает активное автопродление Nintendo Switch Online или предзаказанное DLC. В Америке ещё и ненулевой баланс eShop.",
            ),
            (
                "Подойдёт ли карта eShop другой страны?",
                "Берите карту страны своего аккаунта. Карта другой страны может не приняться, а её валюта не совпадёт с валютой баланса.",
            ),
            (
                "Где взять код после оплаты в YuPay?",
                "Код появится на странице заказа и придёт на e-mail. Его можно ввести в Nintendo eShop на Switch или Switch 2 либо на сайте Nintendo.",
            ),
        ],
    },
    "en": {
        "slug": "nintendo-eshop-from-uzbekistan",
        "title": "Nintendo eShop from Uzbekistan: top up your Switch with your country's card",
        "excerpt": "How to top up Nintendo eShop from Uzbekistan: which country your Nintendo Account is in, what happens to the balance if you change it, which eShop card to buy and how to redeem it.",
        "seo_title": "Nintendo eShop from Uzbekistan — how to top up your Switch",
        "seo_description": "How to top up a Nintendo Switch from Uzbekistan: Nintendo Account country, changing region and the eShop balance, the right card and redeeming the code.",
        "body": """
You can top up Nintendo eShop from Uzbekistan with an eShop card from the country your Nintendo Account is registered in. Check the account's country first, then buy a card for that country and redeem the code on the console or on the web.

## Key takeaways

- The eShop balance is tied to the Nintendo Account's country. Buy a card from the same country.
- You can change the country on the Nintendo Account website, but your balance will not move with you.
- In the Americas you must spend the balance to zero first. In Europe the change goes through, but the balance is lost after you confirm.
- An active Nintendo Switch Online auto-renewal or a pre-ordered DLC blocks the change.
- YuPay sells eShop cards for 10 countries; you pay in soʻm with Click, Payme or Uzum.

## Which country your Nintendo Account is in

Everything in eShop follows the account's country: the balance currency, prices, the catalogue, and which card will work. Players in Uzbekistan usually keep an account from another country — the USA, Poland, Germany, the UK — and top it up with that country's card.

Checking is simple. Sign in to the Nintendo Account website and open User Info. The country is shown in your profile. The console gives a hint too: the currency of your eShop balance. US dollars mean a US account, euros an account in a euro-area country, pounds the UK, złoty Poland.

If you already have an account with games on it, it is better to leave the country alone. Your purchases stay with the account, but the balance and subscriptions come with conditions when you switch.

## How to change the country and what happens to the balance

The country is changed on the Nintendo Account website: User Info → Profile → Edit. Pick the new country and save.

The key issue is the money in your eShop balance. It does not move to the new country. The rule depends on where the account is now:

- **Account in the Americas** (USA, Canada, Brazil and others). You can only change the country with a zero balance. Spend everything in eShop first.
- **Account in Europe.** You can change the country with money still in the balance, but it is gone once you confirm. Nintendo explicitly asks you to give up the balance — that is not a bug, it is a condition of the change.

If you have money in the balance, spend it first. Do not top up the old region right before moving.

## What blocks a country change

Even with a zero balance, the change will not go through while the account has:

- **Nintendo Switch Online auto-renewal** — turn it off in your Nintendo Account settings;
- **pre-ordered DLC** — add-ons paid for in advance that have not come out yet. Wait for the release or cancel the pre-order.

Once these are cleared, change the country. From then on, top up with cards of the new country.

## Which eShop card to buy

One rule: a card from the country your Nintendo Account is in. A card from another country may be refused when you redeem it, and its currency will not match your balance.

On YuPay, the [Nintendo eShop](/store/nintendo) page has cards for 10 countries. The switcher at the top of the page picks the country:

- [USA](/store/nintendo?region=us) — for a US account, in dollars;
- [Europe](/store/nintendo?region=eu) — for an account in a euro-area country;
- [Germany](/store/nintendo?region=de), [Poland](/store/nintendo?region=pl), [United Kingdom](/store/nintendo?region=uk), [Sweden](/store/nintendo?region=se);
- [Canada](/store/nintendo?region=ca), [Brazil](/store/nintendo?region=br), [Japan](/store/nintendo?region=jp), [Hong Kong](/store/nintendo?region=hk).

Before paying, check two things: the card's country and your eShop balance currency. If they match, the code will work.

## How to buy a card on YuPay

1. Open [Nintendo eShop](/store/nintendo) and pick your account's country.
2. Choose the amount.
3. Pay in soʻm with Click, Payme or Uzum. The total in soʻm is shown before payment, and that is exactly what is charged.
4. The code appears on the order page and is sent to your email.

## How to redeem the code on Nintendo Switch and Switch 2

1. Open Nintendo eShop on the console.
2. Select the user linked to the right Nintendo Account.
3. In the left-hand menu, choose Redeem Code.
4. Enter the code from the card and confirm.

The amount is added to your eShop balance. You can spend it from the console or on the Nintendo website.

You can also redeem without the console: the Nintendo website has a code redemption page. Sign in to the same Nintendo Account and enter the code there. Handy when the console is not at hand.

## Common mistakes

- **A card from the wrong country.** A US card on a European account is the most common reason for a refusal. Account country first, card second.
- **Topping up before a country change.** The money stays in the old region: in the Americas the change will not go through, in Europe the balance is lost.
- **The wrong user on the console.** If your Switch has several profiles, check which Nintendo Account the selected one is linked to.
- **A typo in the code.** Copy the code from the order page instead of retyping it. Similar-looking characters get mixed up.
- **A forgotten auto-renewal.** The country change fails, and the cause is the Nintendo Switch Online subscription. Turn auto-renewal off in advance.

## Other platforms

PlayStation and Xbox have their own country rules. On PlayStation the account's country cannot be changed at all; on Microsoft it can, but not more than once every three months. Details are in our guides on [how to buy PS Store games from Uzbekistan](/blog/how-to-buy-ps-store-games-from-uzbekistan) and [how to top up Xbox from Uzbekistan](/blog/how-to-top-up-xbox-from-uzbekistan).

Checked your account's country? Open [Nintendo eShop on YuPay](/store/nintendo), pick the same country and the amount you need.
""",
        "faqs": [
            (
                "Can I top up Nintendo eShop from Uzbekistan?",
                "Yes. Buy an eShop card from the country your Nintendo Account is registered in and redeem the code on the console or on the Nintendo website.",
            ),
            (
                "Will my eShop balance survive a country change?",
                "No. In the Americas you must spend the balance to zero or the country will not change. In Europe the change goes through, but the balance is lost after you confirm.",
            ),
            (
                "Why can't I change my Nintendo Account country?",
                "Usually an active Nintendo Switch Online auto-renewal or a pre-ordered DLC is in the way. In the Americas, a non-zero eShop balance blocks it too.",
            ),
            (
                "Will an eShop card from another country work?",
                "Buy a card from your account's country. A card from another country may be refused, and its currency will not match your balance.",
            ),
            (
                "Where do I get the code after paying on YuPay?",
                "The code appears on the order page and is sent to your email. Redeem it in Nintendo eShop on Switch or Switch 2, or on the Nintendo website.",
            ),
        ],
    },
    "uz": {
        "slug": "nintendo-eshop-ozbekistondan",
        "title": "Nintendo eShop Oʻzbekistondan: Switch’ni oʻz mamlakatingiz kartasi bilan toʻldirish",
        "excerpt": "Nintendo eShop’ni Oʻzbekistondan qanday toʻldirish: Nintendo Account qaysi mamlakatda, mamlakat almashtirilsa balans nima boʻladi, qaysi eShop kartasini olish va kodni qanday kiritish.",
        "seo_title": "Nintendo eShop Oʻzbekistondan — Switch’ni toʻldirish",
        "seo_description": "Nintendo Switch’ni Oʻzbekistondan toʻldirish: Nintendo Account mamlakati, regionni almashtirish va eShop balansi, oʻz mamlakatingiz kartasi va kodni kiritish.",
        "body": """
Nintendo eShop’ni Oʻzbekistondan Nintendo Account roʻyxatdan oʻtgan mamlakatning eShop kartasi bilan toʻldirish mumkin. Avval akkaunt mamlakatini tekshiring, soʻng shu mamlakat kartasini oling va kodni konsolda yoki saytda kiriting.

## Asosiysi

- eShop balansi Nintendo Account mamlakatiga bogʻlangan. Kartani ham shu mamlakatnikini oling.
- Mamlakatni Nintendo Account saytida almashtirish mumkin, lekin balans siz bilan koʻchmaydi.
- Amerikada balansni avval nolgacha sarflash kerak. Yevropada almashtirish mumkin, lekin tasdiqlangach balans yoʻqoladi.
- Nintendo Switch Online avtomatik uzaytirilishi va oldindan buyurtma qilingan DLC almashtirishni toʻsadi.
- YuPay’da 10 ta mamlakat uchun eShop kartalari bor, toʻlov soʻmda, Click, Payme yoki Uzum orqali.

## Nintendo Account qaysi mamlakatda

eShop’dagi hamma narsa akkaunt mamlakatiga bogʻliq: balans valyutasi, narxlar, assortiment va qaysi karta mos kelishi. Oʻzbekistondagi oʻyinchilar odatda boshqa mamlakat akkauntini — AQSh, Polsha, Germaniya, Buyuk Britaniya — ishlatadi va uni shu mamlakat kartasi bilan toʻldiradi.

Tekshirish oson. Nintendo Account saytiga kiring va «Foydalanuvchi maʼlumotlari» boʻlimini oching. Mamlakat profilda koʻrsatilgan. Konsolda ham ishora bor: eShop balansining valyutasi. AQSh dollari — Amerika akkaunti, yevro — yevrohududdagi mamlakat, funt — Buyuk Britaniya, zlotiy — Polsha.

Agar akkaunt allaqachon bor va unda oʻyinlar sotib olingan boʻlsa, mamlakatni oʻzgartirmagan maʼqul. Xaridlar akkauntda qoladi, lekin almashtirishda balans va obunalar bilan bogʻliq shartlar bor.

## Mamlakatni qanday almashtirish va balans nima boʻladi

Mamlakat Nintendo Account saytida almashtiriladi: «Foydalanuvchi maʼlumotlari» → «Profil» → «Oʻzgartirish». Yangi mamlakatni tanlang va saqlang.

Bu yerda asosiysi — eShop balansidagi pul. U yangi mamlakatga oʻtmaydi. Qoida akkaunt hozir qayerda ekaniga bogʻliq:

- **Amerika mamlakatlaridagi akkaunt** (AQSh, Kanada, Braziliya va boshqalar). Mamlakatni faqat nol balans bilan almashtirish mumkin. Avval eShop’dagi hamma pulni sarflang.
- **Yevropadagi akkaunt.** Balansda pul boʻlsa ham almashtirish mumkin, lekin tasdiqlangach u yoʻqoladi. Nintendo balansdan voz kechishni ochiq taklif qiladi — bu xato emas, almashtirish sharti.

Balansda pul boʻlsa, avval uni sarflang. Koʻchishdan oldin eski regionni toʻldirmang.

## Mamlakat almashtirishni nima toʻsadi

Balans nol boʻlsa ham, akkauntda quyidagilar boʻlsa almashtirish oʻtmaydi:

- **Nintendo Switch Online avtomatik uzaytirilishi** — uni Nintendo Account sozlamalarida oʻchiring;
- **oldindan buyurtma qilingan DLC** — oldindan toʻlangan, hali chiqmagan qoʻshimchalar. Chiqishini kuting yoki oldindan buyurtmani bekor qiling.

Toʻsiqlarni olib tashlagach, mamlakatni almashtiring. Shundan keyin akkauntni yangi mamlakat kartasi bilan toʻldiring.

## Qaysi eShop kartasini olish

Qoida bitta: Nintendo Account qaysi mamlakatda boʻlsa, karta ham shu mamlakatniki. Boshqa mamlakat kartasi kodni kiritishda qabul qilinmasligi mumkin, uning valyutasi esa balans valyutasiga mos kelmaydi.

YuPay’da [Nintendo eShop](/store/nintendo) sahifasida 10 ta mamlakat kartalari bor. Sahifa yuqorisidagi almashtirgich mamlakatni tanlaydi:

- [AQSh](/store/nintendo?region=us) — Amerika akkaunti uchun, dollarda;
- [Yevropa](/store/nintendo?region=eu) — yevrohududdagi mamlakat akkaunti uchun;
- [Germaniya](/store/nintendo?region=de), [Polsha](/store/nintendo?region=pl), [Buyuk Britaniya](/store/nintendo?region=uk), [Shvetsiya](/store/nintendo?region=se);
- [Kanada](/store/nintendo?region=ca), [Braziliya](/store/nintendo?region=br), [Yaponiya](/store/nintendo?region=jp), [Gonkong](/store/nintendo?region=hk).

Toʻlovdan oldin ikki narsani solishtiring: karta mamlakati va eShop balansi valyutasi. Ular mos kelsa, kod ishlaydi.

## YuPay’da kartani qanday sotib olish

1. [Nintendo eShop](/store/nintendo) sahifasini oching va akkauntingiz mamlakatini tanlang.
2. Nominalni tanlang.
3. Click, Payme yoki Uzum orqali soʻmda toʻlang. Yakuniy summa toʻlovdan oldin koʻrinadi va aynan u yechiladi.
4. Kod buyurtma sahifasida paydo boʻladi va e-mail’ga keladi.

## Kodni Nintendo Switch va Switch 2’da qanday kiritish

1. Konsolda Nintendo eShop’ni oching.
2. Kerakli Nintendo Account bogʻlangan foydalanuvchini tanlang.
3. Chap menyuda «Kodni kiritish» bandini tanlang.
4. Kartadagi kodni kiriting va tasdiqlang.

Summa eShop balansiga tushadi. Uni konsoldan ham, Nintendo saytida ham sarflash mumkin.

Kodni konsolsiz ham kiritish mumkin: Nintendo saytida kodni faollashtirish sahifasi bor. Oʻsha Nintendo Account’ga kiring va kodni shu yerda kiriting. Konsol yoningizda boʻlmasa, bu qulay.

## Koʻp uchraydigan xatolar

- **Boshqa mamlakat kartasi.** Yevropa akkauntiga AQSh kartasi — rad etilishning eng koʻp sababi. Avval akkaunt mamlakati, keyin karta.
- **Mamlakatni almashtirishdan oldin toʻldirish.** Pul eski regionda qoladi: Amerikada almashtirish oʻtmaydi, Yevropada balans yoʻqoladi.
- **Konsolda boshqa foydalanuvchi.** Switch’da bir nechta profil boʻlsa, tanlangani qaysi Nintendo Account’ga bogʻlanganini tekshiring.
- **Koddagi xato.** Kodni qoʻlda qayta yozmang, buyurtma sahifasidan nusxalang. Oʻxshash belgilar adashtiriladi.
- **Unutilgan avtomatik uzaytirish.** Mamlakat almashmaydi, sababi esa Nintendo Switch Online obunasi. Avtomatik uzaytirishni oldindan oʻchiring.

## Boshqa platformalar

PlayStation va Xbox’da mamlakat qoidalari boshqacha. PlayStation’da akkaunt mamlakatini umuman oʻzgartirib boʻlmaydi, Microsoft’da mumkin, lekin uch oyda bir martadan koʻp emas. Batafsil — [PS Store’dan oʻyin sotib olish](/blog/ps-store-dan-oyin-sotib-olish) va [Xbox hisobini toʻldirish](/blog/xbox-hisobini-toldirish) qoʻllanmalarida.

Akkaunt mamlakatini tekshirdingizmi? YuPay’da [Nintendo eShop](/store/nintendo) sahifasini oching, oʻsha mamlakatni va kerakli nominalni tanlang.
""",
        "faqs": [
            (
                "Nintendo eShop’ni Oʻzbekistondan toʻldirish mumkinmi?",
                "Ha. Nintendo Account roʻyxatdan oʻtgan mamlakatning eShop kartasini oling va kodni konsolda yoki Nintendo saytida kiriting.",
            ),
            (
                "Akkaunt mamlakati almashtirilsa, eShop balansi saqlanadimi?",
                "Yoʻq. Amerikada balansni nolgacha sarflash kerak, aks holda mamlakat almashmaydi. Yevropada almashtirish mumkin, lekin tasdiqlangach balans yoʻqoladi.",
            ),
            (
                "Nega Nintendo Account mamlakatini almashtirib boʻlmayapti?",
                "Koʻpincha Nintendo Switch Online avtomatik uzaytirilishi yoki oldindan buyurtma qilingan DLC xalal beradi. Amerikada nol boʻlmagan eShop balansi ham toʻsadi.",
            ),
            (
                "Boshqa mamlakat eShop kartasi mos keladimi?",
                "Akkauntingiz mamlakati kartasini oling. Boshqa mamlakat kartasi qabul qilinmasligi mumkin, uning valyutasi esa balans valyutasiga mos kelmaydi.",
            ),
            (
                "YuPay’da toʻlovdan keyin kodni qayerdan olaman?",
                "Kod buyurtma sahifasida paydo boʻladi va e-mail’ga keladi. Uni Switch yoki Switch 2’dagi Nintendo eShop’da yoki Nintendo saytida kiritish mumkin.",
            ),
        ],
    },
}
