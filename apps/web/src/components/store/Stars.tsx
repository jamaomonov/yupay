import { Star } from "lucide-react";

/**
 * Five stars filled to `value` (0–5) via a gold overlay clipped to the
 * fractional width over a faint base row. Presentational; no client JS.
 *
 * `role="img"` is what makes this readable rather than decorative. Without a
 * role the wrapper is a generic element, and ARIA forbids labelling those — the
 * `aria-label` was silently dropped, leaving ten unexplained star glyphs in the
 * accessibility tree. The role also prunes the subtree, so the whole widget is
 * announced once, as its label.
 */
export function Stars({
  value,
  size = 14,
  label,
}: {
  value: number;
  size?: number;
  /** Localised, e.g. "Рейтинг 4,3 из 5". Falls back to bare notation. */
  label?: string;
}) {
  const pct = Math.max(0, Math.min(100, (value / 5) * 100));
  return (
    <span
      className="relative inline-flex"
      role="img"
      aria-label={label ?? `${value.toFixed(1)} / 5`}
    >
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
