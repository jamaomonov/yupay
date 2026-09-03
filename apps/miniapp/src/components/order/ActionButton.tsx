/**
 * Extracted out of `OrderSuccess.tsx` (2026-09-03 review) purely to keep
 * that file near the repo's TS file-length budget — no behaviour change.
 */
export function ActionButton({
  icon,
  label,
  variant,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  variant: "primary" | "secondary";
  onClick?: () => void;
}) {
  const primary = variant === "primary";
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center justify-center gap-2 rounded-2xl py-3 text-sm font-semibold transition-transform active:scale-[0.97]"
      style={{
        background: primary ? "hsl(var(--primary))" : "hsl(var(--surface-2))",
        color: primary ? "hsl(var(--primary-foreground))" : "rgba(255,255,255,0.85)",
        border: primary ? "1px solid hsl(var(--primary))" : "1px solid hsl(var(--border))",
      }}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}
