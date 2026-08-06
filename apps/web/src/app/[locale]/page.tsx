import { setRequestLocale } from "next-intl/server";

import { AppShowcase } from "@/components/sections/AppShowcase";
import { CatalogBento } from "@/components/sections/CatalogBento";
import { CtaBand } from "@/components/sections/CtaBand";
import { Hero } from "@/components/sections/Hero";
import { HowItWorks } from "@/components/sections/HowItWorks";
import { MetricsBand } from "@/components/sections/MetricsBand";
import { SteamZeroCommission } from "@/components/sections/SteamZeroCommission";
import { Ticker } from "@/components/sections/Ticker";
import { TrustBand } from "@/components/sections/TrustBand";

export default async function HomePage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);

  return (
    // Every other route wraps its content in <main>; this one returned a bare
    // fragment, so the home page had no content landmark at all — and it is the
    // page a skip-link has to land on.
    <main id="main-content">
      <Hero locale={locale} />
      <Ticker />
      <TrustBand />
      <SteamZeroCommission locale={locale} />
      <CatalogBento locale={locale} />
      <HowItWorks />
      <AppShowcase />
      <MetricsBand />
      <CtaBand locale={locale} />
    </main>
  );
}
