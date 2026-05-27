/** Per-supplier detail page (currently only G2B).
 *
 * Three concerns share one screen because operators treat them as one job:
 *  1. Connectivity / balance probe (calls ``/admin/integrations/g2b/health``).
 *  2. Refreshing the catalog cache that feeds the mapping editor's
 *     autocomplete (``POST /admin/integrations/g2b/sync-catalog``).
 *  3. A live tail of supplier interactions for debugging (filtered
 *     ``fulfillment_attempts``).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { Database, ListTree, RefreshCw, TrendingUp } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { Spinner } from "@/components/States";
import { useToast } from "@/components/Toast";
import { ApiError, apiGet, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

import { G2bAttemptsTab } from "./G2bAttemptsTab";
import {
  SUPPLIER_LABELS,
  type CatalogSyncResult,
  type PriceRefreshOut,
  type SupplierHealth,
} from "./types";

export function G2bDetailPage() {
  const { slug = "g2b" } = useParams<{ slug?: string }>();
  const qc = useQueryClient();
  const toast = useToast();
  const label = SUPPLIER_LABELS[slug as keyof typeof SUPPLIER_LABELS] ?? slug;

  const health = useQuery<SupplierHealth>({
    queryKey: qk.integrationHealth(slug),
    queryFn: () => apiGet<SupplierHealth>(`/api/v1/admin/integrations/${slug}/health`),
    refetchInterval: 60_000,
  });

  const refreshPrices = useMutation<PriceRefreshOut, ApiError>({
    mutationFn: () => apiPost<PriceRefreshOut>("/api/v1/admin/integrations/refresh-all-prices", {}),
    onSuccess: (data) => {
      toast.success(
        `Цены обновлены · проверено ${data.checked.toString()} · изменилось ${data.moved.toString()} · алертов ${data.alerts_sent.toString()}` +
          (data.errors > 0 ? ` · ошибок ${data.errors.toString()}` : ""),
      );
    },
    onError: (err) => {
      toast.error(`Не удалось обновить цены: ${formatError(err)}`);
    },
  });

  const sync = useMutation<CatalogSyncResult, ApiError>({
    mutationFn: () =>
      apiPost<CatalogSyncResult>(`/api/v1/admin/integrations/${slug}/sync-catalog`, {}),
    onSuccess: (data) => {
      void qc.invalidateQueries({ queryKey: qk.integrationCatalog({ supplierSlug: slug }) });
      const summary = `ваучеры: ${data.vouchers_synced.toString()}, игры: ${data.games_synced.toString()}`;
      if (data.error) {
        toast.error(`Каталог синхронизирован частично — ${summary}. ${data.error}`);
      } else {
        toast.success(`Каталог обновлён — ${summary}`);
      }
    },
    onError: (err) => {
      toast.error(`Не удалось синхронизировать каталог: ${formatError(err)}`);
    },
  });

  return (
    <div>
      <PageHeader
        title={label}
        description={
          <>
            Подключение через <code className="font-mono text-xs">{slug}</code> в реестре{" "}
            <code className="font-mono text-xs">fulfillment/suppliers</code>. См.{" "}
            <Link to="/integrations" className="underline">
              все интеграции
            </Link>
            .
          </>
        }
        breadcrumbs={[{ label: "Интеграции", to: "/integrations" }, { label }]}
        actions={
          <Button
            onClick={() => {
              void qc.invalidateQueries({ queryKey: qk.integrationHealth(slug) });
            }}
            disabled={health.isFetching}
            variant="secondary"
            size="sm"
          >
            <RefreshCw className={`size-4 ${health.isFetching ? "animate-spin" : ""}`} />
            {health.isFetching ? "Проверяем…" : "Проверить связь"}
          </Button>
        }
      />

      {health.isLoading ? (
        <Spinner label="Проверяем подключение…" />
      ) : (
        <HealthSummary data={health.data} />
      )}

      <section className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-3">
        <ActionCard
          icon={ListTree}
          title="Маппинг SKU"
          description="Свяжите наши SKU с продуктами и играми поставщика. Без маппинга задача упадёт в failed."
          actionLabel="Открыть маппинги"
          to={`/integrations/mappings?supplier=${slug}`}
        />
        <ActionCard
          icon={Database}
          title="Каталог поставщика"
          description="Синхронизируйте список товаров / игр в локальный кэш. Используется для автокомплита в форме маппинга."
          actionLabel={sync.isPending ? "Синхронизируем…" : "Синхронизировать"}
          onClick={() => {
            sync.mutate();
          }}
          actionDisabled={sync.isPending || !health.data?.available}
          hint={
            health.data?.available
              ? null
              : "Доступно только когда ключ настроен и подключение зелёное."
          }
        />
        <ActionCard
          icon={TrendingUp}
          title="Цены маппингов"
          description="Прогнать все активные маппинги и обновить cost_usdt. То же делает воркер каждый час; кнопка для ручного запуска."
          actionLabel={refreshPrices.isPending ? "Обновляем…" : "Обновить цены"}
          onClick={() => {
            refreshPrices.mutate();
          }}
          actionDisabled={refreshPrices.isPending || !health.data?.available}
          hint={health.data?.available ? null : "Нужно настроенное и онлайн-подключение к G2B."}
        />
      </section>

      <section className="mt-8">
        <h2 className="mb-3 text-lg font-semibold">Последние взаимодействия</h2>
        <p className="mb-3 text-xs text-[var(--text-secondary)]">
          Аудит вызовов <code className="font-mono">fulfill / status_check / cancel</code> по
          задачам, привязанным к этому поставщику. PII (player_id, коды) не показывается — только
          счётчики и хэши.
        </p>
        <G2bAttemptsTab supplier={slug} />
      </section>
    </div>
  );
}

function HealthSummary({ data }: { data: SupplierHealth | undefined }) {
  if (!data) {
    return null;
  }
  const tone = data.available
    ? "border-[var(--accent)] bg-[var(--bg-accent-soft)]"
    : "border-[var(--border-default)] bg-[var(--bg-muted)]";
  return (
    <section className={`rounded-lg border p-5 ${tone}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-lg font-semibold">
            {data.available ? "Онлайн" : "Не настроен / недоступен"}
          </div>
          {data.reason && (
            <p className="mt-1 text-sm text-[var(--text-secondary)]">{data.reason}</p>
          )}
        </div>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <div className="text-[10px] uppercase tracking-wide text-[var(--text-tertiary)]">
              Баланс
            </div>
            <div className="font-mono">{data.balance ?? "—"}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-[var(--text-tertiary)]">
              Аккаунт
            </div>
            <div>{data.username ?? "—"}</div>
          </div>
        </div>
      </div>
      {data.last_checked_at && (
        <p className="mt-3 text-xs text-[var(--text-tertiary)]">
          Последняя проверка: {new Date(data.last_checked_at).toLocaleString("ru")}
        </p>
      )}
    </section>
  );
}

function ActionCard({
  icon: Icon,
  title,
  description,
  actionLabel,
  to,
  onClick,
  actionDisabled,
  hint,
}: {
  icon: typeof Database;
  title: string;
  description: string;
  actionLabel: string;
  to?: string;
  onClick?: () => void;
  actionDisabled?: boolean;
  hint?: string | null;
}) {
  return (
    <article className="flex flex-col gap-3 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-5">
      <header className="flex items-center gap-2">
        <Icon className="size-5 text-[var(--accent)]" />
        <h3 className="font-semibold">{title}</h3>
      </header>
      <p className="text-sm text-[var(--text-secondary)]">{description}</p>
      <div className="mt-auto flex items-center justify-between gap-2">
        {hint && <span className="text-xs text-[var(--text-tertiary)]">{hint}</span>}
        {to ? (
          <Link
            to={to}
            className="ml-auto inline-flex h-8 items-center rounded-md border border-[var(--border-default)] px-3 text-sm font-medium hover:bg-[var(--bg-muted)]"
          >
            {actionLabel}
          </Link>
        ) : (
          <Button
            type="button"
            size="sm"
            onClick={onClick}
            disabled={actionDisabled}
            className="ml-auto"
          >
            {actionLabel}
          </Button>
        )}
      </div>
    </article>
  );
}

function formatError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: string; title?: string } | null;
    return body?.detail ?? body?.title ?? err.message;
  }
  if (err instanceof Error) return err.message;
  return "неизвестная ошибка";
}
