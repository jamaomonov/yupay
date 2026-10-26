# Refunding a delivered order to the card

For when the goods did not really reach the customer — a promo code that does not
activate, currency the supplier reported as credited that never arrived — and the
money should go back to the card, not to the YuPay balance and not by a manual
transfer (risky, and the transfer costs a fee).

Open the order in admin → **Платежи** card. What you see depends on the provider.

## Paynet, Payme, Uzum

Their cabinet cancel reaches us, and we refuse it once the goods shipped
(Paynet `306`, Payme `-31007`, Uzum `10017`).

1. **«Разрешить возврат через …»** → type why the goods did not arrive.
2. Cancel the transaction in that provider's cabinet.
3. The order turns «Возвращён», the payment `refunded`, the ledger reversed.

Step 1 moves no money; it only lets step 2 through for this one payment. The
card note then reads «Возврат разрешён — оформите отмену в кабинете …».

## Click

Click never tells us about a refund made in its cabinet.

1. Refund in Click's cabinet first; note the refund's number.
2. **«Отметить возврат, сделанный в Click»** → the number, then the reason.
3. The order turns «Возвращён» and the ledger is reversed.

Refused while a supplier or a CS2 skin trade is still working on the order —
wait for the task to finish or fail.

## Not covered

- A payment already refunded to the YuPay balance is never refunded to the card
  as well — every path refuses it.
- The supplier is not asked for its money back by any of this; that stays a
  conversation with the supplier.
