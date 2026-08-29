import { getTranslations } from "next-intl/server";

import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { Wordmark } from "@/components/Wordmark";
import { Link } from "@/i18n/navigation";

import { SHELL } from "./shell";

/** The storefront. The wordmark points there rather than back at this page:
 *  a partner deciding whether we are real will click it, and the fastest
 *  answer is the shop itself. */
const STOREFRONT = process.env.NEXT_PUBLIC_STOREFRONT_URL ?? "https://yupay.uz";

/**
 * The thin monospaced bar across the top.
 *
 * Deliberately not a navigation: there is one page and one destination that
 * isn't on it. A logo-and-menu header would promise a site that does not
 * exist, and would compete with the headline immediately below — which is the
 * only thing on this page doing any persuading.
 */
export async function SiteHeader({ locale }: { locale: string }) {
  const t = await getTranslations({ locale, namespace: "partners" });

  return (
    <header className="border-border border-b">
      <div
        className={`${SHELL} flex items-center justify-between gap-4 py-5 font-mono text-[11px] uppercase tracking-[0.14em] sm:text-[12px]`}
      >
        {/* The mark, then what this particular page is. Without the second
            half the bar would say "yupay" and leave a partner to work out
            which of our sites they landed on. */}
        <a href={STOREFRONT} className="-my-2 flex items-center gap-3.5 py-2">
          <Wordmark height={22} />
          <span className="border-border text-tx-mute hidden border-l pl-3.5 sm:inline">
            {t("nav.brand")}
          </span>
        </a>
        <div className="flex items-center gap-5 sm:gap-7">
          <LocaleSwitcher />
          {/* Through `@/i18n/navigation`, not `next/link`: a bare `/login`
              drops the prefix, and with `as-needed` routing that silently
              means Russian. */}
          <Link href="/login" className="text-tx-mute hover:text-foreground -my-2 py-2 transition">
            {t("hero.ctaLogin")} <span aria-hidden="true">→</span>
          </Link>
        </div>
      </div>
    </header>
  );
}
