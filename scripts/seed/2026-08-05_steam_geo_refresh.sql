-- Steam — GEO/AI-citation content refresh (ru/en/uz).
--
-- Measured AI-answer probes for "пополнить Steam в Узбекистане" cite paytool.ru,
-- banks (Unired, AVO) and steam.ru — not YuPay. This refresh adds the concrete,
-- extractable answers those queries want: a som price example, the $1–$300
-- limits, the supported account regions, and where to find the Steam login.
--
-- Content-managed, NOT a fixture / Alembic migration. Idempotent:
-- brand_translations UPDATEd in place; FAQs rebuilt via delete-then-insert.
-- Single transaction. Dollar-quoted ($c$/$q$/$a$).
--
-- Apply on prod (operator psql):
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     psql -U yupay_app -d yupay -f - < scripts/seed/2026-08-05_steam_geo_refresh.sql

BEGIN;

UPDATE brand_translations SET
    highlights = $c$["0% комиссии","Оплата в сумах (Uzcard/Humo)","Зачисление моментальное","По логину, без пароля"]$c$::json,
    short_description = $c$Пополнение Steam в Узбекистане за сумы без комиссии: Любая сумма от $1 до $300 по логину Steam (без пароля), оплата картами Uzcard и Humo через Click, Payme или Uzum, зачисление моментальное и автоматическое.$c$,
    description = $c$YuPay — независимый сервис пополнения кошелька Steam в Узбекистане (не связан с Valve). Пополнение идёт по логину Steam (имя для входа) — пароль от аккаунта не нужен, и мы его не запрашиваем.

Комиссия сервиса 0%: сколько вы вводите, столько и зачисляется на кошелёк, один к одному; наша маржа заложена в курс, а итог виден до оплаты. Пополнить можно на любую сумму от $1 до $300 за одну операцию — итог в сумах по текущему курсу показывается сразу.

Оплата — в узбекских сумах картами Uzcard и Humo через Click, Payme или Uzum. Средства зачисляются на баланс Steam моментально и автоматически после подтверждения платежа. Поддерживаются аккаунты в регионах СНГ (РФ, Беларусь, Казахстан, Узбекистан).$c$,
    instructions = $c$Как пополнить кошелёк Steam в Узбекистане:

1. Введите логин Steam (имя для входа в аккаунт) — пароль не нужен.
2. Укажите сумму пополнения от $1 до $300. Итог к оплате в сумах показывается сразу, без дополнительной комиссии.
3. Выберите способ оплаты: Click, Payme или Uzum.
4. Оплатите — средства зачисляются на баланс Steam моментально и автоматически.

Где найти логин Steam: откройте приложение Steam или сайт store.steampowered.com, нажмите на имя профиля в правом верхнем углу и перейдите в «Об аккаунте» — логин для входа указан там же. Это именно логин (имя аккаунта), а не отображаемое имя. Пароль передавать не требуется. Поддерживаемые регионы: СНГ (РФ, Беларусь, Казахстан, Узбекистан).$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'steam') AND locale = 'ru';

UPDATE brand_translations SET
    highlights = $c$["0% commission","Pay in sum (Uzcard/Humo)","Instant crediting","By login, no password"]$c$::json,
    short_description = $c$Top up Steam in Uzbekistan in sum with no commission: Any amount from $1 to $300 by Steam login (no password), pay with Uzcard and Humo via Click, Payme or Uzum, credited instantly and automatically.$c$,
    description = $c$YuPay is an independent Steam wallet top-up service in Uzbekistan (not affiliated with Valve). Top-ups go by your Steam login (the account name you sign in with) — no account password is needed, and we never ask for it.

The service commission is 0%: what you enter is exactly what lands on your wallet, one to one; our margin is in the rate, and the total is shown before you pay. You can top up any amount from $1 to $300 per transaction — the total in sum at the current rate is shown right away.

You pay in Uzbek sum with Uzcard and Humo cards via Click, Payme or Uzum. Funds are credited to your Steam balance instantly and automatically after the payment is confirmed. Accounts in the CIS region (Russia, Belarus, Kazakhstan, Uzbekistan) are supported.$c$,
    instructions = $c$How to top up a Steam wallet in Uzbekistan:

1. Enter your Steam login (the account name you sign in with) — no password needed.
2. Enter an amount from $1 to $300. The total to pay in sum is shown right away, with no extra commission.
3. Choose a payment method: Click, Payme or Uzum.
4. Pay — the funds are credited to your Steam balance instantly and automatically.

Where to find your Steam login: open the Steam app or store.steampowered.com, click your profile name in the top-right corner and open Account details — your login is shown there. This is the login (account name), not your display name. No password is needed. Supported regions: CIS (Russia, Belarus, Kazakhstan, Uzbekistan).$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'steam') AND locale = 'en';

UPDATE brand_translations SET
    highlights = $c$["0% komissiya","Soʻmda toʻlov (Uzcard/Humo)","Bir zumda tushadi","Login boʻyicha, parolsiz"]$c$::json,
    short_description = $c$Steam ni Oʻzbekistonda soʻmda komissiyasiz toʻldirish: $1 dan $300 gacha istalgan summa Steam login boʻyicha (parolsiz), Uzcard va Humo kartalari bilan Click, Payme yoki Uzum orqali, bir zumda va avtomatik tushadi.$c$,
    description = $c$YuPay — Oʻzbekistonda Steam hamyonini toʻldirish uchun mustaqil xizmat (Valve bilan bogʻliq emas). Toʻldirish Steam login (kirish uchun hisob nomi) boʻyicha amalga oshiriladi — akkaunt paroli kerak emas, biz uni soʻramaymiz.

Xizmat komissiyasi 0%: qancha kiritsangiz, shuncha hamyonga tushadi, bir xil; marjamiz kursda, yakuniy summa toʻlovdan oldin koʻrinadi. Bir operatsiyada $1 dan $300 gacha istalgan summani toʻldirish mumkin — joriy kurs boʻyicha soʻmdagi summa darhol koʻrsatiladi.

Toʻlov — oʻzbek soʻmida Uzcard va Humo kartalari orqali Click, Payme yoki Uzum bilan. Mablagʻ toʻlov tasdiqlangach Steam balansiga bir zumda va avtomatik tushadi. MDH mintaqasidagi (Rossiya, Belarus, Qozogʻiston, Oʻzbekiston) akkauntlar qoʻllab-quvvatlanadi.$c$,
    instructions = $c$Steam hamyonini Oʻzbekistonda qanday toʻldirish:

1. Steam login (kirish uchun hisob nomi) ni kiriting — parol kerak emas.
2. $1 dan $300 gacha summani kiriting. Soʻmdagi toʻlov summasi darhol, qoʻshimcha komissiyasiz koʻrsatiladi.
3. Toʻlov usulini tanlang: Click, Payme yoki Uzum.
4. Toʻlang — mablagʻ Steam balansiga bir zumda va avtomatik tushadi.

Steam login ni qayerdan topish: Steam ilovasini yoki store.steampowered.com saytini oching, yuqori oʻng burchakdagi profil nomini bosing va «Hisob haqida» boʻlimiga oʻting — login shu yerda koʻrsatilgan. Bu aynan login (hisob nomi), koʻrsatiladigan nom emas. Parol kerak emas. Qoʻllab-quvvatlanadigan mintaqalar: MDH (Rossiya, Belarus, Qozogʻiston, Oʻzbekiston).$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'steam') AND locale = 'uz';

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'steam');

WITH steam AS (
    SELECT id FROM brands WHERE slug = 'steam'
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), steam.id, v.sort_order, true
    FROM steam, (VALUES (1),(2),(3),(4),(5),(6),(7),(8),(9)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. Комиссия
        (1, 'ru', $q$Есть ли комиссия за пополнение Steam?$q$,
            $a$Сервисной комиссии поверх суммы пополнения нет — 0%. Сколько вы вводите, столько и зачисляется на кошелёк Steam, один к одному. Наша маржа заложена в курс конвертации, а не в отдельный сбор, поэтому итог к оплате вы видите заранее.$a$),
        (1, 'en', $q$Is there a commission on Steam top-ups?$q$,
            $a$There is no service commission on top of your amount — 0%. What you enter is exactly what lands on your Steam wallet, one to one. Our margin is in the conversion rate, not a separate fee, so you see the final amount to pay in advance.$a$),
        (1, 'uz', $q$Steam toʻldirishda komissiya bormi?$q$,
            $a$Toʻldirish summasi ustiga xizmat komissiyasi yoʻq — 0%. Qancha kiritsangiz, shuncha Steam hamyoniga tushadi, bir xil. Marjamiz konvertatsiya kursida, alohida yigʻimda emas, shuning uchun toʻlov summasini oldindan koʻrasiz.$a$),

        -- 2. Оплата в сумах
        (2, 'ru', $q$Можно ли платить в сумах?$q$,
            $a$Да. Оплата в узбекских сумах доступна картами Uzcard и Humo через Click, Payme и Uzum. Итоговая сумма по текущему курсу видна до оплаты.$a$),
        (2, 'en', $q$Can I pay in sum?$q$,
            $a$Yes. You can pay in Uzbek sum with Uzcard and Humo cards via Click, Payme and Uzum. The final amount at the current rate is shown before you pay.$a$),
        (2, 'uz', $q$Soʻmda toʻlash mumkinmi?$q$,
            $a$Ha. Oʻzbek soʻmida Uzcard va Humo kartalari orqali Click, Payme va Uzum bilan toʻlash mumkin. Joriy kurs boʻyicha yakuniy summa toʻlovdan oldin koʻrinadi.$a$),

        -- 3. NEW: сколько стоит $10 (price answer target)
        (3, 'ru', $q$Сколько стоит пополнить Steam на $10 в сумах?$q$,
            $a$Итог в сумах показывается до оплаты и зависит от курса. Ориентир по текущему курсу: $5 ≈ 71 000 сум, $10 ≈ 142 000 сум, $20 ≈ 284 000 сум. Комиссии сверху нет — сколько вводите, столько и зачисляется на кошелёк Steam.$a$),
        (3, 'en', $q$How much does topping up Steam by $10 cost in sum?$q$,
            $a$The total in sum is shown before payment and depends on the rate. As a guide at the current rate: $5 ≈ 71,000 sum, $10 ≈ 142,000 sum, $20 ≈ 284,000 sum. There is no extra commission — what you enter is what lands on your Steam wallet.$a$),
        (3, 'uz', $q$Steam ni $10 ga toʻldirish soʻmda qancha turadi?$q$,
            $a$Soʻmdagi summa toʻlovdan oldin koʻrsatiladi va kursga bogʻliq. Joriy kurs boʻyicha taxminan: $5 ≈ 71 000 soʻm, $10 ≈ 142 000 soʻm, $20 ≈ 284 000 soʻm. Ustiga komissiya yoʻq — qancha kiritsangiz, shuncha Steam hamyoniga tushadi.$a$),

        -- 4. NEW: мин/макс
        (4, 'ru', $q$Какая минимальная и максимальная сумма пополнения?$q$,
            $a$За одну операцию можно пополнить от $1 до $300. Для большей суммы оформите несколько пополнений. Итог в сумах по текущему курсу виден до оплаты.$a$),
        (4, 'en', $q$What are the minimum and maximum top-up amounts?$q$,
            $a$You can top up from $1 to $300 per transaction. For a larger amount, make several top-ups. The total in sum at the current rate is shown before payment.$a$),
        (4, 'uz', $q$Toʻldirishning eng kam va eng koʻp summasi qancha?$q$,
            $a$Bitta operatsiyada $1 dan $300 gacha toʻldirish mumkin. Katta summa uchun bir necha marta toʻldiring. Joriy kurs boʻyicha soʻmdagi summa toʻlovdan oldin koʻrinadi.$a$),

        -- 5. NEW: регион аккаунта
        (5, 'ru', $q$В каком регионе должен быть аккаунт Steam?$q$,
            $a$Пополнение работает для аккаунтов Steam в регионах СНГ (Россия, Беларусь, Казахстан, Узбекистан). Валюта кошелька зависит от региона аккаунта; средства зачисляются в валюте вашего кошелька Steam.$a$),
        (5, 'en', $q$Which region does my Steam account need to be in?$q$,
            $a$Top-ups work for Steam accounts in the CIS region (Russia, Belarus, Kazakhstan, Uzbekistan). The wallet currency depends on the account region; funds are credited in your Steam wallet's currency.$a$),
        (5, 'uz', $q$Steam akkaunti qaysi mintaqada boʻlishi kerak?$q$,
            $a$Toʻldirish MDH mintaqasidagi (Rossiya, Belarus, Qozogʻiston, Oʻzbekiston) Steam akkauntlari uchun ishlaydi. Hamyon valyutasi akkaunt mintaqasiga bogʻliq; mablagʻ Steam hamyoningiz valyutasida tushadi.$a$),

        -- 6. NEW: где найти логин
        (6, 'ru', $q$Где найти логин Steam?$q$,
            $a$Откройте приложение Steam или сайт store.steampowered.com, нажмите на имя профиля в правом верхнем углу и перейдите в «Об аккаунте» — логин для входа указан там же. Это именно логин (имя аккаунта), а не отображаемое имя профиля. Пароль передавать не нужно.$a$),
        (6, 'en', $q$Where do I find my Steam login?$q$,
            $a$Open the Steam app or store.steampowered.com, click your profile name in the top-right corner and open Account details — your login is shown there. This is the login (account name), not your display name. No password is needed.$a$),
        (6, 'uz', $q$Steam login ni qayerdan topaman?$q$,
            $a$Steam ilovasini yoki store.steampowered.com saytini oching, yuqori oʻng burchakdagi profil nomini bosing va «Hisob haqida» boʻlimiga oʻting — login shu yerda koʻrsatilgan. Bu aynan login (hisob nomi), profil koʻrsatiladigan nomi emas. Parol kerak emas.$a$),

        -- 7. За сколько зачислится
        (7, 'ru', $q$За сколько зачислится пополнение?$q$,
            $a$Зачисление на кошелёк Steam происходит моментально и автоматически сразу после подтверждения оплаты.$a$),
        (7, 'en', $q$How fast is the top-up credited?$q$,
            $a$The funds are credited to your Steam wallet instantly and automatically right after the payment is confirmed.$a$),
        (7, 'uz', $q$Toʻldirish qancha vaqtda tushadi?$q$,
            $a$Steam hamyoniga mablagʻ toʻlov tasdiqlangach bir zumda va avtomatik tushadi.$a$),

        -- 8. Пароль
        (8, 'ru', $q$Нужен ли пароль от аккаунта?$q$,
            $a$Нет. Для пополнения достаточно логина Steam — пароль от аккаунта передавать не нужно, и мы его не запрашиваем.$a$),
        (8, 'en', $q$Do I need my account password?$q$,
            $a$No. Only your Steam login is needed to top up — you never share your account password, and we never ask for it.$a$),
        (8, 'uz', $q$Akkaunt paroli kerakmi?$q$,
            $a$Yoʻq. Toʻldirish uchun Steam login yetarli — akkaunt parolini berish shart emas, biz uni soʻramaymiz.$a$),

        -- 9. Официальный сайт
        (9, 'ru', $q$Это официальный сайт Steam?$q$,
            $a$Нет. YuPay — независимый сервис пополнения, не связанный с Valve. Мы покупаем и перепродаём пополнения по прозрачному курсу, без скрытых комиссий.$a$),
        (9, 'en', $q$Is this the official Steam website?$q$,
            $a$No. YuPay is an independent top-up service, not affiliated with Valve. We buy and resell top-ups at a transparent rate, with no hidden fees.$a$),
        (9, 'uz', $q$Bu Steam rasmiy saytimi?$q$,
            $a$Yoʻq. YuPay — mustaqil toʻldirish xizmati, Valve bilan bogʻliq emas. Biz toʻldirishlarni shaffof kurs boʻyicha sotib olib, qayta sotamiz, yashirin komissiyalarsiz.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
