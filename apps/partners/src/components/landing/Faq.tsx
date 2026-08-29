import { getTranslations } from "next-intl/server";

import { SHELL } from "./shell";

/**
 * The awkward questions, answered before someone joins.
 *
 * A partner who discovers the 14-day hold, the withdrawal floor or the
 * first-order-only rule *after* signing up feels tricked — and a partner who
 * feels tricked tells their audience. Putting the unflattering answers on the
 * page that recruits them costs a few sign-ups and buys every one that remains.
 *
 * Laid out as a ruled list rather than accordions: every answer here is one a
 * partner should read, and a control that hides them by default is how a page
 * gets to claim it disclosed something nobody saw.
 */
export async function Faq({ locale }: { locale: string }) {
  const t = await getTranslations({ locale, namespace: "partners.faq" });
  // Not 1..6. A sceptic under this heading used to read about the payout delay
  // first; now the two questions that decide whether they apply at all — "am I
  // too small" and "what do repeat orders pay" — open it, and the two
  // unflattering ones still get read, just not first.
  const items = [6, 5, 1, 2, 4, 3].map((i) => ({
    q: t(`q${String(i)}`),
    a: t(`a${String(i)}`),
  }));

  return (
    <section id="faq" className="border-border border-t">
      <div className={`${SHELL} grid grid-cols-1 gap-9 py-14 lg:grid-cols-[280px_1fr] lg:gap-14`}>
        <h2 className="font-display text-[26px] font-bold leading-[1.06] tracking-[-0.03em] sm:text-[30px]">
          {t("title")}
        </h2>
        <dl className="flex flex-col">
          {items.map((item) => (
            <div
              key={item.q}
              className="border-border grid grid-cols-1 gap-2 border-t py-4 sm:grid-cols-[300px_1fr] sm:gap-8"
            >
              <dt className="text-[14.5px] font-bold leading-snug">{item.q}</dt>
              <dd className="text-tx-mute text-pretty text-[13.5px] leading-relaxed">{item.a}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}
