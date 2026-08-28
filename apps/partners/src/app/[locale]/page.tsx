import { setRequestLocale } from "next-intl/server";

import { ApplyForm } from "@/components/landing/ApplyForm";
import { Calculator } from "@/components/landing/Calculator";
import { Faq } from "@/components/landing/Faq";
import { Hero } from "@/components/landing/Hero";
import { HowItWorks } from "@/components/landing/HowItWorks";

/**
 * The recruiting page.
 *
 * Prerendered and contacts nothing. It has no data to fetch, so it must not
 * acquire a dependency on the API being reachable during a build — the
 * storefront's prerender pass already overwhelms the dev stack, and a second
 * app doing the same would double it.
 */
export default async function LandingPage(props: { params: Promise<{ locale: string }> }) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  return (
    <main>
      <Hero locale={locale} />
      <HowItWorks locale={locale} />
      <Calculator />
      <Faq locale={locale} />
      <ApplyForm />
    </main>
  );
}
