/**
 * Shared query definitions + row predicates for the Fulfilment Inbox tabs.
 *
 * The Inbox header shows a count badge per tab, and the badge has to agree with
 * what the tab actually renders. Two of the three tabs narrow the server result
 * client-side (Failed drops `supplier=manual`; Stuck keeps only rows older than
 * {@link STUCK_AFTER_MS}), so a server `total` would overstate them. Keeping the
 * URL, the query key and the predicate in one module means the badge and the
 * tab can't drift apart — and because the keys are identical, React Query
 * serves both from a single request instead of fetching twice.
 *
 * Failed drops a second class of row as of 2026-09-20: a merchant task whose
 * deposit has already been returned. See {@link selectFailedRows}.
 */

import type { TaskAdminOut, TaskListOut } from "./types";

import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

/** How long an `in_progress` task may sit before we call it stuck. */
export const STUCK_AFTER_MS = 30 * 60_000;

const BASE = "/api/v1/admin/fulfillment/tasks";

/** Manual queue: tasks a human has to fulfil. Server-side filter is exact. */
export const manualQueueQuery = {
  queryKey: qk.manualQueue(),
  queryFn: () =>
    apiGet<TaskListOut>(`${BASE}?supplier=manual&status_filter=in_progress&order=oldest&limit=200`),
  refetchInterval: 15_000,
} as const;

/** Automatic failures. `supplier=manual` rows belong to the manual tab. */
export const failedTasksQuery = {
  queryKey: [...qk.fulfillmentTasks({ status: "failed" }), "no-manual"],
  queryFn: () => apiGet<TaskListOut>(`${BASE}?status_filter=failed&order=oldest&limit=200`),
  refetchInterval: 30_000,
} as const;

/** In-flight tasks; the "stuck" cut is by age, applied client-side. */
export const stuckTasksQuery = {
  queryKey: [...qk.fulfillmentTasks({ status: "in_progress" }), "stuck"],
  queryFn: () => apiGet<TaskListOut>(`${BASE}?status_filter=in_progress&order=oldest&limit=200`),
  refetchInterval: 30_000,
} as const;

/**
 * Rows the Failed tab shows: automatic failures an operator can still act on.
 *
 * Two exclusions, and the second is not cosmetic. `supplier === "manual"`
 * belongs to the manual tab. `deposit_settled` is a merchant order whose
 * deposit has already been returned in full: every button on the row —
 * «Перезапустить», «Другой поставщик», manual completion — is refused by the
 * API with `409 deposit_already_returned`, because delivering now would hand
 * over goods nobody paid for. The task is left `failed` on purpose (the
 * refund gates on exactly that state), and the order is already closed for
 * the same reason; the row was simply never taken out of the work queue, so
 * two permanently un-actionable lines sat in production's Failed tab.
 *
 * They stay visible under «Все» — this hides work that is done, not history.
 */
export function selectFailedRows(data: TaskListOut | undefined): TaskAdminOut[] {
  return (data?.items ?? []).filter((t) => t.supplier !== "manual" && !t.deposit_settled);
}

/** Rows the Stuck tab shows: in-flight for longer than {@link STUCK_AFTER_MS}. */
export function selectStuckRows(data: TaskListOut | undefined): TaskAdminOut[] {
  const cutoff = Date.now() - STUCK_AFTER_MS;
  return (data?.items ?? []).filter((t) => new Date(t.created_at).getTime() < cutoff);
}
