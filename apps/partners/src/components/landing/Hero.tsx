import { getTranslations } from "next-intl/server";

import { SHELL } from "./shell";

/**
 * The first screen: four short lines of display type, the last one on lime.
 *
 * The heading carries the offer and nothing else supports it — no badge, no
 * card, no glow. That is the whole bet of this layout: at this size the
 * sentence has to be short enough to break into four lines that each read on
 * their own, which is why the copy is four fragments rather than one sentence
 * wrapped.
 *
 * The claim worth putting first is lifetime attribution — a partner earns on
 * every later order, not just the one that carried their code. The discount
 * percentage is what every affiliate programme says; that line is not.
 */
export async function Hero({ locale }: { locale: string }) {
  const t = await getTranslations({ locale, namespace: "partners.hero" });

  return (
    <section className={`${SHELL} pb-10 pt-10 sm:pb-14 sm:pt-16`}>
      <h1 className="font-display whitespace-pre-line text-[clamp(2.4rem,8.4vw,6.75rem)] font-extrabold leading-[0.94] tracking-[-0.045em]">
        {t("title")}
        {"\n"}
        {/* `box-decoration-clone` so a wrapped accent keeps its padding on both
            fragments instead of losing it mid-word. */}
        <span className="bg-primary text-primary-foreground box-decoration-clone px-[0.12em]">
          {t("titleAccent")}
        </span>
      </h1>

      <div className="mt-10 grid grid-cols-1 items-end gap-8 sm:mt-14 lg:grid-cols-2 lg:gap-16">
        <p className="text-tx-mute max-w-xl text-pretty text-[16px] leading-relaxed sm:text-[19px]">
          {t("subtitle")}
        </p>

        <div className="flex flex-col items-start gap-4 lg:items-start">
          <div className="flex flex-wrap gap-3">
            <a
              href="#apply"
              className="bg-primary text-primary-foreground inline-flex items-center rounded-full px-7 py-4 text-[15px] font-bold transition hover:brightness-110"
            >
              {t("ctaApply")}
            </a>
            <a
              href="#faq"
              className="border-border-2 text-foreground hover:bg-card inline-flex items-center rounded-full border px-7 py-4 text-[15px] font-semibold transition"
            >
              {t("ctaTerms")}
            </a>
          </div>
          <p className="text-tx-dim font-mono text-[11.5px] leading-relaxed sm:text-[12.5px]">
            {t("micro")}
          </p>
        </div>
      </div>
    </section>
  );
}
