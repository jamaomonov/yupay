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

import { Hand, ListChecks, Truck, XCircle } from "lucide-react";

import { FailedAutomaticTab } from "./FailedAutomaticTab";
import { FulfillmentPage } from "./FulfillmentPage";
import { StuckTab } from "./StuckTab";

import { PageHeader } from "@/components/PageHeader";
import { Tabs, type TabDescriptor } from "@/components/Tabs";
import { ManualQueuePage } from "@/features/manual-fulfillment/ManualQueuePage";
import { SaveSegmentButton } from "@/features/segments/SaveSegmentButton";
import { useSearchParamsState } from "@/lib/useSearchParamsState";

type InboxTab = "manual" | "failed" | "stuck" | "all";

const VALID_TABS: ReadonlySet<InboxTab> = new Set<InboxTab>(["manual", "failed", "stuck", "all"]);

const TABS: TabDescriptor<InboxTab>[] = [
  { id: "manual", label: "Ручная выдача", icon: Hand },
  { id: "failed", label: "Failed", icon: XCircle },
  { id: "stuck", label: "Stuck", icon: Truck },
  { id: "all", label: "Все", icon: ListChecks },
];

export function InboxPage() {
  const [rawTab, setTab] = useSearchParamsState("tab", "manual");
  const tab: InboxTab = VALID_TABS.has(rawTab as InboxTab) ? (rawTab as InboxTab) : "manual";

  return (
    <div className="space-y-4">
      <PageHeader
        title="Fulfilment Inbox"
        description="Задачи, требующие внимания оператора: ручная выдача, retry, висяки."
        actions={<SaveSegmentButton />}
      />

      <Tabs<InboxTab> value={tab} onChange={setTab} tabs={TABS} ariaLabel="Вкладки Inbox" />

      <div role="tabpanel">
        {tab === "manual" && <ManualQueuePage />}
        {tab === "failed" && <FailedAutomaticTab />}
        {tab === "stuck" && <StuckTab />}
        {tab === "all" && <FulfillmentPage />}
      </div>
    </div>
  );
}
