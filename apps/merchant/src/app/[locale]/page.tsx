import { ArrowRight, KeyRound, ShoppingCart, UserPlus } from "lucide-react";
import Link from "next/link";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { countBrands } from "@/lib/brands";

export const revalidate = 3600;

export default async function Landing({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("merchant.landing");
  const brands = await countBrands();

  const steps = [
    { icon: UserPlus, title: t("step1Title"), body: t("step1Body") },
    { icon: KeyRound, title: t("step2Title"), body: t("step2Body") },
    { icon: ShoppingCart, title: t("step3Title"), body: t("step3Body") },
  ];

  return (
    <main className="mx-auto w-full max-w-5xl px-5 py-16 sm:py-24">
      <section>
        <h1 className="max-w-3xl text-4xl font-bold leading-tight tracking-tight sm:text-5xl">
          {t("heading")}
        </h1>
        <p className="text-tx-mute mt-5 max-w-2xl text-lg leading-relaxed">{t("subheading")}</p>
        {/* Brands, never SKUs — the landing-copy rule. A count of denominations
            reads as inventory padding and is not what a reseller is choosing
            between. Omitted entirely when the catalog cannot be reached: a
            made-up number on a page about wholesale is worse than no number. */}
        {brands !== null && (
          <p className="text-tx-dim mt-3 font-mono text-sm">
            {t("brandsCount", { count: brands })}
          </p>
        )}
        <div className="mt-9 flex flex-wrap gap-3">
          <Link
            href={`/${locale}/register`}
            className="bg-primary text-primary-foreground rounded-btn inline-flex items-center gap-2 px-5 py-3 text-sm font-semibold"
          >
            {t("ctaPrimary")}
            <ArrowRight size={16} />
          </Link>
          <Link
            href={`/${locale}/docs`}
            className="border-border rounded-btn inline-flex items-center px-5 py-3 text-sm font-semibold"
          >
            {t("ctaSecondary")}
          </Link>
        </div>
      </section>

      <section className="mt-20">
        <h2 className="text-2xl font-semibold tracking-tight">{t("stepsHeading")}</h2>
        <ol className="mt-7 grid gap-4 sm:grid-cols-3">
          {steps.map(({ icon: Icon, title, body }, index) => (
            <li key={title} className="border-border bg-card rounded-xl border p-5">
              <div className="text-primary flex items-center gap-2">
                <Icon size={18} />
                <span className="font-mono text-xs">{String(index + 1).padStart(2, "0")}</span>
              </div>
              <h3 className="mt-3 font-semibold">{title}</h3>
              <p className="text-tx-mute mt-2 text-sm leading-relaxed">{body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="mt-20">
        <h2 className="text-2xl font-semibold tracking-tight">{t("sectionsHeading")}</h2>
        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          {[t("sectionTopups"), t("sectionVouchers")].map((name) => (
            <div key={name} className="border-border bg-card-2 rounded-xl border p-6">
              <p className="font-semibold">{name}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="border-border bg-card mt-20 rounded-2xl border p-8">
        <h2 className="text-xl font-semibold tracking-tight">{t("supportHeading")}</h2>
        <p className="text-tx-mute mt-2 text-sm">{t("supportBody")}</p>
        <a
          href="https://t.me/yupay_support"
          className="border-border rounded-btn mt-5 inline-flex items-center px-4 py-2.5 text-sm font-semibold"
        >
          {t("supportCta")}
        </a>
      </section>
    </main>
  );
}
