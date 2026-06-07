import { setRequestLocale } from "next-intl/server";

import { AppShowcase } from "@/components/sections/AppShowcase";
import { CatalogBento } from "@/components/sections/CatalogBento";
import { CtaBand } from "@/components/sections/CtaBand";
import { Hero } from "@/components/sections/Hero";
import { HowItWorks } from "@/components/sections/HowItWorks";
import { MetricsBand } from "@/components/sections/MetricsBand";
import { Reviews } from "@/components/sections/Reviews";
import { Ticker } from "@/components/sections/Ticker";
import { TrustBand } from "@/components/sections/TrustBand";

export default async function HomePage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);

  return (
    <>
      <Hero locale={locale} />
      <Ticker />
      <TrustBand />
      <CatalogBento locale={locale} />
      <HowItWorks />
      <AppShowcase />
      <MetricsBand />
      <Reviews />
      <CtaBand locale={locale} />
    </>
  );
}
