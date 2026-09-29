import { useTranslations } from "next-intl";

/** In the order a purchase happens; each key is `web.skins.how.<step>.{title,body}`. */
const STEPS = ["link", "pay", "accept", "protect", "refund"] as const;

/**
 * How a skin purchase goes, under the offers: the trade link and Steam Guard, payment,
 * accepting within 30 minutes, Steam's 7-day protection, and the refund to the balance.
 *
 * No `"use client"`: static copy, rendered on the server.
 */
export function SkinHowItWorks() {
  const t = useTranslations("web.skins.how");
  return (
    <section className="mt-8" aria-labelledby="skin-how">
      <h2 id="skin-how" className="mb-3 text-[17px] font-bold">
        {t("title")}
      </h2>
      <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {STEPS.map((step, i) => (
          <li
            key={step}
            className="border-border bg-card flex gap-3 rounded-xl border p-3 sm:block sm:p-4"
          >
            <span className="bg-primary/15 text-primary inline-flex size-6 flex-shrink-0 items-center justify-center rounded-full text-[12px] font-bold sm:mb-2">
              {i + 1}
            </span>
            <div>
              <p className="text-[14px] font-semibold">{t(`${step}.title`)}</p>
              <p className="text-tx-dim mt-1 text-[13px] leading-snug">{t(`${step}.body`)}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
