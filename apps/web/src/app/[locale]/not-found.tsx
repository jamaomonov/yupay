import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import { Wordmark } from "@/components/Wordmark";
import { buttonStyles } from "@/lib/button";
import { pathFor } from "@/lib/seo";

/**
 * Localised 404 inside the [locale] segment — renders between the shared
 * Header/Footer (from layout) so a missed route degrades gracefully instead
 * of dead-ending. Copy comes from web.notFound in all three locales.
 */
export default async function NotFound() {
  const t = await getTranslations("web.notFound");
  // Home in the visitor's own language: a bare "/" sent uz and en to Russian.
  const home = pathFor(await getLocale(), "/");

  return (
    <main className="relative flex min-h-[70vh] flex-col items-center justify-center px-6 py-32 text-center">
      <div aria-hidden className="grid-cell pointer-events-none absolute inset-0 -z-10" />
      <Wordmark />
      <div className="font-display text-primary mt-10 text-[clamp(4rem,12vw,8rem)] font-extrabold leading-none tracking-[-0.05em]">
        404
      </div>
      <h1 className="font-display mt-2 text-2xl font-bold tracking-[-0.02em] sm:text-3xl">
        {t("title")}
      </h1>
      <p className="text-tx-mute mt-4 max-w-[420px] text-base leading-relaxed">{t("subtitle")}</p>
      <Link href={home} className={buttonStyles({ size: "lg", className: "mt-8" })}>
        {t("cta")}
      </Link>
    </main>
  );
}
