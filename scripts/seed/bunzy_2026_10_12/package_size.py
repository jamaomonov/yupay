"""«Как выбрать пакет доната: маленький или большой» (Bunzy `kak-vybrat-paket-donata-…`, 2026-10-08).

Review of the Russian draft:

* The draft argued in the abstract («средний добавит процентов десять»,
  «условный пример» with 300 / 3300 units). Replaced with our real PUBG
  Mobile UC grid, priced from the live catalogue on 2026-10-12 at the
  system rate 11 895 сум/$ and labelled as a guide for October 2026. The
  real grid says something the draft could not: price per UC is **not**
  monotonic. 985 UC costs more per UC than 660 UC, 5650 more than 3850,
  11 950 more than 8100; 8100 UC is the cheapest per unit. 660 + 325 is
  cheaper than one 985, and 3850 + 1800 is cheaper than one 5650 — a
  concrete tip the draft lacked.
* Cut the Sensor Tower $82 bn statistic: unrelated to choosing a package.
* «Первый пакет с удвоенным бонусом … почти во всех играх» was stated as
  fact for every game and implied it applies to any top-up. Rewritten as an
  in-game offer the reader should check in the game's own shop; no promise
  about how it behaves on a top-up by ID.
* Cut the per-game paragraphs for MLBB and Free Fire that said nothing
  game-specific («сетка плавная», «сетка похожа»); kept the general rule.
* «без комиссии» → "итог в сумах виден до оплаты и списывается ровно он";
  dropped «без ручного подтверждения и ожидания оператора»; «Yupay» →
  «YuPay»; absolute yupay.uz links made relative; the PUBG cross-link now
  targets `uc-pubg-mobile` (has en/uz), not the ru-only `pubg-mobile-uc`.
* Slug `kak-vybrat-paket-donata-malenkiy-ili-bolshoy-chto-vygodnee` →
  `kak-vybrat-paket-donata`.

Brand `pubg-mobile` (retail, product `pubg-uc`, top-up by player ID).
Cover: a UC price list card on the right with 8100 UC highlighted, chips
«сум за 1 UC» and «8100 UC — дешевле всех».
"""

from __future__ import annotations

POST = {
    "post_id": "01a11b3c-8683-7f72-941b-1867e0f391fe",
    "brand_slug": "pubg-mobile",
    "cover": "https://cdn.yupay.uz/blog_image/2026/10/01a12f47-4f8d-7de2-915e-479f5126ac87.jpg",
    "publish_at": "2026-10-15 05:00:00+00",
    "ru": {
        "slug": "kak-vybrat-paket-donata",
        "title": "Как выбрать пакет доната: маленький или большой",
        "excerpt": "Какой пакет доната выгоднее: считаем цену за единицу валюты на реальной сетке UC PUBG Mobile и разбираем, когда крупный пакет не окупается.",
        "seo_title": "Какой пакет доната выгоднее: маленький или большой",
        "seo_description": "Как выбрать пакет доната: цена за единицу валюты на реальной сетке UC PUBG Mobile, когда крупный пакет не выгоден и когда две покупки дешевле одной.",
        "body": """
## Главное

- Сравнивайте пакеты по цене за единицу валюты, а не по сумме чека.
- Крупный пакет обычно дешевле за единицу, но не всегда: в сетке бывают «провалы».
- Иногда два маленьких пакета стоят меньше, чем один средний.
- Берите объём под то, что реально потратите. Валюта на балансе деньги не экономит.

Выгоднее не тот пакет, что дешевле на кассе, а тот, у которого ниже цена за одну единицу валюты. И только если вы эту валюту потратите. Ниже считаем на реальной сетке UC в PUBG Mobile.

## Как считать цену за единицу

Формула одна:

**цена за единицу = цена пакета в сумах / количество валюты**

Посчитайте её для двух-трёх пакетов, которые вы рассматриваете, и сравните. Чем меньше число, тем выгоднее пакет.

## Пример: UC в PUBG Mobile

Цены [UC на YuPay](/store/pubg-mobile), ориентир на октябрь 2026 года. Точная сумма зависит от курса и видна до оплаты.

| Пакет | Цена | Сум за 1 UC |
| --- | --- | --- |
| 60 UC | ≈ 11 900 сум | ≈ 198 |
| 325 UC | ≈ 60 400 сум | ≈ 186 |
| 660 UC | ≈ 120 400 сум | ≈ 182 |
| 985 UC | ≈ 183 100 сум | ≈ 186 |
| 1800 UC | ≈ 307 800 сум | ≈ 171 |
| 3850 UC | ≈ 594 000 сум | ≈ 154 |
| 5650 UC | ≈ 907 200 сум | ≈ 161 |
| 8100 UC | ≈ 1 161 900 сум | ≈ 143 |
| 11 950 UC | ≈ 1 782 500 сум | ≈ 149 |

Что видно из таблицы:

- Самый маленький пакет самый дорогой за единицу: почти 200 сум за UC.
- Самый выгодный пакет здесь не последний, а 8100 UC.
- 985 UC дороже за единицу, чем 660 UC. 5650 UC дороже, чем 3850 UC.

## Когда две покупки дешевле одной

Раз сетка неровная, иногда выгоднее собрать нужную сумму из двух пакетов.

- 660 + 325 UC = 985 UC за ≈ 180 800 сум. Один пакет 985 UC стоит ≈ 183 100 сум.
- 3850 + 1800 UC = 5650 UC за ≈ 901 900 сум. Один пакет 5650 UC стоит ≈ 907 200 сум.

Разница небольшая, но она бесплатная. Перед крупной покупкой проверьте, нельзя ли сложить нужный объём из соседних пакетов.

## Когда большой пакет не выгоден

Низкая цена за единицу превращается в экономию, только если вы тратите всю валюту. Крупный пакет теряет смысл, если:

- вам нужна сумма под одну конкретную покупку, а остаток просто зависнет;
- вы играете нерегулярно и не уверены, что вернётесь через месяц;
- вы копите «на всякий случай» без конкретной цели.

Если покупаете раз в несколько месяцев под конкретный предмет, берите пакет под нужную сумму. Если тратите валюту каждый сезон на пропуск и кейсы, крупный пакет с низкой ценой за единицу окупается.

## Бонус за первую покупку

Во многих играх в собственном магазине есть разовые бонусы за первую покупку пакета. Если такой бонус у вас ещё не использован, по цене за единицу он обычно выгоднее любого обычного пакета. Условия у каждой игры свои, поэтому проверьте их в магазине самой игры, прежде чем считать.

## Другие игры

Принцип тот же для алмазов Mobile Legends и Free Fire, кристаллов Genshin Impact и любой другой валюты. Соотношения между пакетами в каждой игре свои, поэтому универсального лучшего номинала нет: считайте внутри своей игры. Про кристаллы Genshin подробно в материале [как купить кристаллы Genesis выгодно](/blog/genshin-impact-genesis), про UC в гайде [как получить UC в PUBG Mobile](/blog/uc-pubg-mobile).

## Оплата в сумах

На YuPay вы платите в сумах через Click, Payme или Uzum. Итог в сумах виден до оплаты и списывается ровно он, поэтому посчитанная цена за единицу не поплывёт на кассе. Валюта зачисляется на аккаунт по ID игрока, пароль не нужен. Откуда берутся переплаты в других местах, разобрано в статье [о скрытых комиссиях при донате](/blog/skrytye-komissii-pri-donate).

Начните с простого: откройте страницу игры, выпишите цены двух-трёх пакетов, посчитайте цену за единицу и возьмите тот, что выгоднее под вашу реальную частоту игры.
""",
        "faqs": [
            (
                "Маленький или большой пакет доната брать выгоднее?",
                "Обычно крупный пакет дешевле за единицу валюты, но не всегда: в сетке UC PUBG Mobile, например, 985 UC дороже за единицу, чем 660 UC. И выгода есть, только если вы потратите всю валюту.",
            ),
            (
                "Как посчитать, какой пакет доната выгоднее?",
                "Разделите цену пакета в сумах на количество валюты. Получится цена за единицу. Сравните её у двух-трёх пакетов и выберите наименьшую.",
            ),
            (
                "Может ли быть дешевле купить два пакета вместо одного?",
                "Да. На YuPay в октябре 2026 года 660 + 325 UC стоили меньше, чем один пакет 985 UC, а 3850 + 1800 UC меньше, чем 5650 UC. Перед крупной покупкой стоит сравнить.",
            ),
            (
                "Сколько я заплачу при оплате в сумах?",
                "Ровно ту сумму, которую видите до оплаты. На YuPay оплата идёт через Click, Payme или Uzum, итог в сумах показан заранее и списывается ровно он.",
            ),
        ],
    },
    "en": {
        "slug": "which-top-up-package-is-better",
        "title": "Small or large top-up package: which one pays off",
        "excerpt": "Which top-up package is the better deal: we work out the price per unit on the real PUBG Mobile UC price list and show when a big package does not pay off.",
        "seo_title": "Small or large top-up package: which one pays off",
        "seo_description": "How to pick a top-up package: price per unit on the real PUBG Mobile UC list, when a big package is not worth it, and when two purchases cost less than one.",
        "body": """
## Key takeaways

- Compare packages by price per unit of currency, not by the total.
- A bigger package is usually cheaper per unit, but not always: price lists have dips.
- Sometimes two small packages cost less than one mid-sized one.
- Buy the amount you will actually spend. Currency sitting on your balance saves nothing.

The better package is not the one that is cheaper at checkout but the one with the lowest price per unit of currency — and only if you spend it. Below we do the maths on the real PUBG Mobile UC price list.

## How to work out the price per unit

One formula:

**price per unit = package price in soʻm / amount of currency**

Work it out for the two or three packages you are considering and compare. The lower the number, the better the deal.

## Example: PUBG Mobile UC

[UC prices on YuPay](/store/pubg-mobile), a guide as of October 2026. The exact amount depends on the exchange rate and is shown before you pay.

| Package | Price | Soʻm per UC |
| --- | --- | --- |
| 60 UC | ≈ 11,900 soʻm | ≈ 198 |
| 325 UC | ≈ 60,400 soʻm | ≈ 186 |
| 660 UC | ≈ 120,400 soʻm | ≈ 182 |
| 985 UC | ≈ 183,100 soʻm | ≈ 186 |
| 1800 UC | ≈ 307,800 soʻm | ≈ 171 |
| 3850 UC | ≈ 594,000 soʻm | ≈ 154 |
| 5650 UC | ≈ 907,200 soʻm | ≈ 161 |
| 8100 UC | ≈ 1,161,900 soʻm | ≈ 143 |
| 11,950 UC | ≈ 1,782,500 soʻm | ≈ 149 |

What the table shows:

- The smallest package is the most expensive per unit: almost 200 soʻm per UC.
- The best deal here is not the biggest package but 8100 UC.
- 985 UC costs more per unit than 660 UC. 5650 UC costs more than 3850 UC.

## When two purchases cost less than one

Because the list is uneven, it sometimes pays to build the amount from two packages.

- 660 + 325 UC = 985 UC for ≈ 180,800 soʻm. A single 985 UC package is ≈ 183,100 soʻm.
- 3850 + 1800 UC = 5650 UC for ≈ 901,900 soʻm. A single 5650 UC package is ≈ 907,200 soʻm.

The difference is small, but it is free. Before a big purchase, check whether neighbouring packages add up to the same amount for less.

## When a big package does not pay off

A low price per unit becomes a saving only if you spend all of it. A big package makes no sense if:

- you need an amount for one specific item and the rest will just sit there;
- you play irregularly and are not sure you will be back next month;
- you are stocking up "just in case" with no goal in mind.

If you buy once every few months for a specific item, take the package that covers it. If you spend currency every season on the pass and crates, a big package with a low price per unit pays off.

## First-purchase bonus

Many games run one-off bonuses for the first purchase of a package in their own shop. If you have not used one yet, it is usually better per unit than any regular package. The terms differ from game to game, so check them in the game's shop before you do the maths.

## Other games

The same rule works for Mobile Legends and Free Fire diamonds, Genshin Impact crystals and any other currency. The ratios between packages differ in every game, so there is no universal best size: do the maths inside your game. More on Genshin in [how to buy Genesis Crystals for less](/blog/genshin-impact-genesis-crystals), and on UC in [how to get UC in PUBG Mobile](/blog/how-to-get-uc-pubg-mobile).

## Paying in soʻm

On YuPay you pay in soʻm with Click, Payme or Uzum. The total in soʻm is shown before you pay and exactly that is charged, so your price per unit does not drift at checkout. The currency is credited by player ID, no password needed. Where overpayment hides elsewhere is covered in [hidden fees in game top-ups](/blog/hidden-fees-game-top-ups).

Start simple: open the game's page, note the prices of two or three packages, work out the price per unit and take the one that fits how often you really play.
""",
        "faqs": [
            (
                "Is a small or a large top-up package the better deal?",
                "A large package is usually cheaper per unit, but not always: on the PUBG Mobile UC list, for example, 985 UC costs more per unit than 660 UC. And it only pays off if you spend all the currency.",
            ),
            (
                "How do I work out which package is the better deal?",
                "Divide the package price in soʻm by the amount of currency. That is the price per unit. Compare it across two or three packages and pick the lowest.",
            ),
            (
                "Can two packages be cheaper than one?",
                "Yes. On YuPay in October 2026, 660 + 325 UC cost less than a single 985 UC package, and 3850 + 1800 UC less than 5650 UC. It is worth comparing before a big purchase.",
            ),
            (
                "How much will I pay in soʻm?",
                "Exactly the amount you see before paying. On YuPay you pay with Click, Payme or Uzum; the total in soʻm is shown up front and exactly that is charged.",
            ),
        ],
    },
    "uz": {
        "slug": "qaysi-donat-paketi-foydali",
        "title": "Donat paketini tanlash: kichigi foydalimi yoki kattasi",
        "excerpt": "Qaysi donat paketi foydaliroq: PUBG Mobile UC ning haqiqiy narxlar roʻyxatida bir birlik narxini hisoblaymiz va katta paket qachon oʻzini oqlamasligini koʻrsatamiz.",
        "seo_title": "Qaysi donat paketi foydali: kichigi yoki kattasi",
        "seo_description": "Donat paketini qanday tanlash kerak: PUBG Mobile UC roʻyxatida bir birlik narxi, katta paket qachon foydasiz va qachon ikki xarid bittadan arzon.",
        "body": """
## Asosiysi

- Paketlarni chek summasiga qarab emas, valyutaning bir birligi narxiga qarab solishtiring.
- Katta paket odatda bir birlikka arzonroq, lekin har doim emas: roʻyxatda «chuqurlar» boʻladi.
- Baʼzan ikkita kichik paket bitta oʻrtachadan arzonroq turadi.
- Haqiqatan sarflaydigan miqdorni oling. Balansda turgan valyuta pul tejamaydi.

Kassada arzonroq paket emas, valyutaning bir birligi narxi pastroq boʻlgan paket foydali. Va faqat bu valyutani sarflasangiz. Quyida PUBG Mobile dagi UC ning haqiqiy roʻyxatida hisoblaymiz.

## Bir birlik narxini qanday hisoblash

Formula bitta:

**bir birlik narxi = paket narxi soʻmda / valyuta miqdori**

Koʻrib chiqayotgan ikki-uchta paket uchun hisoblang va solishtiring. Son qancha kichik boʻlsa, paket shuncha foydali.

## Misol: PUBG Mobile dagi UC

[YuPay dagi UC narxlari](/store/pubg-mobile), 2026-yil oktabr holatiga taxminiy. Aniq summa kursga bogʻliq va toʻlovdan oldin koʻrsatiladi.

| Paket | Narx | 1 UC uchun soʻm |
| --- | --- | --- |
| 60 UC | ≈ 11 900 soʻm | ≈ 198 |
| 325 UC | ≈ 60 400 soʻm | ≈ 186 |
| 660 UC | ≈ 120 400 soʻm | ≈ 182 |
| 985 UC | ≈ 183 100 soʻm | ≈ 186 |
| 1800 UC | ≈ 307 800 soʻm | ≈ 171 |
| 3850 UC | ≈ 594 000 soʻm | ≈ 154 |
| 5650 UC | ≈ 907 200 soʻm | ≈ 161 |
| 8100 UC | ≈ 1 161 900 soʻm | ≈ 143 |
| 11 950 UC | ≈ 1 782 500 soʻm | ≈ 149 |

Jadvaldan nima koʻrinadi:

- Eng kichik paket bir birlikka eng qimmat: bir UC uchun deyarli 200 soʻm.
- Bu yerda eng foydalisi oxirgi paket emas, 8100 UC.
- 985 UC bir birlikka 660 UC dan qimmat. 5650 UC esa 3850 UC dan qimmat.

## Ikki xarid bittadan qachon arzon

Roʻyxat notekis boʻlgani uchun baʼzan kerakli miqdorni ikkita paketdan yigʻish foydaliroq.

- 660 + 325 UC = 985 UC, taxminan 180 800 soʻm. Bitta 985 UC paketi taxminan 183 100 soʻm.
- 3850 + 1800 UC = 5650 UC, taxminan 901 900 soʻm. Bitta 5650 UC paketi taxminan 907 200 soʻm.

Farq katta emas, lekin u tekin. Katta xariddan oldin kerakli miqdorni qoʻshni paketlardan yigʻib boʻlmasligini tekshiring.

## Katta paket qachon foydasiz

Bir birlikning past narxi faqat butun valyutani sarflasangiz tejamga aylanadi. Katta paket maʼnosiz, agar:

- sizga bitta aniq xarid uchun summa kerak boʻlsa va qoldiq shunchaki turib qolsa;
- notekis oʻynasangiz va bir oydan keyin qaytishingizga ishonchingiz boʻlmasa;
- aniq maqsadsiz «har ehtimolga qarshi» yigʻsangiz.

Bir necha oyda bir marta aniq narsa uchun xarid qilsangiz, kerakli summaga mos paketni oling. Har mavsum valyutani propusk va keyslarga sarflasangiz, bir birligi arzon katta paket oʻzini oqlaydi.

## Birinchi xarid bonusi

Koʻp oʻyinlarning oʻz doʻkonida paketni birinchi marta xarid qilganda bir martalik bonuslar bor. Agar bunday bonusdan hali foydalanmagan boʻlsangiz, bir birlik narxi boʻyicha u odatda har qanday oddiy paketdan foydaliroq. Shartlar har bir oʻyinda oʻziga xos, shuning uchun hisoblashdan oldin ularni oʻyin doʻkonida tekshiring.

## Boshqa oʻyinlar

Xuddi shu qoida Mobile Legends va Free Fire olmoslari, Genshin Impact kristallari va boshqa har qanday valyuta uchun ishlaydi. Paketlar orasidagi nisbat har bir oʻyinda oʻzgacha, shuning uchun universal eng yaxshi nominal yoʻq: oʻz oʻyiningiz ichida hisoblang. Genshin haqida batafsil [Genesis kristallarini foydali sotib olish](/blog/genshin-impact-genesis-kristallari) maqolasida, UC haqida esa [PUBG Mobile da UC olish](/blog/pubg-mobile-uc-olish) qoʻllanmasida.

## Soʻmda toʻlov

YuPay da Click, Payme yoki Uzum orqali soʻmda toʻlaysiz. Soʻmdagi yakuniy summa toʻlovdan oldin koʻrinadi va aynan u yechiladi, shuning uchun hisoblagan bir birlik narxingiz kassada oʻzgarmaydi. Valyuta oʻyinchi ID si orqali tushadi, parol kerak emas. Boshqa joylarda ortiqcha toʻlov qayerdan kelishi [donatdagi yashirin komissiyalar](/blog/donatdagi-yashirin-komissiyalar) maqolasida tahlil qilingan.

Oddiydan boshlang: oʻyin sahifasini oching, ikki-uchta paket narxini yozib oling, bir birlik narxini hisoblang va haqiqiy oʻyin chastotangizga mosini oling.
""",
        "faqs": [
            (
                "Qaysi donat paketi foydali: kichigimi yoki kattasi?",
                "Odatda katta paket bir birlikka arzonroq, lekin har doim emas: masalan, PUBG Mobile UC roʻyxatida 985 UC bir birlikka 660 UC dan qimmat. Foyda esa faqat butun valyutani sarflasangiz boʻladi.",
            ),
            (
                "Qaysi paket foydaliroq ekanini qanday hisoblash mumkin?",
                "Paket narxini soʻmda valyuta miqdoriga boʻling. Bu bir birlik narxi. Uni ikki-uchta paketda solishtiring va eng kichigini tanlang.",
            ),
            (
                "Ikki paket bittadan arzon boʻlishi mumkinmi?",
                "Ha. 2026-yil oktabrda YuPay da 660 + 325 UC bitta 985 UC paketidan, 3850 + 1800 UC esa 5650 UC dan arzon edi. Katta xariddan oldin solishtirishga arziydi.",
            ),
            (
                "Soʻmda qancha toʻlayman?",
                "Toʻlovdan oldin koʻrgan summani aynan. YuPay da Click, Payme yoki Uzum orqali toʻlaysiz, soʻmdagi yakuniy summa oldindan koʻrsatiladi va aynan u yechiladi.",
            ),
        ],
    },
}
