"use client";

import { ChevronRight } from "lucide-react";
import Image from "next/image";
import { useTranslations } from "next-intl";

import { TetherMark } from "@/components/TetherMark";

/** Ways to top up: a card transfer to Uzcard or Humo, or USDT on TRON. */
export type TopUpMethod = "card" | "usdt";

interface TopUpMethodsProps {
  /** Which methods are on for this reseller; a method that is off has no tile. */
  card: boolean;
  usdt: boolean;
  onPick: (method: TopUpMethod) => void;
}

const TILE =
  "border-border bg-card hover:border-primary mt-2 flex w-full items-center gap-4 rounded-xl border p-4 text-left transition-colors";

const CARD_LOGOS = [
  { src: "/payment/uzcard.png", alt: "Uzcard", w: 461, h: 676 },
  { src: "/payment/humo.png", alt: "Humo", w: 600, h: 359 },
] as const;

/** The first step of a top-up: pick how to pay, then enter the amount. */
export function TopUpMethods({ card, usdt, onPick }: TopUpMethodsProps) {
  const t = useTranslations("merchant.topUp");
  return (
    <section className="mt-5 max-w-md">
      <p className="text-tx-dim text-xs">{t("methodTitle")}</p>
      {card && (
        <button
          type="button"
          onClick={() => {
            onPick("card");
          }}
          className={TILE}
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
      )}
      {usdt && (
        <button
          type="button"
          onClick={() => {
            onPick("usdt");
          }}
          className={TILE}
        >
          <span className="flex h-10 w-14 shrink-0 items-center justify-center">
            <TetherMark size={36} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block font-semibold">{t("methodUsdt")}</span>
            <span className="text-tx-mute block text-sm">{t("methodUsdtHint")}</span>
          </span>
          <ChevronRight aria-hidden size={18} className="text-tx-dim shrink-0" />
        </button>
      )}
    </section>
  );
}
