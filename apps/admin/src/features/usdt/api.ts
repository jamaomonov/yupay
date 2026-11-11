/**
 * USDT deposit admin feature (TRC20 / BEP20 / ERC20) — DTOs, fetch helpers and
 * pure formatters.
 *
 * Types mirror the admin block of `apps/api/src/yupay/modules/usdt/schemas.py`
 * (ADR-0104). Amounts are Decimal strings and never pass through a float: the
 * USDT journal carries up to 18 decimals (BEP20), the deposit is booked in cents.
 */

import adminRu from "@yupay/i18n/locales/ru/admin.json";

import { ApiError, apiGet, apiPatch, apiPost } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";

/** The feature's Russian string catalog (the admin SPA reads `ru`). */
export const T = adminRu.usdt;

const BASE = "/api/v1/admin/usdt";

export type UsdtMode = "off" | "allowlist" | "all";
export type UsdtNetworkCode = "trc20" | "bep20" | "erc20";
export type UsdtResult = "matched" | "unmatched" | "ignored" | "manual" | "dismissed";

/** One receiving chain: its own address and on/off switch. */
export interface UsdtNetwork {
  network: UsdtNetworkCode;
  enabled: boolean;
  address: string | null;
  /** Read-only: where the next poll starts (TRON: block time ms; EVM: block number). */
  cursor: number | null;
  updated_at: string;
}

export interface UsdtSettings {
  mode: UsdtMode;
  allowlist_merchant_ids: string[];
  min_amount_usd: string;
  max_amount_usd: string;
  updated_at: string;
  /** Always all three chains, trc20 → bep20 → erc20. */
  networks: UsdtNetwork[];
}

export interface UsdtSettingsPatch {
  mode?: UsdtMode;
  allowlist_merchant_ids?: string[];
  min_amount_usd?: string;
  max_amount_usd?: string;
}

/** Partial update of one chain; absent fields are left alone. */
export interface UsdtNetworkPatch {
  enabled?: boolean;
  address?: string | null;
}

export interface UsdtIncoming {
  id: string;
  network: UsdtNetworkCode;
  tx_id: string;
  from_address: string;
  /** USDT amount as a Decimal string (6 decimals on TRC20/ERC20, up to 18 on BEP20). */
  amount_usdt: string;
  block_at: string;
  received_at: string;
  result: UsdtResult;
  reservation_number: string | null;
  merchant_id: string | null;
  merchant_title: string | null;
  note: string | null;
  resolved_at: string | null;
}

export interface UsdtReservation {
  number: string;
  network: UsdtNetworkCode;
  merchant_id: string;
  merchant_title: string | null;
  amount: string;
  status: string;
  created_at: string;
  expires_at: string;
  closed_at: string | null;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
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

export const fetchSettings = () => apiGet<UsdtSettings>(`${BASE}/settings`);
export const saveSettings = (body: UsdtSettingsPatch, key: string) =>
  apiPatch<UsdtSettings>(`${BASE}/settings`, body, idem(key));
export const saveNetwork = (network: UsdtNetworkCode, body: UsdtNetworkPatch, key: string) =>
  apiPatch<UsdtSettings>(`${BASE}/networks/${network}`, body, idem(key));

export const fetchIncoming = (result: string, cursor: string | null) =>
  apiGet<Page<UsdtIncoming>>(`${BASE}/incoming${qs({ result, cursor })}`);
export const creditIncoming = (
  id: string,
  body: { merchant_id: string; note?: string },
  key: string,
) => apiPost<UsdtIncoming>(`${BASE}/incoming/${id}/credit`, body, idem(key));
export const dismissIncoming = (id: string, note: string, key: string) =>
  apiPost<UsdtIncoming>(`${BASE}/incoming/${id}/dismiss`, { note }, idem(key));

export const fetchReservations = (cursor: string | null) =>
  apiGet<Page<UsdtReservation>>(`${BASE}/reservations${qs({ cursor })}`);

/** `{placeholder}` interpolation for catalog strings. */
export function fill(template: string, vars: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) => vars[key] ?? match);
}

/** Readable Russian message: a catalog entry for known `code`s, else the server's text. */
export function usdtErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    // A known-shape problem body; the cast narrows it for the two fields read here.
    const body = err.body as { code?: unknown; merchant_ids?: unknown } | null;
    const code = body?.code;
    if (typeof code === "string" && code in T.errors) {
      const ids = Array.isArray(body?.merchant_ids) ? body.merchant_ids.join(", ") : "";
      return fill(T.errors[code as keyof typeof T.errors], { ids });
    }
  }
  return extractApiMessage(err);
}

/**
 * A USDT amount rounded DOWN to cents — what the credit endpoint books
 * (`quantize(CENT, ROUND_DOWN)`). String-only: `"12.345678"` → `"12.34"`.
 */
export function floorToCents(raw: string): string {
  const [intRaw = "", fracRaw = ""] = raw.trim().split(".");
  const intPart = intRaw.replace(/^0+(?=\d)/, "") || "0";
  return `${intPart}.${(fracRaw + "00").slice(0, 2)}`;
}

/**
 * USDT amount for display: at most six decimals (cut, not rounded — BEP20
 * carries 18), trailing zeros trimmed down to two.
 */
export function formatUsdt(raw: string): string {
  const [intRaw = "", fracRaw = ""] = raw.trim().split(".");
  let frac = fracRaw.slice(0, 6).replace(/0+$/, "");
  while (frac.length < 2) frac += "0";
  const grouped = (intRaw.replace(/^0+(?=\d)/, "") || "0").replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return `${grouped}.${frac}`;
}

/** `TXyz…abcd` for a long address or hash; short values pass through untouched. */
export function shortHash(value: string, head = 6, tail = 4): string {
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}

/** Positive USD amount with up to two decimals (comma accepted), or `null`. */
export function parseUsdBound(raw: string): string | null {
  const cleaned = raw.replace(/\s/g, "").replace(",", ".");
  if (!/^\d{1,10}(\.\d{1,2})?$/.test(cleaned) || !/[1-9]/.test(cleaned)) return null;
  return cleaned;
}

interface Explorer {
  tx: string;
  address: string;
}

/** Block explorer URL prefixes per chain; the hash or address is appended. */
const EXPLORERS: Record<UsdtNetworkCode, Explorer> = {
  trc20: { tx: "https://tronscan.org/#/transaction/", address: "https://tronscan.org/#/address/" },
  bep20: { tx: "https://bscscan.com/tx/", address: "https://bscscan.com/address/" },
  erc20: { tx: "https://etherscan.io/tx/", address: "https://etherscan.io/address/" },
};

/** Short chain name for a badge: `TRC20` / `BEP20` / `ERC20`. */
export const networkShort = (network: UsdtNetworkCode) => T.networks.short[network];

export const explorerTx = (network: UsdtNetworkCode, tx: string) =>
  `${EXPLORERS[network].tx}${encodeURIComponent(tx)}`;
export const explorerAddress = (network: UsdtNetworkCode, addr: string) =>
  `${EXPLORERS[network].address}${encodeURIComponent(addr)}`;
