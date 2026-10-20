import { useQuery } from "@tanstack/react-query";
import { TrendingUp } from "lucide-react";

import { supplierLabel } from "@/features/integrations/types";
import { apiGet } from "@/lib/api";

/** `GET /admin/orders/{id}/economics` — see `orders/economics.py`. */
export interface LineEconomics {
  item_id: string;
  label: string;
  qty: number;
  supplier: string | null;
  charged_usd: string;
  cost_usd: string | null;
  unit_cost_usd: string | null;
  cost_source: "frozen" | "estimated" | null;
  current_unit_cost_usd: string | null;
  margin_usd: string | null;
  margin_pct: string | null;
  discount_usd: string;
}

export interface OrderEconomics {
  lines: LineEconomics[];
  charged_usd: string;
  cost_usd: string | null;
  margin_usd: string | null;
  margin_pct: string | null;
  unknown_lines: number;
}

/** `$1.7` → `$1.70`; a unit cost keeps up to four decimals, trailing zeros dropped to cents. */
export function usd(value: string, unit = false): string {
  const negative = value.startsWith("-");
  const [whole = "0", fraction = ""] = value.replace("-", "").split(".");
  const digits = unit ? fraction.slice(0, 4).replace(/0+$/, "") : fraction.slice(0, 2);
  const cents = digits.padEnd(2, "0");
  return `${negative ? "−" : ""}$${whole}.${cents}`;
}

function marginTone(pct: string | null): string {
  if (pct === null) return "text-[var(--text-secondary)]";
  const value = Number(pct);
  if (value < 0) return "text-[var(--danger,#dc2626)]";
  if (value < 3) return "text-[var(--warning,#b45309)]";
  return "text-[var(--success,#15803d)]";
}

/**
 * «Закупка и маржа»: what each line cost us, at which supplier, and what we kept.
 *
 * The figures are the business tab's own (`orders.revenue`), so this order's margin is
 * its exact share of the dashboard's. «Сейчас» is today's price at the routed supplier,
 * so «купили за / покупаем за» reads in one row; «оценка» marks a cost that was not
 * frozen on the line and is reconstructed from the price history.
 */
export function EconomicsCard({ orderId }: { orderId: string }) {
  const query = useQuery<OrderEconomics>({
    queryKey: ["admin", "order", orderId, "economics"],
    queryFn: () => apiGet<OrderEconomics>(`/api/v1/admin/orders/${orderId}/economics`),
  });
  // An answer without lines (an older API, a stubbed one) renders as nothing, not a crash
  // that takes the whole order page down.
  const data = Array.isArray(query.data?.lines) ? query.data : undefined;

  return (
    <div className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)]">
      <header className="flex items-center gap-2 border-b px-4 py-3">
        <TrendingUp className="size-4 text-[var(--text-secondary)]" />
        <h2 className="text-sm font-semibold">Закупка и маржа</h2>
        {data?.margin_usd !== null && (
          <span className={`ml-auto text-sm font-semibold ${marginTone(data.margin_pct)}`}>
            {usd(data.margin_usd)}
            {data.margin_pct !== null && ` · ${data.margin_pct}%`}
          </span>
        )}
      </header>

      {query.isPending && (
        <p className="px-4 py-3 text-sm text-[var(--text-secondary)]">Считаем…</p>
      )}
      {query.isError && (
        <p className="px-4 py-3 text-sm text-[var(--text-secondary)]">
          Не удалось посчитать.{" "}
          <button type="button" className="underline" onClick={() => void query.refetch()}>
            Повторить
          </button>
        </p>
      )}

      {data && (
        <table className="w-full text-sm">
          <thead className="text-xs uppercase text-[var(--text-secondary)]">
            <tr>
              <th className="px-4 py-2 text-left font-medium">Позиция</th>
              <th className="px-3 py-2 text-left font-medium">Поставщик</th>
              <th className="px-3 py-2 text-right font-medium">Продали</th>
              <th className="px-3 py-2 text-right font-medium">Закупка</th>
              <th className="px-3 py-2 text-right font-medium">Маржа</th>
            </tr>
          </thead>
          <tbody>
            {data.lines.map((line) => (
              <tr key={line.item_id} className="border-t align-top">
                <td className="px-4 py-2.5">
                  {line.label}
                  {line.qty > 1 && (
                    <span className="text-[var(--text-secondary)]"> × {line.qty}</span>
                  )}
                </td>
                <td className="px-3 py-2.5">
                  {line.supplier === null ? (
                    <span className="text-[var(--text-tertiary)]">—</span>
                  ) : (
                    supplierLabel(line.supplier)
                  )}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {usd(line.charged_usd)}
                  {Number(line.discount_usd) > 0 && (
                    <div className="text-xs text-[var(--text-secondary)]">
                      скидка {usd(line.discount_usd)}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {line.cost_usd === null ? (
                    <span className="text-[var(--text-tertiary)]">неизвестна</span>
                  ) : (
                    <>
                      {usd(line.cost_usd)}
                      {line.qty > 1 && line.unit_cost_usd !== null && (
                        <div className="text-xs text-[var(--text-secondary)]">
                          {usd(line.unit_cost_usd, true)} / шт
                        </div>
                      )}
                      {line.cost_source === "estimated" && (
                        <div className="text-xs text-[var(--text-tertiary)]">оценка</div>
                      )}
                    </>
                  )}
                  {line.current_unit_cost_usd !== null && (
                    <div className="text-xs text-[var(--text-secondary)]">
                      сейчас {usd(line.current_unit_cost_usd, true)}
                      {line.qty > 1 ? " / шт" : ""}
                    </div>
                  )}
                </td>
                <td
                  className={`px-3 py-2.5 text-right font-medium tabular-nums ${marginTone(line.margin_pct)}`}
                >
                  {line.margin_usd === null ? "—" : usd(line.margin_usd)}
                  {line.margin_pct !== null && (
                    <div className="text-xs font-normal">{line.margin_pct}%</div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
          {data.lines.length > 1 && (
            <tfoot>
              <tr className="border-t font-semibold">
                <td className="px-4 py-2.5" colSpan={2}>
                  Итого
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">{usd(data.charged_usd)}</td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {data.cost_usd === null ? "—" : usd(data.cost_usd)}
                </td>
                <td
                  className={`px-3 py-2.5 text-right tabular-nums ${marginTone(data.margin_pct)}`}
                >
                  {data.margin_usd === null ? "—" : usd(data.margin_usd)}
                </td>
              </tr>
            </tfoot>
          )}
        </table>
      )}

      {data && data.unknown_lines > 0 && (
        <p className="border-t px-4 py-2 text-xs text-[var(--text-secondary)]">
          Себестоимость {data.unknown_lines} поз. неизвестна — в итог не вошла.
        </p>
      )}
    </div>
  );
}
