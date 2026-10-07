import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { setRequestLocale } from "next-intl/server";

import { AppShowcase } from "@/components/sections/AppShowcase";
import { CatalogBento } from "@/components/sections/CatalogBento";
import { CS2SkinsBand } from "@/components/sections/CS2SkinsBand";
import { CtaBand } from "@/components/sections/CtaBand";
import { Hero } from "@/components/sections/Hero";
import { SteamZeroCommission } from "@/components/sections/SteamZeroCommission";
import { TrustReviews } from "@/components/sections/TrustReviews";
import { routing } from "@/i18n/routing";

export default async function HomePage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  // The layout already 404s an unknown segment, but a page renders in parallel
  // with its layout, so by the time the layout's `notFound()` lands this page
  // has already asked `Intl` to format prices in the locale
  // `apple-touch-icon.png` (every iOS visit requests that path; the middleware
  // skips dotted paths and the file does not exist) and thrown a 500 of its
  // own. Decide here, before any section runs.
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);

  return (
    // Every other route wraps its content in <main>; this one returned a bare
    // fragment, so the home page had no content landmark at all — and it is the
    // page a skip-link has to land on.
    <main id="main-content">
      <Hero locale={locale} />
      <SteamZeroCommission locale={locale} />
      <CS2SkinsBand locale={locale} />
      <CatalogBento locale={locale} />
      <AppShowcase />
      <TrustReviews locale={locale} />
      <CtaBand locale={locale} />
    </main>
  );
}
