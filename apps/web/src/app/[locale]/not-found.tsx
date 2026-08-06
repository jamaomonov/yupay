import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { Wordmark } from "@/components/Wordmark";

/**
 * Localised 404 inside the [locale] segment — renders between the shared
 * Header/Footer (from layout) so a missed route degrades gracefully instead
 * of dead-ending. Copy comes from web.notFound in all three locales.
 */
export default async function NotFound() {
  const t = await getTranslations("web.notFound");

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
      <Link
        href="/"
        className="bg-primary text-primary-foreground rounded-btn mt-8 inline-flex h-[52px] items-center px-6 text-[15px] font-bold shadow-[0_12px_30px_-10px_hsl(var(--primary)/0.45)] transition hover:-translate-y-0.5"
      >
        {t("cta")}
      </Link>
    </main>
  );
}
