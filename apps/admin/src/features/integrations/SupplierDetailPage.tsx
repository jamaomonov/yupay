/** Per-supplier detail page.
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

import { SupplierAttemptsTab } from "./SupplierAttemptsTab";
import {
  FULFILMENT_ROUTES,
  HEALTH_CHECK_TIMEOUT_MS,
  SUPPLIER_CAPABILITIES,
  SUPPLIER_LABELS,
  SUPPLIER_NO_CATALOGUE_NOTE,
  type CatalogSyncResult,
  type PriceRefreshOut,
  type SupplierHealth,
} from "./types";

import { PageHeader } from "@/components/PageHeader";
import { ErrorState, Spinner } from "@/components/States";
import { useToast } from "@/components/Toast";
import { ApiError, apiGet, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

export function SupplierDetailPage() {
  const { slug = "g2b" } = useParams<{ slug?: string }>();
  const qc = useQueryClient();
  const toast = useToast();
  const label = SUPPLIER_LABELS[slug as keyof typeof SUPPLIER_LABELS] ?? slug;
  // Unknown suppliers get the full set rather than a blank page: better to
  // offer an action that might fail than to silently hide tooling from a
  // supplier someone just added.
  const caps = SUPPLIER_CAPABILITIES[slug as keyof typeof SUPPLIER_CAPABILITIES] ?? {
    catalogue: true,
  };
  const noCatalogueNote =
    SUPPLIER_NO_CATALOGUE_NOTE[slug as keyof typeof SUPPLIER_NO_CATALOGUE_NOTE] ?? null;
  // "Takes SKU mappings" and "has a catalogue cache" are two different
  // properties, and this page used one flag for both. G-Engine takes mappings
  // (typed by hand — service_id, denomination_id) but mirrors no catalogue, so
  // the only doorway to its mapping form was hidden behind the catalogue
  // switch. Waxpeer has neither and stays as it was. Unknown slugs get the
  // door, for the same reason `caps` defaults open above.
  const canMap = FULFILMENT_ROUTES.find((r) => r.slug === slug)?.mappings ?? true;

  const health = useQuery<SupplierHealth>({
    queryKey: qk.integrationHealth(slug),
    // See `HEALTH_CHECK_TIMEOUT_MS` — without a client-side cap a dead
    // upstream leaves this query (and the Sync/Pricing actions gated on
    // `health.data?.available`) hanging forever instead of failing visibly.
    queryFn: () =>
      apiGet<SupplierHealth>(`/api/v1/admin/integrations/${slug}/health`, {
        signal: AbortSignal.timeout(HEALTH_CHECK_TIMEOUT_MS),
      }),
    refetchInterval: 60_000,
    retry: 1,
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
            Подключение, баланс и синхронизация каталога для поставщика{" "}
            <code className="font-mono text-xs">{slug}</code>. См.{" "}
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
      ) : health.isError ? (
        <ErrorState
          title="Проверка связи не отвечает"
          description={`Поставщик не ответил за ${(HEALTH_CHECK_TIMEOUT_MS / 1000).toString()} с — возможно, сервис недоступен или ключ не настроен.`}
          onRetry={() => {
            void qc.invalidateQueries({ queryKey: qk.integrationHealth(slug) });
          }}
          retryPending={health.isFetching}
        />
      ) : (
        <HealthSummary data={health.data} />
      )}

      {canMap && (
        <section className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-3">
          <ActionCard
            icon={ListTree}
            title="Маппинг SKU"
            description="Свяжите наши SKU с продуктами и играми поставщика. Без маппинга задача упадёт в failed."
            actionLabel="Открыть маппинги"
            to={`/integrations/mappings?supplier=${slug}`}
          />
          {caps.catalogue && (
            <>
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
                icon={Database}
                title="Просмотр каталога"
                description="Откройте список игр поставщика и импортируйте игру как бренд с номиналами одним действием."
                actionLabel="Перейти к каталогу"
                to={`/integrations/${slug}/catalog`}
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
                hint={
                  health.data?.available ? null : "Нужно настроенное и онлайн-подключение к G2B."
                }
              />
            </>
          )}
        </section>
      )}

      {!caps.catalogue && noCatalogueNote && (
        <p className="mt-6 rounded-md border border-dashed border-[var(--border-default)] p-4 text-sm text-[var(--text-secondary)]">
          {noCatalogueNote}
        </p>
      )}

      <section className="mt-8">
        <h2 className="mb-3 text-lg font-semibold">Последние взаимодействия</h2>
        <p className="mb-3 text-xs text-[var(--text-secondary)]">
          Аудит вызовов <code className="font-mono">fulfill / status_check / cancel</code> по
          задачам, привязанным к этому поставщику. PII (player_id, коды) не показывается — только
          счётчики и хэши.
        </p>
        <SupplierAttemptsTab supplier={slug} />
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
