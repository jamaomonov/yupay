/**
 * Tab navigation row — accessible tablist with arrow-key roving, used in
 * Fulfilment Inbox, Payments Triage, Customer 360 (eventually), etc.
 *
 * The component does not render the tab *panels* — the parent renders them
 * conditionally below this row. Each tab gets `aria-controls` pointing at
 * the panel id the parent assigns, so `aria-selected` stays meaningful for
 * a screen reader.
 *
 * Roving tabIndex (active tab = 0, others = −1) matches APG conventions:
 * the user Tabs into the row once, then uses Left/Right (or Home/End) to
 * switch tabs. The active tab is the only Tab-stop for the whole list.
 */

import { useId } from "react";
import { type LucideIcon } from "lucide-react";

export interface TabDescriptor<T extends string> {
  id: T;
  label: string;
  icon?: LucideIcon;
  /** Optional counter shown after the label (`tone="warn"` for non-zero queues). */
  badge?: { count: number; tone?: "warn" | "muted" };
  /** Id of the panel below — wires up aria-controls. Auto-generated when omitted. */
  panelId?: string;
}

interface Props<T extends string> {
  value: T;
  onChange: (next: T) => void;
  tabs: TabDescriptor<T>[];
  /** WAI-ARIA label for the tablist — disambiguates when more than one is on a page. */
  ariaLabel: string;
  className?: string;
}

export function Tabs<T extends string>({
  value,
  onChange,
  tabs,
  ariaLabel,
  className,
}: Props<T>) {
  const baseId = useId();

  const onKeyDown = (e: React.KeyboardEvent) => {
    const i = tabs.findIndex((t) => t.id === value);
    if (i < 0) return;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      e.preventDefault();
      const next = tabs[(i + 1) % tabs.length];
      if (next) onChange(next.id);
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      e.preventDefault();
      const next = tabs[(i - 1 + tabs.length) % tabs.length];
      if (next) onChange(next.id);
    } else if (e.key === "Home") {
      e.preventDefault();
      const first = tabs[0];
      if (first) onChange(first.id);
    } else if (e.key === "End") {
      e.preventDefault();
      const last = tabs[tabs.length - 1];
      if (last) onChange(last.id);
    }
  };

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
      className={[
        "flex flex-wrap gap-1 border-b border-[--border-default]",
        className ?? "",
      ].join(" ")}
    >
      {tabs.map((tab) => {
        const Icon = tab.icon;
        const active = tab.id === value;
        const tabId = `${baseId}-${tab.id}`;
        const panelId = tab.panelId ?? `${baseId}-panel-${tab.id}`;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={tabId}
            aria-selected={active}
            aria-controls={panelId}
            tabIndex={active ? 0 : -1}
            onClick={() => { onChange(tab.id); }}
            className={[
              "inline-flex items-center gap-2 border-b-2 px-3 py-2 text-sm font-medium transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[--accent] focus-visible:ring-offset-2 focus-visible:ring-offset-[--bg-base] focus-visible:rounded",
              active
                ? "border-[--accent] text-[--text-primary]"
                : "border-transparent text-[--text-secondary] hover:text-[--text-primary]",
            ].join(" ")}
          >
            {Icon && <Icon className="size-4" aria-hidden />}
            <span>{tab.label}</span>
            {tab.badge && (
              <span
                className={[
                  "rounded-full px-1.5 py-0.5 text-[11px]",
                  tab.badge.count > 0 && tab.badge.tone === "warn"
                    ? "bg-[--danger-soft] text-[--danger-fg]"
                    : "bg-[--bg-muted] text-[--text-secondary]",
                ].join(" ")}
              >
                {tab.badge.count.toString()}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
