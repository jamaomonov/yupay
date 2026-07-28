/**
 * Review moderation queue. Lists reviews (optionally filtered by status or
 * "reported only") and offers hide / unhide / remove actions. Post-moderation:
 * reviews publish immediately; this is where an operator pulls abusive ones.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { AdminReview, AdminReviewList } from "./types";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { apiGet, apiPost } from "@/lib/api";

type StatusFilter = "all" | "published" | "hidden" | "removed";

const STATUS_CLS: Record<string, string> = {
  published: "bg-emerald-500/15 text-emerald-400",
  hidden: "bg-amber-500/15 text-amber-400",
  removed: "bg-red-500/15 text-red-400",
};

const FILTERS: StatusFilter[] = ["all", "published", "hidden", "removed"];

function idemHeaders(): Record<string, string> {
  return { "Idempotency-Key": crypto.randomUUID() };
}

export function ReviewsPage() {
  const qc = useQueryClient();
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

  async function moderate(id: string, action: "hide" | "unhide" | "remove") {
    await apiPost(`/api/v1/admin/reviews/${id}/${action}`, {}, idemHeaders());
    await qc.invalidateQueries({ queryKey: ["admin", "reviews"] });
  }

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
          <span>{r.brand_id.slice(0, 8)}…</span>
          <span>{r.order_id.slice(0, 8)}…</span>
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
      render: (r) => (
        <span
          className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
            STATUS_CLS[r.status] ?? ""
          }`}
        >
          {r.status}
        </span>
      ),
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
              onClick={() => void moderate(r.id, "hide")}
            >
              Скрыть
            </button>
          ) : (
            <button
              type="button"
              className="text-emerald-400 hover:underline"
              onClick={() => void moderate(r.id, "unhide")}
            >
              Вернуть
            </button>
          )}
          {r.status !== "removed" && (
            <button
              type="button"
              className="text-red-400 hover:underline"
              onClick={() => void moderate(r.id, "remove")}
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
            {f}
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

      {query.isError && (
        <p className="mb-3 text-sm text-[var(--danger)]">
          Не удалось загрузить: {(query.error as Error | undefined)?.message ?? "ошибка сети"}
        </p>
      )}

      <DataTable
        rows={query.data?.items ?? []}
        columns={columns}
        rowKey={(r) => r.id}
        empty="Нет отзывов под фильтр."
      />
    </div>
  );
}
