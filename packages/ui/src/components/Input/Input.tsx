import { type InputHTMLAttributes, forwardRef } from "react";

import { cn } from "../../lib/cn";

export type InputProps = InputHTMLAttributes<HTMLInputElement>;

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, type = "text", ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(
        "flex h-10 w-full rounded-md border border-[--color-border] bg-[--color-bg] px-3 py-2 text-sm",
        "placeholder:text-[--color-muted]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[--color-brand]",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);

Input.displayName = "Input";
