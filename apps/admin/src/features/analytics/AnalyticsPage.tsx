import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { BusinessTab } from "./BusinessTab";
import { OpsTab } from "./OpsTab";

import type { AnalyticsRange, BusinessAnalytics, OpsAnalytics } from "./types";

import { PageHeader } from "@/components/PageHeader";
import { Spinner } from "@/components/States";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

const RANGES: AnalyticsRange[] = ["7d", "30d", "90d"];
const RANGE_LABEL: Record<AnalyticsRange, string> = {
  "7d": "7 дней",
  "30d": "30 дней",
  "90d": "90 дней",
};

export function AnalyticsPage() {
  const [tab, setTab] = useState<"business" | "ops">("business");
  const [range, setRange] = useState<AnalyticsRange>("30d");

  const business = useQuery<BusinessAnalytics>({
    queryKey: qk.analyticsBusiness(range),
    queryFn: () =>
      apiGet<BusinessAnalytics>(`/api/v1/admin/stats/analytics/business?range=${range}`),
    enabled: tab === "business",
  });
  const ops = useQuery<OpsAnalytics>({
    queryKey: qk.analyticsOps(range),
    queryFn: () => apiGet<OpsAnalytics>(`/api/v1/admin/stats/analytics/ops?range=${range}`),
    enabled: tab === "ops",
  });

  const active = tab === "business" ? business : ops;

  return (
    <div>
      <PageHeader title="Аналитика" description="Тренды по бизнесу и операционке." />

      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1 rounded-lg border border-[var(--border-default)] p-1">
          {(["business", "ops"] as const).map((t) => (
            <button
              key={t}
              type="button"
              aria-pressed={tab === t}
              onClick={() => {
                setTab(t);
              }}
              className={`rounded-md px-3 py-1.5 text-sm font-medium ${tab === t ? "bg-[var(--bg-accent-soft)] text-[var(--accent)]" : "text-[var(--text-secondary)]"}`}
            >
              {t === "business" ? "Бизнес" : "Операционка"}
            </button>
          ))}
        </div>
        <div className="flex gap-1 rounded-lg border border-[var(--border-default)] p-1">
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              aria-pressed={range === r}
              onClick={() => {
                setRange(r);
              }}
              className={`rounded-md px-3 py-1.5 text-sm ${range === r ? "bg-[var(--bg-accent-soft)] text-[var(--accent)]" : "text-[var(--text-secondary)]"}`}
            >
              {RANGE_LABEL[r]}
            </button>
          ))}
        </div>
      </div>

      {active.isLoading ? (
        <Spinner label="Считаем…" />
      ) : active.isError ? (
        <div role="alert" className="rounded-lg border border-[var(--danger)] p-4 text-sm">
          Не удалось загрузить аналитику.
        </div>
      ) : tab === "business" && business.data ? (
        <BusinessTab data={business.data} />
      ) : tab === "ops" && ops.data ? (
        <OpsTab data={ops.data} />
      ) : null}
    </div>
  );
}
