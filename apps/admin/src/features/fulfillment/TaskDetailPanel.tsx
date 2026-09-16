/**
 * One task, opened from the inbox list.
 *
 * The attempt log is fetched here rather than arriving with the row, and it is
 * fetched a page at a time: a task whose supplier order stays open records a
 * `status_check` every minute for as long as that lasts, and the worst one in
 * production carries 1641 of them. Rendering that list whole is what made the
 * page scroll forever; it also meant every row of every page shipped its own
 * log whether or not anyone opened it.
 *
 * The log is therefore capped at a page, newest first, with the poll noise
 * filterable out — an operator opening a failing task wants the errors, and
 * they were buried under a day and a half of "still in progress".
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Select } from "@yupay/ui";
import { ExternalLink, X } from "lucide-react";
import { useEffect, useState } from "react";

import type { AttemptListOut, AttemptOut, TaskAdminOut } from "./types";

import { CopyId } from "@/components/CopyId";
import { StatusChip } from "@/components/StatusChip";
import { useToast } from "@/components/Toast";
import { FULFILMENT_ROUTES } from "@/features/integrations/types";
import { type ApiError, apiGet, apiPost, formatApiError } from "@/lib/api";

/** One screenful of log. Enough to see a failure's context, small enough that
 *  a 1641-attempt task opens as fast as a 3-attempt one. */
const ATTEMPTS_PAGE = 25;

type AttemptFilter = "all" | "error";

export function TaskDetailPanel({ task, onClose }: { task: TaskAdminOut; onClose: () => void }) {
  const [filter, setFilter] = useState<AttemptFilter>("all");
  const [limit, setLimit] = useState(ATTEMPTS_PAGE);

  // Reopening on a different task must not inherit the previous one's
  // "show more" depth — otherwise clicking through a list quietly gets
  // slower with every task opened.
  useEffect(() => {
    setLimit(ATTEMPTS_PAGE);
    setFilter("all");
  }, [task.id]);

  // Where a failed task can be moved. External suppliers only, minus the one
  // it is on: the warehouse is not a supplier and the manual queue has its
  // own intake (`mode="manual"`), and the API refuses both anyway — this just
  // keeps the list honest before the operator clicks.
  const targets = FULFILMENT_ROUTES.filter((r) => r.external && r.slug !== task.supplier);
  const [target, setTarget] = useState<string>(targets[0]?.slug ?? "");
  useEffect(() => {
    setTarget(targets[0]?.slug ?? "");
    // `targets` is derived from `task.supplier`; keying on that keeps the
    // effect from re-running on every render for an array that never changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task.id, task.supplier]);
  const canMove = task.status === "failed" || task.status === "pending";

  const qc = useQueryClient();
  const toast = useToast();
  const reassign = useMutation<TaskAdminOut, ApiError, string>({
    mutationFn: (supplier) =>
      apiPost<TaskAdminOut>(`/api/v1/admin/fulfillment/tasks/${task.id}/reassign`, { supplier }),
    onSuccess: (updated) => {
      toast.success(`Задача переведена на ${updated.supplier} и запущена.`);
      void qc.invalidateQueries({ queryKey: ["admin", "fulfillment"] });
    },
    onError: (err) => {
      toast.error(formatApiError(err));
    },
  });

  const attempts = useQuery<AttemptListOut>({
    queryKey: ["admin", "fulfillment", "attempts", task.id, filter, limit],
    queryFn: () => {
      const params = new URLSearchParams({ task_id: task.id, limit: String(limit), offset: "0" });
      if (filter === "error") params.set("status_filter", "error");
      return apiGet<AttemptListOut>(`/api/v1/admin/fulfillment/attempts?${params.toString()}`);
    },
  });

  const rows = attempts.data?.items ?? [];
  const total = attempts.data?.total ?? 0;

  const proofUrl =
    typeof task.extra_metadata.proof_url === "string" ? task.extra_metadata.proof_url : null;
  const queuedAt =
    typeof task.extra_metadata.queued_at === "string" ? task.extra_metadata.queued_at : null;
  const otherMeta = Object.fromEntries(
    Object.entries(task.extra_metadata).filter(([k]) => k !== "proof_url" && k !== "queued_at"),
  );

  return (
    <article className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)]">
      <header className="flex items-center justify-between gap-2 border-b px-4 py-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">Детали задачи</h3>
          <CopyId value={task.id} className="text-xs text-[var(--text-secondary)]" />
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Закрыть детали">
          <X className="size-4" />
        </Button>
      </header>

      <div className="space-y-4 p-4 text-sm">
        <section className="grid grid-cols-2 gap-3">
          <DetailField label="Маршрут" value={task.supplier} mono />
          <div>
            <FieldLabel>Статус</FieldLabel>
            <div className="mt-0.5">
              <StatusChip domain="taskStatus" value={task.status} />
            </div>
          </div>
          <DetailField label="Создана" value={fmt(task.created_at)} />
          {task.succeeded_at && <DetailField label="Завершена" value={fmt(task.succeeded_at)} />}
          {task.failed_at && <DetailField label="Провалена" value={fmt(task.failed_at)} />}
          {task.cancelled_at && <DetailField label="Отменена" value={fmt(task.cancelled_at)} />}
          {queuedAt && <DetailField label="В очереди с" value={fmt(queuedAt)} />}
          {task.external_order_id && (
            <DetailField label="External order" value={task.external_order_id} mono />
          )}
        </section>

        {task.last_error && (
          <section>
            <FieldLabel>Последняя ошибка</FieldLabel>
            <p className="mt-1 break-words text-[var(--danger)]">{task.last_error}</p>
          </section>
        )}

        {canMove && targets.length > 0 && (
          <section className="border-[var(--border-default)]/60 rounded-md border p-3">
            <FieldLabel>Сменить поставщика</FieldLabel>
            {/* For the two cases retry cannot help with: the supplier answered
                with an error, or our balance there ran dry. The sourcing rule
                only governs orders not yet placed; this moves *this* one. */}
            <p className="mb-2 mt-1 text-xs text-[var(--text-secondary)]">
              Задача уйдёт на выбранного поставщика и запустится там сразу. Правило сорсинга при
              этом не меняется — оно действует только на новые заказы.
            </p>
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-[12rem]">
                <label
                  htmlFor={`reassign-${task.id}`}
                  className="text-xs text-[var(--text-secondary)]"
                >
                  Новый поставщик
                </label>
                <Select
                  id={`reassign-${task.id}`}
                  value={target}
                  onChange={(e) => {
                    setTarget(e.target.value);
                  }}
                  containerClassName="mt-1 w-full"
                >
                  {targets.map((r) => (
                    <option key={r.slug} value={r.slug}>
                      {r.label}
                    </option>
                  ))}
                </Select>
              </div>
              <Button
                size="sm"
                disabled={reassign.isPending || target === ""}
                onClick={() => {
                  reassign.mutate(target);
                }}
              >
                {reassign.isPending ? "Переводим…" : "Сменить поставщика"}
              </Button>
            </div>
          </section>
        )}

        {(task.completed_by || task.admin_note || proofUrl) && (
          <section className="border-[var(--border-default)]/60 bg-[var(--bg-muted)]/40 space-y-2 rounded-md border p-3">
            <FieldLabel>Ручная обработка</FieldLabel>
            {task.completed_by && <DetailField label="Обработал" value={task.completed_by} mono />}
            {task.admin_note && <DetailField label="Заметка" value={task.admin_note} />}
            {proofUrl && (
              <a
                href={proofUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-[var(--accent)] hover:underline"
              >
                <ExternalLink className="size-3.5" />
                Открыть пруф
              </a>
            )}
          </section>
        )}

        {Object.keys(otherMeta).length > 0 && (
          <section>
            <FieldLabel>Метаданные</FieldLabel>
            <pre className="border-[var(--border-default)]/50 bg-[var(--bg-muted)]/40 mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded border p-2 text-xs">
              {JSON.stringify(otherMeta, null, 2)}
            </pre>
          </section>
        )}

        <section>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <FieldLabel>Лог обращений{attempts.data ? ` — ${String(total)}` : ""}</FieldLabel>
            {/* A day of once-a-minute status polls buries the one line that
                explains a failure. */}
            <div className="flex gap-1">
              {(["all", "error"] as const).map((f) => (
                <button
                  key={f}
                  type="button"
                  onClick={() => {
                    setFilter(f);
                    setLimit(ATTEMPTS_PAGE);
                  }}
                  aria-pressed={filter === f}
                  className={`rounded-md px-2 py-0.5 text-xs transition ${
                    filter === f
                      ? "bg-[var(--bg-accent-soft)] text-[var(--accent-soft-fg)]"
                      : "text-[var(--text-secondary)] hover:bg-[var(--bg-muted)]"
                  }`}
                >
                  {f === "all" ? "Все" : "Только ошибки"}
                </button>
              ))}
            </div>
          </div>

          {attempts.isPending && <p className="text-[var(--text-secondary)]">Загружаем…</p>}
          {attempts.isError && (
            <p role="alert" className="text-[var(--danger)]">
              Не удалось загрузить лог.
            </p>
          )}
          {attempts.data && rows.length === 0 && (
            <p className="text-[var(--text-secondary)]">
              {filter === "error" ? "Ошибок не было." : "Обращений ещё не было."}
            </p>
          )}

          <ol className="space-y-1.5">
            {rows.map((a, i) => (
              <AttemptRow key={`${a.kind}-${a.created_at}-${String(i)}`} attempt={a} />
            ))}
          </ol>

          {rows.length < total && (
            <Button
              variant="ghost"
              size="sm"
              className="mt-2"
              onClick={() => {
                setLimit((n) => n + ATTEMPTS_PAGE);
              }}
              disabled={attempts.isFetching}
            >
              {attempts.isFetching
                ? "Загружаем…"
                : `Показать ещё ${String(Math.min(ATTEMPTS_PAGE, total - rows.length))}`}
            </Button>
          )}
        </section>
      </div>
    </article>
  );
}

/** One log line. The payload stays folded — most are a two-key status echo,
 *  and the ones that are not would each push the next entry off screen. */
function AttemptRow({ attempt }: { attempt: AttemptOut }) {
  const [open, setOpen] = useState(false);
  const hasBody = attempt.error !== null || Object.keys(attempt.payload).length > 0;
  const failed = attempt.status !== "ok";

  return (
    <li className="border-[var(--border-default)]/50 rounded border text-xs">
      <button
        type="button"
        onClick={() => {
          if (hasBody) setOpen((v) => !v);
        }}
        aria-expanded={hasBody ? open : undefined}
        className={`flex w-full items-center justify-between gap-2 px-2 py-1.5 text-left ${
          hasBody ? "hover:bg-[var(--bg-muted)]/60" : "cursor-default"
        }`}
      >
        <span className="flex min-w-0 items-center gap-1.5">
          <code>{attempt.kind}</code>
          <span className={failed ? "text-[var(--danger)]" : "text-[var(--success)]"}>
            {attempt.status}
          </span>
          {attempt.repeat_count > 1 && (
            <span
              className="shrink-0 rounded bg-[var(--bg-muted)] px-1 text-[var(--text-secondary)]"
              title="Столько раз подряд поставщик ответил тем же"
            >
              ×{attempt.repeat_count}
            </span>
          )}
          {attempt.error && <span className="truncate text-[var(--danger)]">{attempt.error}</span>}
        </span>
        <span className="shrink-0 text-[var(--text-secondary)]">
          {attempt.last_seen_at
            ? `${fmt(attempt.created_at)} → ${fmt(attempt.last_seen_at)}`
            : fmt(attempt.created_at)}
        </span>
      </button>
      {open && (
        <div className="border-[var(--border-default)]/50 border-t px-2 py-1.5">
          {attempt.error && (
            <pre className="whitespace-pre-wrap text-[var(--danger)]">{attempt.error}</pre>
          )}
          {Object.keys(attempt.payload).length > 0 && (
            <pre className="whitespace-pre-wrap text-[var(--text-secondary)]">
              {JSON.stringify(attempt.payload, null, 2)}
            </pre>
          )}
        </div>
      )}
    </li>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
      {children}
    </p>
  );
}

function DetailField({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <FieldLabel>{label}</FieldLabel>
      <p className={`mt-0.5 break-words ${mono ? "font-mono text-xs" : "text-sm"}`}>{value}</p>
    </div>
  );
}

function fmt(iso: string): string {
  return new Date(iso).toLocaleString("ru");
}
