import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";

import type { ReactNode } from "react";

export interface Crumb {
  label: string;
  /** When set, the crumb renders as a `<Link>`. The last crumb is usually
   *  current-location, rendered as plain text. */
  to?: string;
}

interface Props {
  title: string;
  description?: ReactNode;
  /** Breadcrumb trail rendered above the title. Last item is the current page. */
  breadcrumbs?: Crumb[];
  actions?: ReactNode;
}

export function PageHeader({ title, description, breadcrumbs, actions }: Props) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {breadcrumbs && breadcrumbs.length > 0 && (
          <nav
            aria-label="Breadcrumb"
            className="mb-1 flex items-center gap-1 text-xs text-[var(--text-secondary)]"
          >
            {breadcrumbs.map((c, i) => {
              const last = i === breadcrumbs.length - 1;
              return (
                <span key={`${c.label}-${i.toString()}`} className="flex items-center gap-1">
                  {c.to && !last ? (
                    <Link
                      to={c.to}
                      className="rounded transition-colors hover:text-[var(--text-primary)] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-base)]"
                    >
                      {c.label}
                    </Link>
                  ) : (
                    <span
                      aria-current={last ? "page" : undefined}
                      className={last ? "text-[var(--text-primary)]" : undefined}
                    >
                      {c.label}
                    </span>
                  )}
                  {!last && (
                    <ChevronRight className="size-3 text-[var(--text-tertiary)]" aria-hidden />
                  )}
                </span>
              );
            })}
          </nav>
        )}
        <h1 className="text-2xl font-semibold">{title}</h1>
        {description && <p className="mt-1 text-sm text-[var(--text-secondary)]">{description}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </header>
  );
}
