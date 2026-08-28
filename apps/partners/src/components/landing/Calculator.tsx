"use client";

import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";

import { DEFAULTS, estimateEarnings } from "@/lib/earnings";
import { formatUzs } from "@/lib/money";

/**
 * "What would I make?", answered honestly.
 *
 * Every default comes from a measurement — see `lib/earnings.ts`. The
 * temptation on a page like this is to seed a large average order and a
 * generous conversion so the headline number impresses; the cost of doing that
 * is a partner comparing their first real payout to it.
 */

interface Field {
  key: keyof typeof DEFAULTS;
  label: string;
  min: number;
  max: number;
  step: number;
}

export function Calculator() {
  const t = useTranslations("partners.calc");
  const [values, setValues] = useState<Record<keyof typeof DEFAULTS, number>>({ ...DEFAULTS });

  const fields: Field[] = [
    { key: "audience", label: t("audience"), min: 100, max: 200_000, step: 100 },
    { key: "conversionPercent", label: t("conversion"), min: 0.1, max: 20, step: 0.1 },
    { key: "averageOrderUzs", label: t("avgOrder"), min: 1_000, max: 500_000, step: 1_000 },
    { key: "ordersPerBuyer", label: t("repeat"), min: 1, max: 10, step: 0.1 },
    { key: "commissionPercent", label: t("commission"), min: 1, max: 2, step: 0.1 },
  ];

  const result = useMemo(
    () =>
      estimateEarnings({
        audience: values.audience,
        conversionPercent: values.conversionPercent,
        averageOrderUzs: values.averageOrderUzs,
        ordersPerBuyer: values.ordersPerBuyer,
        commissionPercent: values.commissionPercent,
      }),
    [values],
  );

  return (
    <section className="mx-auto max-w-5xl px-5 py-20 sm:py-24">
      <h2 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">{t("title")}</h2>
      <p className="text-tx-mute mt-2 text-[14px]">{t("subtitle")}</p>

      <div className="border-border bg-card mt-8 grid grid-cols-1 gap-8 rounded-2xl border p-6 sm:p-8 lg:grid-cols-[1fr_auto] lg:gap-12">
        <div className="space-y-5">
          {fields.map((f) => (
            <label key={f.key} className="block">
              <span className="text-tx-mute mb-2 flex items-baseline justify-between text-[13px]">
                <span>{f.label}</span>
                <span className="text-foreground font-mono text-[13px]">
                  {values[f.key].toLocaleString("ru-RU")}
                </span>
              </span>
              <input
                type="range"
                min={f.min}
                max={f.max}
                step={f.step}
                value={values[f.key]}
                onChange={(e) => {
                  setValues((v) => ({ ...v, [f.key]: Number(e.target.value) }));
                }}
                className="accent-primary h-1.5 w-full cursor-pointer"
              />
            </label>
          ))}
        </div>

        <div className="border-border-2 bg-card-2 rounded-xl border p-6 lg:w-72">
          <span className="text-tx-mute text-[13px]">{t("result")}</span>
          <p className="font-display text-primary mt-2 break-words text-3xl font-bold leading-tight sm:text-4xl">
            {formatUzs(result.earnedUzs)}
          </p>
          <p className="text-tx-dim mt-5 text-[12px] leading-relaxed">{t("note")}</p>
        </div>
      </div>
    </section>
  );
}
