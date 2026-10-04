"use client";

import { ChevronRight } from "lucide-react";
import Image from "next/image";
import { useTranslations } from "next-intl";

/** Ways to top up. One today — a card transfer to Uzcard or Humo. */
export type TopUpMethod = "card";

interface TopUpMethodsProps {
  onPick: (method: TopUpMethod) => void;
}

const CARD_LOGOS = [
  { src: "/payment/uzcard.png", alt: "Uzcard", w: 461, h: 676 },
  { src: "/payment/humo.png", alt: "Humo", w: 600, h: 359 },
] as const;

/** The first step of a top-up: pick how to pay, then enter the amount. */
export function TopUpMethods({ onPick }: TopUpMethodsProps) {
  const t = useTranslations("merchant.topUp");
  return (
    <section className="mt-5 max-w-md">
      <p className="text-tx-dim text-xs">{t("methodTitle")}</p>
      <button
        type="button"
        onClick={() => {
          onPick("card");
        }}
        className="border-border bg-card hover:border-primary mt-2 flex w-full items-center gap-4 rounded-xl border p-4 text-left transition-colors"
      >
        <span className="flex shrink-0 items-center gap-2">
          {CARD_LOGOS.map((logo) => (
            // On a white tile: the Uzcard mark is dark blue and vanishes on the
            // dark theme's card otherwise.
            <span
              key={logo.alt}
              className="flex h-10 w-14 items-center justify-center rounded-lg bg-white p-1.5"
            >
              <Image
                src={logo.src}
                alt={logo.alt}
                width={logo.w}
                height={logo.h}
                className="h-full w-auto object-contain"
              />
            </span>
          ))}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block font-semibold">{t("methodCard")}</span>
          <span className="text-tx-mute block text-sm">{t("methodCardHint")}</span>
        </span>
        <ChevronRight aria-hidden size={18} className="text-tx-dim shrink-0" />
      </button>
    </section>
  );
}
