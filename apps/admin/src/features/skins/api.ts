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
  /** Our key on Waxpeer — what their dashboard is searched by. */
  project_id: string;
  waxpeer_id: number | null;
  order_id: string;
  order_item_id: string;
  created_at: string;
  market_hash_name: string;
  phase: string;
  image_url: string | null;
  /** What the customer paid for the line, USD decimal string. */
  sold_usd: string;
  paid_units: number;
  bought_units: number | null;
  waxpeer_status: number | null;
  state: SkinTradeState;
  reason_code: "not_accepted" | "sold_out" | "try_later" | "support" | "other" | null;
  reason: string | null;
  /** Waxpeer's own penalty object, passed through. */
  penalties: unknown;
  seller_name: string | null;
  trade_id: string | null;
  offer_url: string | null;
  send_until: string | null;
  release_date: string | null;
  accepted_at: string | null;
  last_checked_at: string | null;
  task_id: string | null;
  task_status: string | null;
  task_sub_state: "buy_pending" | "buy_unconfirmed" | null;
  /** Where the order's money went back, if it did. */
  refunded_to: "wallet" | "card" | null;
  /** The money is still ours and the line has settled: «Вернуть деньги». */
  can_refund: boolean;
  /** The task failed and nothing was refunded: «Повторить» (the fulfilment retry). */
  can_retry: boolean;
  /** An operator marked it settled; it has left «needs attention». */
  resolved_at: string | null;
  resolved_note: string | null;
  attention: boolean;
}

export interface AdminSkinTradesOut {
  items: AdminSkinTradeOut[];
  total: number;
  /** Tab badges: in flight, needing a human (search ignored). */
  counts: { active: number; attention: number };
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

/** Mark a trade settled by a human, with what was done (idempotent server-side too). */
export function resolveTrade(id: string, note: string): Promise<AdminSkinTradeOut> {
  return apiPost<AdminSkinTradeOut>(
    `/api/v1/admin/skins/trades/${encodeURIComponent(id)}/resolve`,
    { note },
    { "Idempotency-Key": `skin-resolve-${id}-${crypto.randomUUID()}` },
  );
}

/** Refund the trade's order to the buyer's YuPay balance (refused while the skin travels). */
export function refundTrade(id: string): Promise<AdminSkinTradeOut> {
  return apiPost<AdminSkinTradeOut>(
    `/api/v1/admin/skins/trades/${encodeURIComponent(id)}/refund`,
    {},
    { "Idempotency-Key": `skin-refund-${id}-${crypto.randomUUID()}` },
  );
}

/** Re-run the trade's failed fulfilment task (the fulfilment retry). */
export function retryTask(taskId: string): Promise<unknown> {
  return apiPost<unknown>(
    `/api/v1/admin/fulfillment/tasks/${encodeURIComponent(taskId)}/retry`,
    {},
    { "Idempotency-Key": `skin-retry-${taskId}-${crypto.randomUUID()}` },
  );
}

/** A USD decimal string as "$12.30". */
export function usd(amount: string | number): string {
  const n = Number(amount);
  return `${n < 0 ? "−" : ""}$${Math.abs(n).toFixed(2)}`;
}

/** What we paid Waxpeer, in USD (the actual charge when known, else the quote). */
export function boughtUsd(t: AdminSkinTradeOut): number {
  return (t.bought_units ?? t.paid_units) / 1000;
}

/** "$3.00 (10%)": what the customer paid minus what Waxpeer charged. */
export function marginText(t: AdminSkinTradeOut): string {
  const sold = Number(t.sold_usd);
  const margin = sold - boughtUsd(t);
  const percent = sold > 0 ? Math.round((margin / sold) * 100) : 0;
  return fill(T.trades.marginValue, { amount: usd(margin), percent: `${String(percent)}%` });
}

/** "29.09 14:23" — short enough not to wrap in a table cell. */
export function shortWhen(iso: string): string {
  const d = new Date(iso);
  const day = new Intl.DateTimeFormat("ru", { day: "2-digit", month: "2-digit" }).format(d);
  const time = new Intl.DateTimeFormat("ru", { hour: "2-digit", minute: "2-digit" }).format(d);
  return `${day} ${time}`;
}

const REASON_KEYS = new Set(["buy_unconfirmed", "ambiguous_trade"]);

/** Why, in the operator's words: our reason names, never Waxpeer's raw text alone. */
export function reasonText(t: AdminSkinTradeOut): string | null {
  const R = T.trades.reasons;
  const penalty = penaltyTotal(t.penalties);
  const parts: string[] = [];
  if (t.task_sub_state) parts.push(R[t.task_sub_state]);
  else if (t.waxpeer_status === 6 && penalty) parts.push(R.rollback);
  else if (t.reason && REASON_KEYS.has(t.reason)) {
    parts.push(R[t.reason as "buy_unconfirmed" | "ambiguous_trade"]); // narrowed by the set
  } else if (t.state === "failed" && t.reason_code === "not_accepted") parts.push(R.not_accepted);
  else if (t.state === "failed" && t.reason_code === "sold_out") parts.push(R.sold_out);
  else if (t.state === "failed" && t.reason_code === "try_later") parts.push(R.low_balance);
  else if (t.reason) parts.push(t.reason);
  if (penalty) parts.push(fill(T.trades.penaltyUsd, { amount: usd(Number(penalty) / 1000) }));
  return parts.length > 0 ? parts.join(" · ") : null;
}
