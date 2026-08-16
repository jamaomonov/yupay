export type TaskStatus = "pending" | "in_progress" | "succeeded" | "failed" | "cancelled";

/** One row of the supplier-interaction log, as the audit feed returns it
 *  (`GET /admin/fulfillment/attempts`). Fetched per task on demand — the log
 *  is unbounded, since a task polls its supplier once a minute for as long as
 *  the order stays open. */
export interface AttemptOut {
  task_id: string;
  supplier: string;
  kind: string;
  status: string;
  payload: Record<string, unknown>;
  error: string | null;
  created_at: string;
}

export interface AttemptListOut {
  items: AttemptOut[];
  total: number;
}

export interface TaskAdminOut {
  id: string;
  order_id: string;
  order_item_id: string;
  supplier: string;
  status: TaskStatus;
  attempts_count: number;
  last_error: string | null;
  external_order_id: string | null;
  /** Free-text note the admin recorded when manually completing / rejecting. */
  admin_note: string | null;
  /** Admin user id that completed or rejected the task (manual flow only). */
  completed_by: string | null;
  /** Merged supplier-returned + admin-set metadata. Known keys today:
   *  - ``queued_at`` (ManualFulfiller stamps it on intake)
   *  - ``proof_url`` (admin-only link to receipt / screenshot, see
   *    ManualCompleteIn). */
  extra_metadata: Record<string, unknown>;
  created_at: string;
  succeeded_at: string | null;
  failed_at: string | null;
  cancelled_at: string | null;
}

export interface TaskListOut {
  items: TaskAdminOut[];
  total: number;
}

/** A delivered artifact as the ADMIN sees it — unfiltered, unlike the
 *  customer view which whitelists artifact keys. */
export interface DeliveryOut {
  id: string;
  order_item_id: string;
  channel: string;
  artifact_kind: string;
  artifact: Record<string, unknown>;
  delivered_at: string;
}

export interface DeliveryListOut {
  items: DeliveryOut[];
}
