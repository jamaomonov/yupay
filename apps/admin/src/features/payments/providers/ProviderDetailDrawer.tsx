/**
 * Provider detail drawer — opens from `ProvidersPage` on row click.
 *
 * Fetches `GET /admin/payments/providers/{provider}?window=` (switchable
 * today/7d/30d) and renders the analytics blocks from
 * `ProviderAnalyticsBlocks.tsx`: volume by currency, success rate,
 * tech/config state, recent payments, and incident counters. Three
 * state-change actions (disable / maintenance / enable) call
 * `PUT .../state` with a fresh Idempotency-Key each time, then invalidate
 * both the providers list and this provider's detail queries so the list
 * badge and the drawer itself reflect the new state without a manual
 * refetch.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { X } from "lucide-react";
import { useRef, useState } from "react";

import {
  IncidentsBlock,
  RecentPaymentsBlock,
  SuccessRateBlock,
  TechStateBlock,
  VolumeBlock,
} from "./ProviderAnalyticsBlocks";
import {
  STATE_LABEL,
  WINDOW_LABEL,
  WINDOWS,
  type AdminProviderDetailOut,
  type AdminProviderSummary,
  type AnalyticsWindow,
  type ProviderState,
} from "./types";

import { ErrorState, Spinner } from "@/components/States";
import { useToast } from "@/components/Toast";
import { api, type ApiError, apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { useDialog } from "@/lib/useDialog";

interface Props {
  provider: string;
  onClose: () => void;
}

export function ProviderDetailDrawer({ provider, onClose }: Props) {
  const qc = useQueryClient();
  const toast = useToast();
  const [win, setWin] = useState<AnalyticsWindow>("7d");
  const containerRef = useRef<HTMLDivElement | null>(null);
  useDialog({ open: true, onClose, containerRef });

  const query = useQuery<AdminProviderDetailOut>({
    queryKey: qk.paymentProviderDetail(provider, win),
    queryFn: () =>
      apiGet<AdminProviderDetailOut>(`/api/v1/admin/payments/providers/${provider}?window=${win}`),
  });

  const stateMutation = useMutation<AdminProviderSummary, ApiError, ProviderState>({
    mutationFn: (state) =>
      api<AdminProviderSummary>(`/api/v1/admin/payments/providers/${provider}/state`, {
        method: "PUT",
        body: JSON.stringify({ state }),
        headers: { "Idempotency-Key": crypto.randomUUID() },
      }),
    onSuccess: (summary) => {
      toast.success(`${summary.display_name}: ${STATE_LABEL[summary.state]}.`);
      void qc.invalidateQueries({ queryKey: qk.paymentProviders() });
      void qc.invalidateQueries({ queryKey: ["admin", "payments", "providers", provider] });
    },
    onError: (err) => {
      toast.error(formatApiError(err));
    },
  });

  const summary = query.data?.summary;

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/40"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-label={`Провайдер ${provider}`}
        className="flex h-full w-full max-w-2xl flex-col overflow-y-auto border-l border-[var(--border-default)] bg-[var(--bg-surface)] shadow-[var(--shadow-md)]"
      >
        <header className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-[var(--border-default)] bg-[var(--bg-surface)] px-5 py-3">
          <div className="min-w-0">
            <p className="text-xs uppercase text-[var(--text-secondary)]">Провайдер</p>
            <p className="truncate text-base font-semibold">{summary?.display_name ?? provider}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="rounded-md p-1.5 text-[var(--text-secondary)] hover:bg-[var(--bg-muted)] hover:text-[var(--text-primary)]"
          >
            <X className="size-4" aria-hidden />
          </button>
        </header>

        <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border-subtle)] px-5 py-3">
          {WINDOWS.map((w) => (
            <button
              key={w}
              type="button"
              onClick={() => {
                setWin(w);
              }}
              className={[
                "rounded-full px-3 py-1 text-xs font-semibold",
                win === w
                  ? "bg-[var(--accent)] text-[var(--text-on-accent)]"
                  : "bg-[var(--bg-muted)] text-[var(--text-secondary)]",
              ].join(" ")}
            >
              {WINDOW_LABEL[w]}
            </button>
          ))}
        </div>

        <div className="flex-1 space-y-5 px-5 py-4">
          {query.isError && (
            <ErrorState
              description="Не удалось загрузить аналитику провайдера."
              onRetry={() => void query.refetch()}
              retryPending={query.isFetching}
            />
          )}
          {query.isPending && <Spinner label="Загрузка…" />}

          {query.data && (
            <>
              <TechStateBlock summary={query.data.summary} />
              <VolumeBlock rows={query.data.volume} />
              <SuccessRateBlock rate={query.data.success_rate} />
              <IncidentsBlock incidents={query.data.incidents} />
              <RecentPaymentsBlock rows={query.data.recent} />
            </>
          )}
        </div>

        {summary && (
          <footer className="sticky bottom-0 flex flex-wrap items-center justify-end gap-2 border-t border-[var(--border-default)] bg-[var(--bg-surface)] px-5 py-3">
            <Button
              type="button"
              variant="danger"
              size="sm"
              disabled={stateMutation.isPending}
              onClick={() => {
                if (
                  window.confirm(
                    `Отключить провайдер «${summary.display_name}»? Клиенты не смогут им оплатить заказы.`,
                  )
                ) {
                  stateMutation.mutate("disabled");
                }
              }}
            >
              Отключить
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={stateMutation.isPending}
              onClick={() => {
                stateMutation.mutate("maintenance");
              }}
            >
              Технические работы
            </Button>
            {summary.state !== "active" && (
              <Button
                type="button"
                variant="primary"
                size="sm"
                disabled={stateMutation.isPending}
                onClick={() => {
                  stateMutation.mutate("active");
                }}
              >
                Включить
              </Button>
            )}
          </footer>
        )}
      </div>
    </div>
  );
}

function formatApiError(err: ApiError): string {
  const body = err.body as { detail?: string; title?: string } | null;
  return body?.detail ?? body?.title ?? err.message;
}
