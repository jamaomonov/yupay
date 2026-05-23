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
        "inline-flex items-center gap-2 text-sm text-[var(--text-secondary)]",
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
            "h-4 rounded bg-[var(--bg-muted)] animate-pulse",
            className ?? "",
          ].join(" ")}
        />
      ))}
    </div>
  );
}

interface TableSkeletonProps {
  /** Number of placeholder rows. */
  rows?: number;
  /** Column count — used to fan placeholder bars across each row. */
  columns?: number;
}

/**
 * Table-shaped loading state — preserves the shell, header row, and row
 * stripes so the page doesn't reflow when the real data arrives. Each cell
 * gets a placeholder bar of jittered width so the result doesn't look like
 * a barcode.
 */
export function TableSkeleton({ rows = 6, columns = 5 }: TableSkeletonProps) {
  return (
    <div
      role="status"
      aria-busy="true"
      aria-live="polite"
      className="overflow-hidden rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] shadow-[var(--shadow-sm)]"
    >
      <div className="flex border-b border-[var(--border-subtle)] bg-[var(--bg-muted)] px-4 py-2">
        {Array.from({ length: columns }, (_, i) => (
          <span
            key={i}
            className="mr-4 h-3 w-16 animate-pulse rounded bg-[var(--border-default)] last:mr-0"
          />
        ))}
      </div>
      {Array.from({ length: rows }, (_, r) => (
        <div
          key={r}
          className={[
            "flex items-center border-t border-[var(--border-subtle)] px-4 py-3",
            r % 2 === 1 ? "bg-[var(--bg-surface-2)]" : "",
          ].join(" ")}
        >
          {Array.from({ length: columns }, (_, c) => {
            // Pseudo-random width per cell to break up the grid.
            const w = 40 + ((r * 7 + c * 13) % 6) * 12;
            return (
              <span
                key={c}
                className="mr-4 h-3 animate-pulse rounded bg-[var(--bg-muted)] last:mr-0"
                style={{ width: `${w.toString()}px` }}
              />
            );
          })}
        </div>
      ))}
      <span className="sr-only">Загрузка данных…</span>
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
        "rounded-lg border border-dashed border-[var(--border-default)] bg-[var(--bg-surface)] px-6 py-10 text-center",
        tone === "muted" ? "bg-[var(--bg-muted)]" : "",
        className ?? "",
      ].join(" ")}
    >
      {Icon && (
        <div className="mx-auto mb-3 grid size-12 place-items-center rounded-full bg-[var(--bg-muted)] text-[var(--text-secondary)]">
          <Icon className="size-6" aria-hidden />
        </div>
      )}
      <p className="text-sm font-medium text-[var(--text-primary)]">{title}</p>
      {description && (
        <p className="mt-1 text-sm text-[var(--text-secondary)]">{description}</p>
      )}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}
