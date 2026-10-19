/**
 * Orders placed on this phone without an account, kept on the phone: the email they were placed
 * under is what lets the API show them again. SecureStore, because the email is personal data.
 */
import { readPref, writePref } from "@/lib/prefs";

export interface GuestOrder {
  id: string;
  email: string;
  brand: string;
  brandSlug: string;
  label: string;
  /** ISO 8601. */
  at: string;
}

const KEY = "guest_orders";
const EMAIL_KEY = "checkout_email";
/** SecureStore warns past 2 KB a value; a dozen records stay under it. */
const LIMIT = 12;

function parse(raw: string | null): GuestOrder[] {
  if (raw === null) return [];
  try {
    const value: unknown = JSON.parse(raw);
    return Array.isArray(value) ? (value as GuestOrder[]) : [];
  } catch {
    return [];
  }
}

export async function readGuestOrders(): Promise<GuestOrder[]> {
  return parse(await readPref(KEY));
}

export async function saveGuestOrder(order: GuestOrder): Promise<void> {
  const rest = (await readGuestOrders()).filter((item) => item.id !== order.id);
  await writePref(KEY, JSON.stringify([order, ...rest].slice(0, LIMIT)));
  await writePref(EMAIL_KEY, order.email);
}

export async function findGuestOrder(id: string): Promise<GuestOrder | null> {
  return (await readGuestOrders()).find((item) => item.id === id) ?? null;
}

/** The last email paid with, to fill the field next time. */
export function readCheckoutEmail(): Promise<string | null> {
  return readPref(EMAIL_KEY);
}
