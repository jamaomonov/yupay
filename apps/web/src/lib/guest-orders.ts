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
