export type AccountKind =
  | "user_wallet"
  | "user_cashback"
  | "user_promo_credit"
  | "house_revenue"
  | "house_cogs"
  | "house_promo_expense"
  | "house_refunds"
  | "house_fx_pnl"
  | "provider_clearing";

export interface AccountWithBalance {
  id: string;
  owner_type: "user" | "house" | "provider";
  owner_id: string;
  kind: AccountKind;
  currency: string;
  status: "active" | "frozen";
  balance: string;
}

export interface Posting {
  id: string;
  account_id: string;
  direction: "D" | "C";
  amount: string;
  currency: string;
  created_at: string;
}

export interface Transaction {
  id: string;
  kind: string;
  reference_type: string | null;
  reference_id: string | null;
  actor: string | null;
  extra_metadata: Record<string, unknown>;
  created_at: string;
  postings: Posting[];
}

export interface AdminUserLedgerOut {
  user_id: string;
  accounts: AccountWithBalance[];
  recent_transactions: Transaction[];
}

export interface AdjustmentsListOut {
  items: Transaction[];
}
