/**
 * «Сменить поставщика» for one task: only the suppliers mapped for its SKU,
 * each with its live price, cheapest first.
 *
 * It used to be a dropdown of every external supplier — most of which had no
 * mapping for the line, so picking one failed with a 409 — and the price that
 * decides the pick lived on the Sourcing screen, three clicks away. The list
 * now comes from `GET …/reassign-options`, which quotes each mapped supplier
 * read-only, and the operator chooses by price and margin right here.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { useEffect, useState } from "react";

import type { ReassignOptionsOut, TaskAdminOut } from "./types";

import { useToast } from "@/components/Toast";
import { FULFILMENT_ROUTES } from "@/features/integrations/types";
import { type ApiError, apiGet, apiPost, formatApiError } from "@/lib/api";

function label(slug: string): string {
  return FULFILMENT_ROUTES.find((r) => r.slug === slug)?.label ?? slug;
}

function money(value: string): string {
  const n = Number(value);
  return `$${n < 1 ? n.toFixed(4).replace(/0+$/, "").replace(/\.$/, ".00") : n.toFixed(2)}`;
}

export function ReassignControl({ task }: { task: TaskAdminOut }) {
  const qc = useQueryClient();
  const toast = useToast();
  const options = useQuery<ReassignOptionsOut>({
    queryKey: ["admin", "fulfillment", "reassign-options", task.id, task.supplier],
    queryFn: () =>
      apiGet<ReassignOptionsOut>(`/api/v1/admin/fulfillment/tasks/${task.id}/reassign-options`),
    staleTime: 60_000,
  });
  const rows = options.data?.options ?? [];
  const [target, setTarget] = useState("");
  // Cheapest quoted supplier preselected — the API sorts that way — and
  // re-picked whenever a different task's list arrives.
  useEffect(() => {
    setTarget(rows.find((o) => o.cost_usdt !== null)?.supplier ?? rows[0]?.supplier ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options.data]);

  const reassign = useMutation<TaskAdminOut, ApiError, string>({
    mutationFn: (supplier) =>
      apiPost<TaskAdminOut>(`/api/v1/admin/fulfillment/tasks/${task.id}/reassign`, { supplier }),
    onSuccess: (updated) => {
      toast.success(`Задача переведена на ${label(updated.supplier)} и запущена.`);
      void qc.invalidateQueries({ queryKey: ["admin", "fulfillment"] });
    },
    onError: (err) => {
      toast.error(formatApiError(err));
    },
  });

  const price = options.data ? Number(options.data.price_usd) : null;
  const cheapest = rows.find((o) => o.cost_usdt !== null)?.supplier ?? null;

  return (
    <section className="border-[var(--border-default)]/60 rounded-md border p-3">
      <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
        Сменить поставщика
      </p>
      {/* For the two cases retry cannot help with: the supplier answered with
          an error, or our balance there ran dry. The sourcing rule only
          governs orders not yet placed; this moves *this* one. */}
      <p className="mb-2 mt-1 text-xs text-[var(--text-secondary)]">
        Задача уйдёт на выбранного поставщика и запустится там сразу. Правило сорсинга не меняется.
        {price !== null && <> Продано за {money(String(price))}.</>}
      </p>

      {options.isLoading && (
        <p className="text-xs text-[var(--text-secondary)]">Спрашиваем цены у поставщиков…</p>
      )}
      {options.isError && (
        <p className="text-xs text-[var(--danger)]">Не удалось получить варианты.</p>
      )}
      {options.data && rows.length === 0 && (
        <p className="text-xs text-[var(--text-secondary)]">
          У этого товара нет маппинга у других поставщиков — его можно добавить в «Интеграции →
          Маппинги».
        </p>
      )}

      {rows.length > 0 && (
        <div role="radiogroup" aria-label="Новый поставщик" className="space-y-1.5">
          {rows.map((o) => {
            const cost = o.cost_usdt === null ? null : Number(o.cost_usdt);
            const margin =
              cost !== null && price !== null && price > 0 ? ((price - cost) / price) * 100 : null;
            const active = target === o.supplier;
            return (
              <label
                key={o.supplier}
                className={`flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2 text-sm ${
                  active
                    ? "border-[var(--accent)] bg-[var(--bg-muted)]"
                    : "border-[var(--border-default)]"
                }`}
              >
                <input
                  type="radio"
                  name={`reassign-${task.id}`}
                  value={o.supplier}
                  checked={active}
                  onChange={() => {
                    setTarget(o.supplier);
                  }}
                  aria-label={label(o.supplier)}
                />
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{label(o.supplier)}</span>
                  {o.supplier === cheapest && rows.length > 1 && (
                    <span className="bg-[var(--success)]/15 ml-2 rounded px-1.5 py-0.5 text-[11px] text-[var(--success)]">
                      дешевле всех
                    </span>
                  )}
                  {o.reserve && (
                    <span className="ml-2 rounded bg-[var(--bg-muted)] px-1.5 py-0.5 text-[11px] text-[var(--text-secondary)]">
                      резерв
                    </span>
                  )}
                  {o.stock !== null && (
                    <span className="ml-2 text-[11px] text-[var(--text-secondary)]">
                      в наличии: {o.stock}
                    </span>
                  )}
                </span>
                {cost === null ? (
                  <span className="text-xs text-[var(--text-secondary)]">
                    цена неизвестна{o.cost_reason ? ` — ${o.cost_reason}` : ""}
                  </span>
                ) : (
                  <span className="text-right font-mono">
                    {money(o.cost_usdt ?? "0")}
                    {margin !== null && (
                      <span
                        className={`block text-[11px] ${
                          margin < 0 ? "text-[var(--danger)]" : "text-[var(--text-secondary)]"
                        }`}
                      >
                        маржа {margin.toFixed(1)}%
                      </span>
                    )}
                  </span>
                )}
              </label>
            );
          })}
          <Button
            size="sm"
            className="mt-1"
            disabled={reassign.isPending || target === ""}
            onClick={() => {
              reassign.mutate(target);
            }}
          >
            {reassign.isPending ? "Переводим…" : "Сменить поставщика"}
          </Button>
        </div>
      )}
    </section>
  );
}
