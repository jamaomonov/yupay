import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { AccountMenu } from "./auth/AccountMenu";
import { LocaleSwitcher } from "./LocaleSwitcher";
import { MobileNav } from "./MobileNav";
import { PrimaryNav } from "./PrimaryNav";
import { Wordmark } from "./Wordmark";

import { buttonStyles } from "@/lib/button";
import { pathFor } from "@/lib/seo";

/**
 * Fixed glass header. On md+ the full lockup shows (mark + 4 nav links +
 * LocaleSwitcher + account control + lime ‟Пополнить"); below md it collapses
 * to a persistent top-up pill + hamburger sheet (see MobileNav).
 */
export async function Header({ locale }: { locale: string }) {
  const t = await getTranslations("web.nav");

  return (
    <header className="border-border/60 bg-bg/70 fixed inset-x-0 top-0 z-50 h-[72px] border-b backdrop-blur-xl">
      <div className="mx-auto flex h-full max-w-[1200px] items-center justify-between px-6 sm:px-10">
        {/* `shrink-0`: the logo has a pinned height and an auto width, so as a
            shrinkable flex item it absorbed the balance pill's growth by
            condensing its own letterforms — 27% narrower at 360px. */}
        <Link href={pathFor(locale)} aria-label="yupay" className="flex shrink-0 items-center">
          <Wordmark />
        </Link>

        <PrimaryNav
          locale={locale}
          label={t("primaryLabel")}
          store={t("store")}
          blog={t("blog")}
          how={t("how")}
          support={t("support")}
        />

        {/* Desktop controls */}
        <div className="hidden items-center gap-2.5 md:flex">
          {/* The one filled control in the header belongs to the action that
              earns money. It says "Купить", not "Пополнить": with a wallet in
              the product the latter promises a balance top-up and delivered
              the catalogue — which the nav's own "Магазин" already links to. */}
          <Link href={pathFor(locale, "/store")} className={buttonStyles({ size: "md" })}>
            {t("buy")}
          </Link>
          <LocaleSwitcher />
          {/* The balance rides inside AccountMenu now — one control instead of
              two competing for the same corner, and it reaches mobile, which
              uses the same component. */}
          <AccountMenu locale={locale} />
        </div>

        {/* Mobile controls */}
        <MobileNav />
      </div>
    </header>
  );
}
