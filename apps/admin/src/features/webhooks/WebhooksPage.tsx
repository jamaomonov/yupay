import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, RotateCcw, ShieldAlert } from "lucide-react";

import { Button } from "@yupay/ui";

import { PageHeader } from "@/components/PageHeader";
import { DataTable, type Column } from "@/components/DataTable";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

interface WebhookOut {
  id: string;
  provider: string;
  external_event_id: string;
  received_at: string;
  processed_at: string | null;
  signature_ok: boolean;
  payload: Record<string, unknown>;
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
  const [provider, setProvider] = useState("");
  const [sig, setSig] = useState<"all" | "ok" | "bad">("all");
  const [expanded, setExpanded] = useState<string | null>(null);

  const sigOk =
    sig === "ok" ? true : sig === "bad" ? false : null;

  const q = useQuery<WebhookListOut>({
    queryKey: qk.webhooks({
      provider: provider || null,
      signature_ok: sigOk,
    }),
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

  const rows = q.data?.items ?? [];

  const counters = useMemo(() => {
    const total = rows.length;
    const rejected = rows.filter((w) => !w.signature_ok).length;
    const providers = new Set(rows.map((w) => w.provider)).size;
    return { total, rejected, providers };
  }, [rows]);

  const columns: Column<WebhookOut>[] = [
    {
      key: "provider",
      header: "Провайдер",
      render: (w) => (
        <span className="rounded-md bg-[--color-subtle] px-2 py-0.5 font-mono text-xs">
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
          <span className="inline-flex items-center gap-1 text-xs text-emerald-700">
            <CheckCircle2 className="size-3" />
            OK
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-xs text-rose-700">
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
          onChange={(e) => setProvider(e.target.value)}
          className="h-10 rounded-md border border-[--color-border] bg-[--color-bg] px-3 text-sm"
        >
          {PROVIDERS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label || "Все провайдеры"}
            </option>
          ))}
        </select>
        <select
          value={sig}
          onChange={(e) => setSig(e.target.value as "all" | "ok" | "bad")}
          className="h-10 rounded-md border border-[--color-border] bg-[--color-bg] px-3 text-sm"
        >
          {SIG_OPTIONS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </section>

      {q.isError && (
        <p className="text-sm text-[--color-danger]">Ошибка загрузки.</p>
      )}

      <DataTable
        rows={rows}
        columns={columns}
        rowKey={(w) => w.id}
        onRowClick={(w) => setExpanded(expanded === w.id ? null : w.id)}
        empty="Webhook-ов ещё не приходило."
      />

      {expanded && (
        <PayloadPreview row={rows.find((w) => w.id === expanded)!} />
      )}

      <p className="mt-3 text-xs text-[--color-muted]">
        Запись о невалидной подписи остаётся в аудит-таблице как
        ``rejected:&lt;uuid&gt;``, чтобы можно было разобраться при подозрении
        на атаку.
      </p>
    </div>
  );
}

function PayloadPreview({ row }: { row: WebhookOut }) {
  return (
    <article className="mt-4 rounded-lg border bg-[--color-bg] p-4 text-sm">
      <header className="mb-2 flex items-baseline justify-between">
        <h3 className="font-semibold">
          {row.provider} · {row.external_event_id}
        </h3>
        <span className="text-xs text-[--color-muted]">
          {formatDate(row.received_at)}
        </span>
      </header>
      <pre className="whitespace-pre-wrap break-all rounded border bg-[--color-subtle] p-3 text-[11px] leading-relaxed text-[--color-fg]">
        {JSON.stringify(row.payload, null, 2)}
      </pre>
    </article>
  );
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
    tone === "warn" ? "text-[--color-danger]" : "text-[--color-fg]";
  return (
    <div className="rounded-lg border bg-[--color-bg] p-4">
      <div className={`text-2xl font-semibold ${valueCls}`}>{value}</div>
      <div className="text-xs uppercase tracking-wide text-[--color-muted]">
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
