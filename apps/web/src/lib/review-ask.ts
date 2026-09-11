/** Session-local "don't ask about this order again" for the catch-up prompt. */

const PREFIX = "yupay.reviewAsk.dismissed.";

export function dismissReviewAsk(orderId: string): void {
  try {
    window.localStorage.setItem(`${PREFIX}${orderId}`, "1");
  } catch {
    /* storage blocked */
  }
}

export function isReviewAskDismissed(orderId: string): boolean {
  try {
    return window.localStorage.getItem(`${PREFIX}${orderId}`) === "1";
  } catch {
    return false;
  }
}
