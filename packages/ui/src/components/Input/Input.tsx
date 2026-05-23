import { type InputHTMLAttributes, forwardRef } from "react";

import { cn } from "../../lib/cn";

export type InputProps = InputHTMLAttributes<HTMLInputElement>;

/**
 * Text input with a focus ring that survives both themes — the ring sits
 * outside the input via `ring-offset-2`, so it remains visible even when the
 * input is set on the same surface colour as the page.
 */
export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, type = "text", ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(
        "flex h-10 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)]",
        // Use --text-secondary (passes AA 4.5:1 on surfaces) rather than --text-tertiary,
        // which is borderline against light --bg-surface. Stays readable in both themes.
        "placeholder:text-[var(--text-secondary)]",
        "transition-[border-color,box-shadow] duration-150 ease-out",
        "hover:border-[var(--border-strong)]",
        "focus-visible:outline-none focus-visible:border-[var(--accent)]",
        "focus-visible:ring-2 focus-visible:ring-[var(--accent)]/30",
        "focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-base)]",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);

Input.displayName = "Input";
