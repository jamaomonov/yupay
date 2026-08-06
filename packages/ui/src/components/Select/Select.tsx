import { ChevronDown } from "lucide-react";
import { type SelectHTMLAttributes, forwardRef } from "react";

import { cn } from "../../lib/cn";

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  /**
   * Layout classes for the wrapper — width and margins. They belong here
   * rather than on the select itself: the chevron is positioned against the
   * wrapper, so a width applied only to the select would leave the arrow
   * floating somewhere to its right.
   */
  containerClassName?: string;
}

/**
 * Native select styled to match {@link Input}.
 *
 * The admin had thirty-four hand-styled `<select>` elements across nineteen
 * files, drifting between `h-9` and `h-10` and — more importantly — none of
 * them carrying a focus ring, so keyboard users had no idea where they were.
 * This keeps the native element (the OS picker is better than anything we
 * would build, especially on mobile) and only takes over the chrome.
 *
 * `appearance-none` plus an overlaid chevron is what makes the control look the
 * same in both themes: the platform arrow ignores our colours and turns near
 * invisible on a dark surface.
 */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, containerClassName, children, ...props }, ref) => (
    <div className={cn("relative inline-flex", containerClassName ?? "w-full")}>
      <select
        ref={ref}
        className={cn(
          "flex h-10 w-full appearance-none rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] py-2 pl-3 pr-9 text-sm text-[var(--text-primary)]",
          "transition-[border-color,box-shadow] duration-150 ease-out",
          "hover:border-[var(--border-strong)]",
          "focus-visible:border-[var(--accent)] focus-visible:outline-none",
          "focus-visible:ring-[var(--accent)]/30 focus-visible:ring-2",
          "focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-base)]",
          "disabled:cursor-not-allowed disabled:opacity-50",
          className,
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-[var(--text-secondary)]"
        aria-hidden
      />
    </div>
  ),
);

Select.displayName = "Select";
