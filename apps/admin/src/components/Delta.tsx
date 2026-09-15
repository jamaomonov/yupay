/**
 * The movement chip: this figure against the one it replaced.
 *
 * Lives here rather than in a feature folder because two screens draw it —
 * the analytics KPIs and the overview — and a dashboard where the same
 * movement is coloured one way on one card and another way on the next is
 * worse than one with no chips at all.
 *
 * A move from zero has no percentage: "+∞%" is noise, so it says «новое». A
 * move *to* zero is -100%, which is meaningful and stays. Nothing to compare
 * against draws nothing.
 */
export function Delta({
  now,
  was,
  inverted = false,
  className = "",
}: {
  now: number;
  was: number;
  /** `true` when up is bad — refunds, cancellations. */
  inverted?: boolean;
  className?: string;
}) {
  if (was === 0) {
    return now === 0 ? null : (
      <span className={`text-[var(--text-secondary)] ${className}`}>новое</span>
    );
  }
  const pct = ((now - was) / Math.abs(was)) * 100;
  if (Math.abs(pct) < 0.5) {
    return <span className={`text-[var(--text-secondary)] ${className}`}>без изменений</span>;
  }
  const good = inverted ? pct < 0 : pct > 0;
  return (
    <span
      className={`${good ? "text-[var(--success-fg)]" : "text-[var(--danger-fg)]"} ${className}`}
      // The arrow is decoration; the sign and the number carry the meaning,
      // and a screen reader announcing "up arrow minus twelve percent" would
      // contradict itself.
      title={`было ${was.toLocaleString("ru-RU", { maximumFractionDigits: 2 })}`}
    >
      {pct > 0 ? "+" : "−"}
      {Math.abs(pct).toFixed(pct >= 10 || pct <= -10 ? 0 : 1)}%
    </span>
  );
}
