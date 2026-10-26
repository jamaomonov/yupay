/**
 * Guest order history, persisted client-side only. The server has no notion
 * of "a guest's orders" (there's no account to list against), so the browser
 * remembers which orders a guest paid for in this browser, keyed by email at
 * save time. Used to render a guest order list (see OrderStatus's caller).
 */
const KEY = "yupay.web.guest_orders";
const CAP = 50;

export interface GuestOrder {
  orderId: string;
  email: string;
  brandSlug: string;
  brandName: string;
  createdAt: string; // ISO
}

export function listGuestOrders(): GuestOrder[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    const arr = raw ? (JSON.parse(raw) as GuestOrder[]) : [];
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

export function saveGuestOrder(entry: GuestOrder): void {
  if (typeof window === "undefined") return;
  const existing = listGuestOrders().filter((o) => o.orderId !== entry.orderId);
  const next = [entry, ...existing].slice(0, CAP);
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* storage blocked — ignore */
  }
}

export function removeGuestOrders(orderIds: string[]): void {
  if (typeof window === "undefined") return;
  const drop = new Set(orderIds);
  const next = listGuestOrders().filter((o) => !drop.has(o.orderId));
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* ignore */
  }
}

/** Which email a guest order belongs to, by order id.
 *
 * The order page used to learn it from `?email=` in its own URL, which put the
 * address in every SPA navigation an analytics tag could report and in the
 * edge access log. Checkout now records it here and links to the bare
 * `/orders/{id}`. Separate from {@link saveGuestOrder}: that entry needs brand
 * data checkout does not always have, and this one must always exist. */
const EMAIL_KEY = "yupay.web.guest_order_emails";

function readEmails(): Record<string, string> {
  try {
    const raw = window.localStorage.getItem(EMAIL_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    return parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)
      ? // A JSON object we wrote ourselves; values are checked on read below.
        (parsed as Record<string, string>)
      : {};
  } catch {
    return {};
  }
}

export function rememberGuestEmail(orderId: string, email: string): void {
  if (typeof window === "undefined") return;
  const entries = Object.entries(readEmails()).filter(([id]) => id !== orderId);
  const first: [string, string] = [orderId, email];
  const kept = [first, ...entries].slice(0, CAP);
  const next = Object.fromEntries(kept);
  try {
    window.localStorage.setItem(EMAIL_KEY, JSON.stringify(next));
  } catch {
    /* storage blocked — the order page then asks the guest to sign in */
  }
}

/** The email this browser placed `orderId` with, or `null`. */
export function guestEmailFor(orderId: string): string | null {
  if (typeof window === "undefined") return null;
  const stored = readEmails()[orderId];
  if (typeof stored === "string" && stored !== "") return stored;
  return listGuestOrders().find((o) => o.orderId === orderId)?.email ?? null;
}

const LAST_EMAIL_KEY = "yupay.checkout.email";

/** Remember the address a checkout went out with, so the next one starts filled
 *  in. This browser only; a blocked storage just means typing it again. */
export function rememberCheckoutEmail(email: string): void {
  if (typeof window === "undefined" || email === "") return;
  try {
    window.localStorage.setItem(LAST_EMAIL_KEY, email);
  } catch {
    /* storage blocked */
  }
}

/** The address the last checkout in this browser used, or `""`. */
export function lastCheckoutEmail(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(LAST_EMAIL_KEY) ?? "";
  } catch {
    return "";
  }
}
