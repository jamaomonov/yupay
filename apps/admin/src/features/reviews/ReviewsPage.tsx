/**
 * Review moderation queue. Lists reviews (optionally filtered by status or
 * "reported only") and offers hide / unhide / remove actions. Post-moderation:
 * reviews publish immediately; this is where an operator pulls abusive ones.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { AdminReview, AdminReviewList } from "./types";

import { CopyId } from "@/components/CopyId";
import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState } from "@/components/States";
import { StatusChip, localizeStatus } from "@/components/StatusChip";
import { useToast } from "@/components/Toast";
import { type ApiError, apiGet, apiPost } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";

type StatusFilter = "all" | "published" | "hidden" | "removed";

const FILTERS: StatusFilter[] = ["all", "published", "hidden", "removed"];

function filterLabel(f: StatusFilter): string {
  return f === "all" ? "Все" : localizeStatus("reviewStatus", f).label;
}

function idemHeaders(): Record<string, string> {
  return { "Idempotency-Key": crypto.randomUUID() };
}

type ModerateAction = "hide" | "unhide" | "remove";

const MODERATE_DONE: Record<ModerateAction, string> = {
  hide: "Отзыв скрыт",
  unhide: "Отзыв возвращён на витрину",
  remove: "Отзыв удалён",
};

export function ReviewsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [status, setStatus] = useState<StatusFilter>("all");
  const [reported, setReported] = useState(false);

  const query = useQuery<AdminReviewList>({
    queryKey: ["admin", "reviews", status, reported],
    queryFn: () => {
      const params = new URLSearchParams({ limit: "200" });
      if (status !== "all") params.set("status", status);
      if (reported) params.set("reported", "true");
      return apiGet<AdminReviewList>(`/api/v1/admin/reviews?${params.toString()}`);
    },
    refetchInterval: 30_000,
  });

  // A plain async function swallowed every failure into an unhandled rejection:
  // hiding or deleting a review looked identical whether it worked or 500'd.
  // useMutation gives the operator a result and a pending state to key off.
  const moderate = useMutation<void, ApiError, { id: string; action: ModerateAction }>({
    mutationFn: async ({ id, action }) => {
      await apiPost(`/api/v1/admin/reviews/${id}/${action}`, {}, idemHeaders());
    },
    onSuccess: (_data, { action }) => {
      toast.success(MODERATE_DONE[action]);
      void qc.invalidateQueries({ queryKey: ["admin", "reviews"] });
    },
    onError: (err) => {
      toast.error(extractApiMessage(err));
    },
  });

  const columns: Column<AdminReview>[] = [
    {
      key: "rating",
      header: "Оценка",
      render: (r) => <span className="font-mono text-sm">{"★".repeat(r.rating)}</span>,
      sortAccessor: (r) => r.rating,
    },
    {
      key: "body",
      header: "Текст",
      render: (r) => (
        <span className="line-clamp-2 max-w-[360px] text-sm">
          {r.body ?? <span className="text-[var(--text-secondary)]">—</span>}
        </span>
      ),
    },
    {
      key: "brand",
      header: "Бренд / заказ",
      render: (r) => (
        <div className="flex flex-col font-mono text-xs text-[var(--text-secondary)]">
          <CopyId value={r.brand_id} to={`/brands/${r.brand_id}`} />
          <CopyId value={r.order_id} to={`/orders/${r.order_id}`} />
        </div>
      ),
    },
    {
      key: "reports",
      header: "Жалобы",
      className: "text-right",
      render: (r) => (
        <span className={r.report_count > 0 ? "font-semibold text-amber-400" : ""}>
          {r.report_count}
        </span>
      ),
      sortAccessor: (r) => r.report_count,
    },
    {
      key: "status",
      header: "Статус",
      render: (r) => <StatusChip domain="reviewStatus" value={r.status} />,
    },
    {
      key: "actions",
      header: "",
      render: (r) => (
        <div className="flex gap-2 text-xs">
          {r.status === "published" ? (
            <button
              type="button"
              className="text-amber-400 hover:underline"
              onClick={() => {
                moderate.mutate({ id: r.id, action: "hide" });
              }}
              disabled={moderate.isPending}
            >
              Скрыть
            </button>
          ) : (
            <button
              type="button"
              className="text-emerald-400 hover:underline"
              onClick={() => {
                moderate.mutate({ id: r.id, action: "unhide" });
              }}
              disabled={moderate.isPending}
            >
              Вернуть
            </button>
          )}
          {r.status !== "removed" && (
            <button
              type="button"
              className="text-red-400 hover:underline"
              onClick={() => {
                if (!confirm("Удалить отзыв? Он исчезнет с витрины бренда.")) return;
                moderate.mutate({ id: r.id, action: "remove" });
              }}
              disabled={moderate.isPending}
            >
              Удалить
            </button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeader title="Отзывы" description="Модерация отзывов: скрыть, вернуть или удалить." />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => {
              setStatus(f);
            }}
            className={`rounded-full px-3 py-1 text-xs font-semibold ${
              status === f
                ? "bg-[var(--accent)] text-black"
                : "bg-[var(--surface-2)] text-[var(--text-secondary)]"
            }`}
          >
            {filterLabel(f)}
          </button>
        ))}
        <label className="ml-2 flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
          <input
            type="checkbox"
            checked={reported}
            onChange={(e) => {
              setReported(e.target.checked);
            }}
          />
          Только с жалобами
        </label>
      </div>

      {query.isError ? (
        <ErrorState
          description={(query.error as Error | undefined)?.message ?? "Ошибка сети."}
          onRetry={() => void query.refetch()}
          retryPending={query.isFetching}
        />
      ) : (
        <DataTable
          rows={query.data?.items ?? []}
          columns={columns}
          rowKey={(r) => r.id}
          loading={query.isLoading}
          empty="Нет отзывов под фильтр."
        />
      )}
    </div>
  );
}
