-- Tail-brand GEO FAQ top-up: adds two answer-target FAQs per brand for the
-- lower-demand titles (Free Fire, Genshin Impact, Delta Force, Arena Breakout,
-- Arena Breakout: Infinite). Measured AI-answer probes show these brands aren't
-- cited for price and "where to find ID" queries; these entries give the
-- extractable, answer-shaped content those queries want.
--
-- Deliberately light: existing FAQs are left untouched. The two new FAQs use
-- sort_order 90/91 (appended after the existing set), and each brand block is
-- idempotent — it deletes only 90/91 for that brand before re-inserting.
-- Prices are rate-dependent → hedged as "ориентир"/"до оплаты". Single
-- transaction. Dollar-quoted ($q$/$a$).
--
-- Apply on prod (operator psql):
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     psql -U yupay_app -d yupay -f - < scripts/seed/2026-08-05_tail_geo_faqs.sql

BEGIN;

-- ======================= Free Fire =======================
DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'free-fire') AND sort_order IN (90, 91);
WITH b AS (SELECT id FROM brands WHERE slug = 'free-fire'),
nf AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), b.id, v.so, true FROM b, (VALUES (90),(91)) AS v(so)
    RETURNING id, sort_order)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer FROM nf JOIN (VALUES
    (90,'ru',$q$Сколько стоят алмазы Free Fire в сумах?$q$,$a$Итог в сумах показывается до оплаты и зависит от курса. Ориентир: 110 алмазов ≈ 11 700 сум, 341 ≈ 35 300, 572 ≈ 57 400, 1166 ≈ 115 000, 2398 ≈ 231 000, 6160 ≈ 585 000 сум. Комиссии сверху нет.$a$),
    (90,'en',$q$How much do Free Fire diamonds cost in sum?$q$,$a$The total in sum is shown before payment and depends on the rate. As a guide: 110 diamonds ≈ 11,700 sum, 341 ≈ 35,300, 572 ≈ 57,400, 1,166 ≈ 115,000, 2,398 ≈ 231,000, 6,160 ≈ 585,000 sum. No extra commission.$a$),
    (90,'uz',$q$Free Fire olmoslari soʻmda qancha turadi?$q$,$a$Soʻmdagi summa toʻlovdan oldin koʻrsatiladi va kursga bogʻliq. Taxminan: 110 olmos ≈ 11 700 soʻm, 341 ≈ 35 300, 572 ≈ 57 400, 1166 ≈ 115 000, 2398 ≈ 231 000, 6160 ≈ 585 000 soʻm. Ustiga komissiya yoʻq.$a$),
    (91,'ru',$q$Какие пакеты алмазов и подписки доступны?$q$,$a$Доступно 6 пакетов алмазов: 110, 341, 572, 1166, 2398 и 6160. Также есть недельная и месячная подписка (Weekly / Monthly Membership) — они дают стартовый бонус и ежедневные алмазы в течение срока действия.$a$),
    (91,'en',$q$Which diamond packs and subscriptions are available?$q$,$a$There are 6 diamond packs: 110, 341, 572, 1,166, 2,398 and 6,160. Weekly and Monthly Membership subscriptions are also available — they give a starter bonus and daily diamonds for the duration.$a$),
    (91,'uz',$q$Qanday olmos paketlari va obunalar mavjud?$q$,$a$6 ta olmos paketi mavjud: 110, 341, 572, 1166, 2398 va 6160. Shuningdek haftalik va oylik obuna (Weekly / Monthly Membership) bor — ular boshlangʻich bonus va muddat davomida har kunlik olmos beradi.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

-- ======================= Genshin Impact =======================
DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'genshin-impact') AND sort_order IN (90, 91);
WITH b AS (SELECT id FROM brands WHERE slug = 'genshin-impact'),
nf AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), b.id, v.so, true FROM b, (VALUES (90),(91)) AS v(so)
    RETURNING id, sort_order)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer FROM nf JOIN (VALUES
    (90,'ru',$q$Сколько стоят Кристаллы Сотворения в сумах?$q$,$a$Итог в сумах виден до оплаты и зависит от курса. Ориентир: 60 кристаллов ≈ 14 300 сум, 330 ≈ 71 500, 1090 ≈ 214 000, 2240 ≈ 429 000, 3880 ≈ 715 000, 8080 ≈ 1 430 000 сум. Благословение полой луны ≈ 71 500 сум. Комиссии сверху нет.$a$),
    (90,'en',$q$How much do Genesis Crystals cost in sum?$q$,$a$The total in sum is shown before payment and depends on the rate. As a guide: 60 crystals ≈ 14,300 sum, 330 ≈ 71,500, 1,090 ≈ 214,000, 2,240 ≈ 429,000, 3,880 ≈ 715,000, 8,080 ≈ 1,430,000 sum. Blessing of the Welkin Moon ≈ 71,500 sum. No extra commission.$a$),
    (90,'uz',$q$Genesis Crystals soʻmda qancha turadi?$q$,$a$Soʻmdagi summa toʻlovdan oldin koʻrinadi va kursga bogʻliq. Taxminan: 60 kristall ≈ 14 300 soʻm, 330 ≈ 71 500, 1090 ≈ 214 000, 2240 ≈ 429 000, 3880 ≈ 715 000, 8080 ≈ 1 430 000 soʻm. Blessing of the Welkin Moon ≈ 71 500 soʻm. Ustiga komissiya yoʻq.$a$),
    (91,'ru',$q$Где найти UID в Genshin Impact и как выбрать сервер?$q$,$a$UID — это 9-значный номер в правом нижнем углу экрана в игре; его также видно в меню Паймон (значок в левом верхнем углу) под именем персонажа. При пополнении также выберите сервер аккаунта: America, Europe, Asia или TW-HK-MO. Пароль передавать не нужно.$a$),
    (91,'en',$q$Where do I find my UID in Genshin Impact and how do I pick the server?$q$,$a$The UID is the 9-digit number in the bottom-right corner of the in-game screen; it is also shown in the Paimon menu (icon in the top-left) below your character name. When topping up, also select your account server: America, Europe, Asia or TW-HK-MO. No password is needed.$a$),
    (91,'uz',$q$Genshin Impact UID ni qayerdan topaman va serverni qanday tanlayman?$q$,$a$UID — oʻyin ekranining pastki oʻng burchagidagi 9 xonali raqam; u Paimon menyusida (chap yuqoridagi belgi) personaj nomi ostida ham koʻrinadi. Toʻldirishda akkaunt serverini ham tanlang: America, Europe, Asia yoki TW-HK-MO. Parol kerak emas.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

-- ======================= Delta Force =======================
DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'delta-force') AND sort_order IN (90, 91);
WITH b AS (SELECT id FROM brands WHERE slug = 'delta-force'),
nf AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), b.id, v.so, true FROM b, (VALUES (90),(91)) AS v(so)
    RETURNING id, sort_order)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer FROM nf JOIN (VALUES
    (90,'ru',$q$Сколько стоят Delta Coins в сумах?$q$,$a$Итог в сумах виден до оплаты и зависит от курса. Ориентир: 18 Delta Coins ≈ 3 300 сум, 60 ≈ 11 200, 320 ≈ 56 000, 750 ≈ 113 000, 1480 ≈ 226 000, 3950 ≈ 564 000, 8100 ≈ 1 128 000 сум. Комиссии сверху нет.$a$),
    (90,'en',$q$How much do Delta Coins cost in sum?$q$,$a$The total in sum is shown before payment and depends on the rate. As a guide: 18 Delta Coins ≈ 3,300 sum, 60 ≈ 11,200, 320 ≈ 56,000, 750 ≈ 113,000, 1,480 ≈ 226,000, 3,950 ≈ 564,000, 8,100 ≈ 1,128,000 sum. No extra commission.$a$),
    (90,'uz',$q$Delta Coins soʻmda qancha turadi?$q$,$a$Soʻmdagi summa toʻlovdan oldin koʻrinadi va kursga bogʻliq. Taxminan: 18 Delta Coins ≈ 3 300 soʻm, 60 ≈ 11 200, 320 ≈ 56 000, 750 ≈ 113 000, 1480 ≈ 226 000, 3950 ≈ 564 000, 8100 ≈ 1 128 000 soʻm. Ustiga komissiya yoʻq.$a$),
    (91,'ru',$q$Где найти игровой ID (Player ID) в Delta Force?$q$,$a$Зайдите в лобби игры и откройте профиль — значок профиля в правом нижнем углу; ваш ID игрока (Player ID) показан на странице профиля. Пополнение идёт по этому ID, пароль не нужен. Перед оплатой внимательно проверьте ID.$a$),
    (91,'en',$q$Where do I find my Player ID in Delta Force?$q$,$a$Open the game lobby and open your profile — the profile icon is in the bottom-right corner; your Player ID is shown on the profile page. Top-ups use this ID and no password is needed. Double-check the ID before paying.$a$),
    (91,'uz',$q$Delta Force da Player ID ni qayerdan topaman?$q$,$a$Oʻyin lobbisiga kiring va profilni oching — profil belgisi pastki oʻng burchakda; Player ID profil sahifasida koʻrsatiladi. Toʻldirish shu ID boʻyicha, parol kerak emas. Toʻlovdan oldin ID ni diqqat bilan tekshiring.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

-- ======================= Arena Breakout =======================
DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'arena-breakout') AND sort_order IN (90, 91);
WITH b AS (SELECT id FROM brands WHERE slug = 'arena-breakout'),
nf AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), b.id, v.so, true FROM b, (VALUES (90),(91)) AS v(so)
    RETURNING id, sort_order)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer FROM nf JOIN (VALUES
    (90,'ru',$q$Сколько стоят Bonds в Arena Breakout в сумах?$q$,$a$Итог в сумах виден до оплаты и зависит от курса. Ориентир: 66 Bonds ≈ 11 400 сум, 335 ≈ 57 500, 675 ≈ 115 000, 1690 ≈ 288 000, 3400 ≈ 577 000, 6820 ≈ 1 175 000 сум. Комиссии сверху нет.$a$),
    (90,'en',$q$How much do Bonds cost in Arena Breakout in sum?$q$,$a$The total in sum is shown before payment and depends on the rate. As a guide: 66 Bonds ≈ 11,400 sum, 335 ≈ 57,500, 675 ≈ 115,000, 1,690 ≈ 288,000, 3,400 ≈ 577,000, 6,820 ≈ 1,175,000 sum. No extra commission.$a$),
    (90,'uz',$q$Arena Breakout da Bonds soʻmda qancha turadi?$q$,$a$Soʻmdagi summa toʻlovdan oldin koʻrinadi va kursga bogʻliq. Taxminan: 66 Bonds ≈ 11 400 soʻm, 335 ≈ 57 500, 675 ≈ 115 000, 1690 ≈ 288 000, 3400 ≈ 577 000, 6820 ≈ 1 175 000 soʻm. Ustiga komissiya yoʻq.$a$),
    (91,'ru',$q$Где найти ID игрока (UID) в Arena Breakout?$q$,$a$Откройте игру и нажмите на аватар (значок профиля) в левом верхнем углу главного экрана — ваш ID игрока (UID) показан в профиле. Для пополнения нужен только этот ID; пароль передавать не требуется.$a$),
    (91,'en',$q$Where do I find my Player ID (UID) in Arena Breakout?$q$,$a$Open the game and tap your avatar (profile icon) in the top-left corner of the main screen — your Player ID (UID) is shown on the profile. Only this ID is needed to top up; no password is required.$a$),
    (91,'uz',$q$Arena Breakout da Player ID (UID) ni qayerdan topaman?$q$,$a$Oʻyinni oching va asosiy ekranning yuqori chap burchagidagi avatar (profil belgisi) ni bosing — Player ID (UID) profilda koʻrsatiladi. Toʻldirish uchun faqat shu ID kerak; parol talab qilinmaydi.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

-- ======================= Arena Breakout: Infinite (PC) =======================
DELETE FROM brand_faqs WHERE brand_id = (SELECT id FROM brands WHERE slug = 'arena-breakout-infinite') AND sort_order IN (90, 91);
WITH b AS (SELECT id FROM brands WHERE slug = 'arena-breakout-infinite'),
nf AS (
    INSERT INTO brand_faqs (id, brand_id, sort_order, active)
    SELECT gen_random_uuid(), b.id, v.so, true FROM b, (VALUES (90),(91)) AS v(so)
    RETURNING id, sort_order)
INSERT INTO brand_faq_translations (brand_faq_id, locale, question, answer)
SELECT nf.id, t.locale, t.question, t.answer FROM nf JOIN (VALUES
    (90,'ru',$q$Сколько стоят Bonds в Arena Breakout: Infinite в сумах?$q$,$a$Итог в сумах виден до оплаты и зависит от курса. Ориентир: 100 Bonds ≈ 14 200 сум, 500 ≈ 70 500, 1000 ≈ 137 000, 2500 ≈ 341 000, 5000 ≈ 680 000, 10 000 ≈ 1 357 000 сум. Это PC-версия. Комиссии сверху нет.$a$),
    (90,'en',$q$How much do Bonds cost in Arena Breakout: Infinite in sum?$q$,$a$The total in sum is shown before payment and depends on the rate. As a guide: 100 Bonds ≈ 14,200 sum, 500 ≈ 70,500, 1,000 ≈ 137,000, 2,500 ≈ 341,000, 5,000 ≈ 680,000, 10,000 ≈ 1,357,000 sum. This is the PC version. No extra commission.$a$),
    (90,'uz',$q$Arena Breakout: Infinite da Bonds soʻmda qancha turadi?$q$,$a$Soʻmdagi summa toʻlovdan oldin koʻrinadi va kursga bogʻliq. Taxminan: 100 Bonds ≈ 14 200 soʻm, 500 ≈ 70 500, 1000 ≈ 137 000, 2500 ≈ 341 000, 5000 ≈ 680 000, 10 000 ≈ 1 357 000 soʻm. Bu PC versiyasi. Ustiga komissiya yoʻq.$a$),
    (91,'ru',$q$Где найти UID (ПК-аккаунт) в Arena Breakout: Infinite?$q$,$a$UID можно найти двумя способами: в лаунчере игры (Account Center лаунчера Level Infinite) или в профиле внутри игры на ПК (запустите игру, нажмите на аватар и откройте профиль — UID на странице профиля). Это PC-версия: Bonds и пропуск зачисляются только на PC-аккаунт и не переносятся в мобильную Arena Breakout. Пароль передавать не нужно.$a$),
    (91,'en',$q$Where do I find my UID (PC account) in Arena Breakout: Infinite?$q$,$a$You can find the UID in two ways: in the game launcher (the Level Infinite launcher's Account Center) or in your in-game profile on PC (launch the game, click your avatar and open the profile — the UID is on the profile page). This is the PC version: Bonds and the pass are credited only to the PC account and do not carry over to mobile Arena Breakout. No password is needed.$a$),
    (91,'uz',$q$Arena Breakout: Infinite da UID (PC akkaunt) ni qayerdan topaman?$q$,$a$UID ni ikki usulda topish mumkin: oʻyin launcherida (Level Infinite launcherining Account Center boʻlimi) yoki PC dagi oʻyin ichidagi profilda (oʻyinni ishga tushiring, avatarni bosing va profilni oching — UID profil sahifasida). Bu PC versiyasi: Bonds va pass faqat PC akkauntga tushadi va mobil Arena Breakout ga oʻtmaydi. Parol kerak emas.$a$)
) AS t(sort_order, locale, question, answer) ON t.sort_order = nf.sort_order;

COMMIT;
