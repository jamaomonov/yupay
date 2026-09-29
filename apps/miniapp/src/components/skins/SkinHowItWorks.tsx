import { useT } from "@/lib/i18n";

/** In the order a purchase happens; each key is `cs2.how.<step>.{title,body}`. */
export const HOW_STEPS = ["link", "pay", "accept", "protect", "refund"] as const;

/**
 * How a skin purchase goes, on the pay step: the trade link and Steam Guard, payment,
 * accepting within 30 minutes, Steam's 7-day protection, and the refund to the balance.
 */
export function SkinHowItWorks() {
  const { t } = useT();
  return (
    <section className="space-y-2">
      <p className="px-1 text-xs font-semibold uppercase tracking-wide text-white/50">
        {t("cs2.how.title")}
      </p>
      <ol
        className="space-y-3 rounded-2xl p-3"
        style={{ background: "hsl(var(--surface-2))", border: "1px solid hsl(var(--border))" }}
      >
        {HOW_STEPS.map((step, i) => (
          <li key={step} className="flex gap-3">
            <span className="bg-primary/15 text-primary flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-[11px] font-bold">
              {i + 1}
            </span>
            <div className="min-w-0">
              <p className="text-[13px] font-semibold text-white">{t(`cs2.how.${step}.title`)}</p>
              <p className="text-[12px] leading-snug text-white/50">{t(`cs2.how.${step}.body`)}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
