/**
 * One figure with its label, as a cell in a ruled grid.
 *
 * Flat on purpose. Its parent draws the hairlines by showing its own
 * background through a `gap-px` grid (see `.grid-ruled` in `globals.css`), so
 * this must not carry a border or a radius of its own — two boxes' worth of
 * edges around one number is how the panel came to look like a different
 * product from the page that recruits for it.
 *
 * Money uses the display face and the accent; the hint underneath is where an
 * explanation goes, so a number never has to carry one inline.
 */
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
    <div className="bg-bg px-5 py-6 sm:px-6">
      <span className="text-tx-mute block font-mono text-[11px] uppercase tracking-[0.12em]">
        {label}
      </span>
      <p
        className={`font-display mt-3 break-words text-[26px] font-extrabold leading-none tracking-[-0.03em] ${
          accent ? "text-primary" : "text-foreground"
        }`}
      >
        {value}
      </p>
      {hint !== undefined && <p className="text-tx-dim mt-3 text-[12px] leading-snug">{hint}</p>}
    </div>
  );
}
