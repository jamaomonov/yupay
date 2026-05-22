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

import { PageHeader } from "@/components/PageHeader";
import { SaveSegmentButton } from "@/features/segments/SaveSegmentButton";
import { useSearchParamsState } from "@/lib/useSearchParamsState";

import { FailedAutomaticTab } from "./FailedAutomaticTab";
import { FulfillmentPage } from "./FulfillmentPage";
import { StuckTab } from "./StuckTab";
import { ManualQueuePage } from "@/features/manual-fulfillment/ManualQueuePage";

type InboxTab = "manual" | "failed" | "stuck" | "all";

const VALID_TABS: ReadonlySet<InboxTab> = new Set<InboxTab>([
  "manual",
  "failed",
  "stuck",
  "all",
]);

const TABS: {
  id: InboxTab;
  label: string;
  icon: typeof Hand;
}[] = [
  { id: "manual", label: "Ручная выдача", icon: Hand },
  { id: "failed", label: "Failed", icon: XCircle },
  { id: "stuck", label: "Stuck", icon: Truck },
  { id: "all", label: "Все", icon: ListChecks },
];

export function InboxPage() {
  const [rawTab, setTab] = useSearchParamsState<string>("tab", "manual");
  const tab: InboxTab = VALID_TABS.has(rawTab as InboxTab)
    ? (rawTab as InboxTab)
    : "manual";

  return (
    <div className="space-y-4">
      <PageHeader
        title="Fulfilment Inbox"
        description="Задачи, требующие внимания оператора: ручная выдача, retry, висяки."
        actions={<SaveSegmentButton />}
      />

      <nav
        className="flex flex-wrap gap-1 border-b border-[--color-border]"
        aria-label="Вкладки Inbox"
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => { setTab(t.id); }}
            className={[
              "inline-flex items-center gap-2 border-b-2 px-3 py-2 text-sm font-medium transition-colors",
              tab === t.id
                ? "border-[--color-brand] text-[--color-fg]"
                : "border-transparent text-[--color-muted] hover:text-[--color-fg]",
            ].join(" ")}
            aria-current={tab === t.id ? "page" : undefined}
          >
            <t.icon className="size-4" />
            {t.label}
          </button>
        ))}
      </nav>

      <div>
        {tab === "manual" && <ManualQueuePage />}
        {tab === "failed" && <FailedAutomaticTab />}
        {tab === "stuck" && <StuckTab />}
        {tab === "all" && <FulfillmentPage />}
      </div>
    </div>
  );
}
