/**
 * BroadcastDetailPage — live view of one broadcast: FSM status + delivery
 * counters, a cancel action while the broadcast is still `sending` or
 * `scheduled`, and a problem-recipients table (failed + blocked) once the
 * dispatch job has produced any.
 *
 * Polling: the detail query re-fetches every 3s only while `status ===
 * "sending"` — `refetchInterval` reads the *current* cached data
 * (`query.state.data`), not component state, so the interval turns itself
 * off the moment a poll comes back `sent`/`failed`/`canceled` without an
 * extra effect. Draft/scheduled/terminal states never change on their own
 * between admin actions, so they never poll at all.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, buttonVariants } from "@yupay/ui";
import { ArrowLeft, Ban } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { BroadcastPreview } from "./BroadcastPreview";
import { STATUS_LABEL, STATUS_TONE } from "./types";

import type { BroadcastOut, RecipientListOut, RecipientOut, RecipientStatus } from "./types";
import type { ReactNode } from "react";

import { Badge } from "@/components/Badge";
import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { Spinner } from "@/components/States";
import { useToast } from "@/components/Toast";
import { type ApiError, apiGet, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

/** `RecipientOut.status` → human label (ru) for the problem-recipients table. */
const RECIPIENT_STATUS_LABEL: Record<RecipientStatus, string> = {
  pending: "Ожидает",
  sent: "Отправлено",
  failed: "Ошибка",
  blocked: "Заблокирован",
};

/** Same semantic tone tokens as `STATUS_TONE` in `./types`. */
const RECIPIENT_STATUS_TONE: Record<RecipientStatus, string> = {
  pending: "bg-[var(--bg-muted)] text-[var(--text-secondary)]",
  sent: "bg-[var(--success-soft)] text-[var(--success-fg)]",
  failed: "bg-[var(--danger-soft)] text-[var(--danger-fg)]",
  blocked: "bg-[var(--warning-soft)] text-[var(--warning-fg)]",
};

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("ru", { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(iso),
  );
}

/** A fresh key per write call — every broadcast write endpoint requires one
 *  (Task 6). Mirrors `BroadcastComposerPage`'s `idemHeaders`. */
function idemHeaders(): HeadersInit {
  return { "Idempotency-Key": crypto.randomUUID() };
}

export function BroadcastDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id ?? "";
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();

  const detailQuery = useQuery<BroadcastOut>({
    queryKey: qk.broadcast(id),
    enabled: Boolean(id),
    queryFn: () => apiGet<BroadcastOut>(`/api/v1/admin/broadcasts/${id}`),
    refetchInterval: (query) => (query.state.data?.status === "sending" ? 3000 : false),
  });

  const broadcast = detailQuery.data;
  const failedCount = broadcast?.failed_count ?? 0;
  const blockedCount = broadcast?.blocked_count ?? 0;

  // Only fetched once the FSM has actually produced a problem row — an empty
  // broadcast (or one still sending cleanly) never issues these requests.
  const failedQuery = useQuery<RecipientListOut>({
    queryKey: qk.broadcastRecipients(id, "failed"),
    enabled: Boolean(id) && failedCount > 0,
    queryFn: () =>
      apiGet<RecipientListOut>(
        `/api/v1/admin/broadcasts/${id}/recipients?status=failed&limit=100&offset=0`,
      ),
  });

  const blockedQuery = useQuery<RecipientListOut>({
    queryKey: qk.broadcastRecipients(id, "blocked"),
    enabled: Boolean(id) && blockedCount > 0,
    queryFn: () =>
      apiGet<RecipientListOut>(
        `/api/v1/admin/broadcasts/${id}/recipients?status=blocked&limit=100&offset=0`,
      ),
  });

  const cancelMutation = useMutation<BroadcastOut, ApiError>({
    mutationFn: () =>
      apiPost<BroadcastOut>(`/api/v1/admin/broadcasts/${id}/cancel`, {}, idemHeaders()),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.broadcast(id) });
      void qc.invalidateQueries({ queryKey: qk.broadcasts() });
      toast.success("Рассылка отменена");
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Не удалось отменить рассылку");
    },
  });

  function handleCancelClick(): void {
    if (!window.confirm("Отменить отправку рассылки?")) return;
    cancelMutation.mutate();
  }

  if (detailQuery.isLoading) {
    return <Spinner label="Загрузка…" />;
  }
  if (detailQuery.isError || !broadcast) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-[var(--danger)]">Не удалось загрузить рассылку.</p>
        <Button variant="ghost" onClick={() => navigate("/broadcasts")}>
          <ArrowLeft className="size-4" />К списку
        </Button>
      </div>
    );
  }

  const done = broadcast.sent_count + broadcast.failed_count + broadcast.blocked_count;
  const total = broadcast.total_recipients;
  // Guard: `total_recipients` stays 0 until the dispatch job snapshots the
  // audience (draft, or a send/schedule just issued) — dividing then would
  // read as NaN/Infinity instead of a sane "not started yet" state.
  const progressLabel =
    total > 0
      ? `Обработано ${done.toLocaleString("ru")} из ${total.toLocaleString("ru")} (${Math.round(
          (done / total) * 100,
        ).toString()}%)`
      : "Запускается…";

  const canCancel = broadcast.status === "sending" || broadcast.status === "scheduled";
  const canEdit = broadcast.status === "draft";
  const showProblems = failedCount > 0 || blockedCount > 0;
  const problemRows = [...(failedQuery.data?.items ?? []), ...(blockedQuery.data?.items ?? [])];
  const problemsLoading =
    (failedCount > 0 && failedQuery.isLoading) || (blockedCount > 0 && blockedQuery.isLoading);

  const problemColumns: Column<RecipientOut>[] = [
    {
      key: "tg_chat_id",
      header: "Chat ID",
      render: (r) => <code className="text-xs">{r.tg_chat_id}</code>,
      className: "w-40",
    },
    {
      key: "status",
      header: "Статус",
      render: (r) => (
        <Badge tone={RECIPIENT_STATUS_TONE[r.status]} dot>
          {RECIPIENT_STATUS_LABEL[r.status]}
        </Badge>
      ),
      className: "w-36",
    },
    {
      key: "error",
      header: "Ошибка",
      render: (r) => <span className="text-[var(--text-secondary)]">{r.error ?? "—"}</span>,
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumbs={[{ label: "Рассылки", to: "/broadcasts" }, { label: broadcast.title }]}
        title={broadcast.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={STATUS_TONE[broadcast.status]} dot>
              {STATUS_LABEL[broadcast.status]}
            </Badge>
            <span>{progressLabel}</span>
          </span>
        }
        actions={
          <>
            <Button variant="ghost" onClick={() => navigate("/broadcasts")}>
              <ArrowLeft className="size-4" />К списку
            </Button>
            {canEdit && (
              <Link
                to={`/broadcasts/${id}/edit`}
                className={buttonVariants({ variant: "secondary" })}
              >
                Редактировать
              </Link>
            )}
            {canCancel && (
              <Button
                variant="danger"
                onClick={handleCancelClick}
                disabled={cancelMutation.isPending}
              >
                <Ban className="size-4" />
                {cancelMutation.isPending ? "Отменяем…" : "Отменить отправку"}
              </Button>
            )}
          </>
        }
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <section className="space-y-6 lg:col-span-2">
          <CountersCard broadcast={broadcast} />

          {showProblems && (
            <div>
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
                Проблемные получатели ({(failedCount + blockedCount).toString()})
              </h2>
              <DataTable
                rows={problemRows}
                columns={problemColumns}
                rowKey={(r) => `${r.user_id}-${r.status}`}
                loading={problemsLoading}
                empty="Проблемных получателей нет."
                ariaLabel="Проблемные получатели"
                sortable={false}
              />
            </div>
          )}
        </section>

        <aside className="space-y-2">
          <BroadcastPreview
            bodyHtml={broadcast.body_html}
            mediaType={broadcast.media_type}
            mediaUrl={broadcast.media_url}
          />
          <p className="text-xs text-[var(--text-secondary)]">
            {broadcast.locale_filter
              ? `Локаль: ${broadcast.locale_filter.toUpperCase()}`
              : "Все локали"}
          </p>
        </aside>
      </div>
    </div>
  );
}

function CountersCard({ broadcast }: { broadcast: BroadcastOut }) {
  const rows: { label: string; value: ReactNode }[] = [
    { label: "Аудитория", value: broadcast.total_recipients.toLocaleString("ru") },
    {
      label: "Успешно",
      value: <span className="text-[var(--success-fg)]">{broadcast.sent_count}</span>,
    },
    {
      label: "Ошибки",
      value: <span className="text-[var(--danger-fg)]">{broadcast.failed_count}</span>,
    },
    {
      label: "Заблокировано",
      value: <span className="text-[var(--text-secondary)]">{broadcast.blocked_count}</span>,
    },
    { label: "Запланирована на", value: fmtDate(broadcast.scheduled_at) },
    { label: "Начата", value: fmtDate(broadcast.started_at) },
    { label: "Завершена", value: fmtDate(broadcast.finished_at) },
  ];
  return (
    <div className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
        Счётчики
      </h2>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 md:grid-cols-2">
        {rows.map((r) => (
          <div key={r.label} className="flex items-baseline justify-between text-sm">
            <dt className="text-[var(--text-secondary)]">{r.label}</dt>
            <dd>{r.value}</dd>
          </div>
        ))}
      </dl>
      {broadcast.last_error && (
        <p className="mt-3 text-xs text-[var(--danger-fg)]">{broadcast.last_error}</p>
      )}
    </div>
  );
}
