/**
 * Theme picker — a three-way dropdown (Light / Dark / System) in the topbar.
 *
 * Why dropdown and not a cycle button: the third state (System) isn't
 * intuitive when you can only flip — operators sometimes need to *see* which
 * mode is active, and a dropdown with checkmarks shows that directly.
 *
 * Accessibility:
 *  - The trigger carries `aria-label="Theme"` (the visible icon alone isn't
 *    enough for a screen-reader to know what the button does).
 *  - The menu uses `role="menu"` and each option `role="menuitemradio"` with
 *    `aria-checked` reflecting the active mode.
 *  - Closes on Escape, outside-click, route change, and after picking.
 */

import { useEffect, useRef, useState } from "react";
import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react";

import { useThemeStore, type ThemeMode } from "./themeStore";

const OPTIONS: { mode: ThemeMode; label: string; icon: LucideIcon }[] = [
  { mode: "light", label: "Светлая", icon: Sun },
  { mode: "dark", label: "Тёмная", icon: Moon },
  { mode: "system", label: "Системная", icon: Monitor },
];

const ICON_FOR_MODE: Record<ThemeMode, LucideIcon> = {
  light: Sun,
  dark: Moon,
  system: Monitor,
};

export function ThemeMenu() {
  const mode = useThemeStore((s) => s.mode);
  const setMode = useThemeStore((s) => s.setMode);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  // Close on outside click or Escape.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (
        wrapRef.current &&
        e.target instanceof Node &&
        !wrapRef.current.contains(e.target)
      ) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("mousedown", onClick);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onClick);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const CurrentIcon = ICON_FOR_MODE[mode];

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => { setOpen((v) => !v); }}
        aria-label="Theme"
        aria-haspopup="menu"
        aria-expanded={open}
        className="inline-flex size-9 items-center justify-center rounded-md border border-[--border-default] text-[--text-secondary] hover:bg-[--bg-muted] hover:text-[--text-primary]"
      >
        <CurrentIcon className="size-4" />
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Theme"
          className="absolute right-0 z-50 mt-2 w-44 overflow-hidden rounded-lg border border-[--border-default] bg-[--bg-surface] py-1 text-sm shadow-[var(--shadow-md)]"
        >
          {OPTIONS.map((opt) => {
            const Icon = opt.icon;
            const active = mode === opt.mode;
            return (
              <button
                key={opt.mode}
                type="button"
                role="menuitemradio"
                aria-checked={active}
                onClick={() => {
                  setMode(opt.mode);
                  setOpen(false);
                }}
                className={[
                  "flex w-full items-center gap-2 px-3 py-2 text-left text-[--text-primary]",
                  active
                    ? "bg-[--bg-accent-soft] text-[--accent-soft-fg]"
                    : "hover:bg-[--bg-muted]",
                ].join(" ")}
              >
                <Icon className="size-4" />
                <span className="flex-1">{opt.label}</span>
                {active && (
                  <span className="text-[--accent-soft-fg]" aria-hidden>
                    ✓
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
