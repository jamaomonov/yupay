/**
 * "Not now" for the catch-up review prompt — a snooze, not a tombstone.
 *
 * It used to write a bare `"1"` that never expired, so one tap on a
 * full-screen backdrop ended the conversation about that order permanently.
 * That is a lot of weight for a mis-tap, and the prompt is the only thing that
 * reaches somebody who left without rating.
 *
 * Seven days, against the 14-day ceiling on asking about an order at all
 * (`PENDING_ASK_MAX_AGE`), means at most a second ask — declining twice is an
 * answer, and the order ages out on its own either way.
 */
export const REVIEW_SNOOZE_MS = 7 * 24 * 60 * 60 * 1000;

/** What to store when the prompt is declined. */
export function reviewSnoozeValue(nowMs: number): string {
  return String(nowMs);
}

/**
 * Whether a stored snooze is still holding.
 *
 * A legacy `"1"` — written by the version that never expired — reads as
 * lapsed: it carries no clock, and the alternative is honouring a dismissal of
 * unknown age forever. The blast radius is one extra prompt for orders still
 * inside the 14-day window.
 */
export function isReviewSnoozeActive(raw: string | null, nowMs: number): boolean {
  if (raw === null) return false;
  const at = Number(raw);
  if (!Number.isFinite(at) || at <= 1) return false;
  return nowMs - at < REVIEW_SNOOZE_MS;
}
