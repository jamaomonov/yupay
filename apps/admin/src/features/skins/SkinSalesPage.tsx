/**
 * Skin sales — received, failed and in-flight trades for 7 / 30 / 90 days: revenue, what
 * Waxpeer charged, the margin and its share, then received skins per Tashkent day.
 */

import { useQuery } from "@tanstack/react-query";

import { fill, T, usd } from "./api";
import { fetchSummary, marginPercent, SALES_PERIODS, type SalesPeriod } from "./sales-api";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { EmptyState, ErrorState, Skeleton } from "@/components/States";
import { Tabs } from "@/components/Tabs";
import { qk } from "@/lib/queryKeys";
import { numberCodec, useSearchParamsState } from "@/lib/useSearchParamsState";

const S = T.sales;
const NUM = "text-right tabular-nums";

const isPeriod = (n: number): n is SalesPeriod => (SALES_PERIODS as readonly number[]).includes(n);

export function SkinSalesPage() {
  const [raw, setRaw] = useSearchParamsState("days", 30, numberCodec);
  const days: SalesPeriod = isPeriod(raw) ? raw : 30;
  const query = useQuery({ queryKey: qk.skinSales(days), queryFn: () => fetchSummary(days) });
  const data = query.data;

  const columns: Column<NonNullable<typeof data>["by_day"][number]>[] = [
    { key: "day", header: S.day, render: (d) => d.day },
    { key: "count", header: S.count, render: (d) => d.count, className: NUM },
    { key: "revenue", header: S.revenue, render: (d) => usd(d.revenue_usd), className: NUM },
    { key: "margin", header: S.margin, render: (d) => usd(d.margin_usd), className: NUM },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title={S.title} description={S.description} />
      <Tabs<string>
        ariaLabel={S.periods}
        value={String(days)}
        onChange={(v) => {
          setRaw(Number(v));
        }}
        tabs={SALES_PERIODS.map((n) => ({ id: String(n), label: fill(S.days, { n: String(n) }) }))}
      />
      {query.isError && <ErrorState title={S.error} onRetry={() => void query.refetch()} />}
      {query.isPending && <Skeleton rows={3} />}
      {data && (
        <>
          <section className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
            <StatCard label={S.sold} value={data.sold.count} accent />
            <StatCard label={S.revenue} value={usd(data.sold.revenue_usd)} mono />
            <StatCard label={S.cost} value={usd(data.sold.cost_usd)} mono />
            <StatCard
              label={S.margin}
              value={
                <span>
                  {usd(data.sold.margin_usd)}
                  {marginPercent(data.sold) && (
                    <span className="ml-1 text-sm text-[var(--text-secondary)]">
                      {marginPercent(data.sold)}
                    </span>
                  )}
                </span>
              }
              mono
            />
            <StatCard
              label={S.failed}
              value={data.failed.count}
              tone={data.failed.count > 0 ? "warn" : "muted"}
            />
            <StatCard label={S.inFlight} value={data.in_flight.count} tone="muted" />
          </section>
          <section className="space-y-2">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
              {S.byDay}
            </h2>
            {data.by_day.length === 0 ? (
              <EmptyState title={S.empty} />
            ) : (
              <DataTable rows={data.by_day} columns={columns} rowKey={(d) => d.day} />
            )}
          </section>
        </>
      )}
    </div>
  );
}
