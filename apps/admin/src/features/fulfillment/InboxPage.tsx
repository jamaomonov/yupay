/**
 * Fulfillment Inbox — unified entry point for everything that needs an
 * operator's attention.
 *
 * Tabs (URL-bound via `?tab=`):
 *   - Ручная выдача — supplier=manual, status=in_progress (existing manual queue)
 *   - Failed       — automatic tasks that fell off; bulk-retry available
 *   - Stuck        — in_progress > 30 min (client-side filter on created_at)
 *   - Все          — full list with filters (legacy FulfillmentPage)
 *
 * Replaces the old /fulfillment list as the default entry. /manual-fulfillment
 * still works for muscle-memory but redirects here.
 */

import { useQuery } from "@tanstack/react-query";
import { Hand, ListChecks, Truck, XCircle } from "lucide-react";

import { FailedAutomaticTab } from "./FailedAutomaticTab";
import { FulfillmentPage } from "./FulfillmentPage";
import {
  failedTasksQuery,
  manualQueueQuery,
  selectFailedRows,
  selectStuckRows,
  stuckTasksQuery,
} from "./inboxQueries";
import { StuckTab } from "./StuckTab";

import type { TaskListOut } from "./types";

import { PageHeader } from "@/components/PageHeader";
import { Tabs, type TabDescriptor } from "@/components/Tabs";
import { ManualQueuePage } from "@/features/manual-fulfillment/ManualQueuePage";
import { SaveSegmentButton } from "@/features/segments/SaveSegmentButton";
import { useSearchParamsState } from "@/lib/useSearchParamsState";

type InboxTab = "manual" | "failed" | "stuck" | "all";

const VALID_TABS: ReadonlySet<InboxTab> = new Set<InboxTab>(["manual", "failed", "stuck", "all"]);

const PANEL_ID = "inbox-panel";

export function InboxPage() {
  const [rawTab, setTab] = useSearchParamsState("tab", "manual");
  const tab: InboxTab = VALID_TABS.has(rawTab as InboxTab) ? (rawTab as InboxTab) : "manual";

  // Counts for the tab badges. These use the *same* query keys as the tabs, so
  // React Query serves the mounted tab and its badge from one request; the
  // client-side predicates are shared too, so a badge can't disagree with the
  // list behind it. Without them an "Inbox" forces the operator to click every
  // tab just to learn whether there is any work at all.
  const manual = useQuery<TaskListOut>(manualQueueQuery);
  const failed = useQuery<TaskListOut>(failedTasksQuery);
  const stuck = useQuery<TaskListOut>(stuckTasksQuery);

  const tabs: TabDescriptor<InboxTab>[] = [
    {
      id: "manual",
      label: "Ручная выдача",
      icon: Hand,
      badge: { count: manual.data?.items.length ?? 0, tone: "warn" },
      panelId: PANEL_ID,
    },
    {
      id: "failed",
      label: "Failed",
      icon: XCircle,
      badge: { count: selectFailedRows(failed.data).length, tone: "warn" },
      panelId: PANEL_ID,
    },
    {
      id: "stuck",
      label: "Stuck",
      icon: Truck,
      badge: { count: selectStuckRows(stuck.data).length, tone: "warn" },
      panelId: PANEL_ID,
    },
    { id: "all", label: "Все", icon: ListChecks, panelId: PANEL_ID },
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Fulfilment Inbox"
        description="Задачи, требующие внимания оператора: ручная выдача, retry, висяки."
        actions={<SaveSegmentButton />}
      />

      <Tabs<InboxTab> value={tab} onChange={setTab} tabs={tabs} ariaLabel="Вкладки Inbox" />

      {/* `id` matches the tabs' aria-controls — without it the reference dangles. */}
      <div role="tabpanel" id={PANEL_ID}>
        {tab === "manual" && <ManualQueuePage />}
        {tab === "failed" && <FailedAutomaticTab />}
        {tab === "stuck" && <StuckTab />}
        {tab === "all" && <FulfillmentPage />}
      </div>
    </div>
  );
}
