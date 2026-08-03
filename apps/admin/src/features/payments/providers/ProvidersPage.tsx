/**
 * Payment providers — admin control panel (`/payments/providers`).
 *
 * Lists every logical payment provider (the admin-facing grouping over one
 * or more gateway slugs, e.g. Click groups `click`+`uzcard`+`humo`) with its
 * current admin-controlled state, whether server-side config is present,
 * and who last changed it. Row click opens `<ProviderDetailDrawer>` with
 * the per-provider analytics + the disable/maintenance/enable actions.
 */

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { ProviderDetailDrawer } from "./ProviderDetailDrawer";
import { STATE_LABEL, STATE_TONE } from "./types";

import type { AdminProviderListOut, AdminProviderSummary } from "./types";

import { Badge } from "@/components/Badge";
import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState } from "@/components/States";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

export function ProvidersPage() {
  const [selected, setSelected] = useState<string | null>(null);

  const query = useQuery<AdminProviderListOut>({
    queryKey: qk.paymentProviders(),
    queryFn: () => apiGet<AdminProviderListOut>("/api/v1/admin/payments/providers"),
  });

  const columns: Column<AdminProviderSummary>[] = [
    {
      key: "provider",
      header: "Провайдер",
      render: (p) => (
        <div className="flex flex-col">
          <span className="font-medium">{p.display_name}</span>
          <span className="font-mono text-xs text-[var(--text-secondary)]">{p.provider}</span>
        </div>
      ),
      sortAccessor: (p) => p.display_name,
    },
    {
      key: "state",
      header: "Статус",
      render: (p) => (
        <Badge tone={STATE_TONE[p.state]} dot>
          {STATE_LABEL[p.state]}
        </Badge>
      ),
      className: "w-36",
      sortAccessor: (p) => p.state,
    },
    {
      key: "config",
      header: "Конфиг",
      render: (p) =>
        p.config_available ? (
          <span className="text-xs text-[var(--success-fg)]">Настроен</span>
        ) : (
          <span className="text-xs text-[var(--danger-fg)]">Нет конфига</span>
        ),
      className: "w-32",
      sortAccessor: (p) => (p.config_available ? 1 : 0),
    },
    {
      key: "slugs",
      header: "Слаги",
      render: (p) => <span className="font-mono text-xs">{p.slugs.join(", ") || "—"}</span>,
    },
    {
      key: "changed",
      header: "Изменён",
      render: (p) =>
        p.changed_at ? (
          <div className="flex flex-col text-xs">
            <span>{new Date(p.changed_at).toLocaleString("ru")}</span>
            {p.changed_by && (
              <span className="text-[var(--text-secondary)]">
                админ {p.changed_by.slice(0, 8)}…
              </span>
            )}
          </div>
        ) : (
          <span className="text-xs text-[var(--text-secondary)]">—</span>
        ),
      className: "w-48",
      sortAccessor: (p) => p.changed_at ?? "",
    },
  ];

  return (
    <div>
      <PageHeader
        title="Провайдеры оплаты"
        description="Состояние платёжных провайдеров: включение, отключение, тех. работы."
      />

      {query.isError ? (
        <ErrorState
          description={(query.error as Error | undefined)?.message ?? "Ошибка сети."}
          onRetry={() => void query.refetch()}
          retryPending={query.isFetching}
        />
      ) : (
        <DataTable
          rows={query.data?.providers ?? []}
          columns={columns}
          rowKey={(p) => p.provider}
          loading={query.isPending}
          empty="Провайдеров нет."
          selectedKey={selected}
          onRowClick={(p) => {
            setSelected(p.provider);
          }}
        />
      )}

      {selected && (
        <ProviderDetailDrawer
          provider={selected}
          onClose={() => {
            setSelected(null);
          }}
        />
      )}
    </div>
  );
}
