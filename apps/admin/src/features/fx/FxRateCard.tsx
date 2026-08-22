import { Button, Input } from "@yupay/ui";
import { useEffect, useState } from "react";

import type { AdminRateOut } from "./types";

interface Props {
  row: AdminRateOut;
  saving: boolean;
  error: string | null;
  onSave: (next: { use_manual: boolean; manual_rate: string | null }) => void;
}

export function FxRateCard({ row, saving, error, onSave }: Props) {
  const [useManual, setUseManual] = useState(row.use_manual);
  const [manualRate, setManualRate] = useState(row.manual_rate ?? "");
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    setUseManual(row.use_manual);
    setManualRate(row.manual_rate ?? "");
    setConfirming(false);
  }, [row.use_manual, row.manual_rate, row.rate]);

  const parsed = parseRate(manualRate);
  const dirty =
    useManual !== row.use_manual ||
    (manualRate.trim() === "" ? null : manualRate.trim()) !== (row.manual_rate ?? "");
  const canSave = dirty && (!useManual || parsed !== null);
  const drift = useManual ? deviation(parsed, row.fx_rate) : null;
  // No live rate means no sanity check — and FX being down is exactly when
  // somebody pins a rate by hand, so that is the wrong moment for the guard to
  // disappear. Ask either way.
  const noReference = useManual && parsed !== null && row.fx_rate === null;
  const needsConfirm = noReference || (drift !== null && drift > CONFIRM_DEVIATION);

  const save = () => {
    onSave({
      use_manual: useManual,
      manual_rate: manualRate.trim() === "" ? null : manualRate.trim(),
    });
    setConfirming(false);
  };

  return (
    <article className="rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
      <header className="mb-3 flex items-baseline justify-between gap-3">
        <div>
          <h2 className="font-medium">
            {row.base} → {row.quote}
          </h2>
          <p className="text-xs text-[var(--text-secondary)]">
            Система сейчас берёт {row.source === "manual" ? "наш курс" : "курс FX"}
          </p>
        </div>
        <span className="font-mono text-lg">{formatRate(row.rate)}</span>
      </header>

      <dl className="mb-4 grid grid-cols-2 gap-3 text-sm">
        <div>
          <dt className="text-xs text-[var(--text-secondary)]">Курс FX</dt>
          <dd className="font-mono">{row.fx_rate ? formatRate(row.fx_rate) : "недоступен"}</dd>
          {row.fx_source ? (
            <dd className="text-[10px] text-[var(--text-secondary)]">{row.fx_source}</dd>
          ) : null}
        </div>
        <div>
          <dt className="text-xs text-[var(--text-secondary)]">Действующий</dt>
          <dd className="font-mono">{formatRate(row.rate)}</dd>
        </div>
      </dl>

      <div className="mb-3 flex rounded-md border p-0.5">
        <button
          type="button"
          className={toggleClass(!useManual)}
          onClick={() => {
            setUseManual(false);
          }}
        >
          Курс FX
        </button>
        <button
          type="button"
          className={toggleClass(useManual)}
          onClick={() => {
            setUseManual(true);
          }}
        >
          Наш курс
        </button>
      </div>

      <label className="mb-3 block text-sm">
        <span className="mb-1 block text-xs text-[var(--text-secondary)]">Наш курс</span>
        <Input
          inputMode="decimal"
          value={manualRate}
          onChange={(e) => {
            setManualRate(e.target.value);
            setConfirming(false);
          }}
          placeholder={row.fx_rate ? formatRate(row.fx_rate) : "например 12500"}
        />
      </label>

      {needsConfirm ? (
        <p className="mb-2 text-sm text-[var(--warning,var(--danger))]">
          {noReference
            ? "Курс FX недоступен — сверить не с чем."
            : `Это на ${formatPercent(drift)} от курса FX (${formatRate(row.fx_rate ?? "")}).`}{" "}
          Наш курс идёт в цены без проверки на отклонение — убедитесь, что не потеряли ноль.
        </p>
      ) : null}

      {error ? <p className="mb-2 text-sm text-[var(--danger)]">{error}</p> : null}

      <Button
        onClick={() => {
          if (needsConfirm && !confirming) {
            setConfirming(true);
            return;
          }
          save();
        }}
        disabled={saving || !canSave}
      >
        {saving
          ? "Сохраняем…"
          : needsConfirm && confirming
            ? "Да, сохранить этот курс"
            : "Сохранить"}
      </Button>
    </article>
  );
}

function toggleClass(active: boolean): string {
  return [
    "flex-1 rounded-sm px-3 py-1.5 text-sm",
    active
      ? "bg-[var(--bg-muted)] font-medium"
      : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
  ].join(" ");
}

function formatPercent(fraction: number | null): string {
  if (fraction === null) return "—";
  return `${Math.round(fraction * 100).toLocaleString("ru")}%`;
}

export function formatRate(s: string): string {
  const n = Number.parseFloat(s);
  if (Number.isNaN(n)) return s;
  if (n >= 1000) return n.toLocaleString("ru", { maximumFractionDigits: 2 });
  return n.toLocaleString("ru", { maximumFractionDigits: 4 });
}

/** How far a typed rate sits from the live FX one, as a fraction, or `null`
 *  when there is nothing to compare against. */
export function deviation(typed: string | null, market: string | null): number | null {
  if (typed === null || market === null) return null;
  const t = Number.parseFloat(typed);
  const m = Number.parseFloat(market);
  if (!Number.isFinite(t) || !Number.isFinite(m) || m <= 0) return null;
  return Math.abs(t - m) / m;
}

/** Past this, we ask before saving.
 *
 * A pinned rate deliberately bypasses the pricing trust gate (ADR-0055), so a
 * typo in this one field re-prices the whole catalogue with nothing downstream
 * to argue. 12500 typed as 1250 is a factor of ten; 20% is comfortably above
 * any real pin and far below any fat finger. */
const CONFIRM_DEVIATION = 0.2;

function parseRate(s: string): string | null {
  const trimmed = s.trim().replace(",", ".");
  if (trimmed === "") return null;
  const n = Number.parseFloat(trimmed);
  if (!Number.isFinite(n) || n <= 0) return null;
  return trimmed;
}
