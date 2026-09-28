"use client";

import { offerHeadline, steamDiscount } from "@yupay/utils";
import { ExternalLink, Zap } from "lucide-react";
import { useTranslations } from "next-intl";

import { useSelectedOffer, useSkinOffers } from "./SkinOffers";

import { displayPrice } from "@/lib/skins";

/**
 * The headline price — the picked offer (the cheapest until another is picked) once
 * offers load, with how much cheaper than Steam it is; the stored
 * price as «от …» before that — the delivery promise, the buy button and, on a
 * line of its own, the Steam market link for comparison.
 */
export function SkinPriceBlock({
  storedUzs,
  storedUsd,
  steamUsd = null,
  steamUrl,
  locale,
  buyable = false,
}: {
  storedUzs: string | null;
  storedUsd: string | null;
  /** Steam's market price, for "cheaper than Steam". */
  steamUsd?: string | null;
  steamUrl: string;
  locale: string;
  /** Buying is live (the panel below does it): no placeholder button. */
  buyable?: boolean;
}) {
  const t = useTranslations("web.skins");
  const offers = useSkinOffers();
  const { selected } = useSelectedOffer();
  // The picked offer is what the button charges; before offers load, the stored «от» price.
  const head = selected
    ? { uzs: selected.price_uzs, usd: selected.price_usd, from: false }
    : offerHeadline(storedUzs, storedUsd, offers);
  const price = displayPrice(locale, head.uzs, head.usd);
  const off = head.usd !== null ? steamDiscount(head.usd, steamUsd) : null;
  return (
    <div className="space-y-4">
      <div>
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-display text-3xl font-bold tabular-nums">
            {price === null ? t("soldOut") : head.from ? t("fromPrice", { price }) : price}
          </span>
          {off !== null && (
            <span className="rounded-md bg-emerald-500/15 px-2 py-0.5 text-[13px] font-bold text-emerald-400">
              {t("belowSteam", { percent: off })}
            </span>
          )}
        </p>
        {price !== null && (
          <p className="mt-1 inline-flex items-center gap-1.5 text-[13px] font-semibold text-emerald-400">
            <Zap className="h-3.5 w-3.5" aria-hidden />
            {t("instantDelivery")}
          </p>
        )}
      </div>
      {!buyable && (
        <>
          {/* Purchase is plan 3; the button says so, and does not look clickable. */}
          <button
            type="button"
            disabled
            className="bg-muted text-tx-mute w-full cursor-not-allowed rounded-xl py-3.5 text-[15px] font-bold"
          >
            {t("buySoon")}
          </button>
        </>
      )}
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
