import { Star } from "lucide-react";

/**
 * Five stars filled to `value` (0–5) via a gold overlay clipped to the
 * fractional width over a faint base row. Presentational; no client JS.
 */
export function Stars({ value, size = 14 }: { value: number; size?: number }) {
  const pct = Math.max(0, Math.min(100, (value / 5) * 100));
  return (
    <span className="relative inline-flex" aria-label={`${value.toFixed(1)} / 5`}>
      <span className="flex gap-[2px] text-white/20">
        {Array.from({ length: 5 }).map((_, i) => (
          <Star key={i} size={size} className="fill-current" />
        ))}
      </span>
      <span
        className="text-gold absolute inset-0 flex gap-[2px] overflow-hidden"
        style={{ width: `${String(pct)}%` }}
        aria-hidden
      >
        {Array.from({ length: 5 }).map((_, i) => (
          <Star key={i} size={size} className="fill-gold shrink-0" />
        ))}
      </span>
    </span>
  );
}
