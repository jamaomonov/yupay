/**
 * Three heading sizes for the whole storefront (2026-11-13 review).
 *
 * Measured before: home H2s at six sizes (48–68px), page H1s from 24px on
 * /skins to 40px on the account pages, section H2s at 15/17/18/20/24px — one
 * page (PUBG) carried three. Landing heroes (home, /store, the Steam gifts hub,
 * a brand's photo header) keep their own display type on purpose; everything
 * else takes one of these.
 */
export type HeadingLevel = "display" | "page" | "section";

const LEVELS: Record<HeadingLevel, string> = {
  /** The home page's band titles. */
  display:
    "font-display text-[clamp(2.2rem,4.6vw,3.6rem)] font-extrabold leading-[0.98] tracking-[-0.04em]",
  /** A page's H1 outside the landing heroes. */
  page: "font-display text-[28px] font-bold leading-tight tracking-[-0.02em] sm:text-[34px]",
  /** A section's H2 inside a page. */
  section: "font-display text-xl font-bold leading-tight tracking-[-0.02em]",
};

export function headingStyles(level: HeadingLevel, className = ""): string {
  return className ? `${LEVELS[level]} ${className}` : LEVELS[level];
}
