import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { useState } from "react";

import { fmtDate, type PartnerListOut, type PartnerOut } from "./types";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState } from "@/components/States";
import { useToast } from "@/components/Toast";
import { apiGet, apiPost } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";

/**
 * The application queue.
 *
 * Approving sends the applicant a set-password link; rejecting takes a note
 * that is stored but never shown to them. The queue is the first thing an
 * applicant experiences of this programme, and an unattended one reads to them
 * as silence — which is why the count is in the navigation.
 */
export function ApplicationsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [note, setNote] = useState<Record<string, string>>({});

  const query = useQuery<PartnerListOut>({
    queryKey: ["admin", "affiliate", "applications"],
    queryFn: () => apiGet<PartnerListOut>("/api/v1/admin/affiliate/applications"),
  });

  const invalidate = async (): Promise<void> => {
    await qc.invalidateQueries({ queryKey: ["admin", "affiliate"] });
  };

  const approve = useMutation({
    mutationFn: (id: string) =>
      apiPost<PartnerOut>(`/api/v1/admin/affiliate/applications/${id}/approve`, {}),
    onSuccess: async () => {
      toast.success("Заявка одобрена, письмо отправлено");
      await invalidate();
    },
    onError: (err: unknown) => {
      toast.error(extractApiMessage(err));
    },
  });

  const reject = useMutation({
    mutationFn: ({ id, text }: { id: string; text: string }) =>
      apiPost<PartnerOut>(`/api/v1/admin/affiliate/applications/${id}/reject`, {
        note: text || null,
      }),
    onSuccess: async () => {
      toast.success("Заявка отклонена");
      await invalidate();
    },
    onError: (err: unknown) => {
      toast.error(extractApiMessage(err));
    },
  });

  const columns: Column<PartnerOut>[] = [
    {
      key: "email",
      header: "Заявитель",
      render: (row) => (
        <div>
          <div className="font-medium">{row.display_name ?? row.email}</div>
          <div className="text-muted text-xs">{row.email}</div>
        </div>
      ),
      sortAccessor: (row) => row.email,
    },
    {
      key: "contact",
      header: "Контакт",
      render: (row) => <span className="text-sm">{row.contact ?? "—"}</span>,
    },
    {
      key: "channel",
      header: "Где продвигает",
      render: (row) => <span className="break-all text-sm">{row.channel ?? "—"}</span>,
    },
    {
      key: "created",
      header: "Подана",
      render: (row) => <span className="text-muted text-xs">{fmtDate(row.created_at)}</span>,
      sortAccessor: (row) => row.created_at,
    },
    {
      key: "actions",
      header: "",
      render: (row) => (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            onClick={() => {
              approve.mutate(row.id);
            }}
            disabled={approve.isPending}
          >
            Одобрить
          </Button>
          <Input
            value={note[row.id] ?? ""}
            onChange={(e) => {
              setNote((n) => ({ ...n, [row.id]: e.target.value }));
            }}
            placeholder="Причина отказа"
            className="w-44"
          />
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              reject.mutate({ id: row.id, text: note[row.id] ?? "" });
            }}
            disabled={reject.isPending}
          >
            Отклонить
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader title="Заявки в партнёрскую программу" />
      {query.isError ? (
        <ErrorState onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          columns={columns}
          rows={query.data?.items ?? []}
          loading={query.isPending}
          empty="Новых заявок нет"
          rowKey={(row) => row.id}
        />
      )}
    </div>
  );
}
