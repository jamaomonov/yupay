/** The panel's reads, in one place, so no page invents its own shape. */

import { useQuery } from "@tanstack/react-query";

import { api } from "./api";

export interface Balance {
  currency: string;
  available: string;
  held: string;
  reserved: string;
}

export interface Stats {
  period: string;
  since: string;
  earned: string;
  orders: number;
  activations: number;
}

export interface Code {
  id: string;
  code: string;
  discount_percent: string;
  commission_percent: string;
  active: boolean;
  created_at: string;
}

export interface Profile {
  id: string;
  email: string;
  display_name: string | null;
  status: string;
  codes: Code[];
}

export interface Commission {
  id: string;
  order_id: string;
  base_amount: string;
  percent: string;
  amount: string;
  currency: string;
  status: string;
  available_at: string;
  created_at: string;
}

export interface Payout {
  id: string;
  amount: string;
  currency: string;
  card_last4: string;
  card_holder: string;
  status: string;
  admin_note: string | null;
  created_at: string;
  processed_at: string | null;
}

export type Period = "day" | "week" | "month" | "year";

export function useBalance() {
  return useQuery({
    queryKey: ["balance"],
    queryFn: () => api<Balance>("/api/v1/affiliate/balance"),
  });
}

export function useStats(period: Period) {
  return useQuery({
    queryKey: ["stats", period],
    queryFn: () => api<Stats>(`/api/v1/affiliate/stats?period=${period}`),
  });
}

export function useProfile() {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => api<Profile>("/api/v1/affiliate/me"),
  });
}

export function useCommissions() {
  return useQuery({
    queryKey: ["commissions"],
    queryFn: () => api<{ items: Commission[]; total: number }>("/api/v1/affiliate/commissions"),
  });
}

export function usePayouts() {
  return useQuery({
    queryKey: ["payouts"],
    queryFn: () => api<{ items: Payout[] }>("/api/v1/affiliate/payouts"),
  });
}
