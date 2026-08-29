import { getTranslations } from "next-intl/server";

/**
 * Three numbers, ruled off from everything around them.
 *
 * They were cards. As cards they read as three decorative tiles; ruled into a
 * single band they read as a specification, which is what they are — the two
 * rates and the hold, the three facts a partner needs before deciding whether
 * to read further.
 *
 * The unit is coloured rather than the figure: at this size a fully lime
 * number pulls harder than the headline it sits under.
 */
export async function StatBand({ locale }: { locale: string }) {
  const t = await getTranslations({ locale, namespace: "partners.hero" });

  // The third one is not a rate but the thing that makes the other two worth
  // having, so it is accented whole rather than by its unit. The 14-day hold
  // used to sit here; it now lives in the FAQ, where it comes with the reason
  // for it. Ruled into a spec beside two rates and with no explanation, it read
  // as a catch — a third of the first screen spent on the least appealing fact.
  const stats = [
    { value: t("statDiscount"), unit: t("statDiscountUnit"), label: t("statDiscountLabel") },
    { value: t("statCommission"), unit: t("statCommissionUnit"), label: t("statCommissionLabel") },
    { value: t("statForever"), unit: "", label: t("statForeverLabel"), whole: true },
  ];

  return (
    <section className="border-border border-y">
      {/* The shell measure without its padding: each cell carries its own, so
          the dividers meet the band edges instead of floating inside them. */}
      <dl className="mx-auto grid w-full max-w-[1240px] grid-cols-1 sm:grid-cols-3">
        {stats.map((s, i) => (
          <div
            key={s.label}
            className={`border-border px-5 py-7 sm:px-8 lg:px-12 ${
              i > 0 ? "border-t sm:border-l sm:border-t-0" : ""
            }`}
          >
            <dt
              className={`font-display text-[34px] font-extrabold leading-none tracking-[-0.03em] sm:text-[44px] ${
                s.whole === true ? "text-primary" : ""
              }`}
            >
              {s.value}
              <span className="text-primary">{s.unit}</span>
            </dt>
            <dd className="text-tx-mute mt-2.5 text-[12.5px] leading-snug">{s.label}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
