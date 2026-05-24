import { cva, type VariantProps } from "class-variance-authority";
import { type ButtonHTMLAttributes, forwardRef } from "react";

import { cn } from "../../lib/cn";

/**
 * Button variants — five intentions, each with a clear, distinguishable shape:
 *
 *  - `primary`   — the page's main action (one per screen). Filled accent.
 *  - `secondary` — supporting actions. Bordered surface, never flat.
 *  - `ghost`     — low-emphasis but still visibly a control: transparent fill,
 *                  hover reveals a subtle bordered tile. Used for toolbar
 *                  buttons, icon-only triggers, "Назад".
 *  - `danger`    — destructive primary. Same weight as `primary`, danger token.
 *  - `link`      — pure text-link affordance, for the rare case where a button
 *                  truly should read as inline text (footnotes, "see more").
 *                  Don't reach for this where a control is expected — use
 *                  `ghost` instead.
 *
 * Active state (`:active`) is intentional on every variant so a click feels
 * registered even before the route changes. Focus rings sit above an offset
 * matched to the page background, so they're visible in both Dim Slate themes.
 */
export const buttonVariants = cva(
  [
    "relative inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium",
    "transition-[background-color,border-color,color,box-shadow] duration-150 ease-out",
    "disabled:pointer-events-none disabled:opacity-50",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]",
    "focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-base)]",
  ],
  {
    variants: {
      variant: {
        primary: [
          "bg-[var(--accent)] text-[var(--text-on-accent)]",
          "hover:bg-[var(--accent-hover)]",
          "active:bg-[var(--accent-active)]",
          "shadow-[var(--shadow-sm)]",
        ].join(" "),
        secondary: [
          "border border-[var(--border-default)] bg-[var(--bg-surface)] text-[var(--text-primary)]",
          "hover:bg-[var(--bg-muted)] hover:border-[var(--border-strong)]",
          "active:bg-[var(--bg-surface-2)]",
        ].join(" "),
        ghost: [
          // Transparent border by default so the hover state can paint one in
          // place — avoids the box "jumping" 1 px wider on hover.
          "border border-transparent text-[var(--text-primary)]",
          "hover:bg-[var(--bg-muted)] hover:border-[var(--border-default)]",
          "active:bg-[var(--bg-surface-2)]",
        ].join(" "),
        danger: [
          "bg-[var(--danger)] text-white",
          "hover:bg-[var(--danger)]/90",
          "active:bg-[var(--danger)]",
          "shadow-[var(--shadow-sm)]",
        ].join(" "),
        link: [
          "h-auto !p-0 text-[var(--accent)] underline-offset-4",
          "hover:underline hover:text-[var(--accent-hover)]",
          "active:text-[var(--accent-active)]",
          "focus-visible:ring-offset-1",
        ].join(" "),
      },
      size: {
        sm: "h-8 px-3",
        md: "h-10 px-4",
        lg: "h-12 px-6 text-base",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, type = "button", ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  ),
);

Button.displayName = "Button";
