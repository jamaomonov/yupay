/** Tail of supplier interactions for a given slug.
 *
 * Renders the last 50 ``fulfillment_attempts`` rows whose parent task uses
 * the supplier. PII / secrets never reach the payload column — the
 * fulfiller's redact policy strips them at write time. */

import { useQuery } from "@tanstack/react-query";

import type { AttemptListOut, AttemptRow } from "./types";

import { CopyId } from "@/components/CopyId";
import { DataTable, type Column } from "@/components/DataTable";
import { Spinner } from "@/components/States";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

interface Props {
  supplier: string;
  /** Optional row limit override. Default 50 covers ~one shift of work for the
   *  high-volume voucher path. */
  limit?: number;
}

export function G2bAttemptsTab({ supplier, limit = 50 }: Props) {
  const query = useQuery<AttemptListOut>({
    queryKey: qk.integrationAttempts({ supplier }),
    queryFn: () =>
      apiGet<AttemptListOut>(
        `/api/v1/admin/fulfillment/attempts?supplier=${encodeURIComponent(supplier)}&limit=${limit.toString()}`,
      ),
    refetchInterval: 30_000,
  });

  if (query.isLoading) {
    return <Spinner label="Загружаем журнал…" />;
  }

  const columns: Column<AttemptRow>[] = [
    {
      key: "created_at",
      header: "Когда",
      render: (r) => (
        <div className="flex flex-col">
          <span className="text-sm">{formatDateTime(r.created_at)}</span>
          <span className="text-[10px] text-[var(--text-tertiary)]">{ago(r.created_at)}</span>
        </div>
      ),
      className: "w-40",
    },
    {
      key: "kind",
      header: "Операция",
      render: (r) => (
        <span className="rounded-md bg-[var(--bg-muted)] px-2 py-0.5 font-mono text-xs">
          {r.kind}
        </span>
      ),
    },
    {
      key: "status",
      header: "Статус",
      render: (r) => {
        const tone =
          r.status === "ok"
            ? "bg-[var(--bg-accent-soft)] text-[var(--accent-soft-fg)]"
            : "bg-[var(--bg-muted)] text-[var(--danger)]";
        return (
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}>{r.status}</span>
        );
      },
    },
    {
      key: "task_id",
      header: "Задача",
      render: (r) => <CopyId value={r.task_id} className="text-xs text-[var(--text-secondary)]" />,
    },
    {
      key: "payload",
      header: "Payload",
      render: (r) => (
        <details>
          <summary className="cursor-pointer text-xs text-[var(--text-secondary)]">
            {Object.keys(r.payload).length === 0 ? "—" : "Показать"}
          </summary>
          <pre className="mt-1 max-w-md overflow-x-auto rounded bg-[var(--bg-muted)] p-2 text-[10px]">
            {JSON.stringify(r.payload, null, 2)}
          </pre>
        </details>
      ),
    },
    {
      key: "error",
      header: "Ошибка",
      render: (r) =>
        r.error ? (
          <span className="text-xs text-[var(--danger)]">{r.error}</span>
        ) : (
          <span className="text-[var(--text-tertiary)]">—</span>
        ),
    },
  ];

  return (
    <DataTable
      rows={query.data?.items ?? []}
      columns={columns}
      rowKey={(r) => `${r.task_id}-${r.created_at}`}
      ariaLabel={`Журнал попыток ${supplier}`}
      empty="Поставщика ещё ни разу не дёргали — пуск первого заказа создаст первую запись."
      loading={query.isLoading}
      busy={query.isFetching}
    />
  );
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("ru", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function ago(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(diff)) return "—";
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s.toString()} с назад`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m.toString()} мин назад`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h.toString()} ч назад`;
  return `${Math.floor(h / 24).toString()} д назад`;
}
