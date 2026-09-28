"use client";

import { SlidersHorizontal, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

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

  useEffect(() => {
    if (!open) return;
    const close = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", close);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", close);
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <>
      <button
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
          <button
            type="button"
            aria-label={t("done")}
            className="absolute inset-0 bg-black/60"
            onClick={() => setOpen(false)}
          />
          <div className="bg-card border-border absolute inset-x-0 bottom-0 flex max-h-[85vh] flex-col rounded-t-3xl border-t">
            <div className="flex items-center justify-between px-5 pb-2 pt-4">
              <p className="text-[16px] font-bold">{t("filters")}</p>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label={t("done")}
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
