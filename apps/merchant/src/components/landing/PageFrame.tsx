import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { Mark } from "@/components/Mark";
import { pathFor } from "@/lib/locale-href";

/**
 * The public site's chrome: header nav and footer, around any marketing page.
 *
 * Extracted from the landing the moment a second public page was planned —
 * `/telegram`, `/api` and `/faq` all need the same header, and a header that
 * lives in one page file is a header that drifts as soon as it is copied. The
 * nav is the site map: the two audience pages, the questions page, and the
 * developer link kept deliberately small — a reseller who does not write code
 * should not meet the word "API" twice before the fold.
 *
 * A server component with no state: every entry is a link, so there is
 * nothing here to hydrate.
 */
export async function PageFrame({
  locale,
  children,
}: {
  locale: string;
  children: React.ReactNode;
}) {
  const t = await getTranslations("merchant.landing");
  const tOffer = await getTranslations("merchant.offer");

  return (
    <>
      <header className="border-border border-b">
        <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-4 px-5 py-4">
          <Link href={pathFor(locale, "/")} className="flex items-center gap-2.5">
            <Mark />
            <span className="font-display text-[15px] font-semibold tracking-[0.02em]">
              YUPAY <span className="text-tx-dim font-sans text-xs font-medium">{t("badge")}</span>
            </span>
          </Link>
          <nav className="text-tx-mute flex flex-wrap items-center gap-5 text-[13.5px]">
            <LocaleSwitcher />
            <Link href={pathFor(locale, "/telegram")}>{t("navTelegram")}</Link>
            <Link href={pathFor(locale, "/faq")}>{t("navFaq")}</Link>
            {/* Smaller and dimmer than its neighbours on purpose: it is the
                door for the minority audience, and it sits above the fold. */}
            <Link href={pathFor(locale, "/api")} className="text-tx-dim text-[12.5px]">
              {t("navDocs")}
            </Link>
            <Link
              href={pathFor(locale, "/login")}
              className="border-border rounded-btn text-foreground border px-4 py-2 font-semibold"
            >
              {t("login")}
            </Link>
            <Link
              href={pathFor(locale, "/register")}
              className="bg-primary text-primary-foreground rounded-btn px-4 py-2 font-bold"
            >
              {t("ctaPrimary")}
            </Link>
          </nav>
        </div>
      </header>

      {children}

      <footer className="border-border text-tx-dim mx-auto mt-16 flex w-full max-w-5xl flex-wrap items-center justify-between gap-3 border-t px-5 py-7 text-xs">
        <span>© YuPay · reseller.yupay.uz</span>
        <span className="flex flex-wrap gap-4">
          <Link href={pathFor(locale, "/faq")}>{t("navFaq")}</Link>
          <Link href={pathFor(locale, "/offer")}>{tOffer("title")}</Link>
          <a href="https://t.me/yupay_support">{t("supportCta")}</a>
        </span>
      </footer>
    </>
  );
}
