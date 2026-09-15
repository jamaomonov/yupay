import { Delta } from "@/components/Delta";

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
