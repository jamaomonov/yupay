import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { AccountMenu } from "./auth/AccountMenu";
import { LocaleSwitcher } from "./LocaleSwitcher";
import { MobileNav } from "./MobileNav";
import { Wordmark } from "./Wordmark";

import { pathFor } from "@/lib/seo";

/**
 * Fixed glass header. On md+ the full lockup shows (mark + 4 nav links +
 * LocaleSwitcher + account control + lime ‟Пополнить"); below md it collapses
 * to a persistent top-up pill + hamburger sheet (see MobileNav).
 */
export async function Header({ locale }: { locale: string }) {
  const t = await getTranslations("web.nav");

  return (
    <nav className="border-border/60 bg-bg/70 fixed inset-x-0 top-0 z-50 h-[72px] border-b backdrop-blur-xl">
      <div className="mx-auto flex h-full max-w-[1200px] items-center justify-between px-6 sm:px-10">
        <Link href={pathFor(locale)} aria-label="yupay" className="flex items-center">
          <Wordmark />
        </Link>

        <div className="hidden items-center gap-8 md:flex">
          <Link
            href={pathFor(locale, "/store")}
            className="text-tx-mute hover:text-foreground text-sm font-medium transition"
          >
            {t("store")}
          </Link>
          <a
            href={`${pathFor(locale)}#how`}
            className="text-tx-mute hover:text-foreground text-sm font-medium transition"
          >
            {t("how")}
          </a>
          {/* The catalogue, not a home-page anchor: `#reviews` is only ever
              rendered on a brand page, so this link used to do nothing at all.
              Brand cards carry real ratings (drawn only when count > 0). */}
          <Link
            href={pathFor(locale, "/store")}
            className="text-tx-mute hover:text-foreground text-sm font-medium transition"
          >
            {t("reviews")}
          </Link>
          <a
            href="https://t.me/yupay_support"
            target="_blank"
            rel="noreferrer noopener"
            className="text-tx-mute hover:text-foreground text-sm font-medium transition"
          >
            {t("support")}
          </a>
        </div>

        {/* Desktop controls */}
        <div className="hidden items-center gap-2.5 md:flex">
          <LocaleSwitcher />
          <AccountMenu locale={locale} />
        </div>

        {/* Mobile controls */}
        <MobileNav />
      </div>
    </nav>
  );
}
