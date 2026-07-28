import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { buttonStyles } from "@/lib/button";
import { pathFor } from "@/lib/seo";

/**
 * Closing CTA band — large lime card with a dark counter-CTA. A giant ‟24/7"
 * headline on the right anchors the always-on support promise. Lime gradient →
 * primary-2 to feel like an emissive panel rather than a flat fill.
 */
export async function CtaBand({ locale }: { locale: string }) {
  const t = await getTranslations("web.cta");

  return (
    <section className="py-20">
      <div className="mx-auto max-w-[1280px] px-6 sm:px-10">
        <div
          className="relative overflow-hidden rounded-2xl p-12 sm:p-16"
          style={{
            background:
              "linear-gradient(135deg, hsl(var(--primary)) 0%, hsl(var(--primary-2)) 100%)",
          }}
        >
          <div className="dot-band absolute inset-0" />
          <div className="relative flex flex-wrap items-center justify-between gap-8">
            <div className="max-w-[480px]">
              <h2 className="font-display text-bg text-[clamp(2.4rem,4.5vw,3.75rem)] font-extrabold leading-[0.95] tracking-[-0.04em]">
                <span className="block">{t("titleLine1")}</span>
                <span className="block">{t("titleLine2")}</span>
              </h2>
              <p className="text-bg/70 mt-4 text-lg">{t("subtitle")}</p>
              <Link
                href={pathFor(locale, "/store")}
                className={buttonStyles({ variant: "onLime", size: "lg", className: "mt-8" })}
              >
                {t("button")}
                <ArrowRight size={16} className="text-primary" strokeWidth={2.6} />
              </Link>
            </div>

            <div className="relative">
              <div className="font-display text-bg text-[clamp(4rem,9vw,6.5rem)] font-extrabold leading-[0.8] tracking-[-0.04em]">
                24/7
              </div>
              <div className="text-bg/70 mt-1 max-w-[260px] text-base font-semibold">
                {t("offerCaption")}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
