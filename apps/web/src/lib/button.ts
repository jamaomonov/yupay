/**
 * Single source of truth for CTA styling. The lime button was previously
 * hand-rewritten in 6+ files with drifting heights, radii and shadow strings
 * (the classic "looks samey but never identical" tell). buttonStyles() returns
 * the className so it composes with <Link>, <a> and <button> alike.
 *
 * Radius comes from the --radius-btn token (rounded-btn); the CTA shadow is
 * defined once here.
 */
type Variant = "primary" | "ghost" | "onLime";
type Size = "xs" | "sm" | "md" | "lg";

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-btn transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-bg disabled:pointer-events-none disabled:opacity-50";

const SIZES: Record<Size, string> = {
  xs: "h-9 px-3.5 text-[13px]",
  sm: "h-[38px] px-5 text-sm",
  md: "h-[44px] px-5 text-sm",
  lg: "h-[52px] px-6 text-[15px]",
};

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-primary text-primary-foreground font-bold shadow-[0_12px_30px_-10px_hsl(var(--primary)/0.45)] hover:-translate-y-0.5 hover:shadow-[0_16px_36px_-10px_hsl(var(--primary)/0.6)]",
  ghost: "border border-border-2 text-foreground font-semibold hover:border-tx-dim hover:bg-muted",
  onLime: "bg-bg text-primary font-bold hover:-translate-y-0.5",
};

export function buttonStyles(opts?: {
  variant?: Variant;
  size?: Size;
  className?: string;
}): string {
  const { variant = "primary", size = "md", className = "" } = opts ?? {};
  return [BASE, SIZES[size], VARIANTS[variant], className].filter(Boolean).join(" ");
}
