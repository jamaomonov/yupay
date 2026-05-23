import type { ReactNode } from "react";

interface Props {
  /** Tailwind classes that paint the pill: `bg-... text-...`. */
  tone: string;
  /** When true, prepend a small dot in `currentColor` (lit pill). */
  dot?: boolean;
  children: ReactNode;
  className?: string;
}

/**
 * Status pill used across orders / payments / fulfilment lists.
 * The `dot` prop turns the pill into a "lit" indicator so the eye
 * locks onto live states (paid, in_progress, requires_action) faster
 * than a flat coloured pill.
 */
export function Badge({ tone, dot, children, className }: Props) {
  return (
    <span
      className={[
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium",
        tone,
        className ?? "",
      ].join(" ")}
    >
      {dot && (
        <span
          aria-hidden
          className="size-1.5 shrink-0 rounded-full bg-current opacity-90"
        />
      )}
      <span className="truncate">{children}</span>
    </span>
  );
}
