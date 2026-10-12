"""«Как быстро пополнить игру» (Bunzy `post-8`, 2026-10-10).

Review of the Russian draft:

* About half the text was water and mechanism: «платёжная система отправляет
  подтверждение, сервис обращается к игровому API», «алгоритм не уходит в
  отпуск», a second pass over the same ideas in every section. Cut to what a
  buyer does: check the ID, pay, watch the status, what to do if it hangs.
* Cut the Baymard cart-abandonment figure (70.22 %, about e-commerce at
  large, not game top-ups) and the unsourced «десятки миллиардов долларов».
* «обычно за секунды» / «работает без пауз» — we cannot promise seconds for
  every game. Now «обычно несколько минут», and only that.
* Statuses now use the words the order page actually shows: «Выполняется»,
  «Зачислено», «Ошибка» (en: Processing / Credited / Failed; uz: Bajarilmoqda /
  Hisobga olindi / Xatolik). The draft invented «В обработке», «отклонён» and
  a «личный кабинет» — buyers can be guests, so it is «Мои заказы» and the
  order page.
* Cut «деньги вернутся автоматически по правилам платёжной системы» — a
  refund promise about someone else's rules. The advice that holds stays:
  do not pay twice, write to support with the order number.
* The draft linked two posts of this same batch by their draft slugs
  (`arena-breakout`, `kak-vybrat-paket-...`) as absolute URLs; both may be
  renamed in review. Replaced with published posts: the safe-buying guide
  and the hidden-fees one. «Yupay» → «YuPay»; links relative.
* Slug `post-8` → `kak-bystro-popolnit-igru`.

Brand `mobile-legends`: the draft's own example (with Standoff 2, whose
supplier is currently out), and a game with the «Проверить» nickname check
the post recommends. Cover: a stopwatch over an order card reading
«Зачислено» with a green check.
"""

from __future__ import annotations

POST = {
    "post_id": "01a125ca-b0b1-7472-bdc6-e2a2b6086cf1",
    "brand_slug": "mobile-legends",
    "cover": "https://cdn.yupay.uz/blog_image/2026/10/01a12f47-52cf-7160-9b58-283637b3c86a.jpg",
    "publish_at": "2026-10-17 05:00:00+00",
    "ru": {
        "slug": "kak-bystro-popolnit-igru",
        "title": "Как быстро пополнить игру: от оплаты до зачисления",
        "excerpt": "Что ускоряет пополнение игры, где смотреть статус заказа и что делать, если валюта не пришла сразу.",
        "seo_title": "Как быстро пополнить игру: оплата и зачисление в сумах",
        "seo_description": "Как быстро пополнить игру в Узбекистане: проверка ID до оплаты, оплата в сумах через Click, Payme или Uzum, статус заказа и что делать, если валюта задержалась.",
        "body": """
## Главное

- Быстрое пополнение начинается с правильного ID: ошибка в номере аккаунта тормозит заказ сильнее всего остального.
- На YuPay заказ обрабатывается автоматически и обычно зачисляется за несколько минут, днём и ночью.
- Статус виден на странице заказа: «Выполняется», «Зачислено» или «Ошибка».
- Если валюта задержалась, не платите второй раз. Напишите в поддержку с номером заказа.

Акция в игре может идти несколько часов, сезонный пропуск нужен до начала матча. Поэтому важно, сколько проходит от оплаты до валюты на счёте. Ниже о том, что от вас зависит, где следить за заказом и что делать, если он задержался.

## Что ускоряет пополнение

Больше всего времени теряется не на оплате, а на ошибках. Три вещи, которые стоит сделать до нажатия «Оплатить»:

- **Проверьте ID игрока.** Для многих игр, например [Mobile Legends](/store/mobile-legends), на странице есть кнопка «Проверить»: она показывает ник аккаунта. Видите свой ник, значит, валюта уйдёт вам.
- **Укажите сервер или регион, если игра их просит.** В Mobile Legends это второй номер рядом с ID.
- **Выберите способ оплаты, который у вас под рукой.** Click, Payme или Uzum: оплата в сумах проходит в приложении банка за пару нажатий.

Итог в сумах виден до оплаты и списывается ровно он. Не нужно пересчитывать курс и ждать конвертации, как с зарубежной картой.

## Сколько ждать зачисления

После оплаты заказ уходит в работу сам, оператор для этого не нужен. Обычно валюта приходит за несколько минут. Иногда дольше: игра обновляет серверы или банк дольше подтверждает платёж.

Пополнить заранее всё равно разумно. Если акция заканчивается вечером, оформите заказ днём, а не за пять минут до конца.

## Как отследить статус заказа

После оплаты открывается страница заказа. Её же можно найти в разделе «Мои заказы». Статусы такие:

- **Выполняется** — оплата получена, валюта зачисляется.
- **Зачислено** — валюта на вашем аккаунте. Зайдите в игру и проверьте.
- **Ошибка** — заказ не выполнен. Поддержка разберётся по номеру заказа.

Проверяйте статус сразу после оплаты, а не через час. Ошибку в ID проще исправить, пока заказ свежий.

## Если валюта не пришла

Не оплачивайте заказ повторно. Второй платёж не ускорит первый, а разбираться потом придётся с двумя.

Действуйте по порядку:

- Откройте страницу заказа и посмотрите статус.
- Если статус «Выполняется», подождите 10–15 минут.
- Если статус «Зачислено», перезайдите в игру: иногда баланс обновляется не сразу.
- Если статус «Ошибка» или заказ висит дольше 15 минут, напишите в поддержку и приложите номер заказа.

С номером заказа поддержка сразу видит всю историю и не задаёт лишних вопросов.

## Как не попасть на медленный сервис

Скорость важна, но не за счёт безопасности. Пополнение по ID не требует пароля от аккаунта. Если продавец просит логин и пароль, это повод уйти. Подробнее в разборе о том, [как безопасно покупать игровую валюту](/blog/bezopasnaya-pokupka-igrovoy-valyuty).

Второй признак хорошего сервиса — цена без сюрпризов на последнем шаге. О том, где прячутся доплаты, мы писали в статье [про скрытые комиссии при донате](/blog/skrytye-komissii-pri-donate).

Выберите игру в [каталоге](/store), проверьте ID и оформите пополнение заранее, до старта акции.
""",
        "faqs": [
            (
                "Сколько времени занимает пополнение игры на YuPay?",
                "Обычно несколько минут после оплаты. Заказ обрабатывается автоматически в любое время суток. Иногда зачисление занимает дольше, например, если игра обновляет серверы.",
            ),
            (
                "Где посмотреть статус заказа?",
                "На странице заказа, которая открывается после оплаты, или в разделе «Мои заказы». Там виден статус: «Выполняется», «Зачислено» или «Ошибка».",
            ),
            (
                "Что делать, если деньги списались, а валюта не пришла?",
                "Не оплачивайте повторно. Проверьте статус заказа и ID игрока. Если через 15 минут валюты нет или стоит «Ошибка», напишите в поддержку и приложите номер заказа.",
            ),
        ],
    },
    "en": {
        "slug": "fast-game-top-up",
        "title": "How to top up a game fast: from payment to credit",
        "excerpt": "What makes a game top-up faster, where to see your order status, and what to do if the currency does not arrive right away.",
        "seo_title": "How to top up a game fast in Uzbekistan, paid in soʻm",
        "seo_description": "Top up a game fast in Uzbekistan: check your player ID before paying, pay in soʻm with Click, Payme or Uzum, follow the order status, and what to do if it is delayed.",
        "body": """
## Key takeaways

- A fast top-up starts with the right ID: a typo in the account number slows an order more than anything else.
- On YuPay orders are processed automatically and usually credited within a few minutes, day or night.
- The order page shows the status: Processing, Credited or Failed.
- If the currency is late, do not pay a second time. Contact support with your order number.

An in-game offer may last a few hours; a season pass is needed before the next match. So the time between paying and seeing the currency matters. Below: what depends on you, where to follow the order, and what to do if it is delayed.

## What makes a top-up faster

Most time is lost to mistakes, not to payment. Three things to do before you press Pay:

- **Check the player ID.** For many games, such as [Mobile Legends](/store/mobile-legends), the page has a Check button that shows the account nickname. If you see your nickname, the currency goes to you.
- **Enter the server or region if the game asks for it.** In Mobile Legends it is the second number next to the ID.
- **Pick the payment method you have at hand.** Click, Payme or Uzum: paying in soʻm takes a couple of taps in your bank app.

The total in soʻm is shown before you pay, and exactly that is charged. No exchange rate to work out and no conversion to wait for, as there would be with a foreign card.

## How long the credit takes

After payment the order goes into work on its own; no operator is needed. The currency usually arrives within a few minutes. Sometimes it takes longer: the game is updating its servers, or the bank takes longer to confirm the payment.

Topping up ahead of time is still wise. If an offer ends in the evening, place the order during the day, not five minutes before the end.

## How to follow the order status

After payment you land on the order page. You can also find it under My orders. The statuses are:

- **Processing** — payment received, the currency is being credited.
- **Credited** — the currency is on your account. Open the game and check.
- **Failed** — the order was not completed. Support will sort it out by the order number.

Check the status right after paying, not an hour later. A wrong ID is easier to fix while the order is fresh.

## If the currency did not arrive

Do not pay for the order again. A second payment does not speed up the first, and later there are two to untangle.

Go step by step:

- Open the order page and look at the status.
- If it says Processing, wait 10–15 minutes.
- If it says Credited, restart the game: sometimes the balance updates with a delay.
- If it says Failed, or the order has been stuck for more than 15 minutes, contact support and include the order number.

With the order number support sees the whole history at once and asks no extra questions.

## How to avoid a slow or unsafe seller

Speed matters, but not at the cost of safety. A top-up by ID never needs your account password. If a seller asks for a login and password, walk away. More in our guide on [how to buy in-game currency safely](/blog/buy-in-game-currency-safely).

The second sign of a good service is a price without surprises at the last step. We covered where extra charges hide in the post on [hidden fees in game top-ups](/blog/hidden-fees-game-top-ups).

Pick a game in the [catalogue](/store), check your ID and top up ahead of time, before the offer starts.
""",
        "faqs": [
            (
                "How long does a game top-up take on YuPay?",
                "Usually a few minutes after payment. Orders are processed automatically at any time of day. Sometimes the credit takes longer, for example while the game is updating its servers.",
            ),
            (
                "Where can I see the order status?",
                "On the order page that opens after payment, or under My orders. The status reads Processing, Credited or Failed.",
            ),
            (
                "The money was charged but the currency did not arrive. What should I do?",
                "Do not pay again. Check the order status and the player ID. If there is still no currency after 15 minutes, or the status is Failed, contact support and include the order number.",
            ),
        ],
    },
    "uz": {
        "slug": "oyinni-tez-toldirish",
        "title": "Oʻyinni tez toʻldirish: toʻlovdan hisobga tushishgacha",
        "excerpt": "Oʻyinni toʻldirishni nima tezlashtiradi, buyurtma holatini qayerda koʻrish mumkin va valyuta darhol tushmasa nima qilish kerak.",
        "seo_title": "Oʻyinni tez toʻldirish: soʻmda toʻlov va hisobga tushish",
        "seo_description": "Oʻzbekistonda oʻyinni tez toʻldirish: toʻlovdan oldin ID tekshiruvi, Click, Payme yoki Uzum orqali soʻmda toʻlov, buyurtma holati va valyuta kechiksa nima qilish.",
        "body": """
## Asosiysi

- Tez toʻldirish toʻgʻri ID dan boshlanadi: akkaunt raqamidagi xato buyurtmani hammadan koʻp sekinlashtiradi.
- YuPay da buyurtma avtomatik bajariladi va odatda bir necha daqiqada, kechayu kunduz hisobga tushadi.
- Holat buyurtma sahifasida koʻrinadi: «Bajarilmoqda», «Hisobga olindi» yoki «Xatolik».
- Valyuta kechiksa, qayta toʻlamang. Buyurtma raqami bilan qoʻllab-quvvatlash xizmatiga yozing.

Oʻyindagi aksiya bir necha soat davom etishi mumkin, mavsumiy pass esa keyingi matchdan oldin kerak. Shuning uchun toʻlovdan valyuta hisobga tushguncha qancha vaqt oʻtishi muhim. Quyida — sizga nima bogʻliq, buyurtmani qayerda kuzatish va u kechiksa nima qilish haqida.

## Toʻldirishni nima tezlashtiradi

Vaqtning koʻp qismi toʻlovga emas, xatolarga ketadi. «Toʻlash» tugmasini bosishdan oldin uch narsani qiling:

- **Oʻyinchi ID sini tekshiring.** Koʻp oʻyinlarda, masalan, [Mobile Legends](/store/mobile-legends) sahifasida «Tekshirish» tugmasi bor: u akkaunt nikini koʻrsatadi. Oʻz nikingizni koʻrsangiz, valyuta sizga tushadi.
- **Oʻyin soʻrasa, server yoki regionni kiriting.** Mobile Legends da bu ID yonidagi ikkinchi raqam.
- **Qoʻlingizdagi toʻlov usulini tanlang.** Click, Payme yoki Uzum: soʻmda toʻlov bank ilovasida bir necha bosishda oʻtadi.

Soʻmdagi yakuniy summa toʻlovdan oldin koʻrinadi va aynan shu summa yechiladi. Xorijiy kartadagidek kursni hisoblash va konvertatsiyani kutish shart emas.

## Hisobga tushishini qancha kutish kerak

Toʻlovdan keyin buyurtma oʻzi ishga tushadi, operator kerak emas. Odatda valyuta bir necha daqiqada keladi. Baʼzan uzoqroq: oʻyin serverlarini yangilayotgan boʻladi yoki bank toʻlovni sekinroq tasdiqlaydi.

Baribir oldindan toʻldirgan maʼqul. Aksiya kechqurun tugasa, buyurtmani kunduzi bering, tugashiga besh daqiqa qolganda emas.

## Buyurtma holatini qanday kuzatish mumkin

Toʻlovdan keyin buyurtma sahifasi ochiladi. Uni «Buyurtmalarim» boʻlimida ham topasiz. Holatlar:

- **Bajarilmoqda** — toʻlov qabul qilindi, valyuta hisobga oʻtkazilmoqda.
- **Hisobga olindi** — valyuta akkauntingizda. Oʻyinga kirib tekshiring.
- **Xatolik** — buyurtma bajarilmadi. Qoʻllab-quvvatlash xizmati buyurtma raqami boʻyicha hal qiladi.

Holatni bir soatdan keyin emas, toʻlovdan soʻng darhol tekshiring. ID dagi xatoni buyurtma yangi paytida tuzatish osonroq.

## Valyuta tushmasa

Buyurtma uchun qayta toʻlamang. Ikkinchi toʻlov birinchisini tezlashtirmaydi, keyin esa ikkalasini ajratishga toʻgʻri keladi.

Tartib bilan harakat qiling:

- Buyurtma sahifasini oching va holatni koʻring.
- Holat «Bajarilmoqda» boʻlsa, 10–15 daqiqa kuting.
- Holat «Hisobga olindi» boʻlsa, oʻyinga qayta kiring: baʼzan balans kechroq yangilanadi.
- Holat «Xatolik» boʻlsa yoki buyurtma 15 daqiqadan koʻp osilib qolsa, qoʻllab-quvvatlash xizmatiga buyurtma raqami bilan yozing.

Buyurtma raqami boʻlsa, xizmat butun tarixni darhol koʻradi va ortiqcha savol bermaydi.

## Sekin yoki xavfli sotuvchidan qanday qochish mumkin

Tezlik muhim, lekin xavfsizlik hisobiga emas. ID orqali toʻldirish uchun akkaunt paroli kerak emas. Sotuvchi login va parol soʻrasa, undan voz keching. Batafsil — [oʻyin valyutasini xavfsiz sotib olish](/blog/oyin-valyutasini-xavfsiz-sotib-olish) haqidagi maqolada.

Yaxshi xizmatning ikkinchi belgisi — oxirgi qadamda kutilmagan qoʻshimchalarsiz narx. Qoʻshimcha toʻlovlar qayerda yashirinishini [donatdagi yashirin komissiyalar](/blog/donatdagi-yashirin-komissiyalar) haqidagi maqolada yozganmiz.

[Katalogdan](/store) oʻyinni tanlang, ID ni tekshiring va aksiya boshlanishidan oldin toʻldiring.
""",
        "faqs": [
            (
                "YuPay da oʻyinni toʻldirish qancha vaqt oladi?",
                "Odatda toʻlovdan keyin bir necha daqiqa. Buyurtma kunning istalgan vaqtida avtomatik bajariladi. Baʼzan uzoqroq choʻzilishi mumkin, masalan, oʻyin serverlarini yangilayotganda.",
            ),
            (
                "Buyurtma holatini qayerda koʻrish mumkin?",
                "Toʻlovdan keyin ochiladigan buyurtma sahifasida yoki «Buyurtmalarim» boʻlimida. U yerda holat koʻrinadi: «Bajarilmoqda», «Hisobga olindi» yoki «Xatolik».",
            ),
            (
                "Pul yechildi, lekin valyuta tushmadi. Nima qilish kerak?",
                "Qayta toʻlamang. Buyurtma holati va oʻyinchi ID sini tekshiring. 15 daqiqadan keyin ham valyuta boʻlmasa yoki «Xatolik» turgan boʻlsa, qoʻllab-quvvatlash xizmatiga buyurtma raqami bilan yozing.",
            ),
        ],
    },
}
