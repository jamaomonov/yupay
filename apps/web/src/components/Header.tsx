import { Globe } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { LocaleSwitcher } from "./LocaleSwitcher";
import { MobileNav } from "./MobileNav";
import { Wordmark } from "./Wordmark";

import { buttonStyles } from "@/lib/button";

/**
 * Fixed glass header. On md+ the full lockup shows (mark + 4 nav links +
 * region pill + LocaleSwitcher + lime ‟Пополнить"); below md it collapses to
 * a persistent top-up pill + hamburger sheet (see MobileNav).
 */
export async function Header({ locale }: { locale: string }) {
  const t = await getTranslations("web.nav");
  const prefix = `/${locale}`;
  const region = locale === "ru" ? "RU · ₽" : locale === "uz" ? "UZ · сум" : "EN · $";

  return (
    <nav className="border-border/60 bg-bg/70 fixed inset-x-0 top-0 z-50 h-[72px] border-b backdrop-blur-xl">
      <div className="mx-auto flex h-full max-w-[1200px] items-center justify-between px-6 sm:px-10">
        <Link href={prefix} aria-label="yupay" className="flex items-center">
          <Wordmark />
        </Link>

        <div className="hidden items-center gap-8 md:flex">
          <Link
            href={`${prefix}/store`}
            className="text-tx-mute hover:text-foreground text-sm font-medium transition"
          >
            {t("store")}
          </Link>
          <a
            href="#how"
            className="text-tx-mute hover:text-foreground text-sm font-medium transition"
          >
            {t("how")}
          </a>
          <a
            href="#reviews"
            className="text-tx-mute hover:text-foreground text-sm font-medium transition"
          >
            {t("reviews")}
          </a>
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
          <div className="border-border bg-muted text-tx-mute inline-flex items-center gap-1.5 rounded-[10px] border px-3 py-[7px] text-xs font-semibold">
            <Globe size={12} className="text-tx-mute" />
            {region}
          </div>
          <LocaleSwitcher />
          <Link href={`${prefix}/store`} className={buttonStyles({ size: "sm" })}>
            {t("topUp")}
          </Link>
        </div>

        {/* Mobile controls */}
        <MobileNav />
      </div>
    </nav>
  );
}
