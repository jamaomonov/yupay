/**
 * The one text field, the way `buttonStyles` is the one button.
 *
 * Measured on production 2026-11-13: seven input heights (34–49px), three
 * radii (12/14/20px) and two border tokens — `border-border` at 1.33:1, an edge
 * nobody could see on the sign-in and promo forms. Every field now takes the
 * checkout's: 46px, `rounded-btn`, the visible `--border-2`, lime on focus.
 */
type Surface = "card" | "bg";

const BASE =
  "rounded-btn w-full border text-[15px] text-foreground outline-none transition placeholder:text-tx-dim focus:border-primary focus-visible:ring-2 focus-visible:ring-primary/25 disabled:opacity-60";

const SURFACES: Record<Surface, string> = {
  // A field on a card reads as a well in it; on the page background, as a card.
  card: "bg-card",
  bg: "bg-bg",
};

export function inputStyles(opts?: {
  /** The colour behind the field's own fill — default `card`. */
  surface?: Surface;
  /** A leading icon sits at left-3: the text starts after it. */
  icon?: boolean;
  /** A textarea: no fixed height, vertical padding instead. */
  multiline?: boolean;
  invalid?: boolean;
  className?: string;
}): string {
  const {
    surface = "card",
    icon = false,
    multiline = false,
    invalid = false,
    className = "",
  } = opts ?? {};
  return [
    BASE,
    SURFACES[surface],
    multiline ? "py-2.5" : "h-[46px]",
    icon ? "pl-10 pr-3.5" : "px-3.5",
    invalid ? "border-danger" : "border-border-2",
    className,
  ]
    .filter(Boolean)
    .join(" ");
}
