import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { useState } from "react";

import { fmtDate, type PayoutDetailOut, type PayoutListOut, type PayoutOut } from "./types";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState } from "@/components/States";
import { useToast } from "@/components/Toast";
import { apiGet, apiPost } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";
import { formatMoney } from "@/lib/money";

const STATUS_LABEL: Record<string, string> = {
  requested: "в обработке",
  approved: "в обработке",
  paid: "выплачено",
  rejected: "отклонено",
};

/**
 * The withdrawal queue.
 *
 * The list carries four digits of the card. The full number arrives only when
 * an admin opens one request, from a separate endpoint — this screen is open
 * all day and could be screenshotted, while the detail view is opened
 * deliberately at the moment a transfer is about to be made.
 */
export function PayoutsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [openId, setOpenId] = useState<string | null>(null);
  const [note, setNote] = useState("");

  const query = useQuery<PayoutListOut>({
    queryKey: ["admin", "affiliate", "payouts"],
    queryFn: () => apiGet<PayoutListOut>("/api/v1/admin/affiliate/payouts"),
  });

  // Fetched only while a request is open. Nothing prefetches it, and it is
  // dropped from the cache as soon as the panel closes.
  const detail = useQuery<PayoutDetailOut>({
    queryKey: ["admin", "affiliate", "payout", openId],
    queryFn: () => apiGet<PayoutDetailOut>(`/api/v1/admin/affiliate/payouts/${openId ?? ""}`),
    enabled: openId !== null,
    gcTime: 0,
    staleTime: 0,
  });

  const invalidate = async (): Promise<void> => {
    setOpenId(null);
    setNote("");
    await qc.invalidateQueries({ queryKey: ["admin", "affiliate"] });
  };

  const markPaid = useMutation({
    mutationFn: (id: string) =>
      apiPost<PayoutOut>(`/api/v1/admin/affiliate/payouts/${id}/paid`, { note: note || null }),
    onSuccess: async () => {
      toast.success("Отмечено как выплачено");
      await invalidate();
    },
    onError: (err: unknown) => {
      toast.error(extractApiMessage(err));
    },
  });

  const rejectPayout = useMutation({
    mutationFn: (id: string) =>
      apiPost<PayoutOut>(`/api/v1/admin/affiliate/payouts/${id}/reject`, { note: note || null }),
    onSuccess: async () => {
      toast.success("Заявка отклонена, деньги вернулись партнёру");
      await invalidate();
    },
    onError: (err: unknown) => {
      toast.error(extractApiMessage(err));
    },
  });

  function confirmPaid(id: string, amount: string, currency: string): void {
    // The only irreversible action in the programme. Rejecting returns the
    // money; "paid" asserts a transfer happened and cannot be undone.
    const ok = window.confirm(
      `Отметить ${formatMoney(amount, currency)} как выплаченные?\n\n` +
        "Это необратимо: деньги спишутся с резерва и заявка закроется. " +
        "Отмечайте только после того, как перевод действительно ушёл.",
    );
    if (ok) markPaid.mutate(id);
  }

  const columns: Column<PayoutOut>[] = [
    {
      key: "partner",
      header: "Партнёр",
      render: (row) => <span className="text-sm">{row.partner_email}</span>,
      sortAccessor: (row) => row.partner_email,
    },
    {
      key: "amount",
      header: "Сумма",
      render: (row) => <span className="font-medium">{formatMoney(row.amount, row.currency)}</span>,
      sortAccessor: (row) => Number(row.amount),
    },
    {
      key: "card",
      header: "Карта",
      // Four digits here on purpose — see the module docstring.
      render: (row) => (
        <span className="text-muted text-sm">
          ···· {row.card_last4} · {row.card_holder}
        </span>
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
      header: "Создана",
      render: (row) => <span className="text-muted text-xs">{fmtDate(row.created_at)}</span>,
      sortAccessor: (row) => row.created_at,
    },
    {
      key: "actions",
      header: "",
      render: (row) =>
        row.status === "requested" || row.status === "approved" ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setOpenId(row.id);
              setNote("");
            }}
          >
            Открыть
          </Button>
        ) : null,
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader title="Выплаты партнёрам" />

      {openId !== null && (
        <div className="border-border bg-subtle/40 space-y-3 rounded-lg border p-4">
          {detail.isPending ? (
            <p className="text-muted text-sm">Загружаем…</p>
          ) : detail.isError ? (
            <ErrorState onRetry={() => void detail.refetch()} />
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-3">
                <div>
                  <span className="text-muted block text-xs">Партнёр</span>
                  <span className="text-sm">{detail.data.partner_email}</span>
                </div>
                <div>
                  <span className="text-muted block text-xs">Сумма</span>
                  <span className="font-medium">
                    {formatMoney(detail.data.amount, detail.data.currency)}
                  </span>
                </div>
                <div>
                  <span className="text-muted block text-xs">Карта получателя</span>
                  {/* The one place a full card number is shown anywhere. The
                      admin is about to type it into a banking app. */}
                  <span className="select-all font-mono text-sm">{detail.data.card_number}</span>
                  <span className="text-muted block text-xs">{detail.data.card_holder}</span>
                </div>
              </div>

              <Input
                value={note}
                onChange={(e) => {
                  setNote(e.target.value);
                }}
                placeholder="Комментарий (необязательно)"
              />

              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  onClick={() => {
                    confirmPaid(detail.data.id, detail.data.amount, detail.data.currency);
                  }}
                  disabled={markPaid.isPending}
                >
                  Выплачено
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    rejectPayout.mutate(detail.data.id);
                  }}
                  disabled={rejectPayout.isPending}
                >
                  Отклонить и вернуть деньги
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setOpenId(null);
                  }}
                >
                  Закрыть
                </Button>
              </div>
            </>
          )}
        </div>
      )}

      {query.isError ? (
        <ErrorState onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          columns={columns}
          rows={query.data?.items ?? []}
          loading={query.isPending}
          empty="Заявок на вывод нет"
          rowKey={(row) => row.id}
        />
      )}
    </div>
  );
}
