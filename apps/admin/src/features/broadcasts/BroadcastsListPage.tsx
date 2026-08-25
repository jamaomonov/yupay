import { useQuery } from "@tanstack/react-query";
import { Button, Select } from "@yupay/ui";
import { Plus } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { STATUS_LABEL, STATUS_TONE } from "./types";

import type { BroadcastListOut, BroadcastOut, BroadcastStatus } from "./types";

import { CopyId } from "@/components/CopyId";
import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState } from "@/components/States";
import { apiGet } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";
import { qk } from "@/lib/queryKeys";
import { UserRef } from "@/components/UserRef";
import { useAdminRefs } from "@/lib/useAdminRefs";

const STATUS_FILTERS: { value: BroadcastStatus | ""; label: string }[] = [
  { value: "", label: "Все" },
  { value: "draft", label: STATUS_LABEL.draft },
  { value: "scheduled", label: STATUS_LABEL.scheduled },
  { value: "sending", label: STATUS_LABEL.sending },
  { value: "sent", label: STATUS_LABEL.sent },
  { value: "failed", label: STATUS_LABEL.failed },
  { value: "canceled", label: STATUS_LABEL.canceled },
];

function fmtDate(iso: string): string {
  return new Intl.DateTimeFormat("ru", { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(iso),
  );
}

function StatusBadge({ status }: { status: BroadcastStatus }) {
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_TONE[status]}`}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}

export function BroadcastsListPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<BroadcastStatus | "">("");

  const listQuery = useQuery<BroadcastListOut>({
    queryKey: qk.broadcasts({ status: status || null }),
    queryFn: () => {
      const params = new URLSearchParams();
      if (status) params.set("status_filter", status);
      return apiGet<BroadcastListOut>(`/api/v1/admin/broadcasts?${params.toString()}`);
    },
  });

  const items = listQuery.data?.items ?? [];
  const refs = useAdminRefs(items.map((b) => b.created_by));

  const columns: Column<BroadcastOut>[] = [
    {
      key: "title",
      header: "Заголовок",
      render: (b) => <span className="font-medium">{b.title}</span>,
    },
    {
      key: "status",
      header: "Статус",
      render: (b) => <StatusBadge status={b.status} />,
      className: "w-36",
    },
    {
      key: "audience",
      header: "Аудитория",
      render: (b) => <span className="font-mono">{b.total_recipients.toLocaleString("ru")}</span>,
      className: "w-28 text-right",
    },
    {
      key: "sent",
      // Header reads "Успешно" (not "Отправлено") so it never collides with
      // the "Отправлено" status-badge label in the row above it.
      header: "Успешно",
      render: (b) => <span className="font-mono text-[var(--success-fg)]">{b.sent_count}</span>,
      className: "w-24 text-right",
    },
    {
      key: "failed",
      header: "Ошибки",
      render: (b) => <span className="font-mono text-[var(--danger-fg)]">{b.failed_count}</span>,
      className: "w-20 text-right",
    },
    {
      key: "blocked",
      header: "Заблок.",
      render: (b) => (
        <span className="font-mono text-[var(--text-secondary)]">{b.blocked_count}</span>
      ),
      className: "w-20 text-right",
    },
    {
      key: "created_at",
      header: "Когда",
      render: (b) => <span className="text-[var(--text-secondary)]">{fmtDate(b.created_at)}</span>,
      className: "w-48",
    },
    {
      key: "created_by",
      header: "Автор",
      render: (b) => (
        <UserRef id={b.created_by} data={refs.user(b.created_by)} className="text-xs" />
      ),
      className: "w-28",
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Рассылки"
        description="Сообщения в Telegram по сегменту пользователей."
        actions={
          <Button
            onClick={() => {
              void navigate("/broadcasts/new");
            }}
          >
            <Plus className="size-4" />
            Новая рассылка
          </Button>
        }
      />

      <section className="max-w-xs">
        <Select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as BroadcastStatus | "");
          }}
          aria-label="Фильтр по статусу"
          containerClassName="w-auto"
        >
          {STATUS_FILTERS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </Select>
      </section>

      {listQuery.isError ? (
        <ErrorState
          description={extractApiMessage(listQuery.error)}
          onRetry={() => void listQuery.refetch()}
          retryPending={listQuery.isFetching}
        />
      ) : (
        <DataTable
          rows={items}
          columns={columns}
          rowKey={(b) => b.id}
          loading={listQuery.isLoading}
          empty="Рассылок пока нет — создайте первую выше."
          ariaLabel="Рассылки"
          busy={listQuery.isFetching}
          onRowClick={(b) => navigate(`/broadcasts/${b.id}`)}
        />
      )}
    </div>
  );
}
