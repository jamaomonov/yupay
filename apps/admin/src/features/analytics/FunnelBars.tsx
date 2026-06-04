import type { FunnelOut } from "./types";

export function FunnelBars({ funnel }: { funnel: FunnelOut }) {
  const stages: { label: string; n: number }[] = [
    { label: "Создано", n: funnel.created },
    { label: "Оплачено", n: funnel.paid },
    { label: "Выдаётся", n: funnel.fulfilling },
    { label: "Доставлено", n: funnel.delivered },
  ];
  const max = Math.max(1, funnel.created);
  return (
    <div className="space-y-2">
      {stages.map((s) => (
        <div key={s.label} className="flex items-center gap-3">
          <div className="w-24 text-xs text-[var(--text-secondary)]">{s.label}</div>
          <div className="h-6 flex-1 overflow-hidden rounded bg-[var(--bg-muted)]">
            <div
              className="h-full bg-[var(--accent)]"
              style={{ width: `${String((s.n / max) * 100)}%` }}
            />
          </div>
          <div className="w-12 text-right text-xs font-medium">{s.n}</div>
        </div>
      ))}
      <div className="text-xs text-[var(--text-tertiary)]">
        Конверсия в оплату: {funnel.payment_conversion_pct}%
      </div>
    </div>
  );
}
