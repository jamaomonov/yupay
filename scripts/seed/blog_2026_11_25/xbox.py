"""«Как пополнить Xbox из Узбекистана» (blog batch 2026-11-25, key `xbox`).

Sources / facts used:

* Microsoft account country/region can be changed, but not if it was changed
  within the last three months; money in the account does not move to the
  new region (spend it first); some subscriptions and purchases may not work
  in the new region; Xbox/Microsoft gift cards are region-locked and must
  match the account's country/region; Microsoft support cannot convert a
  card's region; the console's store region is set in Settings → System →
  Language & location and should match the account.
  https://support.microsoft.com/help/4039267
* GTA VI released 2026-11-19 on PS5 and Xbox Series X|S; Xbox codes are
  region-free (Rockstar support as quoted by press).
  https://sixhype.com/blog/gta-6-region-locked-ps5-codes-explained/ ,
  https://www.detroitnews.com/story/tech/2026/11/18/when-does-gta-6-online-come-out-grand-theft-auto-vi-release-ps5-xbox/92843185007/
* YuPay catalogue (prod, 2026-11-25): `/store/xbox`, 21 countries — us, tr,
  eu, br, uk, ca, au, jp, hk, ae, sa, mx, za, dk, no, pl, de, es, cz, hu, co.
  Codes are delivered on the order page and by e-mail after payment.

Unverified — owner to check:

* Whether Microsoft accepts Uzbekistan as an account country with a working
  Xbox store. The post only says players in Uzbekistan usually keep an account
  of another country (USA, Turkey, UAE, Poland…).
* Where the country is changed: the post says «профиль Microsoft-аккаунта,
  раздел «Ваши сведения»» (account.microsoft.com → Your info). Path taken from
  general knowledge, not from the brief's facts.
* Redeem paths: on the console — Microsoft Store → «Погасить» (Redeem) via the
  View/menu button; on the web — microsoft.com/redeem. General knowledge,
  menu labels may differ by console and dashboard version. The «25 символов»
  code length is also general knowledge.
* That Microsoft account balance can pay for Game Pass and games in the
  Microsoft Store (general knowledge; no Game Pass prices or tiers quoted).
* The «PUR-…» error wording: the post describes these errors only in general
  terms (wrong account / wrong region / code already used) and names no
  specific code.
* The «EU» card: the post says to choose it only if the account's country is
  in the euro zone and the card page lists it. Exact list of accepted
  countries not verified.
"""

from __future__ import annotations

POST = {
    "post_id": "01a21022-148e-72b0-a348-0acf1b30f13e",
    "brand_slug": "xbox",
    "kind": "guide",
    "cover": "https://cdn.yupay.uz/blog_image/2026/11/01a21024-4167-7ef2-b643-dd8e0b84f81f.jpg",
    "ru": {
        "slug": "kak-popolnit-xbox-iz-uzbekistana",
        "title": "Как пополнить Xbox из Узбекистана",
        "excerpt": "Как пополнить Xbox из Узбекистана: страна Microsoft-аккаунта, правило трёх месяцев для смены региона, какую подарочную карту брать и как её активировать.",
        "seo_title": "Как пополнить Xbox из Узбекистана — карты и смена региона",
        "seo_description": "Пополнение Xbox из Узбекистана: карта страны вашего Microsoft-аккаунта, смена региона раз в три месяца, активация кода и ошибки PUR. Оплата в сумах.",
        "body": """
Xbox пополняют подарочной картой той страны, которая указана в вашем Microsoft-аккаунте. Узнайте страну аккаунта, купите карту этой страны и активируйте код на консоли или на сайте Microsoft.

## Главное

- Карта Xbox работает только на аккаунте той же страны. Регион карты Microsoft не меняет, даже через поддержку.
- Страну Microsoft-аккаунта сменить можно, но не чаще одного раза в три месяца.
- Деньги на балансе при смене страны не переезжают. Сначала потратьте их.
- Регион магазина на консоли держите таким же, как у аккаунта.
- В YuPay карты Xbox 21 страны, оплата в сумах через Click, Payme или Uzum. Итог в сумах виден до оплаты, и списывается ровно он.

## Страна аккаунта и регион консоли

У Xbox две настройки, которые часто путают.

**Страна Microsoft-аккаунта.** От неё зависят валюта баланса и то, какие карты подходят. Её видно в профиле Microsoft-аккаунта, в разделе «Ваши сведения».

**Регион консоли.** Это настройка самой приставки: «Настройки» → «Система» → «Язык и расположение». Она определяет, какой магазин вы видите. Держите её такой же, как страна аккаунта, иначе магазин и баланс будут показывать разное.

Игроки в Узбекистане обычно пользуются аккаунтом другой страны: США, Турции, ОАЭ, Польши. Какую страну выбрать, решаете вы. Главное — дальше пополнять аккаунт картами именно этой страны.

## Как сменить регион Xbox

Если аккаунт уже создан не на ту страну, её можно поменять. Правила Microsoft такие:

1. Страну нельзя сменить, если вы уже меняли её в последние три месяца.
2. Деньги на балансе в новый регион не переходят. Потратьте их до смены.
3. Часть подписок и покупок в новом регионе может не работать. Проверьте это до смены, особенно если у вас активна подписка.
4. После смены страны аккаунта поменяйте и регион консоли в «Язык и расположение».

Из-за правила трёх месяцев страну не стоит менять ради одной скидки. Выберите регион один раз и пополняйте его.

## Какую карту брать

Правило одно: карта той же страны, что и аккаунт. Карта США не активируется на турецком аккаунте, и наоборот. Поддержка Microsoft не может перевести карту в другой регион, поэтому ошибку при покупке уже не исправить.

В [каталоге YuPay](/store/xbox) один раздел Xbox с переключателем стран. Например:

- [Xbox США](/store/xbox?region=us) — для американского аккаунта;
- [Xbox Турция](/store/xbox?region=tr) — для турецкого;
- [Xbox ОАЭ](/store/xbox?region=ae) — для аккаунта ОАЭ;
- [Xbox Польша](/store/xbox?region=pl) — для польского.

Ещё есть Великобритания, Германия, Испания, Бразилия, Мексика, Канада, Япония и другие. Карту «EU» берите, только если страна аккаунта входит в еврозону.

## Как активировать карту Xbox

После оплаты код приходит на страницу заказа и на почту. Активировать его можно двумя способами.

**На консоли:**

1. Войдите в нужный профиль.
2. Откройте Microsoft Store.
3. Нажмите кнопку меню и выберите «Погасить код».
4. Введите 25 символов кода и подтвердите.

**На сайте:**

1. Откройте страницу погашения кода на сайте Microsoft (microsoft.com/redeem).
2. Войдите в тот же Microsoft-аккаунт, что и на консоли.
3. Введите код и подтвердите.

Деньги зачисляются на баланс аккаунта. Код одноразовый: после активации повторно он не сработает.

## Игры и Game Pass с баланса

Баланс тратится в Microsoft Store: на игры, дополнения, внутриигровую валюту и подписку Game Pass. При покупке выберите оплату с баланса аккаунта.

Если денег не хватает до нужной суммы, добавьте ещё одну карту той же страны. Балансы суммируются.

Grand Theft Auto VI вышла 19 ноября 2026 года, в том числе на Xbox Series X|S. Коды для Xbox, по данным Rockstar, не привязаны к региону. Самый простой путь — купить игру в Microsoft Store своего аккаунта с баланса. Подробно — в гайде [как купить GTA 6 в Узбекистане](/blog/kak-kupit-gta-6-v-uzbekistane).

## Ошибки при активации

Если код не принимается, Xbox показывает ошибку, часто с кодом вида «PUR-…». Простыми словами причин три.

- **Не тот аккаунт.** Вы вошли в другой профиль или на сайте — в другой Microsoft-аккаунт. Проверьте почту аккаунта.
- **Не тот регион.** Страна карты не совпадает со страной аккаунта. Это частая причина. Исправить можно только сменой страны аккаунта, с учётом правила трёх месяцев.
- **Код уже активирован или введён с ошибкой.** Сверьте символы: буквы и цифры легко перепутать. Посмотрите историю заказов аккаунта: возможно, деньги уже на балансе.

Если всё сходится, а код не проходит, напишите в поддержку YuPay и приложите номер заказа.

## Итог

Узнайте страну своего Microsoft-аккаунта, возьмите карту этой страны и активируйте её на консоли или на сайте. Регион меняйте редко: раз в три месяца и только с пустым балансом.

Нужная карта — в разделе [Xbox в каталоге YuPay](/store/xbox). Для PlayStation логика похожа, её мы разобрали в гайде [как покупать игры в PS Store из Узбекистана](/blog/kak-pokupat-igry-v-ps-store-iz-uzbekistana).
""",
        "faqs": [
            (
                "Подойдёт ли карта Xbox США к турецкому аккаунту?",
                "Нет. Карта Xbox работает только на аккаунте той же страны, и Microsoft не меняет её регион.",
            ),
            (
                "Как часто можно менять страну Microsoft-аккаунта?",
                "Не чаще одного раза в три месяца. Баланс при смене не переносится, поэтому сначала потратьте его.",
            ),
            (
                "Где активировать код Xbox?",
                "На консоли — в Microsoft Store через «Погасить код», или на сайте Microsoft на странице погашения. Входите в тот же аккаунт, который пополняете.",
            ),
            (
                "Можно ли оплатить Game Pass с баланса?",
                "Да, баланс Microsoft-аккаунта тратится на игры, дополнения и Game Pass в Microsoft Store.",
            ),
            (
                "Что значит ошибка PUR при активации?",
                "Обычно это не тот аккаунт, страна карты не совпадает со страной аккаунта или код уже активирован. Проверьте эти три пункта, затем напишите в поддержку YuPay с номером заказа.",
            ),
        ],
    },
    "en": {
        "slug": "how-to-top-up-xbox-from-uzbekistan",
        "title": "How to top up Xbox from Uzbekistan",
        "excerpt": "How to top up Xbox from Uzbekistan: your Microsoft account's country, the three-month rule for changing region, which gift card to buy and how to redeem it.",
        "seo_title": "How to top up Xbox from Uzbekistan — gift cards and region",
        "seo_description": "Top up Xbox from Uzbekistan: a gift card of your Microsoft account's country, region change once in three months, redeeming the code and PUR errors. Pay in soʻm.",
        "body": """
You top up Xbox with a gift card from the country set on your Microsoft account. Check your account's country, buy a card for that country and redeem the code on the console or on Microsoft's website.

## Key takeaways

- An Xbox card works only on an account of the same country. Microsoft does not change a card's region, not even through support.
- You can change your Microsoft account's country, but not more than once in three months.
- Money in your balance does not move with a country change. Spend it first.
- Keep the console's store region the same as the account's.
- YuPay has Xbox cards for 21 countries. You pay in soʻm with Click, Payme or Uzum. The total in soʻm is shown before payment, and that is exactly what is charged.

## Account country and console region

Xbox has two settings that people often mix up.

**Microsoft account country.** It sets your balance currency and which cards will work. You can see it in your Microsoft account profile, under "Your info".

**Console region.** This is a setting on the console itself: Settings → System → Language & location. It decides which store you see. Keep it the same as the account country, or the store and your balance will disagree.

Players in Uzbekistan usually use an account from another country: the USA, Turkey, the UAE, Poland. Which country is your choice. What matters is that you then top it up with cards of that same country.

## How to change your Xbox region

If the account was created for the wrong country, you can change it. Microsoft's rules:

1. You cannot change the country if you already changed it in the last three months.
2. Money in your balance does not move to the new region. Spend it before switching.
3. Some subscriptions and purchases may not work in the new region. Check this first, especially if you have an active subscription.
4. After changing the account country, change the console region in Language & location as well.

Because of the three-month rule, do not switch country for a single discount. Pick a region once and keep topping it up.

## Which card to buy

One rule: a card from the same country as your account. A US card will not redeem on a Turkish account, and the other way round. Microsoft support cannot move a card to another region, so a wrong purchase cannot be fixed later.

The [YuPay catalogue](/store/xbox) has one Xbox page with a country switcher. For example:

- [Xbox USA](/store/xbox?region=us) — for a US account;
- [Xbox Turkey](/store/xbox?region=tr) — for a Turkish one;
- [Xbox UAE](/store/xbox?region=ae) — for a UAE account;
- [Xbox Poland](/store/xbox?region=pl) — for a Polish one.

There are also the UK, Germany, Spain, Brazil, Mexico, Canada, Japan and others. Take the "EU" card only if your account's country is in the euro zone.

## How to redeem an Xbox card

After payment, the code appears on the order page and arrives by e-mail. You can redeem it in two ways.

**On the console:**

1. Sign in to the right profile.
2. Open Microsoft Store.
3. Press the menu button and choose "Redeem".
4. Enter the 25-character code and confirm.

**On the web:**

1. Open the redeem page on Microsoft's website (microsoft.com/redeem).
2. Sign in to the same Microsoft account you use on the console.
3. Enter the code and confirm.

The money goes to your account balance. The code is single-use: once redeemed, it will not work again.

## Games and Game Pass from your balance

The balance is spent in Microsoft Store: on games, add-ons, in-game currency and a Game Pass subscription. At checkout, choose to pay from your account balance.

If you are short of the amount you need, add another card of the same country. Balances add up.

Grand Theft Auto VI came out on 19 November 2026, including on Xbox Series X|S. According to Rockstar, Xbox codes are not region-locked. The simplest route is to buy the game in your account's Microsoft Store from your balance. Details are in our guide on [how to buy GTA 6 in Uzbekistan](/blog/how-to-buy-gta-6-in-uzbekistan).

## Redeem errors

If a code is not accepted, Xbox shows an error, often with a code like "PUR-…". In plain words there are three causes.

- **Wrong account.** You are signed in to another profile, or to another Microsoft account on the website. Check the account's e-mail.
- **Wrong region.** The card's country does not match the account's. This is a common cause. The only fix is changing the account country, within the three-month rule.
- **The code is already redeemed or mistyped.** Check the characters: letters and digits are easy to confuse. Look at the account's order history: the money may already be in your balance.

If everything matches and the code still fails, contact YuPay support with the order number.

## Summary

Find your Microsoft account's country, get a card for that country and redeem it on the console or on the website. Change region rarely: once in three months and only with an empty balance.

The card you need is in the [Xbox section of the YuPay catalogue](/store/xbox). PlayStation works in a similar way; see our guide on [how to buy PS Store games from Uzbekistan](/blog/how-to-buy-ps-store-games-from-uzbekistan).
""",
        "faqs": [
            (
                "Will a US Xbox card work on a Turkish account?",
                "No. An Xbox card works only on an account of the same country, and Microsoft does not change its region.",
            ),
            (
                "How often can I change my Microsoft account's country?",
                "No more than once in three months. The balance does not carry over, so spend it first.",
            ),
            (
                "Where do I redeem an Xbox code?",
                'On the console, in Microsoft Store via "Redeem", or on the redeem page of Microsoft\'s website. Sign in to the same account you are topping up.',
            ),
            (
                "Can I pay for Game Pass from my balance?",
                "Yes, the Microsoft account balance pays for games, add-ons and Game Pass in Microsoft Store.",
            ),
            (
                "What does a PUR error mean when redeeming?",
                "Usually it is the wrong account, a card country that does not match the account country, or a code that was already redeemed. Check those three things, then contact YuPay support with the order number.",
            ),
        ],
    },
    "uz": {
        "slug": "xbox-hisobini-toldirish",
        "title": "Xbox hisobini Oʻzbekistondan qanday toʻldirish mumkin",
        "excerpt": "Xbox’ni Oʻzbekistondan toʻldirish: Microsoft akkauntining mamlakati, mintaqani almashtirishdagi uch oy qoidasi, qaysi sovgʻa kartasini olish va uni qanday faollashtirish.",
        "seo_title": "Xbox’ni Oʻzbekistondan toʻldirish — kartalar va mintaqa",
        "seo_description": "Xbox’ni Oʻzbekistondan toʻldirish: Microsoft akkauntingiz mamlakatining kartasi, mintaqani uch oyda bir marta almashtirish, kodni faollashtirish va PUR xatolari. Toʻlov soʻmda.",
        "body": """
Xbox Microsoft akkauntingizda koʻrsatilgan mamlakatning sovgʻa kartasi bilan toʻldiriladi. Akkaunt mamlakatini aniqlang, shu mamlakat kartasini oling va kodni konsolda yoki Microsoft saytida faollashtiring.

## Asosiysi

- Xbox kartasi faqat shu mamlakatdagi akkauntda ishlaydi. Microsoft karta mintaqasini oʻzgartirmaydi, hatto qoʻllab-quvvatlash orqali ham.
- Microsoft akkaunti mamlakatini almashtirish mumkin, lekin uch oyda bir martadan koʻp emas.
- Mamlakat almashtirilganda balansdagi pul koʻchmaydi. Avval uni sarflang.
- Konsoldagi doʻkon mintaqasi akkaunt mamlakati bilan bir xil boʻlsin.
- YuPay’da 21 mamlakatning Xbox kartalari bor, toʻlov soʻmda, Click, Payme yoki Uzum orqali. Yakuniy summa soʻmda toʻlovdan oldin koʻrinadi va aynan u yechiladi.

## Akkaunt mamlakati va konsol mintaqasi

Xbox’da koʻpincha adashtiriladigan ikki sozlama bor.

**Microsoft akkaunti mamlakati.** Balans valyutasi va qaysi kartalar mos kelishi shunga bogʻliq. Uni Microsoft akkaunti profilidagi «Shaxsiy maʼlumotlar» boʻlimida koʻrish mumkin.

**Konsol mintaqasi.** Bu konsolning oʻz sozlamasi: «Sozlamalar» → «Tizim» → «Til va joylashuv». U qaysi doʻkonni koʻrishingizni belgilaydi. Uni akkaunt mamlakati bilan bir xil qiling, aks holda doʻkon va balans har xil narsani koʻrsatadi.

Oʻzbekistondagi oʻyinchilar odatda boshqa mamlakat akkauntidan foydalanadi: AQSh, Turkiya, BAA, Polsha. Qaysi mamlakatni tanlash — oʻzingizga bogʻliq. Asosiysi, keyin akkauntni aynan shu mamlakat kartalari bilan toʻldirish.

## Xbox mintaqasini qanday almashtirish

Akkaunt notoʻgʻri mamlakatga ochilgan boʻlsa, uni almashtirish mumkin. Microsoft qoidalari:

1. Oxirgi uch oy ichida mamlakatni almashtirgan boʻlsangiz, uni yana oʻzgartirib boʻlmaydi.
2. Balansdagi pul yangi mintaqaga oʻtmaydi. Almashtirishdan oldin uni sarflang.
3. Baʼzi obunalar va xaridlar yangi mintaqada ishlamasligi mumkin. Buni oldindan tekshiring, ayniqsa faol obunangiz boʻlsa.
4. Akkaunt mamlakatini almashtirgach, «Til va joylashuv»da konsol mintaqasini ham oʻzgartiring.

Uch oy qoidasi sababli bitta chegirma uchun mamlakatni almashtirmang. Mintaqani bir marta tanlang va uni toʻldirib boring.

## Qaysi kartani olish kerak

Qoida bitta: akkaunt bilan bir xil mamlakat kartasi. AQSh kartasi turk akkauntida faollashmaydi va aksincha. Microsoft qoʻllab-quvvatlash xizmati kartani boshqa mintaqaga oʻtkaza olmaydi, shuning uchun notoʻgʻri xaridni keyin tuzatib boʻlmaydi.

[YuPay katalogida](/store/xbox) mamlakat almashtirgichli bitta Xbox sahifasi bor. Masalan:

- [Xbox AQSh](/store/xbox?region=us) — Amerika akkaunti uchun;
- [Xbox Turkiya](/store/xbox?region=tr) — turk akkaunti uchun;
- [Xbox BAA](/store/xbox?region=ae) — BAA akkaunti uchun;
- [Xbox Polsha](/store/xbox?region=pl) — polyak akkaunti uchun.

Shuningdek, Buyuk Britaniya, Germaniya, Ispaniya, Braziliya, Meksika, Kanada, Yaponiya va boshqalar bor. «EU» kartasini faqat akkaunt mamlakati yevrohududda boʻlsa oling.

## Xbox kartasini qanday faollashtirish

Toʻlovdan keyin kod buyurtma sahifasida koʻrinadi va pochtaga keladi. Uni ikki usulda faollashtirish mumkin.

**Konsolda:**

1. Kerakli profilga kiring.
2. Microsoft Store’ni oching.
3. Menyu tugmasini bosing va «Kodni faollashtirish» (Redeem) bandini tanlang.
4. 25 belgili kodni kiriting va tasdiqlang.

**Saytda:**

1. Microsoft saytidagi kodni faollashtirish sahifasini oching (microsoft.com/redeem).
2. Konsoldagi Microsoft akkauntining aynan oʻziga kiring.
3. Kodni kiriting va tasdiqlang.

Pul akkaunt balansiga tushadi. Kod bir martalik: faollashtirilgandan keyin qayta ishlamaydi.

## Balansdan oʻyinlar va Game Pass

Balans Microsoft Store’da sarflanadi: oʻyinlar, qoʻshimchalar, oʻyin ichidagi valyuta va Game Pass obunasiga. Xarid paytida akkaunt balansidan toʻlashni tanlang.

Kerakli summaga yetmasa, shu mamlakatning yana bir kartasini qoʻshing. Balanslar qoʻshiladi.

Grand Theft Auto VI 2026-yil 19-noyabrda chiqdi, jumladan Xbox Series X|S’da. Rockstar maʼlumotiga koʻra, Xbox kodlari mintaqaga bogʻlanmagan. Eng oddiy yoʻl — oʻyinni akkauntingiz Microsoft Store’ida balansdan sotib olish. Batafsil — [GTA 6’ni Oʻzbekistonda sotib olish](/blog/gta-6-ni-ozbekistonda-sotib-olish) qoʻllanmasida.

## Faollashtirishdagi xatolar

Kod qabul qilinmasa, Xbox xato koʻrsatadi, koʻpincha «PUR-…» koʻrinishidagi kod bilan. Oddiy qilib aytganda, sabab uchta.

- **Boshqa akkaunt.** Siz boshqa profilga yoki saytda boshqa Microsoft akkauntiga kirgansiz. Akkaunt pochtasini tekshiring.
- **Boshqa mintaqa.** Karta mamlakati akkaunt mamlakatiga mos emas. Bu koʻp uchraydigan sabab. Uni faqat akkaunt mamlakatini almashtirib, uch oy qoidasini hisobga olib tuzatish mumkin.
- **Kod allaqachon faollashtirilgan yoki xato kiritilgan.** Belgilarni solishtiring: harf va raqamlarni adashtirish oson. Akkauntning buyurtmalar tarixiga qarang: pul allaqachon balansda boʻlishi mumkin.

Hammasi mos kelsa-yu, kod baribir oʻtmasa, buyurtma raqami bilan YuPay qoʻllab-quvvatlash xizmatiga yozing.

## Xulosa

Microsoft akkauntingiz mamlakatini aniqlang, shu mamlakat kartasini oling va uni konsolda yoki saytda faollashtiring. Mintaqani kam almashtiring: uch oyda bir marta va faqat balans boʻsh boʻlganda.

Kerakli karta [YuPay katalogidagi Xbox boʻlimida](/store/xbox). PlayStation’da mantiq oʻxshash, uni [PS Store’dan oʻyin sotib olish](/blog/ps-store-dan-oyin-sotib-olish) qoʻllanmasida koʻrib chiqqanmiz.
""",
        "faqs": [
            (
                "AQSh Xbox kartasi turk akkauntiga mos keladimi?",
                "Yoʻq. Xbox kartasi faqat shu mamlakatdagi akkauntda ishlaydi va Microsoft uning mintaqasini oʻzgartirmaydi.",
            ),
            (
                "Microsoft akkaunti mamlakatini qanchalik tez-tez almashtirish mumkin?",
                "Uch oyda bir martadan koʻp emas. Almashtirishda balans koʻchmaydi, shuning uchun avval uni sarflang.",
            ),
            (
                "Xbox kodini qayerda faollashtirish mumkin?",
                "Konsolda — Microsoft Store’da «Kodni faollashtirish» orqali yoki Microsoft saytidagi faollashtirish sahifasida. Toʻldirayotgan akkauntning aynan oʻziga kiring.",
            ),
            (
                "Game Pass’ni balansdan toʻlash mumkinmi?",
                "Ha, Microsoft akkaunti balansi Microsoft Store’dagi oʻyinlar, qoʻshimchalar va Game Pass’ga sarflanadi.",
            ),
            (
                "Faollashtirishda PUR xatosi nimani bildiradi?",
                "Odatda bu boshqa akkaunt, karta mamlakati akkaunt mamlakatiga mos emasligi yoki kod allaqachon faollashtirilgani. Shu uch narsani tekshiring, soʻng buyurtma raqami bilan YuPay qoʻllab-quvvatlash xizmatiga yozing.",
            ),
        ],
    },
}
