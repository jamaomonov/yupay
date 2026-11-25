-- FAQ answers: the owner's payment wording instead of «no fee» claims (2026-11-25).
--
-- Older seeds wrote «Комиссии сверху нет», «без скрытых комиссий», «комиссия
-- сервиса 0%» (and the en/uz equivalents) into 35 FAQ answers on 13 brands. The
-- owner's rule: never claim "no fee" — say the total in so'm is shown before
-- paying and exactly that is charged. Each sentence is replaced on its own; the
-- facts next to it (automatic delivery, «сколько вводите, столько зачисляется»)
-- stay. Brand descriptions are NOT touched here (Steam, PUBG Mobile, Steam
-- Gifts carry the same claim in their page copy — the owner's call).
-- Idempotent.
BEGIN;
UPDATE brand_faq_translations SET answer = replace(answer, $c$Комиссии сверху нет — сколько вводите, столько и зачисляется на кошелёк Steam.$c$, $c$Сколько вводите, столько и зачисляется на кошелёк Steam.$c$)
 WHERE locale = 'ru' AND position($c$Комиссии сверху нет — сколько вводите, столько и зачисляется на кошелёк Steam.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$Комиссии сверху нет, итог виден до подтверждения.$c$, $c$Итог в сумах виден до оплаты, и списывается ровно он.$c$)
 WHERE locale = 'ru' AND position($c$Комиссии сверху нет, итог виден до подтверждения.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$Сумма к оплате в сумах показывается до подтверждения, дополнительной комиссии сверху нет.$c$, $c$Итог в сумах виден до оплаты, и списывается ровно он.$c$)
 WHERE locale = 'ru' AND position($c$Сумма к оплате в сумах показывается до подтверждения, дополнительной комиссии сверху нет.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$Итоговая сумма в сумах и курс показываются до оплаты, скрытых комиссий нет.$c$, $c$Итоговая сумма в сумах и курс видны до оплаты, и списывается ровно эта сумма.$c$)
 WHERE locale = 'ru' AND position($c$Итоговая сумма в сумах и курс показываются до оплаты, скрытых комиссий нет.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$Сумма в сумах видна до оплаты, комиссии сверху нет.$c$, $c$Итог в сумах виден до оплаты, и списывается ровно он.$c$)
 WHERE locale = 'ru' AND position($c$Сумма в сумах видна до оплаты, комиссии сверху нет.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$Комиссия сервиса 0%, зачисление автоматическое за 1–5 минут.$c$, $c$Зачисление автоматическое за 1–5 минут.$c$)
 WHERE locale = 'ru' AND position($c$Комиссия сервиса 0%, зачисление автоматическое за 1–5 минут.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$Сервисной комиссии поверх суммы пополнения нет — 0%.$c$, $c$Итог в сумах виден до оплаты, и списывается ровно он.$c$)
 WHERE locale = 'ru' AND position($c$Сервисной комиссии поверх суммы пополнения нет — 0%.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$Мы покупаем и перепродаём пополнения по прозрачному курсу, без скрытых комиссий.$c$, $c$Итог в сумах виден до оплаты, и списывается ровно он.$c$)
 WHERE locale = 'ru' AND position($c$Мы покупаем и перепродаём пополнения по прозрачному курсу, без скрытых комиссий.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$Комиссии сверху нет.$c$, $c$Итог в сумах виден до оплаты, и списывается ровно он.$c$)
 WHERE locale = 'ru' AND position($c$Комиссии сверху нет.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$The total in sum is shown before you confirm, with no extra fee on top.$c$, $c$The total in soʻm is shown before you pay, and exactly that is charged.$c$)
 WHERE locale = 'en' AND position($c$The total in sum is shown before you confirm, with no extra fee on top.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$The total in UZS and the rate are shown before you pay, with no hidden fees.$c$, $c$The total in UZS and the rate are shown before you pay, and exactly that total is charged.$c$)
 WHERE locale = 'en' AND position($c$The total in UZS and the rate are shown before you pay, with no hidden fees.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$The total in soʻm is shown before you pay, with no extra fee.$c$, $c$The total in soʻm is shown before you pay, and exactly that is charged.$c$)
 WHERE locale = 'en' AND position($c$The total in soʻm is shown before you pay, with no extra fee.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$We buy and resell top-ups at a transparent rate, with no hidden fees.$c$, $c$The total in soʻm is shown before you pay, and exactly that is charged.$c$)
 WHERE locale = 'en' AND position($c$We buy and resell top-ups at a transparent rate, with no hidden fees.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$Our margin is in the conversion rate, not a separate fee, so you see the final amount to pay in advance.$c$, $c$The total in soʻm is shown before you pay, and exactly that is charged.$c$)
 WHERE locale = 'en' AND position($c$Our margin is in the conversion rate, not a separate fee, so you see the final amount to pay in advance.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$Ustiga komissiya yoʻq — qancha kiritsangiz, shuncha Steam hamyoniga tushadi.$c$, $c$Qancha kiritsangiz, shuncha Steam hamyoniga tushadi.$c$)
 WHERE locale = 'uz' AND position($c$Ustiga komissiya yoʻq — qancha kiritsangiz, shuncha Steam hamyoniga tushadi.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$Ustiga komissiya yoʻq, yakuniy summa tasdiqlashdan oldin koʻrinadi.$c$, $c$Yakuniy summa soʻmda toʻlovdan oldin koʻrinadi va aynan u yechiladi.$c$)
 WHERE locale = 'uz' AND position($c$Ustiga komissiya yoʻq, yakuniy summa tasdiqlashdan oldin koʻrinadi.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$Soʻmdagi summa tasdiqlashdan oldin koʻrsatiladi, ustiga qoʻshimcha komissiya yoʻq.$c$, $c$Yakuniy summa soʻmda toʻlovdan oldin koʻrinadi va aynan u yechiladi.$c$)
 WHERE locale = 'uz' AND position($c$Soʻmdagi summa tasdiqlashdan oldin koʻrsatiladi, ustiga qoʻshimcha komissiya yoʻq.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$Soʻmdagi yakuniy summa va kurs toʻlovdan oldin koʻrsatiladi, yashirin komissiya yoʻq.$c$, $c$Soʻmdagi yakuniy summa va kurs toʻlovdan oldin koʻrsatiladi va aynan shu summa yechiladi.$c$)
 WHERE locale = 'uz' AND position($c$Soʻmdagi yakuniy summa va kurs toʻlovdan oldin koʻrsatiladi, yashirin komissiya yoʻq.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$Xizmat komissiyasi 0%, UC 1–5 daqiqada avtomatik tushadi.$c$, $c$UC 1–5 daqiqada avtomatik tushadi.$c$)
 WHERE locale = 'uz' AND position($c$Xizmat komissiyasi 0%, UC 1–5 daqiqada avtomatik tushadi.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$Soʻmdagi summa toʻlovdan oldin koʻrinadi, ustiga komissiya yoʻq.$c$, $c$Yakuniy summa soʻmda toʻlovdan oldin koʻrinadi va aynan u yechiladi.$c$)
 WHERE locale = 'uz' AND position($c$Soʻmdagi summa toʻlovdan oldin koʻrinadi, ustiga komissiya yoʻq.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$Toʻldirish summasi ustiga xizmat komissiyasi yoʻq — 0%.$c$, $c$Yakuniy summa soʻmda toʻlovdan oldin koʻrinadi va aynan u yechiladi.$c$)
 WHERE locale = 'uz' AND position($c$Toʻldirish summasi ustiga xizmat komissiyasi yoʻq — 0%.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$Biz toʻldirishlarni shaffof kurs boʻyicha sotib olib, qayta sotamiz, yashirin komissiyalarsiz.$c$, $c$Yakuniy summa soʻmda toʻlovdan oldin koʻrinadi va aynan u yechiladi.$c$)
 WHERE locale = 'uz' AND position($c$Biz toʻldirishlarni shaffof kurs boʻyicha sotib olib, qayta sotamiz, yashirin komissiyalarsiz.$c$ in answer) > 0;
UPDATE brand_faq_translations SET answer = replace(answer, $c$Ustiga komissiya yoʻq.$c$, $c$Yakuniy summa soʻmda toʻlovdan oldin koʻrinadi va aynan u yechiladi.$c$)
 WHERE locale = 'uz' AND position($c$Ustiga komissiya yoʻq.$c$ in answer) > 0;

SELECT count(*) AS fee_claims_left FROM brand_faq_translations
 WHERE answer ~* '(комисси|\yfee|komissiya)';

COMMIT;
