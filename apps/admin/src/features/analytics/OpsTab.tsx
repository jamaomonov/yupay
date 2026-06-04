import { BarBreakdown } from "./charts/BarBreakdown";
import { usd, usdt } from "./format";
import { KpiCard } from "./KpiCard";

import type { OpsAnalytics } from "./types";

import { DataTable } from "@/components/DataTable";

export function OpsTab({ data }: { data: OpsAnalytics }) {
  return (
    <div className="space-y-8">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard label="Застрявшие платежи" value={String(data.stuck_pending)} />
        <KpiCard label="Проблемные вебхуки" value={String(data.webhook_unhealthy)} />
        <KpiCard label="Застрявшие задачи" value={String(data.stuck_tasks)} />
        <KpiCard label="Истекают коды (7д)" value={String(data.expiring_soon)} />
      </div>

      <section className="grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">Платежи по провайдерам</h3>
          <BarBreakdown data={data.payments.map((p) => ({ name: p.provider, value: p.count }))} />
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">Провайдеры — успех</h3>
          <DataTable
            rows={data.payments}
            rowKey={(p) => p.provider}
            ariaLabel="Платежи по провайдерам"
            columns={[
              { key: "p", header: "Провайдер", render: (p) => p.provider },
              { key: "n", header: "Транзакций", render: (p) => String(p.count) },
              { key: "v", header: "Объём", render: (p) => usd(p.volume_usd) },
              { key: "ok", header: "Success", render: (p) => `${String(p.success_rate_pct)}%` },
            ]}
          />
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold">Фулфилмент по поставщикам</h3>
        <DataTable
          rows={data.fulfillment}
          rowKey={(f) => f.supplier}
          ariaLabel="Фулфилмент по поставщикам"
          columns={[
            { key: "s", header: "Поставщик", render: (f) => f.supplier },
            { key: "t", header: "Всего", render: (f) => String(f.total) },
            { key: "ok", header: "Success", render: (f) => `${String(f.success_rate_pct)}%` },
            {
              key: "avg",
              header: "Ср. время",
              render: (f) => (f.avg_seconds != null ? `${String(f.avg_seconds)}s` : "—"),
            },
            { key: "m", header: "Вручную", render: (f) => String(f.manual_count) },
            { key: "att", header: "Ср. попыток", render: (f) => String(f.avg_attempts) },
          ]}
        />
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">Заканчивается на складе</h3>
          <DataTable
            rows={data.low_stock}
            rowKey={(l) => l.sku_code}
            ariaLabel="Низкие остатки"
            empty="Низких остатков нет"
            columns={[
              { key: "sku", header: "SKU", render: (l) => l.sku_code },
              { key: "a", header: "Доступно", render: (l) => String(l.available) },
            ]}
          />
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">Изменения себестоимости</h3>
          <DataTable
            rows={data.supplier_cost}
            rowKey={(c) => `${c.sku_code}-${c.captured_at}`}
            ariaLabel="Изменения себестоимости"
            empty="Изменений нет"
            columns={[
              { key: "sku", header: "SKU", render: (c) => c.sku_code },
              { key: "sup", header: "Поставщик", render: (c) => c.supplier_slug },
              {
                key: "was",
                header: "Было",
                render: (c) => (c.previous_cost_usdt ? usdt(c.previous_cost_usdt) : "—"),
              },
              { key: "now", header: "Стало", render: (c) => usdt(c.cost_usdt) },
            ]}
          />
        </div>
      </section>
    </div>
  );
}
