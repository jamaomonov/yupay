"use client";

import { Check } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { routing, type AppLocale } from "@/i18n/routing";

const LOCALE_LABEL_KEY: Record<AppLocale, "localeRu" | "localeEn" | "localeUz"> = {
  ru: "localeRu",
  en: "localeEn",
  uz: "localeUz",
};

// Circular flag icons (en → Union Jack), shared with the miniapp. Decorative:
// the locale code / autonym carries the meaning, so each <Image> is alt="".
const FLAGS: Record<AppLocale, string> = {
  ru: "/flags/ru.png",
  en: "/flags/en.png",
  uz: "/flags/uz.png",
};

export function LocaleSwitcher() {
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
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onFocusIn = (e: FocusEvent) => {
      // Tabbing out of the group closes it — otherwise a keyboard user leaves
      // an open menu floating behind them.
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    document.addEventListener("focusin", onFocusIn);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("focusin", onFocusIn);
    };
  }, [open]);

  // Rewrite the leading ``/<locale>`` segment in the current path. ``as-needed``
  // routing means the default locale may not be present in the URL — we strip
  // whatever's there and prepend the chosen one explicitly.
  const hrefFor = (next: AppLocale) => {
    const stripped = pathname.replace(/^\/(ru|en|uz)(?=\/|$)/, "") || "/";
    return `/${next}${stripped === "/" ? "" : stripped}`;
  };

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v);
        }}
        aria-haspopup="true"
        aria-expanded={open}
        className="border-border bg-muted text-tx-mute hover:bg-card-2 hover:text-foreground rounded-btn flex h-11 items-center gap-2 border px-3 text-xs font-semibold uppercase tracking-wider transition"
      >
        <Image
          src={FLAGS[current]}
          alt=""
          width={18}
          height={18}
          className="h-[18px] w-[18px] rounded-full object-cover"
        />
        {current}
      </button>
      {open && (
        /* Plain links, not a listbox. The previous markup claimed
           `role="listbox"` with `role="option"` buttons nested inside `<li>`
           — which breaks the required parent/child relationship — and shipped
           none of the keyboard behaviour that role promises: no arrows, no
           Home/End, no aria-activedescendant, and Escape did nothing. Changing
           language is a navigation, so a list of links says exactly what it is,
           works without JS, and is indexable. */
        <ul className="border-border bg-card/95 absolute right-0 top-11 z-40 min-w-[10rem] overflow-hidden rounded-xl border p-1 shadow-2xl backdrop-blur-xl">
          {routing.locales.map((loc) => {
            const isActive = loc === current;
            return (
              <li key={loc}>
                <Link
                  href={hrefFor(loc)}
                  hrefLang={loc}
                  aria-current={isActive ? "true" : undefined}
                  onClick={() => {
                    setOpen(false);
                  }}
                  className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-sm transition ${
                    isActive
                      ? "bg-card-2 text-foreground"
                      : "text-tx-mute hover:bg-card-2 hover:text-foreground"
                  }`}
                >
                  <span className="flex items-center gap-2">
                    <Image
                      src={FLAGS[loc]}
                      alt=""
                      width={18}
                      height={18}
                      className="h-[18px] w-[18px] rounded-full object-cover"
                    />
                    {t(LOCALE_LABEL_KEY[loc])}
                  </span>
                  {isActive && <Check size={14} className="text-primary" />}
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
