/**
 * P2P deposit admin feature — DTOs, fetch helpers and error mapping.
 *
 * Types mirror `apps/api/src/yupay/modules/p2p/schemas.py` (admin block).
 * The card number is write-only: the API returns only `pan_last4`, and the
 * UI sends `pan` solely when the operator types a new one. The journal list
 * has no `raw_text` (PII); only `GET /incoming/{id}` returns it.
 */

import adminRu from "@yupay/i18n/locales/ru/admin.json";

import { ApiError, apiGet, apiPatch, apiPost } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";

/** The feature's Russian string catalog (the admin SPA reads `ru`). */
export const T = adminRu.p2p;

const BASE = "/api/v1/admin/p2p";

export type P2PMode = "off" | "allowlist" | "all";
export type P2PNetwork = "humo" | "uzcard";

export interface P2PSettings {
  mode: P2PMode;
  allowlist_merchant_ids: string[];
  humo_bot_user_id: number | null;
  owner_telegram_user_id: number | null;
  /** Read-only: captured by the API when the owner connects the Business bot. */
  business_connection_id: string | null;
  updated_at: string;
}

export interface P2PSettingsPatch {
  mode?: P2PMode;
  allowlist_merchant_ids?: string[];
  humo_bot_user_id?: number | null;
  owner_telegram_user_id?: number | null;
}

export interface P2PCard {
  id: string;
  label: string;
  pan_last4: string;
  holder_name: string;
  network: string;
  active: boolean;
  min_amount_uzs: number;
  max_amount_uzs: number;
  daily_limit_uzs: number | null;
  matched_today_uzs: number;
  last_incoming_at: string | null;
  chain_ok_last: boolean | null;
}

/** Create/edit body; `pan` is present only when a new number was typed. */
export interface P2PCardInput {
  label: string;
  pan?: string;
  holder_name: string;
  network: P2PNetwork;
  min_amount_uzs: number;
  max_amount_uzs: number;
  daily_limit_uzs: number | null;
  active: boolean;
}

export interface P2PIncomingReservation {
  number: string;
  merchant_id: string | null;
  merchant_title: string | null;
  amount_usd: string;
}

export interface P2PIncoming {
  id: string;
  received_at: string;
  bank_time: string | null;
  kind: string;
  amount_uzs: string | null;
  source_text: string | null;
  card_last4: string | null;
  balance_after: string | null;
  chain_ok: boolean | null;
  result: string;
  reservation: P2PIncomingReservation | null;
}

export interface P2PIncomingDetail extends P2PIncoming {
  raw_text: string;
}

export interface P2PReservation {
  number: string;
  merchant_id: string | null;
  merchant_title: string | null;
  card_last4: string;
  amount_uzs: number;
  amount_usd: string;
  status: string;
  created_at: string;
  expires_at: string;
  closed_at: string | null;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface JournalFilters {
  card_last4: string;
  kind: string;
  result: string;
  amount: string;
}

/** Query string from the non-empty entries. */
function qs(params: Record<string, string | null | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v) sp.set(k, v);
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

const idem = (key: string) => ({ "Idempotency-Key": key });

export const fetchSettings = () => apiGet<P2PSettings>(`${BASE}/settings`);
export const saveSettings = (body: P2PSettingsPatch, key: string) =>
  apiPatch<P2PSettings>(`${BASE}/settings`, body, idem(key));

export const fetchCards = () => apiGet<P2PCard[]>(`${BASE}/cards`);
export const createCard = (body: P2PCardInput, key: string) =>
  apiPost<P2PCard>(`${BASE}/cards`, body, idem(key));
export const patchCard = (id: string, body: Partial<P2PCardInput>, key: string) =>
  apiPatch<P2PCard>(`${BASE}/cards/${id}`, body, idem(key));

export const fetchIncoming = (f: JournalFilters, cursor: string | null) =>
  apiGet<Page<P2PIncoming>>(`${BASE}/incoming${qs({ ...f, cursor })}`);
export const fetchIncomingDetail = (id: string) =>
  apiGet<P2PIncomingDetail>(`${BASE}/incoming/${id}`);
export const fetchReservations = (status: string, cursor: string | null) =>
  apiGet<Page<P2PReservation>>(`${BASE}/reservations${qs({ status, cursor })}`);

/** Readable Russian message: a catalog entry for known `code`s, else the server's text. */
export function p2pErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const code = (err.body as { code?: unknown } | null)?.code;
    if (typeof code === "string" && code in T.errors) {
      return T.errors[code as keyof typeof T.errors];
    }
  }
  return extractApiMessage(err);
}

/** Whole-number grouping for UZS (string-safe: amounts may arrive as Decimal strings). */
export function formatUzs(value: number | string | null): string {
  if (value === null) return "—";
  const [int = "", frac] = String(value).split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return frac && /[1-9]/.test(frac) ? `${grouped},${frac}` : grouped;
}

/** Relative time in Russian ("5 мин. назад"). */
export function relativeTime(iso: string, now: number = Date.now()): string {
  const diffSec = Math.round((new Date(iso).getTime() - now) / 1000);
  const rtf = new Intl.RelativeTimeFormat("ru", { numeric: "auto" });
  const abs = Math.abs(diffSec);
  if (abs < 60) return rtf.format(diffSec, "second");
  if (abs < 3600) return rtf.format(Math.round(diffSec / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diffSec / 3600), "hour");
  return rtf.format(Math.round(diffSec / 86400), "day");
}

/** Absolute local date-time for table cells. */
export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("ru", { dateStyle: "short", timeStyle: "short" }).format(
    new Date(iso),
  );
}

/** Catalog label for a server enum value, falling back to the raw value if unknown. */
export function labelOf(map: object, key: string): string {
  // Server enums can outgrow the catalog; the cast widens the typed map for lookup only.
  return (map as Record<string, string | undefined>)[key] ?? key;
}
