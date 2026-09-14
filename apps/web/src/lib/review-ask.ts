/** "Not now" for the catch-up prompt — a snooze with an expiry, not a tombstone. */

import { isReviewSnoozeActive, reviewSnoozeValue } from "@yupay/utils";

const PREFIX = "yupay.reviewAsk.dismissed.";

export function dismissReviewAsk(orderId: string): void {
  try {
    window.localStorage.setItem(`${PREFIX}${orderId}`, reviewSnoozeValue(Date.now()));
  } catch {
    /* storage blocked */
  }
}

/** Snoozed, not buried — see `isReviewSnoozeActive` for why it expires. */
export function isReviewAskDismissed(orderId: string): boolean {
  try {
    return isReviewSnoozeActive(window.localStorage.getItem(`${PREFIX}${orderId}`), Date.now());
  } catch {
    return false;
  }
}
