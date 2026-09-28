"use client";

import { SlidersHorizontal, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import type { ReactNode } from "react";

/**
 * The phone's filter panel: a button beside sort that opens the (server-rendered)
 * filters in a bottom drawer, instead of a `<details>` that pushed the grid a
 * screen down. Filters are links, so each tap reloads the grid behind the drawer;
 * the drawer stays open until «Готово».
 */
export function SkinFilterDrawer({ count, children }: { count: number; children: ReactNode }) {
  const t = useTranslations("web.skins");
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  // A modal that behaves like one: focus moves in on open and back to the
  // trigger on close, Tab stays inside, Escape closes, and the page's own
  // scroll lock (MobileNav sets one too) is restored rather than cleared.
  useEffect(() => {
    if (!open) return;
    const opener = trigger.current;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButton.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        return;
      }
      if (e.key !== "Tab" || !panel.current) return;
      const items = panel.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), [tabindex="0"]',
      );
      const first = items[0];
      const last = items[items.length - 1];
      if (!first || !last) return;
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
      opener?.focus();
    };
  }, [open]);

  return (
    <>
      <button
        ref={trigger}
        type="button"
        onClick={() => setOpen(true)}
        className="border-border bg-card flex shrink-0 items-center gap-2 rounded-xl border px-4 py-2.5 text-[14px] font-semibold lg:hidden"
        aria-label={count > 0 ? `${t("filters")}: ${String(count)}` : t("filters")}
      >
        <SlidersHorizontal className="h-4 w-4" aria-hidden />
        {t("filters")}
        {count > 0 && (
          <span className="bg-primary text-primary-foreground rounded-full px-1.5 text-[11px] font-bold">
            {count}
          </span>
        )}
      </button>
      {open && (
        <div
          className="fixed inset-0 z-[60] lg:hidden"
          role="dialog"
          aria-modal
          aria-label={t("filters")}
        >
          {/* The backdrop closes on a tap but is not a control of its own. */}
          <div
            aria-hidden
            className="absolute inset-0 bg-black/60"
            onClick={() => setOpen(false)}
          />
          <div
            ref={panel}
            className="bg-card border-border absolute inset-x-0 bottom-0 flex max-h-[85vh] flex-col rounded-t-3xl border-t"
          >
            <div className="flex items-center justify-between px-5 pb-2 pt-4">
              <p className="text-[16px] font-bold">{t("filters")}</p>
              <button
                ref={closeButton}
                type="button"
                onClick={() => setOpen(false)}
                aria-label={t("close")}
                className="text-tx-mute hover:text-foreground rounded-lg p-1"
              >
                <X className="h-5 w-5" aria-hidden />
              </button>
            </div>
            <div className="overflow-y-auto px-5 pb-4">{children}</div>
            <div className="border-border border-t p-4">
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="bg-primary text-primary-foreground w-full rounded-xl py-3 text-[15px] font-bold"
              >
                {t("done")}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
