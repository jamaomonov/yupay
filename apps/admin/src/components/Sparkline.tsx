/** Inline-SVG sparkline.
 *
 * Zero-dependency rendering of a small price-history series. We don't
 * pull in recharts / d3 for one widget — the SVG path is ~15 lines of
 * math, and Tailwind handles colour theming via the same CSS variables
 * the rest of the admin uses (so dim-slate / light flips for free).
 *
 * Renders nothing on empty / single-point data — the caller decides what
 * placeholder to show ("ещё нет истории" / sparkline shouldn't draw a
 * single dot pretending to be a trend).
 */

import { useId } from "react";

interface Props {
  /** Series ordered oldest → newest. */
  values: number[];
  width?: number;
  height?: number;
  /** Optional ARIA description for screen readers. */
  ariaLabel?: string;
  /** Whether to fill under the line. Default true. */
  filled?: boolean;
  /** When false, the gradient under the line is muted (lighter
   *  background palette) — useful inside dense table rows. */
  strong?: boolean;
}

export function Sparkline({
  values,
  width = 160,
  height = 36,
  ariaLabel,
  filled = true,
  strong = true,
}: Props) {
  const gradientId = useId();

  if (values.length < 2) return null;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max === min ? 1 : max - min;
  const stepX = width / (values.length - 1);
  // Leave a 2px breathing room top + bottom so the stroke doesn't clip
  // against the SVG edge.
  const pad = 2;
  const innerH = height - pad * 2;

  const points = values.map((v, i) => {
    const x = i * stepX;
    const y = pad + innerH - ((v - min) / range) * innerH;
    return [x, y] as const;
  });
  const pathD = points
    .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`)
    .join(" ");
  // Close to the bottom for the optional fill.
  const lastPoint = points[points.length - 1];
  const fillD =
    filled && lastPoint ? `${pathD} L${lastPoint[0].toFixed(2)},${height} L0,${height} Z` : null;

  const trendUp = values[values.length - 1]! >= values[0]!;
  const stroke = trendUp ? "var(--danger)" : "var(--success, #16a34a)";
  // ↑ for cost: rising cost is bad news; we paint it in danger-red.

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width.toString()} ${height.toString()}`}
      role="img"
      aria-label={ariaLabel ?? "цена со временем"}
      className="block"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity={strong ? 0.35 : 0.18} />
          <stop offset="100%" stopColor={stroke} stopOpacity={0} />
        </linearGradient>
      </defs>
      {fillD && <path d={fillD} fill={`url(#${gradientId})`} />}
      <path d={pathD} fill="none" stroke={stroke} strokeWidth={1.5} strokeLinecap="round" />
      {/* Mark first + last points so the trajectory is readable at a
          glance even on a 3-point series. */}
      {points[0] && (
        <circle cx={points[0][0]} cy={points[0][1]} r={1.5} fill={stroke} opacity={0.6} />
      )}
      {lastPoint && <circle cx={lastPoint[0]} cy={lastPoint[1]} r={2.25} fill={stroke} />}
    </svg>
  );
}
