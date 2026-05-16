export type TaskStatus =
  | "pending"
  | "in_progress"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface AttemptOut {
  kind: string;
  status: string;
  payload: Record<string, unknown>;
  error: string | null;
  created_at: string;
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
  created_at: string;
  succeeded_at: string | null;
  failed_at: string | null;
  cancelled_at: string | null;
  attempts: AttemptOut[];
}

export interface TaskListOut {
  items: TaskAdminOut[];
}
