"""«Как безопасно покупать внутриигровую валюту» (Bunzy `post-6`, 2026-10-02).

Review of the Russian draft:

* Kept one Kaspersky figure (20 million gaming-platform attacks, Jan–Oct
  2025) with its link; cut the second paragraph of phishing counts — one
  sourced number makes the point, three read as padding.
* Trimmed the PCI DSS paragraph to the sentence a buyer can act on.
* Cross-links: «сервис пополнения игр» now targets the published overview
  post rather than the hidden-fees draft, and «почему выгоднее покупать
  донат локально» targets that draft's new slug.
* Slug `post-6` → `bezopasnaya-pokupka-igrovoy-valyuty`. «Yupay» → «YuPay».
  The YuPay paragraph names the real methods and the «Проверить» button.

Brand `pubg-mobile`, as the other general posts use. Cover: an ID field and
an empty password field. Status stays `draft`.
"""

from __future__ import annotations

POST = {
    "post_id": "01a0fa75-99e2-71b0-aac1-3e7ceaafeb7d",
    "brand_slug": "pubg-mobile",
    "cover": "https://cdn.yupay.uz/blog_image/2026/10/01a10bf9-87e9-7c71-a7dd-5e81f40c742d.jpg",
    "ru": {
        "slug": "bezopasnaya-pokupka-igrovoy-valyuty",
        "title": "Как безопасно покупать внутриигровую валюту",
        "excerpt": "Безопасная покупка игровой валюты: как распознать мошенников, проверить сервис, защитить данные карты и почему пополнение по ID безопаснее передачи пароля.",
        "seo_title": "Как безопасно покупать внутриигровую валюту",
        "seo_description": "Безопасная покупка игровой валюты: признаки мошенников, проверка сервиса за минуту, защита данных карты и почему пополнение по ID безопаснее передачи пароля.",
        "body": """
## Главное

- Безопасная покупка игровой валюты начинается с проверки продавца: домен, контакты, отзывы и способ оплаты важнее низкой цены.
- Автоматическая доставка закрывает главный риск ручных схем: продавец не исчезает с деньгами и не просит доступ к вашему аккаунту.
- Никогда не передавайте логин и пароль от игрового аккаунта продавцу валюты: легальное пополнение идёт по игровому ID.
- При оплате картой проверяйте HTTPS, подтверждение по 3-D Secure и отсутствие запроса лишних данных, например PIN-кода.

Безопасная покупка игровой валюты держится на трёх простых проверках: вы покупаете у сервиса с понятными контактами, платите через защищённую платёжную страницу и получаете донат по игровому ID, а не отдаёте продавцу логин с паролем. Если хотя бы один из этих пунктов нарушен, сделку лучше отменить, даже когда цена выглядит очень привлекательной.

## Почему к покупке доната стоит относиться серьёзно

Игровые платформы стали одной из любимых целей мошенников. По данным Kaspersky, за январь-октябрь 2025 года системы компании зафиксировали более 20 миллионов атак, связанных с игровыми платформами ([Kaspersky](https://www.kaspersky.com/about/press-releases/kaspersky-reports-64-million-shopping-phishing-attempts-and-over-20-million-gaming-attacks-detected-in-2025)). Для геймера это значит простую вещь: страница, где вы вводите данные карты ради быстрого доната, вполне может оказаться поддельной.

## Признаки мошеннических сайтов и продавцов

Большинство схем вокруг продажи внутриигровой валюты повторяют один и тот же набор приёмов. Запомнив их, вы отсеете почти всех недобросовестных продавцов ещё до оплаты.

- Цена заметно ниже рынка. Если UC для PUBG Mobile или кристаллы Genesis в Genshin Impact стоят в разы дешевле, чем везде, это приманка, а не выгода.
- Оплата только на карту физлица или криптой. Честный сервис принимает деньги через платёжных провайдеров, а не переводом «другу».
- Просьба дать логин и пароль от аккаунта. Легальное пополнение идёт по игровому ID. Доступ к аккаунту нужен мошеннику, чтобы угнать его или вывести ценные предметы.
- Нет контактов и юридических данных. Отсутствие названия компании, рабочей поддержки и публичных отзывов говорит о том, что отвечать за сделку некому.
- Давление и спешка. «Акция только сегодня», «осталось два места», требование оплатить немедленно: искусственная срочность мешает вам спокойно всё проверить.
- Сайт с ошибками и странным доменом. Опечатки в адресе, свежий домен, кривая вёрстка и отсутствие HTTPS выдают наспех собранную фишинговую страницу.

Отдельный риск несут сторонние площадки перепродажи предметов и валюты между игроками. Там нет гаранта сделки, и покупатель остаётся один на один с продавцом, которого видит впервые.

## Почему важна автоматизация

Главная уязвимость ручных схем в том, что между вашей оплатой и получением доната стоит человек. Он может взять деньги и исчезнуть, затянуть выдачу на сутки или потребовать доплату. Автоматизация убирает это звено.

В автоматическом сервисе процесс выглядит так: вы указываете игровой ID, оплачиваете, и валюта зачисляется сразу, без участия оператора. Именно так работает YuPay: вы вводите ID, нажимаете «Проверить» и видите, что аккаунт найден, платите через Click, Payme или Uzum, и донат приходит на аккаунт автоматически. Итог в сумах виден до оплаты, и списывается ровно он.

Автоматизация решает и вторую проблему: вам не нужно передавать логин и пароль. Пополнение привязано к публичному игровому идентификатору, а доступ к самому аккаунту остаётся только у вас. Подробнее о том, как устроено пополнение, мы разбирали в материале про [пополнение игр онлайн](/blog/popolneniye-igr-onlayn).

## Как проверить надёжность сервиса

Перед первой покупкой потратьте пару минут на проверку. Этого достаточно, чтобы отсеять подозрительные площадки.

- Домен и защищённое соединение. Адрес должен открываться по HTTPS, без предупреждений браузера. Сверьте написание домена по буквам.
- Контакты. У честного сервиса есть название, работающая поддержка и публичная оферта.
- Способы оплаты. Местные методы и расчёты в сумах через платёжных провайдеров надёжнее, чем перевод на личную карту.
- Механика выдачи. Уточните, что для пополнения нужен игровой ID, а не логин с паролем. Это ключевой признак легального сервиса.
- Отзывы и история. Ищите свежие отзывы на внешних площадках, а не только хвалебные цитаты на самом сайте.

Если сервис прозрачно отвечает на эти вопросы, риск минимален. Почему покупка доната у местного продавца часто выгоднее и безопаснее зарубежных посредников, разобрано в статье [почему выгоднее покупать донат локально](/blog/donat-lokalno-v-uzbekistane).

## Защита данных при оплате картой

Даже на честном сайте данные карты нужно вводить аккуратно. Несколько правил снижают риск почти до нуля.

- Платёжная страница должна принадлежать банку или платёжной системе. Настоящая оплата проходит через защищённую форму провайдера, а не через самодельное поле на странице магазина.
- Подтверждение по 3-D Secure. Транзакция с одноразовым кодом из приложения банка или SMS защищает карту от использования без вашего ведома.
- Вводите только платёжные данные. Для оплаты нужны номер карты, срок действия и CVC. PIN-код, пароль от онлайн-банка и коды, которые банк просит никому не сообщать, не передаются никогда и никому.
- Проверяйте адрес прямо перед вводом. Фишинг часто копирует внешний вид известных сайтов.
- Используйте карту с лимитами и уведомлениями. Push о каждой операции и лимит на онлайн-платежи ограничивают ущерб, даже если данные всё-таки утекут.

Отраслевой стандарт PCI DSS требует от платёжных сервисов защищать страницу оплаты от скриптов, ворующих данные карт. Для покупателя это аргумент в пользу сервисов, которые проводят платёж через проверенного провайдера, а не собирают реквизиты сами.

## Чек-лист безопасной покупки доната

Прогоните этот список перед каждой оплатой. Если хотя бы один пункт не выполняется, остановитесь.

- Домен открывается по HTTPS, написание проверено по буквам.
- У сервиса есть название, контакты и работающая поддержка.
- Цена в пределах рынка, без «слишком хорошо, чтобы быть правдой».
- Для пополнения нужен игровой ID, а не логин и пароль от аккаунта.
- Оплата идёт через платёжного провайдера, а не переводом на личную карту.
- Платёжная страница защищена, транзакция подтверждается по 3-D Secure.
- Вы вводите только номер карты, срок и CVC, без PIN и кодов из банка.
- На карте включены уведомления, желательно с лимитом на онлайн-операции.

Безопасность покупки доната почти целиком зависит от выбора сервиса и внимательности при оплате. Выберите один проверенный сервис с автоматической выдачей и оплатой в сумах, сохраните его в закладки и покупайте только там.
""",
        "faqs": [
            (
                "Как понять, что сайт по продаже доната мошеннический?",
                "Тревожные признаки: нереально низкая цена, оплата только на карту физлица или криптой, просьба дать логин и пароль от аккаунта, отсутствие контактов и свежих отзывов.",
            ),
            (
                "Безопасно ли давать продавцу доступ к игровому аккаунту?",
                "Нет. Легальное пополнение выполняется по вашему игровому ID или через привязанный магазин. Передача логина и пароля даёт постороннему полный контроль над аккаунтом.",
            ),
            (
                "Какие данные карты можно вводить при оплате доната?",
                "Номер карты, срок действия и CVC на защищённой платёжной странице банка или платёжной системы. PIN-код, коды из SMS и доступ к онлайн-банку передавать нельзя никому.",
            ),
            (
                "Почему автоматическая доставка безопаснее ручной?",
                "Валюта зачисляется сразу после оплаты без участия человека. Это убирает риск, что продавец возьмёт деньги и пропадёт или затянет выдачу.",
            ),
        ],
    },
    "en": {
        "slug": "buy-in-game-currency-safely",
        "title": "How to buy in-game currency safely",
        "excerpt": "How to spot scam sellers, check a service in a minute, protect your card details, and why a top-up by player ID is safer than handing over a password.",
        "seo_title": "How to buy in-game currency safely",
        "seo_description": "Buying game currency safely: the signs of a scam seller, how to check a service in a minute, protecting card details, and why a top-up by ID beats sharing a password.",
        "body": """
## Key takeaways

- Safe buying starts with checking the seller: domain, contacts, reviews and payment method matter more than a low price.
- Automatic delivery removes the main risk of manual schemes: nobody can take the money and vanish, or ask for your account.
- Never give a currency seller your game login and password: legitimate top-ups go by player ID.
- When paying by card, check HTTPS, 3-D Secure confirmation, and that nothing beyond card details is asked for.

Safe buying rests on three checks: you buy from a service with clear contacts, you pay through a protected payment page, and you receive the top-up by player ID rather than handing over a login and password. If any of the three fails, cancel the purchase, however good the price looks.

## Why it deserves attention

Gaming platforms are a favourite target. Kaspersky counted more than 20 million attacks related to gaming platforms in January–October 2025 ([Kaspersky](https://www.kaspersky.com/about/press-releases/kaspersky-reports-64-million-shopping-phishing-attempts-and-over-20-million-gaming-attacks-detected-in-2025)). For a gamer that means one thing: the page where you type card details for a quick top-up may well be fake.

## Signs of a scam site or seller

- A price far below the market. UC for PUBG Mobile or Genesis Crystals several times cheaper than anywhere else is bait, not a bargain.
- Payment only to a personal card or in crypto. An honest service takes money through payment providers, not as a transfer "to a friend".
- A request for your login and password. Legitimate top-ups go by player ID; account access is what a scammer needs to hijack it or strip valuable items.
- No contacts or company details. No name, no working support, no public reviews means nobody is accountable.
- Pressure and haste. "Today only", "two left", "pay now": manufactured urgency stops you checking.
- Typos, a fresh domain, broken layout, no HTTPS: a phishing page built in a hurry.

Player-to-player resale marketplaces carry their own risk: there is no guarantor, and you are alone with a seller you have never seen.

## Why automation matters

The weak point of manual schemes is the person between your payment and your top-up. They can take the money and disappear, drag delivery out for a day, or demand more. Automation removes that link.

In an automated service you enter the player ID, pay, and the currency is credited at once, with no operator. That is how YuPay works: enter the ID, press "Check" to see the account was found, pay with Click, Payme or Uzum, and the top-up arrives automatically. The total in soʻm is shown before payment and exactly that is charged.

Automation also solves the second problem: you never hand over a login and password. The top-up is tied to a public identifier, and access to the account stays with you. More on how it works in [online game top-ups](/blog/online-game-top-ups-uzbekistan).

## How to check a service

- Domain and connection: HTTPS, no browser warnings, spelling checked letter by letter.
- Contacts: a name, working support, public terms.
- Payment methods: local methods and prices in soʻm through payment providers beat a transfer to a personal card.
- Delivery mechanics: a top-up should need the player ID, not a login and password. This is the key sign of a legitimate service.
- Reviews and history: look for recent reviews on external sites, not only quotes on the site itself.

Why buying from a local seller is often both cheaper and safer than a foreign middleman is covered in [why it pays to buy game top-ups locally](/blog/why-buy-game-top-ups-locally).

## Protecting card details

- The payment page should belong to the bank or payment system, not be a home-made field on the shop's page.
- 3-D Secure confirmation with a one-time code protects the card from being used without you.
- Enter only payment details: card number, expiry and CVC. PIN, online-banking password and the codes the bank tells you never to share go to nobody.
- Check the address right before typing: phishing copies the look of known sites.
- Use a card with limits and notifications, so damage is contained even if details leak.

The PCI DSS standard requires payment services to protect the payment page from card-stealing scripts. For a buyer that is an argument for services that pay through a trusted provider rather than collecting card details themselves.

## The checklist

Run it before every payment; if one item fails, stop.

- HTTPS, domain spelled right.
- A name, contacts and working support.
- A market price, nothing "too good to be true".
- A player ID is enough; no login or password.
- Payment through a provider, not to a personal card.
- A protected payment page with 3-D Secure.
- Only card number, expiry and CVC entered.
- Notifications on, ideally a limit on online payments.

Safety comes almost entirely from choosing the service and paying carefully. Pick one trusted service with automatic delivery and payment in soʻm, bookmark it, and buy only there.
""",
        "faqs": [
            (
                "How do I tell a scam top-up site?",
                "Warning signs: an unrealistically low price, payment only to a personal card or in crypto, a request for your login and password, no contacts and no recent reviews.",
            ),
            (
                "Is it safe to give a seller access to my game account?",
                "No. Legitimate top-ups go by your player ID or through the game's own store. Sharing a login and password gives a stranger full control of the account.",
            ),
            (
                "Which card details may I enter when paying?",
                "Card number, expiry and CVC on the protected payment page of a bank or payment system. Never share the PIN, SMS codes or online-banking access.",
            ),
            (
                "Why is automatic delivery safer than manual?",
                "The currency is credited right after payment with no person involved, so nobody can take the money and vanish or stall the delivery.",
            ),
        ],
    },
    "uz": {
        "slug": "oyin-valyutasini-xavfsiz-sotib-olish",
        "title": "Oʻyin valyutasini qanday xavfsiz sotib olish mumkin",
        "excerpt": "Firibgar sotuvchilarni qanday tanish, xizmatni bir daqiqada tekshirish, karta maʼlumotlarini himoya qilish va nega ID orqali toʻldirish paroldan xavfsizroq.",
        "seo_title": "Oʻyin valyutasini qanday xavfsiz sotib olish mumkin",
        "seo_description": "Oʻyin valyutasini xavfsiz sotib olish: firibgar belgilari, xizmatni bir daqiqada tekshirish, karta maʼlumotlarini himoya qilish va nega ID orqali toʻldirish xavfsizroq.",
        "body": """
## Asosiysi

- Xavfsiz xarid sotuvchini tekshirishdan boshlanadi: domen, kontaktlar, sharhlar va toʻlov usuli past narxdan muhimroq.
- Avtomatik yetkazish qoʻlda sxemalarning asosiy xavfini yopadi: sotuvchi pul bilan gʻoyib boʻlmaydi va akkauntingizga kirishni soʻramaydi.
- Oʻyin akkauntining login va parolini valyuta sotuvchisiga hech qachon bermang: qonuniy toʻldirish oʻyin ID orqali boʻladi.
- Karta bilan toʻlaganda HTTPS, 3-D Secure tasdiqlash va PIN-kod kabi ortiqcha maʼlumot soʻralmasligini tekshiring.

Xavfsiz xarid uchta oddiy tekshiruvga tayanadi: aniq kontaktli xizmatdan sotib olasiz, himoyalangan toʻlov sahifasi orqali toʻlaysiz va donatni oʻyin ID boʻyicha olasiz, login va parolni bermaysiz. Shulardan biri buzilsa, narx qanchalik jozibali boʻlmasin, xariddan voz keching.

## Nega donat xaridiga jiddiy qarash kerak

Oʻyin platformalari firibgarlarning sevimli nishoniga aylangan. Kaspersky maʼlumotiga koʻra, 2025-yil yanvar-oktabr oylarida oʻyin platformalariga oid 20 milliondan ortiq hujum qayd etilgan ([Kaspersky](https://www.kaspersky.com/about/press-releases/kaspersky-reports-64-million-shopping-phishing-attempts-and-over-20-million-gaming-attacks-detected-in-2025)). Geymer uchun bu oddiy narsani anglatadi: tez donat uchun karta maʼlumotlarini kiritayotgan sahifangiz soxta boʻlishi mumkin.

## Firibgar sayt va sotuvchilarning belgilari

- Narx bozordan ancha past. PUBG Mobile uchun UC yoki Genshin Impact kristallari hamma joydagidan bir necha baravar arzon boʻlsa, bu foyda emas, xoʻrak.
- Toʻlov faqat jismoniy shaxs kartasiga yoki kriptoda. Halol xizmat pulni toʻlov provayderlari orqali oladi, «doʻstga» oʻtkazma bilan emas.
- Akkaunt login va parolini soʻrash. Qonuniy toʻldirish oʻyin ID orqali boʻladi. Akkauntga kirish firibgarga uni oʻgʻirlash yoki qimmat buyumlarni chiqarib olish uchun kerak.
- Kontaktlar va yuridik maʼlumotlar yoʻq. Nom, ishlaydigan qoʻllab-quvvatlash va ochiq sharhlar boʻlmasa, bitim uchun javob beradigan hech kim yoʻq.
- Bosim va shoshqaloqlik. «Aksiya faqat bugun», «ikkita joy qoldi», darhol toʻlash talabi — sunʼiy shoshilinchlik tekshirishga xalaqit beradi.
- Xatoli sayt va gʻalati domen. Manzildagi xatolar, yangi domen, qiyshiq dizayn va HTTPS yoʻqligi shoshib yigʻilgan fishing sahifasini fosh qiladi.

Oʻyinchilar oʻrtasida buyum va valyuta qayta sotiladigan tashqi maydonchalar alohida xavf: u yerda bitim kafolati yoʻq, xaridor birinchi marta koʻrgan sotuvchi bilan yolgʻiz qoladi.

## Nega avtomatlashtirish muhim

Qoʻlda sxemalarning asosiy zaifligi — toʻlovingiz va donat olishingiz oʻrtasida odam turadi. U pulni olib gʻoyib boʻlishi, yetkazishni bir kunga choʻzishi yoki qoʻshimcha toʻlov talab qilishi mumkin. Avtomatlashtirish bu boʻgʻinni olib tashlaydi.

Avtomatik xizmatda jarayon shunday: oʻyin ID’ni koʻrsatasiz, toʻlaysiz, valyuta operator ishtirokisiz darhol tushadi. YuPay aynan shunday ishlaydi: ID’ni kiritasiz, «Tekshirish»ni bosib akkaunt topilganini koʻrasiz, Click, Payme yoki Uzum orqali toʻlaysiz, donat akkauntga avtomatik keladi. Soʻmdagi yakuniy summa toʻlovdan oldin koʻrinadi va aynan shu summa yechiladi.

Avtomatlashtirish ikkinchi muammoni ham hal qiladi: login va parolni berish shart emas. Toʻldirish ochiq oʻyin identifikatoriga bogʻlangan, akkauntga kirish esa faqat sizda qoladi. Toʻldirish qanday ishlashi haqida batafsil — [onlayn oʻyin toʻldirish](/blog/onlayn-oyin-toldirish) maqolasida.

## Xizmat ishonchliligini qanday tekshirish

- Domen va himoyalangan ulanish: manzil HTTPS orqali, brauzer ogohlantirishisiz ochilsin; domen yozilishini harfma-harf solishtiring.
- Kontaktlar: halol xizmatda nom, ishlaydigan qoʻllab-quvvatlash va ochiq oferta bor.
- Toʻlov usullari: toʻlov provayderlari orqali soʻmdagi mahalliy usullar shaxsiy kartaga oʻtkazmadan ishonchliroq.
- Yetkazish mexanikasi: toʻldirish uchun login va parol emas, oʻyin ID kerakligini aniqlang. Bu qonuniy xizmatning asosiy belgisi.
- Sharhlar va tarix: saytdagi maqtovlar emas, tashqi maydonchalardagi yangi sharhlarni qidiring.

Mahalliy sotuvchidan donat olish nega koʻpincha xorijiy vositachilardan foydaliroq va xavfsizroq — [donatni mahalliy sotib olish nega foydali](/blog/donatni-mahalliy-sotib-olish) maqolasida.

## Karta bilan toʻlashda maʼlumotlarni himoya qilish

- Toʻlov sahifasi bank yoki toʻlov tizimiga tegishli boʻlsin, doʻkon sahifasidagi oʻzi yasalgan maydon emas.
- 3-D Secure tasdiqlash: bank ilovasi yoki SMS’dan bir martalik kod kartani sizdan bexabar ishlatilishidan himoya qiladi.
- Faqat toʻlov maʼlumotlarini kiriting: karta raqami, amal qilish muddati va CVC. PIN-kod, onlayn-bank paroli va bank hech kimga aytmaslikni soʻragan kodlar hech kimga berilmaydi.
- Kiritishdan oldin manzilni tekshiring: fishing mashhur saytlarning koʻrinishini koʻchiradi.
- Limit va bildirishnomali karta ishlating: maʼlumotlar sizib chiqsa ham zarar cheklanadi.

PCI DSS standarti toʻlov xizmatlaridan toʻlov sahifasini karta maʼlumotlarini oʻgʻirlaydigan skriptlardan himoya qilishni talab qiladi. Xaridor uchun bu rekvizitlarni oʻzi yigʻadigan emas, ishonchli provayder orqali toʻlov oʻtkazadigan xizmatlar foydasiga dalil.

## Xavfsiz donat xaridi uchun tekshiruv roʻyxati

Har toʻlovdan oldin shu roʻyxatni koʻrib chiqing; birorta band bajarilmasa, toʻxtang.

- Domen HTTPS orqali ochiladi, yozilishi tekshirilgan.
- Xizmatda nom, kontaktlar va ishlaydigan qoʻllab-quvvatlash bor.
- Narx bozor doirasida, «haqiqat boʻlish uchun juda yaxshi» emas.
- Toʻldirish uchun oʻyin ID kifoya, login va parol kerak emas.
- Toʻlov shaxsiy kartaga emas, toʻlov provayderi orqali.
- Toʻlov sahifasi himoyalangan, tranzaksiya 3-D Secure bilan tasdiqlanadi.
- Faqat karta raqami, muddat va CVC kiritiladi, PIN va bank kodlari emas.
- Kartada bildirishnomalar yoqilgan, iloji boʻlsa onlayn operatsiyalarga limit bor.

Donat xaridi xavfsizligi deyarli toʻliq xizmat tanlovi va toʻlovdagi eʼtiborga bogʻliq. Avtomatik yetkazish va soʻmda toʻlovli bitta ishonchli xizmatni tanlang, xatcho‘plarga saqlang va faqat oʻsha yerdan xarid qiling.
""",
        "faqs": [
            (
                "Donat sotadigan sayt firibgar ekanini qanday bilish mumkin?",
                "Xavotirli belgilar: haqiqiy boʻlmagan past narx, toʻlov faqat jismoniy shaxs kartasiga yoki kriptoda, akkaunt login va parolini soʻrash, kontaktlar va yangi sharhlar yoʻqligi.",
            ),
            (
                "Sotuvchiga oʻyin akkauntiga kirish berish xavfsizmi?",
                "Yoʻq. Qonuniy toʻldirish oʻyin ID boʻyicha yoki oʻyinning oʻz doʻkoni orqali bajariladi. Login va parolni berish begona odamga akkaunt ustidan toʻliq nazorat beradi.",
            ),
            (
                "Toʻlovda kartaning qaysi maʼlumotlarini kiritish mumkin?",
                "Bank yoki toʻlov tizimining himoyalangan sahifasida karta raqami, amal qilish muddati va CVC. PIN-kod, SMS kodlar va onlayn-bankka kirishni hech kimga berib boʻlmaydi.",
            ),
            (
                "Nega avtomatik yetkazish qoʻldagidan xavfsizroq?",
                "Valyuta toʻlovdan keyin darhol, odam ishtirokisiz tushadi. Bu sotuvchi pulni olib gʻoyib boʻlishi yoki yetkazishni choʻzishi xavfini yoʻq qiladi.",
            ),
        ],
    },
}
