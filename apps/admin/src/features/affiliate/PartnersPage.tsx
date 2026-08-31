import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { fmtDate, type PartnerListOut, type PartnerOut } from "./types";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState } from "@/components/States";
import { apiGet } from "@/lib/api";

const STATUS_LABEL: Record<string, string> = {
  pending: "ожидает",
  active: "активен",
  suspended: "отключён",
  rejected: "отклонён",
};

/**
 * Everyone in the programme, as a plain list. Everything an admin *does* to a
 * partner — codes, editing, switching on and off, stats — lives on the detail
 * page a row click opens; doing it inline here is how the list grew a code
 * form that could not see the codes it had already issued.
 */
export function PartnersPage() {
  const navigate = useNavigate();

  const query = useQuery<PartnerListOut>({
    queryKey: ["admin", "affiliate", "partners"],
    queryFn: () => apiGet<PartnerListOut>("/api/v1/admin/affiliate/partners"),
  });

  const columns: Column<PartnerOut>[] = [
    {
      key: "email",
      header: "Партнёр",
      render: (row) => (
        <div>
          <div className="font-medium">{row.display_name ?? row.email}</div>
          <div className="text-muted text-xs">{row.email}</div>
        </div>
      ),
      sortAccessor: (row) => row.email,
    },
    {
      key: "channel",
      header: "Канал",
      render: (row) => (
        <span className="text-muted max-w-64 truncate text-xs">{row.channel ?? "—"}</span>
      ),
    },
    {
      key: "status",
      header: "Статус",
      render: (row) => <span className="text-sm">{STATUS_LABEL[row.status] ?? row.status}</span>,
      sortAccessor: (row) => row.status,
    },
    {
      key: "created",
      header: "С нами с",
      render: (row) => <span className="text-muted text-xs">{fmtDate(row.created_at)}</span>,
      sortAccessor: (row) => row.created_at,
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader title="Партнёры" />
      {query.isError ? (
        <ErrorState onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          columns={columns}
          rows={query.data?.items ?? []}
          loading={query.isPending}
          empty="Партнёров пока нет"
          rowKey={(row) => row.id}
          onRowClick={(row) => {
            void navigate(`/affiliate/partners/${row.id}`);
          }}
        />
      )}
    </div>
  );
}
