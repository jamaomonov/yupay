/**
 * Order-scoped code access kept by the browser that placed a guest order.
 *
 * `POST /orders` hands a guest the same `guest_order` token the delivered email
 * carries (ADR-0096). Keeping it here lets this browser show the codes even when
 * the email never arrives — a mistyped address bounces, and the buyer was left
 * with a paid order and nothing to open (01A102A2). The token unlocks one order
 * and expires server-side after 7 days; the email link stays the way back from
 * any other device.
 */
const KEY = "yupay.web.order_access";
const CAP = 50;

type Store = Record<string, string>;

function read(): Store {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const out: Store = {};
    for (const [id, token] of Object.entries(parsed)) {
      if (typeof token === "string") out[id] = token;
    }
    return out;
  } catch {
    return {};
  }
}

/** Remember the access token for `orderId`. Newest first, capped. */
export function saveOrderAccess(orderId: string, token: string): void {
  if (typeof window === "undefined") return;
  const rest = Object.entries(read()).filter(([id]) => id !== orderId);
  const entries: [string, string][] = [[orderId, token], ...rest];
  const next: Store = Object.fromEntries(entries.slice(0, CAP));
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* storage blocked — the email link still works */
  }
}

/** The stored access token for `orderId`, or `null`. */
export function getOrderAccess(orderId: string): string | null {
  return read()[orderId] ?? null;
}
