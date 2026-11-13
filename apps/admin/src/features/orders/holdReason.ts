/**
 * Why an order was held, in the operator's words. Keys are the reason codes
 * `orders/risk.py` writes on the `order.held_for_review` event; the alert in
 * Telegram words the same codes in `HOLD_ALERT_TEXT`. Until 2026-11-13 the
 * banner said «сумма не ниже порога» whatever the reason, which sent the
 * owner looking at the amount of a $8 order held for a shared IP.
 */
const HOLD_REASON_TEXT: Record<string, string> = {
  amount_at_or_above_threshold: "Сумма заказа не ниже порога ручной проверки.",
  liquid_amount_at_or_above_threshold:
    "Stars/Roblox/Steam на сумму выше порога для ликвидных товаров.",
  identity_rolling_sum_exceeded:
    "Сумма связанных заказов (тот же покупатель, IP, устройство или получатель) за сутки или неделю превысила лимит.",
  identity_velocity_exceeded:
    "Слишком много оплаченных заказов одного покупателя (или IP, устройства, получателя) за сутки.",
  identity_shared_across_buyers:
    "С одного IP или устройства за неделю платили несколько разных покупателей. У мобильных операторов один IP бывает у многих абонентов — посмотрите остальные заказы группы.",
  guest_liquid_brand_foreign_timezone:
    "Гость покупает Stars/Roblox/Steam, а часовой пояс браузера не из наших стран.",
  new_buyer_over_limits: "Новый покупатель превысил стартовые лимиты на сутки.",
  account_purchase_limit_exceeded: "Аккаунт превысил лимит покупок, заданный в карточке клиента.",
  provider_limit_exceeded: "Покупатель превысил лимит этой кассы за период.",
};

/** The banner's «why» sentence; an unknown code still names itself. */
export function holdReasonText(reason: string): string {
  return HOLD_REASON_TEXT[reason] ?? (reason ? `Причина: ${reason}.` : "Причина не записана.");
}
