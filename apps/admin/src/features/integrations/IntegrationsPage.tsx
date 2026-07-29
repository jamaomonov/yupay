/** Integrations index — one card per supplier. */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { ArrowRight, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";

import {
  HEALTH_CHECK_TIMEOUT_MS,
  KNOWN_SUPPLIERS,
  SUPPLIER_LABELS,
  type SupplierHealth,
} from "./types";

import { PageHeader } from "@/components/PageHeader";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

export function IntegrationsPage() {
  return (
    <div>
      <PageHeader
        title="Интеграции"
        description="Реальные поставщики: API-ключи, статус подключения, маппинг SKU."
      />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {KNOWN_SUPPLIERS.map((slug) => (
          <SupplierCard key={slug} slug={slug} />
        ))}
      </div>
    </div>
  );
}

function SupplierCard({ slug }: { slug: string }) {
  const qc = useQueryClient();
  const query = useQuery<SupplierHealth>({
    queryKey: qk.integrationHealth(slug),
    // The health endpoint calls out to the supplier with no server-side
    // timeout of its own — cap the client wait so a dead upstream settles
    // into an error instead of leaving "Проверяем…" spinning forever.
    queryFn: () =>
      apiGet<SupplierHealth>(`/api/v1/admin/integrations/${slug}/health`, {
        signal: AbortSignal.timeout(HEALTH_CHECK_TIMEOUT_MS),
      }),
    refetchInterval: 60_000,
    retry: 1,
  });
  const label = SUPPLIER_LABELS[slug as keyof typeof SUPPLIER_LABELS] ?? slug;
  const health = query.data;
  const refreshing = query.isFetching;

  return (
    <article className="flex flex-col gap-3 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-5 shadow-[var(--shadow-sm)]">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{label}</h2>
          <p className="font-mono text-xs text-[var(--text-secondary)]">{slug}</p>
        </div>
        <HealthBadge health={health} loading={query.isLoading} error={query.isError} />
      </header>

      <dl className="grid grid-cols-2 gap-2 text-sm">
        <Field label="Баланс" value={health?.balance ?? "—"} mono />
        <Field label="Аккаунт" value={health?.username ?? "—"} />
      </dl>

      {query.isError && (
        <p className="text-xs text-[var(--danger)]">
          Проверка не отвечает (таймаут {(HEALTH_CHECK_TIMEOUT_MS / 1000).toString()} с). Нажми
          «Обновить», чтобы повторить.
        </p>
      )}
      {health?.reason && (
        <p className="text-xs text-[var(--text-secondary)]">
          <span className="text-[var(--text-tertiary)]">Причина:</span> {health.reason}
        </p>
      )}

      <div className="mt-2 flex items-center justify-between gap-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            void qc.invalidateQueries({ queryKey: qk.integrationHealth(slug) });
          }}
          disabled={refreshing}
          aria-label={`Обновить статус ${label}`}
        >
          <RefreshCw className={`size-4 ${refreshing ? "animate-spin" : ""}`} />
          Обновить
        </Button>
        <Link
          to={`/integrations/${slug}`}
          className="inline-flex h-8 items-center gap-2 rounded-md bg-[var(--accent)] px-3 text-sm font-medium text-[var(--text-on-accent)] shadow-[var(--shadow-sm)] transition-colors hover:bg-[var(--accent-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-base)]"
        >
          Открыть
          <ArrowRight className="size-4" />
        </Link>
      </div>
    </article>
  );
}

function HealthBadge({
  health,
  loading,
  error,
}: {
  health: SupplierHealth | undefined;
  loading: boolean;
  error: boolean;
}) {
  if (loading) {
    return (
      <span className="rounded-full bg-[var(--bg-muted)] px-2.5 py-1 text-xs text-[var(--text-secondary)]">
        Проверяем…
      </span>
    );
  }
  if (error) {
    return (
      <span className="bg-[var(--danger)]/10 rounded-full px-2.5 py-1 text-xs font-medium text-[var(--danger)]">
        Офлайн / таймаут
      </span>
    );
  }
  if (!health) {
    return (
      <span className="rounded-full bg-[var(--bg-muted)] px-2.5 py-1 text-xs text-[var(--text-secondary)]">
        Нет данных
      </span>
    );
  }
  const palette = health.available
    ? "bg-[var(--bg-accent-soft)] text-[var(--accent-soft-fg)]"
    : "bg-[var(--bg-muted)] text-[var(--danger)]";
  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${palette}`}>
      {health.available ? "Онлайн" : "Не настроен"}
    </span>
  );
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wide text-[var(--text-tertiary)]">{label}</dt>
      <dd className={mono ? "font-mono" : ""}>{value}</dd>
    </div>
  );
}
