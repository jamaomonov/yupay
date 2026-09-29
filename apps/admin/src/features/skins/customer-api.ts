/**
 * A customer's Steam side — the DTO of `GET /admin/skins/customers/{id}`
 * (`apps/api/src/yupay/modules/skins/admin_reports.py`). Accounts only: a trade link's
 * token is a credential and never leaves the API.
 */

import type { AdminSkinTradeOut } from "./api";

import { apiGet } from "@/lib/api";

export interface SteamAccount {
  steam_id: string;
  profile_url: string;
}

export interface CustomerSkinsOut {
  saved: (SteamAccount & { updated_at: string }) | null;
  accounts: (SteamAccount & { orders: number })[];
  trades: AdminSkinTradeOut[];
}

export function fetchCustomerSkins(userId: string): Promise<CustomerSkinsOut> {
  return apiGet<CustomerSkinsOut>(`/api/v1/admin/skins/customers/${encodeURIComponent(userId)}`);
}
