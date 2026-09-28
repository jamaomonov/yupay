/** Small form pieces shared by the skins pricing cards. */

import { Button } from "@yupay/ui";

import { T } from "./api";

import type { Bracket } from "./pricing-api";
import type { ReactNode } from "react";

const P = T.pricing.rules;

export const INPUT =
  "h-9 w-full rounded-md border border-[var(--border)] bg-transparent px-2 text-sm tabular-nums";

export function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-4 rounded-lg border border-[var(--border-default)] p-4">
      <h2 className="text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}

export function NumberField({
  label,
  value,
  onChange,
  step = "0.01",
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  step?: string;
}) {
  return (
    <label className="block space-y-1 text-sm">
      <span className="text-[var(--text-secondary)]">{label}</span>
      <input
        type="number"
        step={step}
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
        }}
        className={INPUT}
      />
    </label>
  );
}

export function BracketRows({
  title,
  rows,
  onChange,
}: {
  title: string;
  rows: Bracket[];
  onChange: (rows: Bracket[]) => void;
}) {
  const set = (i: number, patch: Partial<Bracket>) => {
    onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  };
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">{title}</legend>
      {rows.map((r, i) => (
        <div key={i} className="flex items-center gap-2">
          <input
            aria-label={`${title}: ${P.fromUsd} ${String(i + 1)}`}
            type="number"
            step="0.01"
            value={r.from_usd}
            onChange={(e) => {
              set(i, { from_usd: e.target.value });
            }}
            className={INPUT}
          />
          <input
            aria-label={`${title}: ${P.percent} ${String(i + 1)}`}
            type="number"
            step="0.01"
            value={r.percent}
            onChange={(e) => {
              set(i, { percent: e.target.value });
            }}
            className={INPUT}
          />
          <Button
            variant="ghost"
            size="sm"
            disabled={rows.length === 1}
            onClick={() => {
              onChange(rows.filter((_, j) => j !== i));
            }}
          >
            {P.removeRow}
          </Button>
        </div>
      ))}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => {
          onChange([...rows, { from_usd: "", percent: "" }]);
        }}
      >
        {P.addRow}
      </Button>
    </fieldset>
  );
}

export function MapRows({
  title,
  keys,
  values,
  onChange,
}: {
  title: string;
  keys: string[];
  values: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}) {
  return (
    <fieldset className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      <legend className="mb-1 text-sm font-medium">{title}</legend>
      {keys.map((k) => (
        <NumberField
          key={k}
          label={k}
          value={values[k] ?? ""}
          onChange={(v) => {
            const rest = Object.fromEntries(Object.entries(values).filter(([key]) => key !== k));
            onChange(v.trim() === "" ? rest : { ...rest, [k]: v });
          }}
        />
      ))}
    </fieldset>
  );
}
