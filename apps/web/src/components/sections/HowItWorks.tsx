import { getTranslations } from "next-intl/server";

const STEPS: { n: string; titleKey: string; subKey: string; time: string }[] = [
  { n: "01", titleKey: "step1Title", subKey: "step1Sub", time: "+0:05" },
  { n: "02", titleKey: "step2Title", subKey: "step2Sub", time: "+0:30" },
  { n: "03", titleKey: "step3Title", subKey: "step3Sub", time: "+1:12" },
];

/**
 * ‟From tap to game in 1:47" — sticky title on the left, three numbered
 * step rows on the right. Each row carries a mono time tag (+0:05, etc.)
 * that adds up to the headline. Borders use the design-ref hairline rule.
 */
export async function HowItWorks() {
  const t = await getTranslations("web.how");
  return (
    <section id="how" className="py-28">
      <div className="mx-auto max-w-[1200px] px-6 sm:px-10">
        <div className="grid grid-cols-1 gap-12 md:grid-cols-[auto_1fr] md:gap-[70px]">
          <div className="md:sticky md:top-[110px] md:self-start">
            <div className="text-primary font-mono text-xs font-semibold uppercase tracking-[0.16em]">
              [ 02 / {t("eyebrow")} ]
            </div>
            <h2 className="font-display mt-3 max-w-[340px] text-[clamp(2.2rem,4vw,3.4rem)] font-extrabold leading-[0.95] tracking-[-0.04em]">
              <span className="block">{t("titleLine1")}</span>
              <span className="block">{t("titleLine2")}</span>
              <span className="text-primary block">{t("titleLine3")}</span>
            </h2>
            <p className="text-tx-mute mt-6 max-w-[320px] text-base leading-relaxed">
              {t("subtitle")}
            </p>
          </div>

          <div>
            {STEPS.map((step, i) => (
              <div
                key={step.n}
                className={`grid grid-cols-[auto_1fr_auto] items-start gap-x-9 gap-y-7 py-9 ${
                  i === 0 ? "border-t" : ""
                } border-border border-b`}
              >
                <div className="font-display text-tx-dim w-[1.4em] text-[76px] font-extrabold leading-[0.85] tracking-[-0.05em] opacity-30">
                  {step.n}
                </div>
                <div>
                  <div className="font-display text-2xl font-bold tracking-[-0.025em] sm:text-[30px]">
                    {t(step.titleKey)}
                  </div>
                  <p className="text-tx-mute mt-3 max-w-[480px] text-base leading-relaxed">
                    {t(step.subKey)}
                  </p>
                </div>
                <div className="border-primary/20 bg-primary/10 text-primary self-start rounded-md border px-2.5 py-1.5 font-mono text-[13px] font-semibold">
                  {step.time}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
