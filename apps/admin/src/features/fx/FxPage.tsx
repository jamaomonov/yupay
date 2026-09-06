import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { RefreshCw } from "lucide-react";

import { FxProviderChain } from "./FxProviderChain";
import { FxRateCard, formatRate } from "./FxRateCard";

import type { AdminRateOut, AdminRatesOut, ProviderChainOut } from "./types";

import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { Spinner } from "@/components/States";
import { type ApiError, apiGet, apiPatch, apiPost, apiPut } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";
import { qk } from "@/lib/queryKeys";

export function FxPage() {
  const qc = useQueryClient();

  const ratesQuery = useQuery<AdminRatesOut>({
    queryKey: qk.fxRates(),
    queryFn: () => apiGet<AdminRatesOut>("/api/v1/admin/fx/rates"),
    refetchInterval: 60_000,
  });

  const refresh = useMutation<AdminRatesOut, ApiError>({
    mutationFn: () => apiPost<AdminRatesOut>("/api/v1/admin/fx/refresh", {}),
    onSuccess: (data) => {
      qc.setQueryData(qk.fxRates(), data);
      void qc.invalidateQueries({ queryKey: qk.fxProviders() });
    },
  });

  // No `refetchInterval`: this endpoint probes every FX adapter live, and the
  // quotas behind them are measured in thousands of calls per month — a tab
  // left open on this page used to spend one on every adapter every minute.
  // The chain is configuration, not a live feed; it refreshes when the
  // operator saves it or presses "Обновить".
  const providersQuery = useQuery<ProviderChainOut>({
    queryKey: qk.fxProviders(),
    queryFn: () => apiGet<ProviderChainOut>("/api/v1/admin/fx/providers"),
  });

  const saveChain = useMutation<ProviderChainOut, ApiError, { slug: string; enabled: boolean }[]>({
    mutationFn: (items) => apiPut<ProviderChainOut>("/api/v1/admin/fx/providers", { items }),
    onSuccess: (data) => {
      qc.setQueryData(qk.fxProviders(), data);
      void qc.invalidateQueries({ queryKey: qk.fxRates() });
    },
  });

  const save = useMutation<
    AdminRateOut,
    ApiError,
    { quote: string; use_manual: boolean; manual_rate: string | null }
  >({
    mutationFn: ({ quote, use_manual, manual_rate }) =>
      apiPatch<AdminRateOut>(`/api/v1/admin/fx/rates/${quote}`, { use_manual, manual_rate }),
    onSuccess: (updated) => {
      qc.setQueryData<AdminRatesOut>(qk.fxRates(), (prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          rates: prev.rates.map((r) => (r.quote === updated.quote ? updated : r)),
        };
      });
    },
  });

  const rates = ratesQuery.data?.rates ?? [];
  const base = ratesQuery.data?.base ?? "USD";
  const manualCount = rates.filter((r) => r.use_manual).length;

  return (
    <div>
      <PageHeader
        title="Курсы валют"
        description={`Для каждой валюты можно оставить курс FX или задать свой. База — ${base}.`}
        actions={
          <Button
            onClick={() => {
              refresh.mutate();
            }}
            disabled={refresh.isPending}
          >
            <RefreshCw className={`size-4 ${refresh.isPending ? "animate-spin" : ""}`} />
            {refresh.isPending ? "Обновляем…" : "Обновить курс FX"}
          </Button>
        }
      />

      <section className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Валют" value={rates.length.toString()} />
        <StatCard label="На нашем курсе" value={manualCount.toString()} />
        <StatCard label="На курсе FX" value={(rates.length - manualCount).toString()} />
        <StatCard label="База" value={base} mono />
      </section>

      {ratesQuery.isLoading && <Spinner label="Загрузка…" />}
      {ratesQuery.isError && (
        <p className="text-sm text-[var(--danger)]">
          Курсы недоступны. Попробуй обновить курс FX — это сбросит кэш и сходит к провайдеру.
        </p>
      )}
      {refresh.isError && (
        <p className="text-sm text-[var(--danger)]">
          Refresh не удался: {extractApiMessage(refresh.error)}
        </p>
      )}

      {providersQuery.isLoading && <Spinner label="Загрузка источников…" />}
      {providersQuery.isError && (
        <p className="mb-4 text-sm text-[var(--danger)]">Не удалось загрузить источники курса.</p>
      )}
      {providersQuery.data ? (
        <FxProviderChain
          data={providersQuery.data}
          saving={saveChain.isPending}
          error={saveChain.isError ? extractApiMessage(saveChain.error) : null}
          onChange={(items) => {
            saveChain.mutate(items);
          }}
        />
      ) : null}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {rates.map((row) => (
          <FxRateCard
            key={row.quote}
            row={row}
            saving={save.isPending && save.variables?.quote === row.quote}
            error={
              save.isError && save.variables?.quote === row.quote
                ? extractApiMessage(save.error)
                : null
            }
            onSave={(next) => {
              save.mutate({ quote: row.quote, ...next });
            }}
          />
        ))}
      </div>

      <p className="mt-3 text-xs text-[var(--text-secondary)]">
        «Наш курс» подменяет FX во всём: каталог, чекаут, публичный <code>GET /fx/rates</code>.
        Обновление FX не сбрасывает переключатель. Основной провайдер — первый живой в списке
        источников. SKU с отдельной ценой в валюте по-прежнему идут своей ценой, не курсом.
        {rates.some((r) => r.use_manual)
          ? ` Сейчас вручную: ${rates
              .filter((r) => r.use_manual)
              .map((r) => `${r.quote} ${formatRate(r.rate)}`)
              .join(", ")}.`
          : ""}
      </p>
    </div>
  );
}
