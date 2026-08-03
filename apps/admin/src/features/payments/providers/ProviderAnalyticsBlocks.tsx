/**
 * Analytics blocks rendered inside `ProviderDetailDrawer`: tech/config
 * state, volume by currency, success rate, incident counters, and the
 * recent-payments table. Split out from the drawer shell purely to keep
 * each file under the repo's ~300 LOC soft limit.
 */

import {
  STATE_LABEL,
  STATE_TONE,
  type AdminProviderDetailOut,
  type AdminProviderSummary,
} from "./types";

import type { RecentPaymentOut } from "./types";

import { Badge } from "@/components/Badge";
import { DataTable, type Column } from "@/components/DataTable";
import { STATUS_LABEL, STATUS_TONE } from "@/features/payments/types";
import { formatMoney } from "@/lib/money";

export function TechStateBlock({ summary }: { summary: AdminProviderSummary }) {
  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
        Тех. состояние
      </h3>
      <div className="grid grid-cols-2 gap-3 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-3 text-sm">
        <DetailField label="Статус">
          <Badge tone={STATE_TONE[summary.state]} dot>
            {STATE_LABEL[summary.state]}
          </Badge>
        </DetailField>
        <DetailField label="Конфиг">
          {summary.config_available ? (
            <span className="text-[var(--success-fg)]">Настроен</span>
          ) : (
            <span className="text-[var(--danger-fg)]">Нет конфига</span>
          )}
        </DetailField>
        <DetailField label="Слаги">
          <span className="font-mono text-xs">{summary.slugs.join(", ") || "—"}</span>
        </DetailField>
        <DetailField label="Изменено">
          {summary.changed_at ? (
            <span className="text-xs">
              {new Date(summary.changed_at).toLocaleString("ru")}
              {summary.changed_by && ` · админ ${summary.changed_by.slice(0, 8)}…`}
            </span>
          ) : (
            <span className="text-xs text-[var(--text-secondary)]">—</span>
          )}
        </DetailField>
      </div>
    </section>
  );
}

export function VolumeBlock({ rows }: { rows: AdminProviderDetailOut["volume"] }) {
  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
        Объём
      </h3>
      {rows.length === 0 ? (
        <p className="text-sm text-[var(--text-secondary)]">Нет платежей за период.</p>
      ) : (
        <ul className="space-y-1 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-3 text-sm">
          {rows.map((r) => (
            <li key={r.currency} className="flex items-center justify-between">
              <span className="font-medium">{formatMoney(r.amount, r.currency)}</span>
              <span className="text-xs text-[var(--text-secondary)]">{r.count} платежей</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function SuccessRateBlock({ rate }: { rate: AdminProviderDetailOut["success_rate"] }) {
  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
        Успешность
      </h3>
      <div className="grid grid-cols-4 gap-3 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-3 text-sm">
        <DetailField label="Успешно">
          <span className="text-[var(--success-fg)]">{rate.succeeded}</span>
        </DetailField>
        <DetailField label="Ошибка">
          <span className="text-[var(--danger-fg)]">{rate.failed}</span>
        </DetailField>
        <DetailField label="Ожидание">
          <span>{rate.pending}</span>
        </DetailField>
        <DetailField label="% успеха">
          <span className="font-semibold">{rate.success_pct.toFixed(1)}%</span>
        </DetailField>
      </div>
    </section>
  );
}

export function IncidentsBlock({ incidents }: { incidents: AdminProviderDetailOut["incidents"] }) {
  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
        Инциденты
      </h3>
      <div className="grid grid-cols-2 gap-3 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-3 text-sm">
        <DetailField label="Висящие платежи">
          <span className={incidents.stuck_pending > 0 ? "text-[var(--warning-fg)]" : ""}>
            {incidents.stuck_pending}
          </span>
        </DetailField>
        <DetailField label="Сбои webhook">
          <span className={incidents.failed_webhooks > 0 ? "text-[var(--danger-fg)]" : ""}>
            {incidents.failed_webhooks}
          </span>
        </DetailField>
      </div>
    </section>
  );
}

export function RecentPaymentsBlock({ rows }: { rows: RecentPaymentOut[] }) {
  const columns: Column<RecentPaymentOut>[] = [
    {
      key: "id",
      header: "ID / Order",
      render: (p) => (
        <div className="flex flex-col font-mono text-xs">
          <span>{p.id.slice(0, 8)}…</span>
          <span className="text-[var(--text-secondary)]">{p.order_id.slice(0, 8)}…</span>
        </div>
      ),
    },
    {
      key: "status",
      header: "Статус",
      render: (p) => (
        <Badge tone={STATUS_TONE[p.status]} dot>
          {STATUS_LABEL[p.status]}
        </Badge>
      ),
    },
    {
      key: "amount",
      header: "Сумма",
      render: (p) => formatMoney(p.amount, p.currency),
      className: "text-right",
    },
    {
      key: "created",
      header: "Создан",
      render: (p) => new Date(p.created_at).toLocaleString("ru"),
    },
  ];

  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
        Последние платежи
      </h3>
      <DataTable
        rows={rows}
        columns={columns}
        rowKey={(p) => p.id}
        empty="Платежей за период нет."
        sortable={false}
      />
    </section>
  );
}

function DetailField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] font-medium uppercase text-[var(--text-tertiary)]">{label}</p>
      <div className="mt-0.5">{children}</div>
    </div>
  );
}
