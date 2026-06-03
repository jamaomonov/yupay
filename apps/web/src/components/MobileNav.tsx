"use client";

import { ArrowRight, Menu, Send, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { type AppLocale } from "@/i18n/routing";
import { buttonStyles } from "@/lib/button";

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
  const prefix = `/${current}`;

  // Lock body scroll while the sheet is open.
  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
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
      <Link href={`${prefix}/store`} className={buttonStyles({ size: "xs" })}>
        {t("topUp")}
      </Link>
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v);
        }}
        aria-label="Menu"
        aria-expanded={open}
        className="border-border bg-muted text-tx-mute flex h-9 w-9 items-center justify-center rounded-[10px] border"
      >
        {open ? <X size={18} /> : <Menu size={18} />}
      </button>

      {open && (
        <>
          <button
            type="button"
            aria-label="Close menu"
            onClick={close}
            className="fixed inset-x-0 bottom-0 top-[72px] z-40 bg-black/50 backdrop-blur-sm"
          />
          <div className="border-border bg-bg/95 fixed inset-x-0 top-[72px] z-50 border-b backdrop-blur-xl">
            <div className="mx-auto max-w-[1200px] px-6 py-5">
              <nav className="flex flex-col">
                <Link href={`${prefix}/store`} onClick={close} className={linkClass}>
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

              <Link
                href={`${prefix}/store`}
                onClick={close}
                className={buttonStyles({ size: "lg", className: "mt-5 w-full" })}
              >
                {t("topUp")}
                <ArrowRight size={16} strokeWidth={2.6} />
              </Link>
              <a
                href="https://t.me/yupay_bot"
                target="_blank"
                rel="noreferrer noopener"
                onClick={close}
                className={buttonStyles({
                  variant: "ghost",
                  size: "lg",
                  className: "mt-2.5 w-full",
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
        </>
      )}
    </div>
  );
}
