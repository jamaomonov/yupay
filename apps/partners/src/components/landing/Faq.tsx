import { getTranslations } from "next-intl/server";

/**
 * The awkward questions, answered before someone joins.
 *
 * A partner who discovers the 14-day hold, the withdrawal floor or the
 * first-order-only rule *after* signing up feels tricked — and a partner who
 * feels tricked tells their audience. Putting the unflattering answers on the
 * page that recruits them costs a few sign-ups and buys every one that remains.
 */
export async function Faq({ locale }: { locale: string }) {
  const t = await getTranslations({ locale, namespace: "partners.faq" });
  const items = [1, 2, 3, 4, 5].map((i) => ({
    q: t(`q${String(i)}`),
    a: t(`a${String(i)}`),
  }));

  return (
    <section className="mx-auto max-w-3xl px-5 py-20 sm:py-24">
      <h2 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">{t("title")}</h2>
      <dl className="mt-8 space-y-3">
        {items.map((item) => (
          <div key={item.q} className="border-border bg-card rounded-xl border p-5 sm:p-6">
            <dt className="text-[15px] font-semibold">{item.q}</dt>
            <dd className="text-tx-mute mt-2 text-[14px] leading-relaxed">{item.a}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
