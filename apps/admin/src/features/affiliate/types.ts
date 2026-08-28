/** Mirrors the backend's admin affiliate schemas. */

export interface PartnerOut {
  id: string;
  email: string;
  display_name: string | null;
  contact: string | null;
  channel: string | null;
  status: string;
  admin_note: string | null;
  created_at: string;
  approved_at: string | null;
}

export interface PartnerListOut {
  items: PartnerOut[];
}

export interface CodeOut {
  id: string;
  code: string;
  discount_percent: string;
  commission_percent: string;
  active: boolean;
  created_at: string;
}

/**
 * The queue view. Carries `card_last4` and deliberately **not** the full
 * number — that lives on `PayoutDetailOut`, fetched only when an admin opens
 * one to make the transfer.
 */
export interface PayoutOut {
  id: string;
  partner_id: string;
  partner_email: string;
  amount: string;
  currency: string;
  card_last4: string;
  card_holder: string;
  status: string;
  admin_note: string | null;
  created_at: string;
  processed_at: string | null;
}

export interface PayoutListOut {
  items: PayoutOut[];
}

/** The only shape anywhere carrying an unmasked card. */
export interface PayoutDetailOut extends PayoutOut {
  card_number: string;
}

/** The ranges the backend enforces, shown to an admin before they type. */
export const DISCOUNT_RANGE = { min: 3, max: 10 } as const;
export const COMMISSION_RANGE = { min: 1, max: 2 } as const;

export function fmtDate(iso: string): string {
  return new Intl.DateTimeFormat("ru", { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(iso),
  );
}
