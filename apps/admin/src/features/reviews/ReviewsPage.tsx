/**
 * Review moderation. Post-moderation: reviews publish immediately, and this is
 * where an operator pulls the abusive ones.
 *
 * Two blocks over one queue. The feed answers "what came in just now", which is
 * the daily job; the by-brand block answers "which brand is having a problem",
 * which is the weekly one. Both render the same row component, so an action
 * behaves identically wherever it is taken.
 *
 * The page used to be a single flat table whose brand column held two raw
 * UUIDs — an operator had to open each one to learn what the row was about.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Filter, MessageSquare, ShieldCheck } from "lucide-react";
import { useMemo } from "react";

import { ReviewRow } from "./ReviewRow";
import type { AdminBrandReviewStatsList, AdminReviewList } from "./types";

import { Badge } from "@/components/Badge";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { EmptyState, ErrorState, Skeleton, Spinner } from "@/components/States";
import { localizeStatus } from "@/components/StatusChip";
import { Tabs } from "@/components/Tabs";
import { Thumb } from "@/components/Thumb";
import { useToast } from "@/components/Toast";
import { type ApiError, apiGet, apiPost } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";
import { useSearchParamsState } from "@/lib/useSearchParamsState";

type StatusFilter = "all" | "published" | "hidden" | "removed";
const FILTERS: StatusFilter[] = ["all", "published", "hidden", "removed"];

type ModerateAction = "hide" | "unhide" | "remove";
const MODERATE_DONE: Record<ModerateAction, string> = {
  hide: "Отзыв скрыт",
  unhide: "Отзыв возвращён на витрину",
  remove: "Отзыв удалён",
};

/** How many rows the feed shows. "Recent" stops meaning anything past a screenful
 *  or two; the by-brand block is where the rest is reached. */
const FEED_LIMIT = 30;

function filterLabel(f: StatusFilter): string {
  return f === "all" ? "Все" : localizeStatus("reviewStatus", f).label;
}

function reviewsUrl(params: Record<string, string>): string {
  return `/api/v1/admin/reviews?${new URLSearchParams(params).toString()}`;
}

export function ReviewsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  // In the URL, like the other admin lists: a filtered view survives the trip
  // to a customer card and back, and can be pasted into a ticket.
  const [status, setStatus] = useSearchParamsState<StatusFilter>("status", "all");
  const [reportedRaw, setReportedRaw] = useSearchParamsState("reported", "");
  const [openBrand, setOpenBrand] = useSearchParamsState("brand", "");
  const reported = reportedRaw === "1";

  const listParams: Record<string, string> = { limit: String(FEED_LIMIT) };
  if (status !== "all") listParams.status = status;
  if (reported) listParams.reported = "true";

  const feed = useQuery<AdminReviewList>({
    queryKey: ["admin", "reviews", "feed", status, reported],
    queryFn: () => apiGet<AdminReviewList>(reviewsUrl(listParams)),
    refetchInterval: 30_000,
  });

  const brands = useQuery<AdminBrandReviewStatsList>({
    queryKey: ["admin", "reviews", "by-brand"],
    queryFn: () => apiGet<AdminBrandReviewStatsList>("/api/v1/admin/reviews/by-brand"),
  });

  // Only when a brand is open: the queue is capped, so a brand's own list is
  // its own request rather than a filter over what the feed happened to load.
  const brandFeed = useQuery<AdminReviewList>({
    queryKey: ["admin", "reviews", "brand", openBrand, status, reported],
    queryFn: () =>
      apiGet<AdminReviewList>(reviewsUrl({ ...listParams, limit: "200", brand: openBrand })),
    enabled: openBrand !== "",
  });

  const moderate = useMutation<void, ApiError, { id: string; action: ModerateAction }>({
    mutationFn: async ({ id, action }) => {
      await apiPost(
        `/api/v1/admin/reviews/${id}/${action}`,
        {},
        { "Idempotency-Key": crypto.randomUUID() },
      );
    },
    onSuccess: (_data, { action }) => {
      toast.success(MODERATE_DONE[action]);
      void qc.invalidateQueries({ queryKey: ["admin", "reviews"] });
    },
    onError: (err) => {
      toast.error(extractApiMessage(err));
    },
  });

  const rows = brands.data?.items ?? [];
  const totals = useMemo(() => {
    const total = rows.reduce((s, b) => s + b.total, 0);
    const reportedSum = rows.reduce((s, b) => s + b.reported, 0);
    // Weighted, not an average of averages — a brand with two reviews must not
    // count as much as one with two hundred.
    const weighted = rows.reduce((s, b) => s + b.avg_rating * b.total, 0);
    return { total, reported: reportedSum, avg: total ? weighted / total : 0, brands: rows.length };
  }, [rows]);

  const filtered = status !== "all" || reported;
  const resetFilters = () => {
    setStatus("all");
    setReportedRaw("");
  };

  const onModerate = (id: string) => (action: ModerateAction) => {
    if (action === "remove" && !confirm("Удалить отзыв? Он исчезнет с витрины бренда.")) return;
    moderate.mutate({ id, action });
  };
  const busyFor = (id: string) => moderate.isPending && moderate.variables?.id === id;

  return (
    <div>
      <PageHeader
        title="Отзывы"
        description="Отзывы публикуются сразу. Здесь их снимают с витрины."
      />

      <section className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="Всего отзывов" value={brands.isLoading ? "—" : totals.total} accent />
        <StatCard
          label="Средняя оценка"
          value={brands.isLoading ? "—" : totals.avg.toFixed(1)}
          mono
        />
        {/* The one tile that asks for work, so it is also the way into it. */}
        <button
          type="button"
          onClick={() => {
            setReportedRaw(reported ? "" : "1");
          }}
          className="text-left"
          title={reported ? "Показать все отзывы" : "Показать только отзывы с жалобами"}
        >
          <StatCard
            label="С жалобами"
            value={brands.isLoading ? "—" : totals.reported}
            tone={totals.reported > 0 ? "warn" : "muted"}
          />
        </button>
        <StatCard
          label="Брендов с отзывами"
          value={brands.isLoading ? "—" : totals.brands}
          tone="muted"
        />
      </section>

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <Tabs
          value={status}
          onChange={setStatus}
          ariaLabel="Фильтр по статусу отзыва"
          tabs={FILTERS.map((f) => ({ id: f, label: filterLabel(f) }))}
        />
        <label className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
          <input
            type="checkbox"
            checked={reported}
            onChange={(e) => {
              setReportedRaw(e.target.checked ? "1" : "");
            }}
            className="size-4"
          />
          Только с жалобами
        </label>
        {filtered && (
          <button
            type="button"
            onClick={resetFilters}
            className="ml-auto text-xs text-[var(--text-secondary)] hover:underline"
          >
            Сбросить фильтры
          </button>
        )}
      </div>

      {/* ---------- Последние отзывы ---------- */}
      <section className="mb-8">
        <header className="mb-2 flex items-center gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
            Последние отзывы
          </h2>
          {feed.isFetching && !feed.isLoading && <Spinner size="sm" />}
        </header>

        {feed.isError ? (
          <ErrorState
            description={extractApiMessage(feed.error)}
            onRetry={() => void feed.refetch()}
            retryPending={feed.isFetching}
          />
        ) : feed.isLoading ? (
          <div className="rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
            <Skeleton rows={5} className="h-12" />
          </div>
        ) : (feed.data?.items.length ?? 0) === 0 ? (
          reported ? (
            /* Good news, and it must not be dressed as "nothing found". */
            <EmptyState
              icon={ShieldCheck}
              title="Жалоб нет"
              description="Ничего не требует модерации."
              tone="muted"
            />
          ) : filtered ? (
            <EmptyState icon={Filter} title="Под фильтр ничего не подошло" />
          ) : (
            <EmptyState
              icon={MessageSquare}
              title="Отзывов пока нет"
              description="Они появятся, когда покупатели начнут оценивать заказы."
            />
          )
        ) : (
          <ul className="divide-y divide-[var(--border-subtle)] overflow-hidden rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)]">
            {(feed.data?.items ?? []).map((r) => (
              <ReviewRow
                key={r.id}
                review={r}
                onPickBrand={setOpenBrand}
                onModerate={onModerate(r.id)}
                busy={busyFor(r.id)}
              />
            ))}
          </ul>
        )}
      </section>

      {/* ---------- По брендам ---------- */}
      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
          По брендам
        </h2>

        {brands.isError ? (
          <ErrorState
            description={extractApiMessage(brands.error)}
            onRetry={() => void brands.refetch()}
            retryPending={brands.isFetching}
          />
        ) : brands.isLoading ? (
          <Skeleton rows={5} className="h-14" />
        ) : rows.length === 0 ? (
          <EmptyState icon={MessageSquare} title="Ни у одного бренда пока нет отзывов" />
        ) : (
          <div className="space-y-2">
            {rows.map((b) => {
              const slug = b.brand_slug ?? "";
              const isOpen = openBrand !== "" && openBrand === slug;
              const label = b.brand_name ?? b.brand_slug ?? "бренд удалён";
              return (
                <article
                  key={slug || label}
                  id={`brand-${slug}`}
                  className={`overflow-hidden rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)] ${
                    b.reported > 0 ? "shadow-[inset_3px_0_0_0_var(--danger)]" : ""
                  }`}
                >
                  <button
                    type="button"
                    aria-expanded={isOpen}
                    onClick={() => {
                      setOpenBrand(isOpen ? "" : slug);
                    }}
                    className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-[var(--bg-accent-soft)]"
                  >
                    <Thumb src={b.brand_logo_url} name={label} size={32} />
                    <span className="font-medium">{label}</span>
                    <code className="hidden text-xs text-[var(--text-secondary)] sm:inline">
                      {b.brand_slug}
                    </code>
                    <span className="ml-auto flex items-center gap-3 text-xs">
                      <span className="font-mono text-[var(--text-secondary)]">
                        ★ {b.avg_rating.toFixed(1)}
                      </span>
                      <span className="hidden text-[var(--text-secondary)] sm:inline">
                        {b.total} отзывов
                      </span>
                      {b.reported > 0 && (
                        <Badge tone="bg-[var(--danger-soft)] text-[var(--danger-fg)]">
                          {b.reported}
                        </Badge>
                      )}
                      <ChevronDown
                        aria-hidden
                        className={`size-4 text-[var(--text-secondary)] transition-transform ${
                          isOpen ? "rotate-180" : ""
                        }`}
                      />
                    </span>
                  </button>

                  {isOpen && (
                    <div className="border-t">
                      {filtered && (
                        <p className="border-b px-4 py-2 text-xs text-[var(--text-secondary)]">
                          Показаны только: {status !== "all" ? filterLabel(status) : "все статусы"}
                          {reported ? " · с жалобами" : ""}
                        </p>
                      )}
                      {brandFeed.isLoading ? (
                        <div className="py-8">
                          <Spinner label="Загрузка отзывов…" />
                        </div>
                      ) : (brandFeed.data?.items.length ?? 0) === 0 ? (
                        /* A full-size empty state inside an accordion reads as
                           a broken panel; one line does the job. */
                        <p className="px-4 py-6 text-center text-sm text-[var(--text-secondary)]">
                          У бренда нет отзывов под текущий фильтр.
                        </p>
                      ) : (
                        <ul className="divide-y divide-[var(--border-subtle)]">
                          {(brandFeed.data?.items ?? []).map((r) => (
                            <ReviewRow
                              key={r.id}
                              review={r}
                              showBrand={false}
                              onModerate={onModerate(r.id)}
                              busy={busyFor(r.id)}
                            />
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
