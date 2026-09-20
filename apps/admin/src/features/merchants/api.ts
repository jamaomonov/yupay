/**
 * Merchant B2B admin feature — DTOs, fetch helpers and money-string utils.
 *
 * Types mirror `apps/api/src/yupay/modules/merchants/schemas.py` (see
 * `docs/api/openapi.json`) — the admin SPA's established thin hand-written
 * DTO layer next to the fetch calls (`features/payments/providers/types.ts`
 * explains the convention). Deliberately NOT reusing
 * `features/wallet/types.ts`: its hand-written `AccountKind` / `owner_type`
 * unions predate the partner and merchant ledger kinds and are stale.
 *
 * Every money value is a USD `Decimal` string straight from the API.
 * Display goes through `formatUsd` — pure string operations, so a ledger
 * amount is never routed through floats on its way to the operator.
 *
 * Strings live in `@yupay/i18n/locales/{ru,en,uz}/admin.json` (parity
 * CI-gated); the admin SPA is Russian-only today, so the feature reads the
 * `ru` catalog directly.
 */

import adminRu from "@yupay/i18n/locales/ru/admin.json";

import { apiGet, apiPost } from "@/lib/api";

/** The feature's Russian string catalog (see module docstring). */
export const T = adminRu.merchants;

/** `{placeholder}` interpolation for catalog strings. */
export function fill(template: string, vars: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) => vars[key] ?? match);
}

/** One merchant row plus its USD deposit balance (`MerchantOut`). */
export interface MerchantOut {
  id: string;
  title: string;
  /** `active` | `frozen` today; typed open because the backend column is. */
  status: string;
  created_at: string;
  deposit_balance: string;
}

export interface MerchantListOut {
  items: MerchantOut[];
}

/** Result of a deposit credit (`DepositCreditOut`). */
export interface DepositCreditOut {
  transaction_id: string;
  merchant_id: string;
  /** What the ledger ACTUALLY booked. On an idempotent replay this is the
   *  ORIGINAL transaction's amount, not the request's — the ledger replays
   *  by key without comparing parameters, so the UI compares this against
   *  the typed amount and warns on a mismatch (money-safety). */
  amount: string;
  balance: string;
  /** The order the transaction is booked against, or `null` for a plain
   *  prepayment. Read off the transaction for the same reason `amount` is,
   *  and it matters more: a posted attribution CANNOT be re-pointed, so a
   *  replay that ignored the order typed here is unfixable and must be
   *  shown, not swallowed. */
  order_id: string | null;
}

/** One deposit movement (`MerchantTxnOut`); `amount` is the signed delta. */
export interface MerchantTxnOut {
  transaction_id: string;
  kind: string;
  amount: string;
  note: string | null;
  actor: string | null;
  created_at: string;
}

export interface MerchantTxnListOut {
  items: MerchantTxnOut[];
}

export function fetchMerchants(): Promise<MerchantListOut> {
  return apiGet<MerchantListOut>("/api/v1/admin/merchants");
}

export function fetchMerchantTxns(merchantId: string): Promise<MerchantTxnListOut> {
  return apiGet<MerchantTxnListOut>(`/api/v1/admin/merchants/${merchantId}/transactions?limit=50`);
}

export function createMerchant(title: string, idempotencyKey: string): Promise<MerchantOut> {
  return apiPost<MerchantOut>(
    "/api/v1/admin/merchants",
    { title },
    { "Idempotency-Key": idempotencyKey },
  );
}

export function setMerchantFrozen(
  merchantId: string,
  frozen: boolean,
  idempotencyKey: string,
): Promise<MerchantOut> {
  const action = frozen ? "freeze" : "unfreeze";
  return apiPost<MerchantOut>(
    `/api/v1/admin/merchants/${merchantId}/${action}`,
    {},
    { "Idempotency-Key": idempotencyKey },
  );
}

export function creditDeposit(
  merchantId: string,
  body: { amount: string; note: string | null; order_id: string | null },
  idempotencyKey: string,
): Promise<DepositCreditOut> {
  return apiPost<DepositCreditOut>(`/api/v1/admin/merchants/${merchantId}/deposit-credits`, body, {
    "Idempotency-Key": idempotencyKey,
  });
}

/** Result of a deposit debit (`DepositDebitOut`).
 *
 *  No `order_id`: a debit is booked against the merchant, never an order —
 *  attributing one would land on that order's `refunded_usd` as money the
 *  merchant never got back. */
export interface DepositDebitOut {
  transaction_id: string;
  merchant_id: string;
  /** What the ledger ACTUALLY booked — the ORIGINAL transaction's amount on
   *  an idempotent replay, for the same reason `DepositCreditOut.amount` is. */
  amount: string;
  balance: string;
}

export function debitDeposit(
  merchantId: string,
  body: { amount: string; reason: string },
  idempotencyKey: string,
): Promise<DepositDebitOut> {
  return apiPost<DepositDebitOut>(`/api/v1/admin/merchants/${merchantId}/deposit-debits`, body, {
    "Idempotency-Key": idempotencyKey,
  });
}

/**
 * `"$1 250.00"` from `"1250.00"` (and `"−$5.00"` from `"-5.000000"`) —
 * trims ledger-precision trailing zeros down to at least two decimals and
 * groups thousands with the NBSP `Intl.NumberFormat("ru-RU")` uses, all with
 * string operations. Decimal strings never go through floats for display.
 */
export function formatUsd(raw: string): string {
  const trimmed = raw.trim();
  const negative = trimmed.startsWith("-");
  const unsigned = negative ? trimmed.slice(1) : trimmed;
  const [intRaw = "", fracRaw = ""] = unsigned.split(".");
  const intPart = intRaw.replace(/^0+(?=\d)/, "") || "0";
  let frac = fracRaw.replace(/0+$/, "");
  while (frac.length < 2) frac += "0";
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return `${negative ? "−" : ""}$${grouped}.${frac}`;
}

/**
 * Canonical positive USD amount (`"10"` / `"10.5"`) from operator input, or
 * `null` when invalid. Accepts comma decimals and `MoneyInput`'s already
 * ungrouped value; caps at the schema's `max_digits=12, decimal_places=2`
 * (so up to ten integer digits).
 */
export function parseUsdAmount(raw: string): string | null {
  const cleaned = raw.replace(/\s/g, "").replace(",", ".");
  if (!/^\d{1,10}(\.\d{1,2})?$/.test(cleaned)) return null;
  if (!/[1-9]/.test(cleaned)) return null; // "0" / "0.00" — not a credit
  return cleaned;
}

/**
 * Canonical order id from operator input, or `null` when it is not a UUID.
 *
 * Mirrors what the API does with this field (`deposit._resolve_order_reference`
 * → `str(UUID(value))`): Python's `UUID()` accepts a `urn:uuid:` prefix,
 * `{braces}`, any casing and dashes anywhere, and normalises all of them to the
 * one spelling Postgres' `uuid` type takes — so `Guid.ToString("B")` output
 * pasted out of a ticket is a legal id here too. Validating client-side is not
 * belt-and-braces: the server answers a **404** for a malformed id, on purpose
 * and indistinguishably from "not this merchant's order", so an operator who
 * pasted a `merchant_order_id` would read "no such order" and go looking in the
 * wrong place.
 */
export function parseOrderId(raw: string): string | null {
  const stripped = raw
    .trim()
    .toLowerCase()
    .replace(/^urn:uuid:/, "")
    .replace(/^\{|\}$/g, "")
    .replace(/-/g, "");
  if (!/^[0-9a-f]{32}$/.test(stripped)) return null;
  return [
    stripped.slice(0, 8),
    stripped.slice(8, 12),
    stripped.slice(12, 16),
    stripped.slice(16, 20),
    stripped.slice(20),
  ].join("-");
}

/**
 * A USD decimal string as an integer number of cents.
 *
 * Safe as a JS number, and the bound is worth stating rather than assuming:
 * the schema caps an amount at `max_digits=12, decimal_places=2`, so the
 * largest value is 10^10 dollars = 10^12 cents — three orders of magnitude
 * under `Number.MAX_SAFE_INTEGER`. Parsing the dollars as a float and
 * multiplying would not be safe; this reads the digits.
 */
export function toCents(raw: string): number {
  const trimmed = raw.trim();
  const negative = trimmed.startsWith("-");
  const [intRaw = "0", fracRaw = ""] = (negative ? trimmed.slice(1) : trimmed).split(".");
  const cents = Number(intRaw || "0") * 100 + Number((fracRaw + "00").slice(0, 2));
  return negative ? -cents : cents;
}

/** `"3.93"` minus `"1.10"` as `"2.83"`, in cents so no float ever sees it. */
export function subtractUsd(a: string, b: string): string {
  const cents = toCents(a) - toCents(b);
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  return `${sign}${String(Math.floor(abs / 100))}.${String(abs % 100).padStart(2, "0")}`;
}

/** Whether two Decimal strings denote the same amount (`"10"` vs `"10.00"`). */
export function sameAmount(a: string, b: string): boolean {
  return canonicalAmount(a) === canonicalAmount(b);
}

function canonicalAmount(raw: string): string {
  const [intRaw = "", fracRaw = ""] = raw.trim().split(".");
  const intPart = intRaw.replace(/^0+(?=\d)/, "") || "0";
  const frac = fracRaw.replace(/0+$/, "");
  return frac ? `${intPart}.${frac}` : intPart;
}
