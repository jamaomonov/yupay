import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

/**
 * Closing CTA band — large lime card with a dark counter-CTA. Uses a
 * dotted texture overlay and a giant ‟0%" headline on the right to anchor
 * the offer (free first Steam top-up). Lime gradient → primary-2 to feel
 * like an emissive panel rather than a flat fill.
 */
export async function CtaBand({ locale }: { locale: string }) {
  const t = await getTranslations("web.cta");
  const prefix = `/${locale}`;

  return (
    <section className="py-20">
      <div className="mx-auto max-w-[1280px] px-6 sm:px-10">
        <div
          className="relative overflow-hidden rounded-[32px] p-12 sm:p-16"
          style={{
            background: "linear-gradient(135deg, hsl(var(--primary)) 0%, hsl(var(--primary-2)) 100%)",
          }}
        >
          <div className="dot-band absolute inset-0" />
          <div className="relative flex flex-wrap items-center justify-between gap-8">
            <div className="max-w-[480px]">
              <h2 className="font-display text-[clamp(2.4rem,4.5vw,3.75rem)] font-extrabold leading-[0.95] tracking-[-0.04em] text-bg">
                <span className="block">{t("titleLine1")}</span>
                <span className="block">{t("titleLine2")}</span>
              </h2>
              <p className="mt-4 text-lg text-bg/70">{t("subtitle")}</p>
              <Link
                href={`${prefix}/store`}
                className="mt-8 inline-flex h-[54px] items-center gap-2 rounded-[13px] bg-bg px-7 text-base font-bold text-primary transition hover:-translate-y-0.5"
              >
                {t("button")}
                <ArrowRight size={16} className="text-primary" strokeWidth={2.6} />
              </Link>
            </div>

            <div className="relative">
              <div className="font-display text-[clamp(5rem,11vw,7.5rem)] font-extrabold leading-[0.8] tracking-[-0.05em] text-bg">
                0%
              </div>
              <div className="mt-1 max-w-[260px] text-base font-semibold text-bg/70">
                {t("offerCaption")}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
