import { setRequestLocale } from "next-intl/server";

import { ApplyForm } from "@/components/landing/ApplyForm";
import { Calculator } from "@/components/landing/Calculator";
import { Faq } from "@/components/landing/Faq";
import { Hero } from "@/components/landing/Hero";
import { HowItWorks } from "@/components/landing/HowItWorks";
import { SiteHeader } from "@/components/landing/SiteHeader";
import { StatBand } from "@/components/landing/StatBand";

/**
 * The recruiting page.
 *
 * Bands, ruled off from each other, in the order a sceptic reads them: the
 * offer, the rates, what it is worth, how it works, what the catch is, and only
 * then the form. The rules are the layout — there is not a card on the page —
 * so each band has to earn its space rather than borrow structure from a box.
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
    <>
      <SiteHeader locale={locale} />
      <main>
        <Hero locale={locale} />
        <StatBand locale={locale} />
        <Calculator />
        <HowItWorks locale={locale} />
        <Faq locale={locale} />
        <ApplyForm />
      </main>
    </>
  );
}
