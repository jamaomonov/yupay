import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import type { Metadata } from "next";

import { pathFor } from "@/lib/locale-href";

/**
 * The 404's own title — without it a missing page carried the landing's.
 * Next resolves metadata from a `not-found` module the same way it does from
 * a page (`collectMetadata` in `next/dist/lib/metadata/resolve-metadata`);
 * Next adds `noindex` to a 404 by itself.
 */
export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("merchant.common");
  return { title: `${t("notFoundTitle")} — YuPay Reseller` };
}

/**
 * A 404 that belongs to this product rather than to the framework.
 *
 * Not a dead end: a reader who followed a stale link gets the four places
 * people actually come here for — the landing, what the catalogue holds, the
 * documentation and support. Unknown paths reach this page through
 * `[...rest]/page.tsx`; without that catch-all they fell through to the root
 * 404, outside the locale layout.
 */
export default async function NotFound() {
  const locale = await getLocale();
  const t = await getTranslations("merchant.common");
  const tLanding = await getTranslations("merchant.landing");
  const tDocs = await getTranslations("merchant.docs");

  const links = [
    { href: pathFor(locale, "/"), label: t("goHome") },
    { href: `${pathFor(locale, "/")}#catalog`, label: tLanding("sectionsHeading") },
    { href: pathFor(locale, "/docs"), label: tDocs("title") },
  ];

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center px-5 py-12">
      <p className="text-tx-dim font-mono text-sm">404</p>
      <h1 className="font-display mt-2 text-2xl font-semibold tracking-tight">
        {t("notFoundTitle")}
      </h1>
      <p className="text-tx-mute mt-2 text-sm leading-relaxed">{t("notFoundBody")}</p>
      <nav className="mt-6 flex flex-col items-start gap-3 text-sm">
        {links.map(({ href, label }, index) => (
          <Link
            key={href}
            href={href}
            className={
              index === 0
                ? "bg-primary text-primary-foreground rounded-btn px-4 py-2.5 font-semibold"
                : "text-primary-ink font-semibold"
            }
          >
            {label}
          </Link>
        ))}
        <a href="https://t.me/yupay_support" className="text-primary-ink font-semibold">
          {tLanding("supportCta")}
        </a>
      </nav>
    </main>
  );
}
