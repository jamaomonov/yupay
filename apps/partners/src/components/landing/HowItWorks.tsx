import { getTranslations } from "next-intl/server";

import { SHELL } from "./shell";

/**
 * Three steps, numbered.
 *
 * The numerals are set large and nearly transparent so they read as position
 * markers rather than as content — a partner scanning this page needs to see
 * "three steps, and the first one is small" without reading a word. Boxing
 * them in cards said the opposite: three things to evaluate.
 */
export async function HowItWorks({ locale }: { locale: string }) {
  const t = await getTranslations({ locale, namespace: "partners.how" });

  const steps = [
    { n: "01", title: t("s1t"), body: t("s1b") },
    { n: "02", title: t("s2t"), body: t("s2b") },
    { n: "03", title: t("s3t"), body: t("s3b") },
  ];

  return (
    <section className="border-border border-t">
      <ol className={`${SHELL} grid grid-cols-1 gap-10 py-14 sm:grid-cols-3 sm:gap-11 lg:py-16`}>
        {steps.map((s) => (
          <li key={s.n}>
            <span
              aria-hidden="true"
              className="font-display text-foreground/[0.13] block text-[52px] font-extrabold leading-none tracking-[-0.04em] sm:text-[60px]"
            >
              {s.n}
            </span>
            <h3 className="font-display mt-1.5 text-[20px] font-bold tracking-[-0.02em] sm:text-[22px]">
              {s.title}
            </h3>
            <p className="text-tx-mute mt-2.5 text-pretty text-[14px] leading-relaxed">{s.body}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}
