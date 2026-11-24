/** Mappings whose price could not be fetched for a day or more (ADR-0108):
 *  a category the supplier removed, an offer gone from its catalogue. The
 *  ones a SKU routes to come first — their orders fail, not just a comparison. */

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { apiGet } from "@/lib/api";

interface FailureItem {
  sku_id: string;
  sku_code: string | null;
  label: string | null;
  supplier_slug: string;
  routed: boolean;
  checked_at: string | null;
  failed_at: string;
  last_error: string | null;
}

/** Optional throughout: a partial answer (an older API, a test stub) renders empty. */
interface FailureReport {
  total?: number;
  routed?: number;
  groups?: { supplier_slug: string; error: string; count: number }[];
  items?: FailureItem[];
}

const HOURS = [24, 72, 168] as const;

function when(iso: string | null): string {
  return iso
    ? new Date(iso).toLocaleString("ru", { dateStyle: "short", timeStyle: "short" })
    : "никогда";
}

export function PriceFailuresCard() {
  const [hours, setHours] = useState<number>(24);
  const [open, setOpen] = useState(false);
  const query = useQuery<FailureReport>({
    queryKey: ["admin", "sourcing", "price-failures", hours],
    queryFn: () =>
      apiGet<FailureReport>(`/api/v1/admin/sourcing/price-failures?hours=${hours.toString()}`),
  });
  const data = query.data
    ? {
        total: query.data.total ?? 0,
        routed: query.data.routed ?? 0,
        groups: query.data.groups ?? [],
        items: query.data.items ?? [],
      }
    : undefined;

  return (
    <section className="space-y-3 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-5 shadow-[var(--shadow-sm)]">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">Цены не собираются</h2>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            Маппинги, у которых цену не удаётся получить дольше выбранного срока. Сверху — те, на
            которые сейчас идут заказы.
          </p>
        </div>
        <select
          value={hours}
          onChange={(e) => {
            setHours(Number(e.target.value));
          }}
          className="h-9 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-2 text-sm"
        >
          {HOURS.map((h) => (
            <option key={h} value={h}>
              {h === 24 ? "больше суток" : h === 72 ? "больше 3 дней" : "больше недели"}
            </option>
          ))}
        </select>
      </div>

      {data === undefined ? (
        <p className="text-sm text-[var(--text-tertiary)]">Загружаем…</p>
      ) : data.total === 0 ? (
        <p className="text-sm text-[var(--text-tertiary)]">Таких нет.</p>
      ) : (
        <>
          <p className="text-sm">
            Всего <b>{data.total}</b>
            {data.routed > 0 && (
              <>
                , из них <b className="text-[var(--danger-fg)]">{data.routed}</b> — текущий маршрут
                SKU
              </>
            )}
            .
          </p>
          <ul className="space-y-1 text-sm">
            {data.groups.slice(0, 10).map((g) => (
              <li key={`${g.supplier_slug}-${g.error}`}>
                <b>{g.supplier_slug}</b> · {g.count} — {g.error}
              </li>
            ))}
          </ul>
          <button
            type="button"
            className="text-sm text-[var(--accent)] hover:underline"
            onClick={() => {
              setOpen(!open);
            }}
          >
            {open ? "Скрыть список" : `Показать список (${data.items.length.toString()})`}
          </button>
          {open && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-[var(--text-tertiary)]">
                  <tr>
                    <th className="py-1 pr-3">SKU</th>
                    <th className="py-1 pr-3">Поставщик</th>
                    <th className="py-1 pr-3">Последняя цена</th>
                    <th className="py-1 pr-3">Ошибка</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((i) => (
                    <tr
                      key={`${i.sku_id}-${i.supplier_slug}`}
                      className="border-t border-[var(--border-subtle)]"
                    >
                      <td className="py-1 pr-3">
                        {i.label ?? i.sku_code ?? i.sku_id}
                        {i.sku_code && (
                          <code className="ml-1 text-[11px] text-[var(--text-tertiary)]">
                            {i.sku_code}
                          </code>
                        )}
                      </td>
                      <td className="whitespace-nowrap py-1 pr-3">
                        {i.supplier_slug}
                        {i.routed && (
                          <span className="ml-1 text-[11px] text-[var(--danger-fg)]">маршрут</span>
                        )}
                      </td>
                      <td className="whitespace-nowrap py-1 pr-3">{when(i.checked_at)}</td>
                      <td className="py-1 pr-3">{i.last_error ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
