"use client";

import { useLocale, useTranslations } from "next-intl";
import { useMemo, useState } from "react";

import { DEFAULTS, estimateEarnings } from "@/lib/earnings";

import { SHELL } from "./shell";

/**
 * "What would I make?", answered honestly.
 *
 * One input, not five. The other four assumptions — conversion, average order,
 * repeat rate, commission — are measurements (see `lib/earnings.ts`), and
 * handing someone sliders for them invites the number to be tuned upward until
 * it impresses. They are still on screen, as read-only lines, because a
 * calculator that hides what it assumed is worse than one that overpromises:
 * at least an overpromise can be checked.
 *
 * The result is deliberately *not* labelled per month. `estimateEarnings`
 * computes lifetime earnings from one campaign, and a monthly figure would
 * imply a partner earns it again every month — true only if they keep bringing
 * new buyers at the same rate.
 */

const AUDIENCE_MIN = 1_000;
const AUDIENCE_MAX = 200_000;

export function Calculator() {
  const t = useTranslations("partners.calc");
  const locale = useLocale();
  const [audience, setAudience] = useState<number>(DEFAULTS.audience);

  const result = useMemo(
    () =>
      estimateEarnings({
        audience,
        conversionPercent: DEFAULTS.conversionPercent,
        averageOrderUzs: DEFAULTS.averageOrderUzs,
        ordersPerBuyer: DEFAULTS.ordersPerBuyer,
        commissionPercent: DEFAULTS.commissionPercent,
      }),
    [audience],
  );

  // The active locale, not a hardcoded one: §11 puts every figure through
  // `Intl` with the reader's locale, and an English page grouping digits
  // the Russian way is exactly what that rule is about.
  const number = (n: number): string => new Intl.NumberFormat(locale).format(n);

  return (
    <section className="border-border border-t">
      <div
        className={`${SHELL} grid grid-cols-1 items-center gap-12 py-14 lg:grid-cols-[1fr_460px] lg:gap-16 lg:py-16`}
      >
        <div>
          <h2 className="text-primary font-mono text-[11px] uppercase tracking-[0.16em]">
            {t("title")}
          </h2>
          <p className="text-tx-mute mt-4 max-w-lg text-pretty text-[15px] leading-relaxed sm:text-[17px]">
            {t("lead")}
          </p>

          <label className="mt-7 block">
            <span className="mb-2.5 flex items-baseline justify-between">
              <span className="text-tx-mute text-[13px]">{t("audience")}</span>
              <span className="font-mono text-[15px] font-bold">{number(audience)}</span>
            </span>
            <input
              type="range"
              min={AUDIENCE_MIN}
              max={AUDIENCE_MAX}
              step={100}
              value={audience}
              onChange={(e) => {
                setAudience(Number(e.target.value));
              }}
              // The track stays 1px; the *element* is 44px so it can be
              // dragged. At `h-1` the hit area was 620x4px — the one
              // interactive thing on the landing, and unusable on a phone.
              className="accent-primary h-11 w-full cursor-pointer appearance-none bg-transparent [&::-moz-range-thumb]:h-5 [&::-moz-range-thumb]:w-5 [&::-moz-range-thumb]:cursor-pointer [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:bg-[hsl(var(--primary))] [&::-moz-range-track]:h-1 [&::-moz-range-track]:rounded-full [&::-moz-range-track]:bg-[hsl(var(--border-2))] [&::-webkit-slider-runnable-track]:h-1 [&::-webkit-slider-runnable-track]:rounded-full [&::-webkit-slider-runnable-track]:bg-[hsl(var(--border-2))] [&::-webkit-slider-thumb]:mt-[-8px] [&::-webkit-slider-thumb]:h-5 [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-[hsl(var(--primary))]"
            />
            <span className="text-tx-dim mt-2.5 flex justify-between font-mono text-[11px]">
              <span>{number(AUDIENCE_MIN)}</span>
              <span>{number(AUDIENCE_MAX)}</span>
            </span>
          </label>
        </div>

        <div className="border-border border-t pt-8 lg:border-l lg:border-t-0 lg:pl-11 lg:pt-0">
          <p className="text-tx-mute font-mono text-[12px] uppercase tracking-[0.1em]">
            {t("result")}
          </p>
          <p
            data-testid="calc-result"
            // No `break-words`: it split the currency across lines as
            // "23 640 UZ / S". A price that wraps mid-token reads as a
            // rendering fault, which is a bad first impression on the page
            // that recruits.
            className="font-display text-primary mt-3.5 whitespace-nowrap text-[clamp(2.25rem,7vw,3.9rem)] font-extrabold leading-none tracking-[-0.04em]"
          >
            {number(result.earnedUzs)}
          </p>
          <p className="font-display text-tx-mute mt-1.5 text-[20px] font-bold">{t("currency")}</p>

          {/* The assumptions, spelled out. Whichever way the estimate lands,
              a partner can see which number to argue with. */}
          <div className="text-tx-dim mt-5 flex flex-col gap-[7px] font-mono text-[12.5px] leading-snug">
            <span>{t("buyers", { count: number(result.buyers) })}</span>
            <span>{t("orders", { count: number(result.orders) })}</span>
            <span>{t("avgCheck", { amount: number(DEFAULTS.averageOrderUzs) })}</span>
          </div>

          <p className="text-tx-dim mt-5 text-[11.5px] leading-relaxed">{t("note")}</p>
        </div>
      </div>
    </section>
  );
}
