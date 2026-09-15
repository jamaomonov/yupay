import type { LucideIcon } from "lucide-react";

/**
 * A code block dressed as a window.
 *
 * The three dots are the macOS traffic lights, and they are doing one job:
 * telling a reader at a glance that the panel is a *screen*, not prose. On the
 * landing especially — where somebody is deciding whether this API is for
 * them — the sample is the thing they look at first, and a bare `<pre>` reads
 * as a wall of grey.
 *
 * Decorative, and marked so: `aria-hidden` on the dots, because a screen
 * reader announcing "three circles" before the code is worse than silence.
 * The title, if there is one, carries the meaning.
 *
 * Deliberately not a `<figure>`: the caption here is a window title, not a
 * description of the content, and the code inside is already a `<pre>`.
 */
export function CodeWindow({
  icon: Icon,
  title,
  actions,
  children,
  className = "",
}: {
  /** A hint at what kind of thing this is — a terminal, a request, a payload. */
  icon?: LucideIcon;
  title?: string;
  /** Tabs, a copy button: whatever belongs on the right of the title bar. */
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  const hasBar = Icon !== undefined || title !== undefined || actions !== undefined;
  return (
    <div className={`border-border bg-card overflow-hidden rounded-xl border ${className}`}>
      {hasBar && (
        <div className="border-border bg-card-2 flex items-center gap-2 border-b px-3 py-2">
          <span aria-hidden="true" className="flex shrink-0 items-center gap-[6px] pr-1">
            {/* Apple's own values, so it reads as the thing it is imitating
                rather than as three red-ish dots. */}
            <span className="block h-[11px] w-[11px] rounded-full bg-[#FF5F57]" />
            <span className="block h-[11px] w-[11px] rounded-full bg-[#FEBC2E]" />
            <span className="block h-[11px] w-[11px] rounded-full bg-[#28C840]" />
          </span>
          {Icon !== undefined && <Icon size={13} className="text-tx-dim shrink-0" />}
          {title !== undefined && (
            <span className="text-tx-mute truncate font-mono text-[11.5px] font-medium">
              {title}
            </span>
          )}
          {actions !== undefined && (
            <div className="ml-auto flex items-center gap-1">{actions}</div>
          )}
        </div>
      )}
      {children}
    </div>
  );
}
