import { DonutShare } from "./charts/DonutShare";
import { LineTrend } from "./charts/LineTrend";
import { usd } from "./format";
import { FunnelBars } from "./FunnelBars";
import { KpiCard } from "./KpiCard";

import type { BusinessAnalytics } from "./types";

import { DataTable } from "@/components/DataTable";

export function BusinessTab({ data }: { data: BusinessAnalytics }) {
  const s = data.summary;
  return (
    <div className="space-y-8">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <KpiCard label="GMV" value={usd(s.gmv_usd)} />
        <KpiCard
          label="Заказов"
          value={String(s.orders)}
          hint={`оплачено ${String(s.paid_orders)}`}
        />
        <KpiCard label="Средний чек" value={usd(s.aov_usd)} />
        <KpiCard
          label="Маржа ≈"
          value={usd(s.gross_margin_usd)}
          hint={`${String(s.margin_pct)}% · оценочно${s.margin_unknown_units ? ` · ${String(s.margin_unknown_units)} ед. без cost` : ""}`}
        />
        <KpiCard label="FX P&L" value={usd(s.fx_pnl_usd)} />
      </div>

      <section>
        <h3 className="mb-2 text-sm font-semibold">Выручка по дням</h3>
        <LineTrend
          data={data.revenue_series.map((p) => ({ x: p.date.slice(5), y: Number(p.revenue_usd) }))}
        />
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold">Воронка</h3>
        <FunnelBars funnel={data.funnel} />
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">Топ бренды</h3>
          <DataTable
            rows={data.top_brands}
            rowKey={(b) => b.slug}
            ariaLabel="Топ бренды"
            columns={[
              { key: "slug", header: "Бренд", render: (b) => b.slug },
              { key: "rev", header: "Выручка", render: (b) => usd(b.revenue_usd) },
              { key: "units", header: "Штук", render: (b) => String(b.units) },
              {
                key: "margin",
                header: "Маржа ≈",
                render: (b) => (b.margin_usd ? usd(b.margin_usd) : "—"),
              },
            ]}
          />
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">Доли брендов</h3>
          <DonutShare
            data={data.top_brands.map((b) => ({ name: b.slug, value: Number(b.revenue_usd) }))}
          />
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">Топ SKU</h3>
          <DataTable
            rows={data.top_skus}
            rowKey={(s) => s.sku_code}
            ariaLabel="Топ SKU"
            empty="Нет продаж за период"
            columns={[
              { key: "code", header: "SKU", render: (s) => s.sku_code },
              { key: "rev", header: "Выручка", render: (s) => usd(s.revenue_usd) },
              { key: "units", header: "Штук", render: (s) => String(s.units) },
              {
                key: "margin",
                header: "Маржа ≈",
                render: (s) => (s.margin_usd ? usd(s.margin_usd) : "—"),
              },
            ]}
          />
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">Новые пользователи</h3>
          <LineTrend
            data={data.customers.new_users_series.map((p) => ({ x: p.date.slice(5), y: p.users }))}
          />
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">Гость vs зарегистрированный</h3>
          <DonutShare
            data={[
              { name: "Гость", value: data.customers.guest_orders },
              { name: "Зарегистр.", value: data.customers.registered_orders },
            ]}
          />
          <div className="mt-2 text-xs text-[var(--text-secondary)]">
            Повторные покупки: {data.customers.repeat_rate_pct}%
          </div>
        </div>
      </section>
    </div>
  );
}
