import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { CheckCheck, CheckCircle2, RotateCcw, ShieldAlert } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/Badge";
import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { useToast } from "@/components/Toast";
import { type ApiError, apiGet, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

interface AdminResolved {
  actor: string;
  reason: string;
  at: string;
}

interface WebhookOut {
  id: string;
  provider: string;
  external_event_id: string;
  received_at: string;
  processed_at: string | null;
  signature_ok: boolean;
  payload: Record<string, unknown> & { _admin_resolved?: AdminResolved };
}

interface WebhookListOut {
  items: WebhookOut[];
}

const PROVIDERS = [
  { value: "", label: "Все" },
  { value: "mock", label: "mock" },
  { value: "click", label: "click" },
  { value: "payme", label: "payme" },
  { value: "uzum", label: "uzum" },
  { value: "yookassa", label: "yookassa" },
  { value: "tinkoff", label: "tinkoff" },
  { value: "crypto", label: "crypto" },
];

const SIG_OPTIONS: { value: "all" | "ok" | "bad"; label: string }[] = [
  { value: "all", label: "Подпись: все" },
  { value: "ok", label: "Подпись: OK" },
  { value: "bad", label: "Подпись: rejected" },
];

export function WebhooksPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [provider, setProvider] = useState("");
  const [sig, setSig] = useState<"all" | "ok" | "bad">("all");
  const [onlyProblems, setOnlyProblems] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const sigOk =
    sig === "ok" ? true : sig === "bad" ? false : null;

  const q = useQuery<WebhookListOut>({
    queryKey: [
      ...qk.webhooks({
        provider: provider || null,
        signature_ok: sigOk,
      }),
      onlyProblems ? "problems" : "all",
    ],
    queryFn: () => {
      const params = new URLSearchParams();
      if (provider) params.set("provider", provider);
      if (sigOk !== null) params.set("signature_ok", String(sigOk));
      params.set("limit", "200");
      return apiGet<WebhookListOut>(
        `/api/v1/admin/webhooks?${params.toString()}`,
      );
    },
    refetchInterval: 15_000,
  });

  const resolveMutation = useMutation<
    WebhookOut,
    ApiError,
    { id: string; reason: string }
  >({
    mutationFn: ({ id, reason }) =>
      apiPost<WebhookOut>(
        `/api/v1/admin/webhooks/${id}/mark-resolved`,
        { reason },
      ),
    onSuccess: () => {
      toast.success("Webhook помечен как разобранный.");
      void qc.invalidateQueries({ queryKey: ["admin", "webhooks"] });
    },
    onError: (err) => {
      toast.error(formatApiError(err));
    },
  });

  const allRows = q.data?.items ?? [];
  const rows = useMemo(() => {
    if (!onlyProblems) return allRows;
    // "Problem" = bad signature OR never processed OR previously stamped
    // as resolved (so an operator can audit what they already touched).
    return allRows.filter(
      (w) =>
        !w.signature_ok ||
        w.processed_at === null ||
        w.payload._admin_resolved !== undefined,
    );
  }, [allRows, onlyProblems]);

  const counters = useMemo(() => {
    const total = allRows.length;
    const rejected = allRows.filter((w) => !w.signature_ok).length;
    const providers = new Set(allRows.map((w) => w.provider)).size;
    return { total, rejected, providers };
  }, [allRows]);

  const columns: Column<WebhookOut>[] = [
    {
      key: "provider",
      header: "Провайдер",
      render: (w) => (
        <span className="rounded-md bg-[var(--bg-muted)] px-2 py-0.5 font-mono text-xs">
          {w.provider}
        </span>
      ),
      className: "w-32",
    },
    {
      key: "event_id",
      header: "Event ID",
      render: (w) => (
        <code className="text-xs">
          {w.external_event_id.length > 18
            ? `${w.external_event_id.slice(0, 18)}…`
            : w.external_event_id}
        </code>
      ),
    },
    {
      key: "sig",
      header: "Подпись",
      render: (w) =>
        w.signature_ok ? (
          <span className="inline-flex items-center gap-1 text-xs text-[var(--success-fg)]">
            <CheckCircle2 className="size-3" />
            OK
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-xs text-[var(--danger-fg)]">
            <ShieldAlert className="size-3" />
            rejected
          </span>
        ),
      className: "w-32",
    },
    {
      key: "received",
      header: "Получен",
      render: (w) => formatDate(w.received_at),
      className: "w-36",
    },
    {
      key: "processed",
      header: "Обработан",
      render: (w) =>
        w.processed_at ? formatDate(w.processed_at) : "—",
      className: "w-36",
    },
    {
      key: "resolved",
      header: "Разбор",
      render: (w) =>
        w.payload._admin_resolved ? (
          <Badge tone="bg-[var(--success-soft)] text-[var(--success-fg)]" dot>
            разобран
          </Badge>
        ) : !w.signature_ok || w.processed_at === null ? (
          <Badge tone="bg-[var(--warning-soft)] text-[var(--warning-fg)]" dot>
            требует
          </Badge>
        ) : (
          <span className="text-xs text-[var(--text-secondary)]">—</span>
        ),
      className: "w-28",
    },
    {
      key: "actions",
      header: "",
      render: (w) => {
        const alreadyResolved = w.payload._admin_resolved !== undefined;
        // Only show the action when the row needs operator attention.
        const needsResolution =
          !w.signature_ok || w.processed_at === null || alreadyResolved;
        if (!needsResolution) {
          return <span className="text-xs text-[var(--text-secondary)]">—</span>;
        }
        return (
          <div
            className="flex justify-end"
            onClick={(e) => { e.stopPropagation(); }}
          >
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={resolveMutation.isPending}
              onClick={() => {
                const fallback = alreadyResolved
                  ? w.payload._admin_resolved?.reason ?? ""
                  : "";
                const reason = window.prompt(
                  `Почему этот webhook разобран?\n${
                    !w.signature_ok ? "(rejected signature)" : "(не обработан)"
                  }`,
                  fallback,
                );
                if (reason === null) return;
                if (!reason.trim()) {
                  toast.error("Нужна причина — она пишется в аудит.");
                  return;
                }
                resolveMutation.mutate({ id: w.id, reason: reason.trim() });
              }}
            >
              <CheckCheck className="size-4" />
              {alreadyResolved ? "Уточнить" : "Разобрался"}
            </Button>
          </div>
        );
      },
      className: "w-40 text-right",
    },
  ];

  return (
    <div>
      <PageHeader
        title="Входящие webhooks"
        description="Аудит подписей и payload-ов. Полезно для разбора, почему провайдер прислал событие со странной shape."
        actions={
          <Button
            type="button"
            variant="ghost"
            onClick={() => q.refetch()}
            disabled={q.isFetching}
          >
            <RotateCcw
              className={`size-4 ${q.isFetching ? "animate-spin" : ""}`}
            />
            Обновить
          </Button>
        }
      />

      <section className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-3">
        <StatCard label="Всего" value={counters.total} />
        <StatCard
          label="Невалидная подпись"
          value={counters.rejected}
          tone={counters.rejected > 0 ? "warn" : "muted"}
        />
        <StatCard
          label="Провайдеров"
          value={counters.providers}
        />
      </section>

      <section className="mb-5 flex flex-wrap items-center gap-3">
        <select
          value={provider}
          onChange={(e) => { setProvider(e.target.value); }}
          className="h-10 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-sm"
        >
          {PROVIDERS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label || "Все провайдеры"}
            </option>
          ))}
        </select>
        <select
          value={sig}
          onChange={(e) => { setSig(e.target.value as "all" | "ok" | "bad"); }}
          className="h-10 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-sm"
        >
          {SIG_OPTIONS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        <label className="inline-flex items-center gap-2 text-sm text-[var(--text-secondary)]">
          <input
            type="checkbox"
            checked={onlyProblems}
            onChange={(e) => { setOnlyProblems(e.target.checked); }}
            className="size-4 accent-[var(--accent)]"
          />
          Только проблемные
        </label>
      </section>

      {q.isError && (
        <p className="text-sm text-[var(--danger)]">Ошибка загрузки.</p>
      )}

      <DataTable
        rows={rows}
        columns={columns}
        rowKey={(w) => w.id}
        onRowClick={(w) => { setExpanded(expanded === w.id ? null : w.id); }}
        empty="Webhook-ов ещё не приходило."
      />

      {expanded && (() => {
        const row = rows.find((w) => w.id === expanded);
        return row ? <PayloadPreview row={row} /> : null;
      })()}

      <p className="mt-3 text-xs text-[var(--text-secondary)]">
        Запись о невалидной подписи остаётся в аудит-таблице как
        ``rejected:&lt;uuid&gt;``, чтобы можно было разобраться при подозрении
        на атаку.
      </p>
    </div>
  );
}

function PayloadPreview({ row }: { row: WebhookOut }) {
  const resolved = row.payload._admin_resolved;
  return (
    <article className="mt-4 rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)] p-4 text-sm">
      <header className="mb-2 flex items-baseline justify-between">
        <h3 className="font-semibold">
          {row.provider} · {row.external_event_id}
        </h3>
        <span className="text-xs text-[var(--text-secondary)]">
          {formatDate(row.received_at)}
        </span>
      </header>
      {resolved && (
        <div className="mb-3 rounded-md border border-[var(--success-fg)]/30 bg-[var(--success-soft)] px-3 py-2 text-xs text-[var(--success-fg)]">
          <strong>Разобран:</strong> {resolved.actor} · {formatDate(resolved.at)}
          <p className="mt-1 text-[var(--text-primary)]">{resolved.reason}</p>
        </div>
      )}
      <pre className="whitespace-pre-wrap break-all rounded border bg-[var(--bg-muted)] p-3 text-[11px] leading-relaxed text-[var(--text-primary)]">
        {JSON.stringify(row.payload, null, 2)}
      </pre>
    </article>
  );
}

function formatApiError(err: ApiError): string {
  const body = err.body as { detail?: string; title?: string } | null;
  return body?.detail ?? body?.title ?? err.message;
}

function StatCard({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: number;
  tone?: "default" | "warn" | "muted";
}) {
  const valueCls =
    tone === "warn" ? "text-[var(--danger)]" : "text-[var(--text-primary)]";
  return (
    <div className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)] p-4">
      <div className={`text-2xl font-semibold ${valueCls}`}>{value}</div>
      <div className="text-xs uppercase tracking-wide text-[var(--text-secondary)]">
        {label}
      </div>
    </div>
  );
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("ru", {
    year: "2-digit",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
