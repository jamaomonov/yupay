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

  // The 14-day hold used to sit third; it now lives in the FAQ, where it comes
  // with the reason for it. Ruled into a spec beside two rates and with no
  // explanation it read as a catch — a third of the first screen spent on the
  // least appealing fact.
  //
  // Its replacement carries no unit, and so no lime: the accent marks units,
  // and a fully lime word here would be the second lime "навсегда" within
  // 200px of the one in the headline, outshouting it.
  const stats = [
    { value: t("statDiscount"), unit: t("statDiscountUnit"), label: t("statDiscountLabel") },
    { value: t("statCommission"), unit: t("statCommissionUnit"), label: t("statCommissionLabel") },
    { value: t("statForever"), unit: "", label: t("statForeverLabel") },
  ];

  return (
    <section className="border-border border-y">
      {/* The shell measure without its padding: each cell carries its own, so
          the dividers meet the band edges instead of floating inside them. */}
      <dl className="mx-auto grid w-full max-w-[1240px] grid-cols-1 lg:grid-cols-3">
        {stats.map((s, i) => (
          <div
            key={s.label}
            // Three columns only from `lg`. At `sm` the cells were 148-235px
            // wide and "навсегда" — one unbreakable word at 44px — overflowed
            // every one of them, clipped by the body's `overflow-x: clip`:
            // measured +114px at 640 down to +27px at 900.
            className={`border-border px-5 py-7 sm:px-8 lg:px-12 ${
              i > 0 ? "border-t lg:border-l lg:border-t-0" : ""
            }`}
          >
            <dt className="font-display text-[32px] font-extrabold leading-none tracking-[-0.03em] lg:text-[40px]">
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
