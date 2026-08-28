import { getTranslations } from "next-intl/server";

/** Three steps. Numbered, because the order matters and a partner reading this
 *  is deciding whether the first one is worth their time. */
export async function HowItWorks({ locale }: { locale: string }) {
  const t = await getTranslations({ locale, namespace: "partners.how" });

  const steps = [
    { n: "01", title: t("s1t"), body: t("s1b") },
    { n: "02", title: t("s2t"), body: t("s2b") },
    { n: "03", title: t("s3t"), body: t("s3b") },
  ];

  return (
    <section className="mx-auto max-w-5xl px-5 py-20 sm:py-24">
      <h2 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">{t("title")}</h2>
      <ol className="mt-9 grid grid-cols-1 gap-4 sm:grid-cols-3">
        {steps.map((s) => (
          <li key={s.n} className="border-border bg-card rounded-xl border p-6">
            <span className="text-primary font-mono text-[13px] font-bold">{s.n}</span>
            <h3 className="font-display mt-3 text-lg font-semibold">{s.title}</h3>
            <p className="text-tx-mute mt-2 text-[14px] leading-relaxed">{s.body}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}
