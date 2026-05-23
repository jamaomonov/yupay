/**
 * Empty / loading / error placeholders.
 *
 * Replaces the previous "`<p>Загрузка…</p>`" plain-text loaders and the
 * disconnected "Пока пусто" strings scattered across queue pages.
 * Three primitives:
 *
 *   - <Spinner>    — inline, with optional text. For headers, buttons, etc.
 *   - <Skeleton>   — visual placeholder shaped like the eventual content.
 *   - <EmptyState> — full panel with icon + title + optional CTA + hint.
 *
 * All three are theme-aware (Dim Slate tokens) and respect motion preferences
 * via a CSS-only fallback (the `animate-spin` Tailwind utility honours
 * `prefers-reduced-motion`).
 */

import { Loader2, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

interface SpinnerProps {
  /** Visible loading text. Omit for icon-only spinner. */
  label?: string;
  size?: "sm" | "md";
  className?: string;
}

export function Spinner({ label, size = "md", className }: SpinnerProps) {
  const px = size === "sm" ? "size-3.5" : "size-4";
  return (
    <span
      role="status"
      aria-live="polite"
      className={[
        "inline-flex items-center gap-2 text-sm text-[--text-secondary]",
        className ?? "",
      ].join(" ")}
    >
      <Loader2 className={`${px} animate-spin`} aria-hidden />
      {label && <span>{label}</span>}
      {!label && <span className="sr-only">Загрузка</span>}
    </span>
  );
}

interface SkeletonProps {
  className?: string;
  /** Render N stacked skeleton rows — handy for list placeholders. */
  rows?: number;
}

export function Skeleton({ className, rows = 1 }: SkeletonProps) {
  return (
    <div className="space-y-2" aria-busy="true" aria-live="polite">
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className={[
            "h-4 rounded bg-[--bg-muted] animate-pulse",
            className ?? "",
          ].join(" ")}
        />
      ))}
    </div>
  );
}

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: ReactNode;
  /** Primary CTA — pass a Button or a Link. */
  action?: ReactNode;
  tone?: "default" | "muted";
  className?: string;
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  tone = "default",
  className,
}: EmptyStateProps) {
  return (
    <div
      role="status"
      className={[
        "rounded-lg border border-dashed border-[--border-default] bg-[--bg-surface] px-6 py-10 text-center",
        tone === "muted" ? "bg-[--bg-muted]" : "",
        className ?? "",
      ].join(" ")}
    >
      {Icon && (
        <div className="mx-auto mb-3 grid size-12 place-items-center rounded-full bg-[--bg-muted] text-[--text-secondary]">
          <Icon className="size-6" aria-hidden />
        </div>
      )}
      <p className="text-sm font-medium text-[--text-primary]">{title}</p>
      {description && (
        <p className="mt-1 text-sm text-[--text-secondary]">{description}</p>
      )}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}
