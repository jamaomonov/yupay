import { ArrowRight, Check } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { CabinetMock } from "@/components/landing/CabinetMock";
import { countBrands } from "@/lib/brands";
import { pathFor } from "@/lib/locale-href";

/**
 * The landing's first screen: headline, the two calls to action, the three
 * metrics and the cabinet mock-up beside them.
 *
 * Extracted from `page.tsx` when the FAQ moved out too — the landing had
 * grown past the 300-line soft limit AGENTS.md §6 sets for TS files, and the
 * hero is the one block with no relationship to anything below it. It fetches
 * its own strings and its own brand count rather than taking them as props:
 * the count is only ever shown here, and a prop-drilled `brands` would make
 * the page await a number it does not use.
 */
export async function Hero({ locale }: { locale: string }) {
  const t = await getTranslations("merchant.landing");
  // The mock-up claims to be a picture of the cabinet, so its words are the
  // cabinet's own — renaming a section there renames it in the picture.
  const tCabinet = await getTranslations("merchant.cabinet");
  const tOrders = await getTranslations("merchant.orders");
  const brands = await countBrands();

  return (
    <section className="grid items-center gap-10 lg:grid-cols-[1fr_24rem]">
      <div>
        {/* The display face, on the one headline on the site that should
            carry the brand. */}
        <h1 className="font-display max-w-3xl text-4xl font-bold leading-tight tracking-tight sm:text-5xl">
          {t("heading")}
        </h1>
        <p className="text-tx-mute mt-5 max-w-2xl text-lg leading-relaxed">{t("subheading")}</p>
        <p className="text-tx-dim mt-4 text-[12.5px]">{t("micro")}</p>
        <div className="mt-7 flex flex-wrap gap-3">
          <Link
            href={pathFor(locale, "/register")}
            className="bg-primary text-primary-foreground rounded-btn inline-flex items-center gap-2 px-5 py-3 text-sm font-semibold"
          >
            {t("ctaPrimary")}
            <ArrowRight size={16} />
          </Link>
          <a
            href="#how"
            className="border-border rounded-btn inline-flex items-center border px-5 py-3 text-sm font-semibold"
          >
            {t("ctaSecondary")}
          </a>
        </div>
        <div className="text-tx-dim mt-7 flex flex-wrap gap-x-6 gap-y-2 text-[12.5px]">
          {/* Brands, never SKUs — the landing-copy rule. Omitted entirely
              when the catalog cannot be reached: a made-up number on a
              page about wholesale is worse than no number. */}
          {brands !== null && (
            <span>
              <span className="text-primary-ink font-mono">{brands}+</span> {t("metricBrands")}
            </span>
          )}
          <span>
            <span aria-hidden="true" className="text-primary-ink">
              ●
            </span>{" "}
            {t("metricAuto")}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Check size={13} aria-hidden="true" className="text-primary-ink" />
            {t("metricCheck")}
          </span>
        </div>
      </div>

      <CabinetMock
        caption={t("mockCaption")}
        labels={{
          catalog: tCabinet("navCatalog"),
          orders: tCabinet("navOrders"),
          settings: tCabinet("navSettings"),
          account: t("mockAccount"),
          delivered: tOrders("statusDelivered"),
        }}
      />
    </section>
  );
}
