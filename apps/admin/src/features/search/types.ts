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
  sublabel: string | null;
  /** Admin SPA deep-link path. */
  path: string;
}

export interface SearchOut {
  users: SearchHit[];
  orders: SearchHit[];
  payments: SearchHit[];
  skus: SearchHit[];
}
