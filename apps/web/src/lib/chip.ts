/**
 * A link pill — instruction, weapon, category, «see also» links.
 *
 * Measured 2026-11-13: the same kind of pill was 32px/12px on the home page,
 * 34px/13px on /skins and 39px/14px on /store. One size now: 36px, 13px.
 */
export function chipStyles(className = ""): string {
  const base =
    "border-border bg-card hover:border-border-2 text-tx-mute hover:text-foreground inline-flex h-9 items-center gap-1.5 rounded-full border px-3.5 text-[13px] font-medium transition";
  return className ? `${base} ${className}` : base;
}
