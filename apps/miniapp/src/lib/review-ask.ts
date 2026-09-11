/** Catch-up review prompt helpers. Pure so they can be tested without jsdom. */

const DISMISS_PREFIX = "yupay.reviewAsk.dismissed.";
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function dismissReviewAsk(orderId: string): void {
  try {
    window.localStorage.setItem(`${DISMISS_PREFIX}${orderId}`, "1");
  } catch {
    /* storage blocked */
  }
}

export function isReviewAskDismissed(orderId: string): boolean {
  try {
    return window.localStorage.getItem(`${DISMISS_PREFIX}${orderId}`) === "1";
  } catch {
    return false;
  }
}

/** Home and history are calm enough to ask; checkout paths are not. */
export function catchUpAllowedOn(path: string): boolean {
  return path === "/" || path === "/history";
}

/**
 * Order id from a Mini App launch (`?review=` on the web_app URL, or Telegram
 * `start_param` of `review_<uuid>` / a bare uuid).
 */
export function parseReviewLaunchParam(
  search: string,
  startParam: string | undefined,
): string | null {
  const q = search.startsWith("?") ? search.slice(1) : search;
  const fromQuery = new URLSearchParams(q).get("review");
  const raw = fromQuery ?? startParam ?? "";
  if (!raw) return null;
  const id = raw.startsWith("review_") ? raw.slice("review_".length) : raw;
  return UUID_RE.test(id) ? id : null;
}
