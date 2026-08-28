import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { useState } from "react";

import {
  COMMISSION_RANGE,
  DISCOUNT_RANGE,
  fmtDate,
  type CodeOut,
  type PartnerListOut,
  type PartnerOut,
} from "./types";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState } from "@/components/States";
import { useToast } from "@/components/Toast";
import { apiGet, apiPost } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";

const STATUS_LABEL: Record<string, string> = {
  pending: "ожидает",
  active: "активен",
  suspended: "отключён",
  rejected: "отклонён",
};

/**
 * Everyone in the programme, and the two things an admin does to them: issue a
 * code and switch them off.
 *
 * The rate ranges are shown in the form rather than only enforced on submit.
 * The backend refuses anything outside them with a readable message, but being
 * told after typing is a worse way to learn a rule than being told before.
 */
export function PartnersPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [issuing, setIssuing] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [discount, setDiscount] = useState("5");
  const [commission, setCommission] = useState("2");

  const query = useQuery<PartnerListOut>({
    queryKey: ["admin", "affiliate", "partners"],
    queryFn: () => apiGet<PartnerListOut>("/api/v1/admin/affiliate/partners"),
  });

  const invalidate = async (): Promise<void> => {
    await qc.invalidateQueries({ queryKey: ["admin", "affiliate"] });
  };

  const issue = useMutation({
    mutationFn: (partnerId: string) =>
      apiPost<CodeOut>(`/api/v1/admin/affiliate/partners/${partnerId}/codes`, {
        code,
        discount_percent: discount,
        commission_percent: commission,
      }),
    onSuccess: async (created) => {
      toast.success(`Код ${created.code} выдан`);
      setIssuing(null);
      setCode("");
      await invalidate();
    },
    onError: (err: unknown) => {
      toast.error(extractApiMessage(err));
    },
  });

  const suspend = useMutation({
    mutationFn: (partnerId: string) =>
      apiPost<PartnerOut>(`/api/v1/admin/affiliate/partners/${partnerId}/suspend`, {}),
    onSuccess: async () => {
      toast.success("Партнёр отключён");
      await invalidate();
    },
    onError: (err: unknown) => {
      toast.error(extractApiMessage(err));
    },
  });

  function confirmSuspend(partner: PartnerOut): void {
    // Spelled out because "suspend" does not say either half: the code stops
    // working for buyers *and* the partner is signed out of their panel.
    const ok = window.confirm(
      `Отключить ${partner.email}?\n\n` +
        "Его промокод перестанет действовать на кассе, а сам он выйдет из панели. " +
        "Уже начисленная комиссия останется за ним.",
    );
    if (ok) suspend.mutate(partner.id);
  }

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
    {
      key: "actions",
      header: "",
      render: (row) =>
        issuing === row.id ? (
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-xs">
              <span className="text-muted mb-1 block">Код</span>
              <Input
                value={code}
                onChange={(e) => {
                  setCode(e.target.value.toUpperCase());
                }}
                placeholder="PARTNER10"
                className="w-36"
              />
            </label>
            <label className="text-xs">
              <span className="text-muted mb-1 block">
                Скидка {DISCOUNT_RANGE.min}–{DISCOUNT_RANGE.max}%
              </span>
              <Input
                value={discount}
                onChange={(e) => {
                  setDiscount(e.target.value);
                }}
                className="w-20"
              />
            </label>
            <label className="text-xs">
              <span className="text-muted mb-1 block">
                Комиссия {COMMISSION_RANGE.min}–{COMMISSION_RANGE.max}%
              </span>
              <Input
                value={commission}
                onChange={(e) => {
                  setCommission(e.target.value);
                }}
                className="w-20"
              />
            </label>
            <Button
              size="sm"
              onClick={() => {
                issue.mutate(row.id);
              }}
              disabled={issue.isPending || !code.trim()}
            >
              Выдать
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setIssuing(null);
              }}
            >
              Отмена
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setIssuing(row.id);
              }}
              disabled={row.status !== "active"}
            >
              Выдать код
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                confirmSuspend(row);
              }}
              disabled={row.status === "suspended" || suspend.isPending}
            >
              Отключить
            </Button>
          </div>
        ),
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
        />
      )}
    </div>
  );
}
