"use client";

import { Menu, Send, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { AccountMenu } from "./auth/AccountMenu";
import { useBlogLocaleSlugs } from "@/components/LocaleAlternates";

import { type AppLocale } from "@/i18n/routing";
import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { hrefForLocale, navSectionActive } from "@/lib/locale-href";
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
  const { user } = useAuth();
  const tShow = useTranslations("web.showcase");
  const router = useRouter();
  const pathname = usePathname();
  const current = useLocale() as AppLocale;
  const blogSlugs = useBlogLocaleSlugs();
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
    router.push(hrefForLocale(next, pathname, blogSlugs));
  };

  const storeHref = pathFor(current, "/store");
  const blogHref = pathFor(current, "/blog");
  const sheetLinkClass =
    "border-border/60 border-b py-3.5 text-[15px] font-semibold text-foreground transition active:text-primary";
  const linkClass = (href: string) =>
    `border-border/60 border-b py-3.5 text-[15px] font-semibold transition active:text-primary ${
      navSectionActive(pathname, href) ? "text-primary" : "text-foreground"
    }`;

  return (
    <div className="flex items-center gap-2 md:hidden">
      <Link href={storeHref} className={buttonStyles({ size: "sm", className: "px-3.5" })}>
        {t("buy")}
      </Link>
      <AccountMenu locale={current} />
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v);
        }}
        aria-label={open ? t("closeMenu") : t("openMenu")}
        aria-expanded={open}
        aria-controls="mobile-nav-sheet"
        className="border-border bg-muted text-tx-mute rounded-btn flex h-11 w-11 items-center justify-center border"
      >
        {open ? <X size={18} /> : <Menu size={18} />}
      </button>

      {open && (
        /* A disclosure, not a dialog. It was labelled `aria-modal` without
           moving focus, trapping it or restoring it — and the sheet starts
           below the 72px header, so the toggle stayed visible and clickable
           while `aria-modal` hid it from assistive tech. `aria-expanded` +
           `aria-controls` on the toggle describe what actually happens. */
        <div
          id="mobile-nav-sheet"
          className="anim-sheet-in bg-bg fixed inset-x-0 top-[72px] z-50 h-[calc(100dvh-72px)] overflow-y-auto"
        >
          <div className="mx-auto max-w-[1200px] px-6 py-5">
            <nav className="flex flex-col">
              <Link
                href={storeHref}
                onClick={close}
                aria-current={navSectionActive(pathname, storeHref) ? "page" : undefined}
                className={linkClass(storeHref)}
              >
                {t("store")}
              </Link>
              <Link
                href={blogHref}
                onClick={close}
                aria-current={navSectionActive(pathname, blogHref) ? "page" : undefined}
                className={linkClass(blogHref)}
              >
                {t("blog")}
              </Link>
              <a href={`${pathFor(current)}#how`} onClick={close} className={sheetLinkClass}>
                {t("how")}
              </a>
              <a
                href="https://t.me/yupay_support"
                target="_blank"
                rel="noreferrer noopener"
                onClick={close}
                className={sheetLinkClass}
              >
                {t("support")}
              </a>
              {/* The header's balance chip is desktop-only, so on a phone this
                  is the only way to the wallet. Signed-in customers only —
                  a guest has no balance to look at. */}
              {user && (
                <Link
                  href={pathFor(current, "/account/wallet")}
                  onClick={close}
                  className={sheetLinkClass}
                >
                  {/* No amount here: `AccountMenu` carries it now, and the
                      sheet opens below that header — both would be on screen
                      at once, saying the same thing twice. */}
                  {t("wallet")}
                </Link>
              )}
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
                  aria-current={l.code === current ? "true" : undefined}
                  className={`rounded-btn flex-1 border py-3 text-sm font-semibold transition ${
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
