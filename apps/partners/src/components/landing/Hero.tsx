import Link from "next/link";
import { getTranslations } from "next-intl/server";

/**
 * The first screen.
 *
 * It leads with the thing that actually distinguishes this programme: the
 * buyer stays attributed forever, so a partner earns on every order, not the
 * one that carried their code. That is the sentence worth putting above the
 * fold — the discount percentage is what every affiliate programme says.
 */
export async function Hero({ locale }: { locale: string }) {
  const t = await getTranslations({ locale, namespace: "partners.hero" });

  const stats = [
    { value: t("statDiscount"), label: t("statDiscountLabel") },
    { value: t("statCommission"), label: t("statCommissionLabel") },
    { value: t("statForever"), label: t("statForeverLabel") },
  ];

  return (
    <section className="grid-cell relative overflow-hidden">
      <div className="glow-lime pointer-events-none absolute -top-40 left-1/2 h-[520px] w-[820px] -translate-x-1/2" />
      <div className="relative mx-auto max-w-5xl px-5 pb-20 pt-24 text-center sm:pb-28 sm:pt-32">
        <span className="border-border-2 bg-card text-primary inline-flex items-center rounded-full border px-3.5 py-1.5 font-mono text-[12px] uppercase tracking-wide">
          {t("eyebrow")}
        </span>

        <h1 className="font-display mt-7 whitespace-pre-line text-4xl font-bold leading-[1.08] tracking-tight sm:text-6xl">
          {t("title")}
        </h1>

        <p className="text-tx-mute mx-auto mt-6 max-w-2xl text-base leading-relaxed sm:text-lg">
          {t("subtitle")}
        </p>

        <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <a
            href="#apply"
            className="bg-primary text-primary-foreground rounded-btn inline-flex h-12 w-full items-center justify-center px-7 text-[15px] font-semibold transition hover:brightness-110 sm:w-auto"
          >
            {t("ctaApply")}
          </a>
          <Link
            href="/login"
            className="border-border-2 text-foreground rounded-btn hover:bg-card inline-flex h-12 w-full items-center justify-center border px-7 text-[15px] font-semibold transition sm:w-auto"
          >
            {t("ctaLogin")}
          </Link>
        </div>

        <dl className="mx-auto mt-16 grid max-w-3xl grid-cols-1 gap-4 sm:grid-cols-3">
          {stats.map((s) => (
            <div
              key={s.label}
              className="border-border bg-card/60 rounded-xl border px-5 py-6 backdrop-blur"
            >
              <dt className="font-display text-primary text-2xl font-bold sm:text-3xl">
                {s.value}
              </dt>
              <dd className="text-tx-mute mt-1.5 text-[13px] leading-snug">{s.label}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}
