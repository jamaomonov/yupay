interface KpiCardProps {
  label: string;
  value: string;
  hint?: string;
  /** This figure and the one it replaced, for the movement chip. Both raw
   *  numbers — the card formats nothing, it only compares. */
  now?: number;
  was?: number;
  /** `true` when up is bad — refunds, for one. */
  inverted?: boolean;
}

/**
 * The delta chip.
 *
 * Every headline on this tab used to be an absolute, and "1486 orders" is
 * neither good nor bad without the number it replaced. The comparison window
 * is the same length as the current one, so the chip is like-for-like.
 *
 * A move from zero has no percentage — "+∞%" is noise — so it says «новое»
 * instead. A move to zero is -100%, which is meaningful and stays.
 */
function Delta({ now, was, inverted }: { now: number; was: number; inverted: boolean }) {
  if (was === 0) {
    return now === 0 ? null : <span className="text-[var(--text-secondary)]">новое</span>;
  }
  const pct = ((now - was) / Math.abs(was)) * 100;
  if (Math.abs(pct) < 0.5)
    return <span className="text-[var(--text-secondary)]">без изменений</span>;
  const good = inverted ? pct < 0 : pct > 0;
  return (
    <span className={good ? "text-[var(--success)]" : "text-[var(--danger)]"}>
      {pct > 0 ? "+" : "−"}
      {Math.abs(pct).toFixed(pct >= 10 || pct <= -10 ? 0 : 1)}%
    </span>
  );
}

export function KpiCard({ label, value, hint, now, was, inverted = false }: KpiCardProps) {
  const showDelta = now !== undefined && was !== undefined;
  return (
    <div className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-4">
      <div className="text-[11px] uppercase tracking-wide text-[var(--text-tertiary)]">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-2 text-xs text-[var(--text-secondary)]">
        {showDelta && <Delta now={now} was={was} inverted={inverted} />}
        {hint && <span>{hint}</span>}
      </div>
    </div>
  );
}
