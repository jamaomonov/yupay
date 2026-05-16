import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import { Button } from "@yupay/ui";

import { PageHeader } from "@/components/PageHeader";
import { DataTable, type Column } from "@/components/DataTable";
import { ApiError, apiGet, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

interface RateOut {
  base: string;
  quote: string;
  rate: string;
  fetched_at: string;
  source: string;
}

interface RatesOut {
  base: string;
  rates: RateOut[];
}

export function FxPage() {
  const qc = useQueryClient();

  const ratesQuery = useQuery<RatesOut>({
    queryKey: qk.fxRates(),
    queryFn: () => apiGet<RatesOut>("/api/v1/admin/fx/rates"),
    refetchInterval: 60_000,
  });

  const refresh = useMutation<RatesOut, ApiError, void>({
    mutationFn: () => apiPost<RatesOut>("/api/v1/admin/fx/refresh", {}),
    onSuccess: (data) => qc.setQueryData(qk.fxRates(), data),
  });

  const rates = ratesQuery.data?.rates ?? [];
  const base = ratesQuery.data?.base ?? "USD";

  const oldest =
    rates.length === 0
      ? null
      : rates
          .map((r) => new Date(r.fetched_at).getTime())
          .reduce((m, t) => Math.min(m, t), Number.POSITIVE_INFINITY);

  const columns: Column<RateOut>[] = [
    {
      key: "pair",
      header: "Пара",
      render: (r) => (
        <div className="flex flex-col">
          <span className="font-medium">
            {r.base} → {r.quote}
          </span>
          <code className="text-xs text-[--color-muted]">{r.base}/{r.quote}</code>
        </div>
      ),
      className: "w-40",
    },
    {
      key: "rate",
      header: "Курс",
      render: (r) => (
        <span className="font-mono text-base">
          {formatRate(r.rate)}
        </span>
      ),
      className: "w-40 text-right",
    },
    {
      key: "source",
      header: "Источник",
      render: (r) => (
        <span className="rounded-md bg-[--color-subtle] px-2 py-0.5 font-mono text-xs">
          {r.source}
        </span>
      ),
    },
    {
      key: "fetched",
      header: "Обновлено",
      render: (r) => (
        <div className="flex flex-col items-end">
          <span className="text-xs">{formatDateTime(r.fetched_at)}</span>
          <span className="text-[10px] text-[--color-muted]">
            {ago(r.fetched_at)}
          </span>
        </div>
      ),
      className: "w-40 text-right",
    },
  ];

  return (
    <div>
      <PageHeader
        title="Курсы валют"
        description={`Через провайдер-цепочку из ADR-0008 (exchangerate-api → exchangerate.host → openexchangerates → coingecko). База — ${base}.`}
        actions={
          <Button
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
          >
            <RefreshCw
              className={`size-4 ${refresh.isPending ? "animate-spin" : ""}`}
            />
            {refresh.isPending ? "Обновляем…" : "Принудительно обновить"}
          </Button>
        }
      />

      <section className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Активных пар" value={rates.length.toString()} />
        <StatCard
          label="Самый старый"
          value={oldest ? ago(new Date(oldest).toISOString()) : "—"}
        />
        <StatCard
          label="Уникальных источников"
          value={new Set(rates.map((r) => r.source)).size.toString()}
        />
        <StatCard
          label="База"
          value={base}
          mono
        />
      </section>

      {ratesQuery.isLoading && (
        <p className="text-sm text-[--color-muted]">Загрузка…</p>
      )}
      {ratesQuery.isError && (
        <p className="text-sm text-[--color-danger]">
          Курсы недоступны. Попробуй «принудительно обновить» — это сбросит
          fresh-кэш и сходит к провайдеру.
        </p>
      )}
      {refresh.isError && (
        <p className="text-sm text-[--color-danger]">
          Refresh не удался: {formatError(refresh.error)}
        </p>
      )}

      <DataTable
        rows={rates}
        columns={columns}
        rowKey={(r) => `${r.base}-${r.quote}`}
        empty="Нет пар. Настрой `FX_SUPPORTED_QUOTES` в env."
      />

      <p className="mt-3 text-xs text-[--color-muted]">
        Кэш TTL: fresh — 15 минут, stale — 24 часа. Обычный GET читает кэш и
        провайдера не дёргает. Refresh сбрасывает fresh-копию для каждой пары и
        форсит сетевой запрос.
      </p>
    </div>
  );
}

function StatCard({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="rounded-lg border bg-[--color-bg] p-4">
      <div className={`text-2xl font-semibold ${mono ? "font-mono" : ""}`}>
        {value}
      </div>
      <div className="text-xs uppercase tracking-wide text-[--color-muted]">
        {label}
      </div>
    </div>
  );
}

function formatRate(s: string): string {
  const n = Number.parseFloat(s);
  if (Number.isNaN(n)) return s;
  // Big numbers (UZS = 12k+) — no decimals. Otherwise 4 decimals.
  if (n >= 1000) return n.toLocaleString("ru", { maximumFractionDigits: 2 });
  return n.toLocaleString("ru", { maximumFractionDigits: 4 });
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("ru", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function ago(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(diff)) return "—";
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s} с назад`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} мин назад`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} ч назад`;
  return `${Math.floor(h / 24)} д назад`;
}

function formatError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: string; title?: string } | null;
    return body?.detail ?? body?.title ?? err.message;
  }
  if (err instanceof Error) return err.message;
  return "неизвестная ошибка";
}
