import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";

import { BusinessTab } from "./BusinessTab";
import { CalendarTab } from "./CalendarTab";
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

/** An explicit window, opened from the calendar or the date pickers. */
interface Period {
  since: string;
  /** Exclusive. */
  until: string;
  label: string;
}

export function AnalyticsPage() {
  const [tab, setTab] = useState<"business" | "calendar" | "ops">("business");
  const [range, setRange] = useState<AnalyticsRange>("30d");
  // A chosen period takes over the Business tab. It is the same tab and the
  // same computation — only the window differs — so there is no second page
  // to keep in step with this one.
  const [period, setPeriod] = useState<Period | null>(null);

  const openPeriod = (since: string, until: string, label: string) => {
    setPeriod({ since, until, label });
    setTab("business");
  };

  const periodQuery = useQuery<BusinessAnalytics>({
    queryKey: ["admin", "stats", "analytics", "business", period?.since, period?.until],
    queryFn: () =>
      apiGet<BusinessAnalytics>(
        `/api/v1/admin/stats/analytics/business?since=${encodeURIComponent(period?.since ?? "")}&until=${encodeURIComponent(period?.until ?? "")}`,
      ),
    enabled: tab === "business" && period !== null,
  });

  const business = useQuery<BusinessAnalytics>({
    queryKey: qk.analyticsBusiness(range),
    queryFn: () =>
      apiGet<BusinessAnalytics>(`/api/v1/admin/stats/analytics/business?range=${range}`),
    enabled: tab === "business" && period === null,
  });
  const ops = useQuery<OpsAnalytics>({
    queryKey: qk.analyticsOps(range),
    queryFn: () => apiGet<OpsAnalytics>(`/api/v1/admin/stats/analytics/ops?range=${range}`),
    enabled: tab === "ops",
  });

  // `active` decides the spinner and the error banner; `businessData` decides
  // what is rendered. Keeping them separate is what avoids casting a union of
  // two query results back into one shape.
  const active = tab === "ops" ? ops : period === null ? business : periodQuery;
  const businessData = period === null ? business.data : periodQuery.data;

  return (
    <div>
      <PageHeader title="Аналитика" description="Тренды по бизнесу и операционке." />

      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1 rounded-lg border border-[var(--border-default)] p-1">
          {(["business", "calendar", "ops"] as const).map((t) => (
            <button
              key={t}
              type="button"
              aria-pressed={tab === t}
              onClick={() => {
                setTab(t);
              }}
              className={`rounded-md px-3 py-1.5 text-sm font-medium ${tab === t ? "bg-[var(--bg-accent-soft)] text-[var(--accent)]" : "text-[var(--text-secondary)]"}`}
            >
              {t === "business" ? "Бизнес" : t === "calendar" ? "Календарь" : "Операционка"}
            </button>
          ))}
        </div>
        {period !== null ? (
          <button
            type="button"
            onClick={() => {
              setPeriod(null);
            }}
            className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border-default)] px-3 py-1.5 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          >
            <ArrowLeft className="size-4" aria-hidden="true" />
            {period.label} · вернуться к периоду
          </button>
        ) : tab === "calendar" ? null : (
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
        )}
      </div>

      {tab === "calendar" ? (
        <CalendarTab onPick={openPeriod} />
      ) : active.isLoading ? (
        <Spinner label="Считаем…" />
      ) : active.isError ? (
        <div role="alert" className="rounded-lg border border-[var(--danger)] p-4 text-sm">
          Не удалось загрузить аналитику.
        </div>
      ) : tab === "business" && businessData ? (
        <BusinessTab data={businessData} />
      ) : tab === "ops" && ops.data ? (
        <OpsTab data={ops.data} />
      ) : null}
    </div>
  );
}
