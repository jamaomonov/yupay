/** Step 3 of the G2B import wizard: per-denomination selection table. */

import type { DenomState } from "./GameImportPage";
import type { GameDenomRow } from "./types";

import { Spinner } from "@/components/States";

export interface DenominationTableProps {
  rows: GameDenomRow[];
  loading: boolean;
  margin: string;
  rowState: (d: GameDenomRow) => DenomState;
  setRow: (name: string, patch: Partial<DenomState>) => void;
}

export function DenominationTable({
  rows,
  loading,
  margin,
  rowState,
  setRow,
}: DenominationTableProps) {
  function sellPrice(amount: string | null, override: string): string {
    if (override.trim()) return override.trim();
    const cost = Number(amount ?? 0);
    const m = Number(margin || 0);
    if (!cost) return "—";
    return (Math.round(cost * (1 + m / 100) * 100) / 100).toFixed(2);
  }

  if (loading) {
    return <Spinner label="Загружаем номиналы…" />;
  }
  if (rows.length === 0) {
    return (
      <p className="text-sm text-[var(--text-secondary)]">G2B не вернул номиналов для этой игры.</p>
    );
  }

  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-[var(--text-tertiary)]">
          <th className="py-1"></th>
          <th>Номинал</th>
          <th>Себест. $</th>
          <th>Цена прод. $</th>
          <th>sku_code</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((d) => {
          const st = rowState(d);
          const label = d.name || d.catalogue_name;
          return (
            <tr key={d.catalogue_name} className="border-t border-[var(--border-default)]">
              <td className="py-1.5">
                <input
                  type="checkbox"
                  aria-label={`Выбрать ${label}`}
                  checked={st.checked}
                  onChange={(e) => {
                    setRow(d.catalogue_name, { checked: e.target.checked });
                  }}
                />
              </td>
              <td>{label}</td>
              <td className="font-mono">{d.amount ?? "—"}</td>
              <td>
                <input
                  aria-label={`Цена продажи ${label}`}
                  value={st.price_override}
                  placeholder={sellPrice(d.amount, "")}
                  onChange={(e) => {
                    setRow(d.catalogue_name, { price_override: e.target.value });
                  }}
                  inputMode="decimal"
                  className="h-8 w-24 rounded border border-[var(--border-default)] bg-[var(--bg-surface)] px-2 font-mono"
                />
              </td>
              <td>
                <input
                  aria-label={`SKU-код ${label}`}
                  value={st.sku_code}
                  onChange={(e) => {
                    setRow(d.catalogue_name, { sku_code: e.target.value });
                  }}
                  className="h-8 w-48 rounded border border-[var(--border-default)] bg-[var(--bg-surface)] px-2 font-mono text-xs"
                />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
