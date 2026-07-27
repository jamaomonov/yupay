-- scripts/seed/steam_seo.sql
--
-- SEO content pack for the `steam` brand: highlights + short/long descriptions +
-- instructions on `brand_translations`, and 4 FAQ entries with ru/en/uz answers.
--
-- Content-managed, NOT a fixture and NOT an Alembic data migration. Applied to
-- prod by an operator (psql / `!`), gated by the standing deploy rule. Depends on
-- migration 0032_brand_highlights (adds `brand_translations.highlights`).
--
-- Idempotent: brand_translations rows are UPDATEd in place; FAQs are rebuilt via
-- delete-then-insert. Wrapped in a single transaction so a half-run cannot leave
-- partial state. Re-running yields identical final content (FAQ row ids are
-- regenerated each run, which is fine — nothing references them).
--
-- Strings are dollar-quoted ($c$…$c$ / $q$…$q$ / $a$…$a$) so the apostrophe-heavy
-- Uzbek copy needs no escaping.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Brand translations (highlights, short_description, description, instructions)
-- ---------------------------------------------------------------------------

UPDATE brand_translations SET
    highlights = $c$["0% комиссии","Оплата в сумах","1–3 минуты","Без пароля"]$c$::json,
    short_description = $c$Пополнение Steam в Узбекистане за сумы без комиссии: сколько платите — столько и зачисляется на кошелёк Steam, один к одному. Оплата картами Uzcard и Humo через Click, Payme, Uzum или в USDT, зачисление за 1–3 минуты и без передачи пароля от аккаунта.$c$,
    description = $c$YuPay — это пополнение Steam Узбекистан за сумы с комиссией 0%. «0%» означает, что поверх суммы пополнения мы не берём отдельный сервисный сбор: сколько вы вводите, столько и попадает на кошелёк Steam — один к одному. Наш заработок заложен в курс конвертации, а не в скрытую комиссию, поэтому итоговая сумма к оплате прозрачна и видна ещё до подтверждения заказа.

Оплатить можно привычными способами: картами Uzcard и Humo через Click, Payme и Uzum, а также в USDT. Средства зачисляются на баланс Steam за 1–3 минуты после подтверждения оплаты, а для пополнения не нужен пароль от вашего аккаунта — достаточно логина Steam. Поддерживаем аккаунты в регионах СНГ, Казахстана и Турции.$c$,
    instructions = $c$Как пополнить кошелёк Steam:

1. Введите логин Steam (имя для входа в аккаунт) — пароль не нужен.
2. Укажите сумму пополнения. Итог к оплате показывается сразу, без дополнительной комиссии.
3. Выберите способ оплаты: Click, Payme, Uzum или USDT.
4. Оплатите — средства обычно приходят на баланс Steam за 1–3 минуты.

Где найти логин Steam: откройте приложение Steam или сайт store.steampowered.com, нажмите на имя профиля в правом верхнем углу и перейдите в «Об аккаунте». Логин для входа указан там же; пароль передавать не требуется.

Поддерживаемые регионы аккаунта: СНГ, Казахстан, Турция.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'steam') AND locale = 'ru';

UPDATE brand_translations SET
    highlights = $c$["0% commission","Pay in UZS","1–3 minutes","No password"]$c$::json,
    short_description = $c$Top up Steam in Uzbekistan in sum with no commission: what you pay is what lands on your Steam wallet, one to one. Pay with Uzcard or Humo via Click, Payme, Uzum, or in USDT — funds arrive in 1–3 minutes, and we never ask for your account password.$c$,
    description = $c$YuPay lets you top up Steam in Uzbekistan in sum with 0% commission. "0%" means we add no separate service fee on top of the amount you top up: the sum you enter is the sum that reaches your Steam wallet, one to one. Our margin sits in the conversion rate, not in a hidden fee, so the total you pay is transparent and shown before you confirm the order.

Pay the way you already do: Uzcard and Humo cards via Click, Payme and Uzum, or in USDT. Funds are credited to your Steam balance within 1–3 minutes of a confirmed payment, and we never need your account password — your Steam login is enough. We support accounts in the CIS, Kazakhstan and Turkey regions.$c$,
    instructions = $c$How to top up your Steam wallet:

1. Enter your Steam login (the account name you sign in with) — no password required.
2. Enter the amount. The total to pay is shown right away, with no extra commission.
3. Choose a payment method: Click, Payme, Uzum or USDT.
4. Pay — funds usually reach your Steam balance in 1–3 minutes.

Where to find your Steam login: open the Steam app or store.steampowered.com, click your profile name in the top-right corner and go to "Account details". Your sign-in login is shown there; you never need to share your password.

Supported account regions: CIS, Kazakhstan, Turkey.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'steam') AND locale = 'en';

UPDATE brand_translations SET
    highlights = $c$["0% komissiya","Soʻmda toʻlov","1–3 daqiqa","Parolsiz"]$c$::json,
    short_description = $c$Steam hisobini Oʻzbekistonda soʻmda komissiyasiz toʻldiring: qancha toʻlasangiz, Steam hamyoningizga shuncha tushadi, birma-bir. Uzcard va Humo kartalari orqali Click, Payme, Uzum yoki USDTʼda toʻlang — mablagʻ 1–3 daqiqada tushadi, akkaunt paroli soʻralmaydi.$c$,
    description = $c$YuPay — Oʻzbekistonda Steam hisobini soʻmda 0% komissiya bilan toʻldirish. «0%» degani — toʻldirish summasi ustiga alohida xizmat haqi qoʻshmaymiz: siz kiritgan summa Steam hamyoningizga birma-bir tushadi. Bizning daromadimiz alohida komissiyada emas, konvertatsiya kursida, shuning uchun toʻlov summasi buyurtmani tasdiqlashdan oldin aniq koʻrinadi.

Toʻlovni odatdagi usullarda amalga oshiring: Uzcard va Humo kartalari Click, Payme va Uzum orqali, yoki USDTʼda. Mablagʻ toʻlov tasdiqlangach Steam balansiga odatda 1–3 daqiqada tushadi, toʻldirish uchun akkaunt paroli kerak emas — Steam login yetarli. MDH, Qozogʻiston va Turkiya mintaqalaridagi akkauntlarni qoʻllab-quvvatlaymiz.$c$,
    instructions = $c$Steam hamyonini qanday toʻldirish:

1. Steam loginingizni (akkauntga kirish nomi) kiriting — parol kerak emas.
2. Summani kiriting. Toʻlov summasi qoʻshimcha komissiyasiz darhol koʻrsatiladi.
3. Toʻlov usulini tanlang: Click, Payme, Uzum yoki USDT.
4. Toʻlang — mablagʻ Steam balansiga odatda 1–3 daqiqada tushadi.

Steam loginini qayerdan topish mumkin: Steam ilovasini yoki store.steampowered.com saytini oching, yuqori oʻng burchakdagi profil nomini bosing va «Akkaunt haqida» boʻlimiga oʻting. Kirish logini oʻsha yerda koʻrsatilgan; parolni berish shart emas.

Qoʻllab-quvvatlanadigan akkaunt mintaqalari: MDH, Qozogʻiston, Turkiya.$c$
WHERE brand_id = (SELECT id FROM brands WHERE slug = 'steam') AND locale = 'uz';

-- ---------------------------------------------------------------------------
-- 2. FAQs (rebuilt each run: delete cascades to brand_faq_translations)
-- ---------------------------------------------------------------------------

DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'steam');

WITH steam AS (
    SELECT id FROM brands WHERE slug = 'steam'
),
new_faqs AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), steam.id, v.sort_order, true
    FROM steam, (VALUES (1), (2), (3), (4)) AS v(sort_order)
    RETURNING id, sort_order
)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer
FROM new_faqs nf
JOIN (
    VALUES
        -- 1. Есть ли комиссия?
        (1, 'ru', $q$Есть ли комиссия за пополнение Steam?$q$,
            $a$Сервисной комиссии поверх суммы пополнения нет — 0%. Сколько вы вводите, столько и зачисляется на кошелёк Steam, один к одному. Наша маржа заложена в курс конвертации, а не в отдельный сбор, поэтому итог к оплате вы видите заранее.$a$),
        (1, 'en', $q$Is there a commission on Steam top-ups?$q$,
            $a$There is no service commission on top of the top-up amount — 0%. The sum you enter is credited to your Steam wallet one to one. Our margin sits in the conversion rate, not in a separate fee, so you see the total to pay in advance.$a$),
        (1, 'uz', $q$Steam toʻldirish uchun komissiya bormi?$q$,
            $a$Toʻldirish summasi ustiga xizmat komissiyasi yoʻq — 0%. Siz kiritgan summa Steam hamyoningizga birma-bir tushadi. Daromadimiz alohida toʻlovda emas, konvertatsiya kursida, shuning uchun toʻlov summasini oldindan koʻrasiz.$a$),

        -- 2. Можно ли платить в сумах?
        (2, 'ru', $q$Можно ли платить в сумах?$q$,
            $a$Да. Оплата в узбекских сумах доступна картами Uzcard и Humo через Click, Payme и Uzum. Также можно оплатить в USDT.$a$),
        (2, 'en', $q$Can I pay in Uzbek sum?$q$,
            $a$Yes. You can pay in Uzbek sum with Uzcard and Humo cards via Click, Payme and Uzum. Payment in USDT is also available.$a$),
        (2, 'uz', $q$Soʻmda toʻlash mumkinmi?$q$,
            $a$Ha. Oʻzbek soʻmida Uzcard va Humo kartalari orqali Click, Payme va Uzum bilan toʻlash mumkin. Shuningdek USDTʼda toʻlov ham mavjud.$a$),

        -- 3. За сколько зачислится?
        (3, 'ru', $q$За сколько зачислится пополнение?$q$,
            $a$Обычно за 1–3 минуты после подтверждения оплаты. В редких случаях при высокой нагрузке зачисление может занять немного больше времени.$a$),
        (3, 'en', $q$How fast is the top-up credited?$q$,
            $a$Usually within 1–3 minutes after your payment is confirmed. In rare cases of high load it can take a little longer.$a$),
        (3, 'uz', $q$Toʻldirish qancha vaqtda tushadi?$q$,
            $a$Odatda toʻlov tasdiqlangach 1–3 daqiqada. Yuklama yuqori boʻlgan kamdan-kam hollarda biroz koʻproq vaqt olishi mumkin.$a$),

        -- 4. Нужен ли пароль?
        (4, 'ru', $q$Нужен ли пароль от аккаунта?$q$,
            $a$Нет. Для пополнения достаточно логина Steam — пароль от аккаунта передавать не нужно, и мы его не запрашиваем.$a$),
        (4, 'en', $q$Do you need my account password?$q$,
            $a$No. Your Steam login is all we need to top up — you never share your account password, and we never ask for it.$a$),
        (4, 'uz', $q$Akkaunt paroli kerakmi?$q$,
            $a$Yoʻq. Toʻldirish uchun Steam login yetarli — akkaunt parolini bermaysiz, biz uni soʻramaymiz.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
