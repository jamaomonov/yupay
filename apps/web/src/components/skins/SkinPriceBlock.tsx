"use client";

import { offerHeadline } from "@yupay/utils";
import { ExternalLink, Zap } from "lucide-react";
import { useTranslations } from "next-intl";

import { useSkinOffers } from "./SkinOffers";

import { displayPrice } from "@/lib/skins";

/**
 * The headline price — the cheapest live offer once offers load, the stored
 * price as «от …» before that — the delivery promise, the buy button and, on a
 * line of its own, the Steam market link for comparison.
 */
export function SkinPriceBlock({
  storedUzs,
  storedUsd,
  steamUrl,
  locale,
}: {
  storedUzs: string | null;
  storedUsd: string | null;
  steamUrl: string;
  locale: string;
}) {
  const t = useTranslations("web.skins");
  const offers = useSkinOffers();
  const head = offerHeadline(storedUzs, storedUsd, offers);
  const price = displayPrice(locale, head.uzs, head.usd);
  return (
    <div className="space-y-4">
      <div>
        <p className="font-display text-3xl font-bold tabular-nums">
          {price === null ? t("soldOut") : head.from ? t("fromPrice", { price }) : price}
        </p>
        {price !== null && (
          <p className="mt-1 inline-flex items-center gap-1.5 text-[13px] font-semibold text-emerald-400">
            <Zap className="h-3.5 w-3.5" aria-hidden />
            {t("instantDelivery")}
          </p>
        )}
      </div>
      {/* Purchase is plan 3; the button says so, and does not look clickable. */}
      <button
        type="button"
        disabled
        className="bg-muted text-tx-mute w-full cursor-not-allowed rounded-xl py-3.5 text-[15px] font-bold"
      >
        {t("buySoon")}
      </button>
      <a
        href={steamUrl}
        target="_blank"
        rel="nofollow noopener noreferrer"
        className="text-tx-dim hover:text-foreground inline-flex items-center gap-1 text-[13px]"
      >
        {t("steamPrice")}
        <ExternalLink className="h-3.5 w-3.5" aria-hidden />
      </a>
    </div>
  );
}
