/**
 * Types mirroring the FastAPI ``SearchOut`` / ``SearchHit`` DTOs from
 * ``apps/api/src/yupay/modules/admin/schemas.py``.
 *
 * Kept hand-written for now — once the project switches to
 * ``@hey-api/openapi-ts`` we'll regenerate these.
 */

export type HitType = "user" | "order" | "payment" | "sku";

export interface SearchHit {
  type: HitType;
  id: string;
  label: string;
  /** Whatever doesn't fit status/amount below (provider, external id, tg handle, …). */
  sublabel: string | null;
  /** Raw backend status (order/payment) — render via `StatusChip`, never as-is. */
  status: string | null;
  /** Raw decimal string — render via `formatMoney`, never as-is. */
  amount: string | null;
  currency: string | null;
  /** Admin SPA deep-link path. */
  path: string;
}

export interface SearchOut {
  users: SearchHit[];
  orders: SearchHit[];
  payments: SearchHit[];
  skus: SearchHit[];
}
