"use client";

import { Check, Globe } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { routing, type AppLocale } from "@/i18n/routing";

const LOCALE_LABEL_KEY: Record<AppLocale, "localeRu" | "localeEn" | "localeUz"> = {
  ru: "localeRu",
  en: "localeEn",
  uz: "localeUz",
};

export function LocaleSwitcher() {
  const router = useRouter();
  const pathname = usePathname();
  const current = useLocale() as AppLocale;
  const t = useTranslations("web.common");

  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const pick = (next: AppLocale) => {
    setOpen(false);
    if (next === current) return;
    // Rewrite the leading ``/<locale>`` segment in the current path. ``as-needed``
    // routing means the default locale may not be present in the URL — we
    // strip whatever's there and prepend the chosen one explicitly.
    const stripped = pathname.replace(/^\/(ru|en|uz)(?=\/|$)/, "") || "/";
    router.push(`/${next}${stripped === "/" ? "" : stripped}`);
  };

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex h-[38px] items-center gap-2 rounded-[10px] border border-border bg-muted px-3 text-xs font-semibold uppercase tracking-wider text-tx-mute transition hover:bg-card-2 hover:text-foreground"
      >
        <Globe size={14} />
        {current}
      </button>
      {open && (
        <ul
          role="listbox"
          className="absolute right-0 top-11 z-40 min-w-[10rem] overflow-hidden rounded-xl border border-border bg-card/95 p-1 shadow-2xl backdrop-blur-xl"
        >
          {routing.locales.map((loc) => {
            const isActive = loc === current;
            return (
              <li key={loc}>
                <button
                  type="button"
                  onClick={() => pick(loc)}
                  role="option"
                  aria-selected={isActive}
                  className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-sm transition ${
                    isActive
                      ? "bg-card-2 text-foreground"
                      : "text-tx-mute hover:bg-card-2 hover:text-foreground"
                  }`}
                >
                  <span>{t(LOCALE_LABEL_KEY[loc])}</span>
                  {isActive && <Check size={14} className="text-primary" />}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
