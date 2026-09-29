import { setRequestLocale } from "next-intl/server";

import { AppShowcase } from "@/components/sections/AppShowcase";
import { CatalogBento } from "@/components/sections/CatalogBento";
import { CS2SkinsBand } from "@/components/sections/CS2SkinsBand";
import { CtaBand } from "@/components/sections/CtaBand";
import { Hero } from "@/components/sections/Hero";
import { SteamZeroCommission } from "@/components/sections/SteamZeroCommission";
import { TrustReviews } from "@/components/sections/TrustReviews";

export default async function HomePage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
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
