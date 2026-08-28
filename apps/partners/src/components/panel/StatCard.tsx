/** One figure with its label. Money uses the display face and the accent; the
 *  hint underneath is where an explanation goes, so a number never has to
 *  carry one inline. */
export function StatCard({
  label,
  value,
  hint,
  accent = false,
}: {
  label: string;
  value: string;
  hint?: string;
  accent?: boolean;
}) {
  return (
    <div className="border-border bg-card rounded-xl border p-5">
      <span className="text-tx-mute block text-[13px]">{label}</span>
      <p
        className={`font-display mt-1.5 break-words text-2xl font-bold ${
          accent ? "text-primary" : "text-foreground"
        }`}
      >
        {value}
      </p>
      {hint !== undefined && <p className="text-tx-dim mt-2 text-[12px] leading-snug">{hint}</p>}
    </div>
  );
}
