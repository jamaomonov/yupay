/**
 * CS2 skins admin — DTOs and fetch helpers for the trades and pricing screens.
 *
 * Types mirror `apps/api/src/yupay/modules/skins/{admin_trades,schemas}.py` (see
 * `docs/api/openapi.json`), the admin SPA's thin hand-written DTO layer. Waxpeer
 * amounts are integer units (1 unit = $0.001); `unitsToUsd` turns them into the
 * dollars an operator reads. Strings live in `@yupay/i18n/locales/*\/admin.json`
 * under `skins`; the admin SPA reads the `ru` catalog.
 */

import adminRu from "@yupay/i18n/locales/ru/admin.json";

import { apiGet, apiPost } from "@/lib/api";

export const T = adminRu.skins;

/** `{placeholder}` interpolation for catalog strings. */
export function fill(template: string, vars: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) => vars[key] ?? match);
}

export type SkinTradeState = "buying" | "offer_sent" | "accepted" | "released" | "failed";
export type TradesView = "all" | "active" | "attention";

export interface AdminSkinTradeOut {
  id: string;
  order_id: string;
  order_item_id: string;
  created_at: string;
  market_hash_name: string;
  phase: string;
  paid_units: number;
  bought_units: number | null;
  waxpeer_status: number | null;
  state: SkinTradeState;
  reason_code: "not_accepted" | "sold_out" | "support" | "other" | null;
  reason: string | null;
  /** Waxpeer's own penalty object, passed through. */
  penalties: unknown;
  seller_name: string | null;
  trade_id: string | null;
  send_until: string | null;
  release_date: string | null;
  accepted_at: string | null;
  last_checked_at: string | null;
  task_status: string | null;
  task_sub_state: "buy_pending" | "buy_unconfirmed" | null;
  /** An operator marked it settled; it has left «needs attention». */
  resolved_at: string | null;
  attention: boolean;
}

export interface AdminSkinTradesOut {
  items: AdminSkinTradeOut[];
  total: number;
}

export const TRADES_PAGE_SIZE = 50;

export function fetchTrades(
  view: TradesView,
  q: string,
  offset: number,
): Promise<AdminSkinTradesOut> {
  const params = new URLSearchParams({
    view,
    limit: String(TRADES_PAGE_SIZE),
    offset: String(offset),
  });
  if (q.trim()) params.set("q", q.trim());
  return apiGet<AdminSkinTradesOut>(`/api/v1/admin/skins/trades?${params.toString()}`);
}

/** Waxpeer units (1 = $0.001) as dollars, two decimals, without floats' drift. */
export function unitsToUsd(units: number): string {
  const cents = Math.round(units / 10);
  return `$${String(Math.floor(cents / 100))}.${String(cents % 100).padStart(2, "0")}`;
}

/** The total of Waxpeer's penalty object, when it names one. */
export function penaltyTotal(penalties: unknown): string | null {
  if (!penalties || typeof penalties !== "object") return null;
  const total = (penalties as Record<string, unknown>).total_penalty; // Waxpeer JSON, narrowed
  return typeof total === "number" || typeof total === "string" ? String(total) : null;
}

/** Mark a trade settled by a human (idempotent server-side too). */
export function resolveTrade(id: string): Promise<AdminSkinTradeOut> {
  return apiPost<AdminSkinTradeOut>(
    `/api/v1/admin/skins/trades/${encodeURIComponent(id)}/resolve`,
    {},
    { "Idempotency-Key": `skin-resolve-${id}-${crypto.randomUUID()}` },
  );
}
