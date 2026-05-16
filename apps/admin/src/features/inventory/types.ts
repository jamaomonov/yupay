/** Types mirroring the backend's inventory / sourcing DTOs. Hand-written. */

export type CodeState = "available" | "reserved" | "issued" | "voided";

export interface SkuCountsOut {
  sku_id: string;
  available: number;
  reserved: number;
  issued: number;
  voided: number;
}

export interface BulkUploadOut {
  upload_id: string;
  total: number;
  succeeded: number;
  duplicates: number;
}

export interface CodeAdminOut {
  id: string;
  sku_id: string;
  code: string;
  state: CodeState;
  order_item_id: string | null;
  reserved_at: string | null;
  issued_at: string | null;
  voided_at: string | null;
  expires_at: string | null;
  created_at: string;
}

export interface CodeAdminListOut {
  items: CodeAdminOut[];
}
