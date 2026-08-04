"use client";

import { Menu, Send, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { AccountMenu } from "./auth/AccountMenu";

import { type AppLocale } from "@/i18n/routing";
import { buttonStyles } from "@/lib/button";
import { TELEGRAM_MINIAPP_URL } from "@/lib/links";
import { pathFor } from "@/lib/seo";

const LOCALES: { code: AppLocale; label: string }[] = [
  { code: "ru", label: "Русский" },
  { code: "en", label: "English" },
  { code: "uz", label: "Oʻzbekcha" },
];

/**
 * Mobile-only header controls (<md): a persistent lime "top up" pill plus a
 * hamburger that opens a full-width sheet with the nav links, an Open-in-
 * Telegram action, and a language row. Keeps a sticky conversion entry point
 * on phones, which is where the UZ/RU/Telegram-native traffic actually lands.
 */
export function MobileNav() {
  const t = useTranslations("web.nav");
  const tShow = useTranslations("web.showcase");
  const router = useRouter();
  const pathname = usePathname();
  const current = useLocale() as AppLocale;
  const [open, setOpen] = useState(false);

  // Lock body scroll while the sheet is open.
  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  // Escape closes the sheet (keyboard users / attached hardware keyboards).
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const close = () => {
    setOpen(false);
  };

  const pickLocale = (next: AppLocale) => {
    close();
    if (next === current) return;
    const stripped = pathname.replace(/^\/(ru|en|uz)(?=\/|$)/, "") || "/";
    router.push(`/${next}${stripped === "/" ? "" : stripped}`);
  };

  const linkClass =
    "border-border/60 text-foreground border-b py-3.5 text-[15px] font-semibold transition active:text-primary";

  return (
    <div className="flex items-center gap-2 md:hidden">
      <AccountMenu locale={current} />
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v);
        }}
        aria-label={t("openMenu")}
        aria-expanded={open}
        className="border-border bg-muted text-tx-mute flex h-11 w-11 items-center justify-center rounded-[10px] border"
      >
        {open ? <X size={18} /> : <Menu size={18} />}
      </button>

      {open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={t("openMenu")}
          className="anim-sheet-in bg-bg fixed inset-x-0 top-[72px] z-50 h-[calc(100dvh-72px)] overflow-y-auto"
        >
          <div className="mx-auto max-w-[1200px] px-6 py-5">
            <nav className="flex flex-col">
              <Link href={pathFor(current, "/store")} onClick={close} className={linkClass}>
                {t("store")}
              </Link>
              <a href="#how" onClick={close} className={linkClass}>
                {t("how")}
              </a>
              <a href="#reviews" onClick={close} className={linkClass}>
                {t("reviews")}
              </a>
              <a
                href="https://t.me/yupay_support"
                target="_blank"
                rel="noreferrer noopener"
                onClick={close}
                className={linkClass}
              >
                {t("support")}
              </a>
            </nav>

            <a
              href={TELEGRAM_MINIAPP_URL}
              target="_blank"
              rel="noreferrer noopener"
              onClick={close}
              className={buttonStyles({
                size: "lg",
                className: "mt-5 w-full",
              })}
            >
              <Send size={16} />
              {tShow("cta")}
            </a>

            <div className="mt-5 flex gap-2">
              {LOCALES.map((l) => (
                <button
                  key={l.code}
                  type="button"
                  onClick={() => {
                    pickLocale(l.code);
                  }}
                  className={`flex-1 rounded-[10px] border py-2.5 text-sm font-semibold transition ${
                    l.code === current
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border bg-muted text-tx-mute"
                  }`}
                >
                  {l.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
