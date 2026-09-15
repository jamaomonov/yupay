import { DonutShare } from "./charts/DonutShare";
import { LineTrend } from "./charts/LineTrend";
import { usd } from "./format";
import { FunnelBars } from "./FunnelBars";
import { KpiCard } from "./KpiCard";

import type { BusinessAnalytics } from "./types";

import { DataTable } from "@/components/DataTable";

const CHANNEL_LABEL: Record<string, string> = { retail: "Розница", b2b: "B2B" };

export function BusinessTab({ data }: { data: BusinessAnalytics }) {
  const s = data.summary;
  const p = data.previous;
  const hourlyPeak = Math.max(...data.hourly.map((h) => h.orders), 0);
  const busiest = data.hourly.find((h) => h.orders === hourlyPeak && hourlyPeak > 0);
  return (
    <div className="space-y-8">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {/* The `was` prop is spread rather than passed: with no earlier
            window the card must draw no chip at all, and under
            `exactOptionalPropertyTypes` an explicit `undefined` is not the
            same as an absent prop. */}
        <KpiCard
          label="GMV"
          value={usd(s.gmv_usd)}
          now={Number(s.gmv_usd)}
          {...(p !== null && { was: Number(p.gmv_usd) })}
        />
        <KpiCard
          label="Заказов"
          value={String(s.orders)}
          hint={`оплачено ${String(s.paid_orders)}`}
          now={s.orders}
          {...(p !== null && { was: p.orders })}
        />
        <KpiCard
          label="Средний чек"
          value={usd(s.aov_usd)}
          now={Number(s.aov_usd)}
          {...(p !== null && { was: Number(p.aov_usd) })}
        />
        <KpiCard
          label="Маржа ≈"
          value={usd(s.gross_margin_usd)}
          hint={`${String(s.margin_pct)}% · оценочно${s.margin_unknown_units ? ` · ${String(s.margin_unknown_units)} ед. без cost` : ""}`}
          now={Number(s.gross_margin_usd)}
          {...(p !== null && { was: Number(p.gross_margin_usd) })}
        />
        {/* Up is bad here, so the chip's colours are flipped. The funnel below
            counts refunds in orders; this is what they cost. */}
        <KpiCard
          label="Возвраты"
          value={usd(s.refunded_usd)}
          inverted
          now={Number(s.refunded_usd)}
          {...(p !== null && { was: Number(p.refunded_usd) })}
        />
      </div>

      <section className="grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">Выручка по дням</h3>
          <LineTrend
            data={data.revenue_series.map((point) => ({
              x: point.date.slice(5),
              y: Number(point.revenue_usd),
            }))}
          />
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">Маржа по дням ≈</h3>
          {/* Beside the revenue chart rather than on it: they share an axis
              only by accident, and a margin line flattened against a revenue
              scale is the chart that made the split necessary. */}
          <LineTrend
            data={data.revenue_series.map((point) => ({
              x: point.date.slice(5),
              y: Number(point.margin_usd ?? 0),
            }))}
          />
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold">Воронка</h3>
        <FunnelBars funnel={data.funnel} />
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">Розница и B2B</h3>
          {/* Always both halves, whatever the tab is scoped to: this is the
              block the scoping is compared against, so narrowing it would
              leave a single bar labelled "100%". */}
          <DataTable
            rows={data.channels}
            rowKey={(c) => c.channel}
            ariaLabel="Розница и B2B"
            empty="Нет продаж за период"
            columns={[
              {
                key: "ch",
                header: "Канал",
                render: (c) => CHANNEL_LABEL[c.channel] ?? c.channel,
              },
              { key: "gmv", header: "GMV", render: (c) => usd(c.gmv_usd) },
              { key: "n", header: "Заказов", render: (c) => String(c.orders) },
              {
                key: "m",
                header: "Маржа ≈",
                render: (c) => (c.margin_usd ? usd(c.margin_usd) : "—"),
              },
            ]}
          />
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">
            Заказы по часам{" "}
            <span className="font-normal text-[var(--text-secondary)]">
              {busiest ? `· пик ${String(busiest.hour)}:00` : ""}
            </span>
          </h3>
          {/* Tashkent time, not UTC: the question is when to staff support,
              and a chart shifted five hours answers a different one. */}
          <LineTrend
            data={data.hourly.map((h) => ({ x: String(h.hour), y: h.orders }))}
            height={200}
          />
        </div>
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
            rowKey={(sku) => sku.sku_code}
            ariaLabel="Топ SKU"
            empty="Нет продаж за период"
            columns={[
              { key: "code", header: "SKU", render: (sku) => sku.sku_code },
              { key: "rev", header: "Выручка", render: (sku) => usd(sku.revenue_usd) },
              { key: "units", header: "Штук", render: (sku) => String(sku.units) },
              {
                key: "margin",
                header: "Маржа ≈",
                render: (sku) => (sku.margin_usd ? usd(sku.margin_usd) : "—"),
              },
            ]}
          />
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">Новые пользователи</h3>
          <LineTrend
            data={data.customers.new_users_series.map((point) => ({
              x: point.date.slice(5),
              y: point.users,
            }))}
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
