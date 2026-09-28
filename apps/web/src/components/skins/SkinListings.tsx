"use client";

import { steamImageSize, wearColor } from "@yupay/utils";
import { Eye } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { SkinFloatBar } from "./SkinFloatBar";
import { useSelectedOffer, useSkinOffers } from "./SkinOffers";

import { displayPrice } from "@/lib/skins";

const FIRST = 10;

/**
 * The live offers, as a market row: the skin, its wear code and float (and seed), the
 * stickers, then the price, inspect and «Купить». When the API answers from its fallback the rows
 * simply carry no float/seed/inspect — nothing is said about it (owner rule: no
 * service meta). Delivery is instant for every offer we sell, so it is said once
 * by the headline price, not on each row.
 */
export function SkinListings({
  locale,
  buyable = false,
  image = null,
  exterior = null,
}: {
  locale: string;
  buyable?: boolean;
  /** The item's picture, shown on every row as a market row does. */
  image?: string | null;
  /** The item's wear code (FN…BS), coloured on every row. */
  exterior?: string | null;
}) {
  const t = useTranslations("web.skins");
  const offers = useSkinOffers();
  const { selected, select } = useSelectedOffer();
  const [all, setAll] = useState(false);

  if (offers === null) {
    return (
      <ul className="space-y-2" aria-hidden>
        {[0, 1, 2, 3, 4].map((i) => (
          <li key={i} className="bg-muted h-[52px] animate-pulse rounded-xl" />
        ))}
      </ul>
    );
  }
  if (offers.length === 0) {
    return <p className="text-tx-mute py-8 text-center">{t("noOffers")}</p>;
  }

  const shown = all ? offers : offers.slice(0, FIRST);
  return (
    <>
      <ul className="space-y-2">
        {shown.map((l) => {
          const picked = selected?.listing_id === l.listing_id;
          return (
            <li
              key={l.listing_id}
              // Phones: a 3-column grid — picture, wear and float, price; then stickers under
              // them and the actions under the price. Wider: one line, left to right.
              className={`bg-card grid grid-cols-[auto_1fr_auto] items-center gap-x-3 gap-y-2 rounded-xl border px-3 py-2.5 sm:flex sm:gap-x-4 sm:px-4 ${
                buyable && picked ? "border-primary" : "border-border"
              }`}
            >
              {image && (
                // A Steam CDN thumbnail, the same for every row: next/image adds nothing.
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={steamImageSize(image, "128fx96f")}
                  alt=""
                  width={64}
                  height={48}
                  loading="lazy"
                  className="h-12 w-16 shrink-0 object-contain"
                />
              )}
              <div className="w-24 shrink-0">
                {exterior && (
                  <span
                    className="block text-[13px] font-bold"
                    style={{ color: wearColor(exterior) ?? undefined }}
                  >
                    {exterior}
                  </span>
                )}
                {l.float_value !== null && (
                  <>
                    <span className="text-tx-dim block text-[12px] tabular-nums">
                      {l.float_value.toFixed(4)}
                    </span>
                    <span className="sr-only">{t("float")}</span>
                  </>
                )}
                {l.paint_seed !== null && (
                  <span className="text-tx-dim block text-[11px]">
                    {t("seed")} <span className="tabular-nums">{l.paint_seed}</span>
                  </span>
                )}
              </div>
              {l.float_value !== null && (
                <div className="hidden w-28 shrink-0 md:block">
                  <SkinFloatBar value={l.float_value} />
                </div>
              )}
              <span
                className="col-span-2 row-start-2 flex min-h-6 min-w-0 flex-wrap items-center gap-1.5 sm:flex-1"
                title={t("stickers")}
              >
                {l.stickers.map((s, i) =>
                  s.image ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      key={`${String(i)}-${s.name}`}
                      src={s.image}
                      alt={s.name}
                      title={s.name}
                      width={32}
                      height={24}
                      loading="lazy"
                      className="h-6 w-8 object-contain"
                    />
                  ) : (
                    <span
                      key={`${String(i)}-${s.name}`}
                      title={s.name}
                      className="bg-muted size-6 rounded-sm"
                    />
                  ),
                )}
              </span>
              <span className="col-start-3 row-start-1 ml-auto whitespace-nowrap text-right text-[15px] font-bold tabular-nums">
                {displayPrice(locale, l.price_uzs, l.price_usd)}
              </span>
              <div className="col-start-3 row-start-2 flex items-center justify-end gap-2">
                {l.inspect_url?.startsWith("steam://") && (
                  <a
                    href={l.inspect_url}
                    aria-label={t("inspect")}
                    title={t("inspect")}
                    className="text-tx-mute hover:text-foreground border-border inline-flex size-9 shrink-0 items-center justify-center rounded-lg border"
                  >
                    <Eye className="h-4 w-4" aria-hidden />
                  </a>
                )}
                {buyable && (
                  <button
                    type="button"
                    onClick={() => {
                      select(l.listing_id);
                      document
                        .getElementById("buy")
                        ?.scrollIntoView({ behavior: "smooth", block: "center" });
                    }}
                    className={`rounded-btn shrink-0 px-4 py-2 text-[13px] font-bold ${
                      picked
                        ? "bg-primary text-primary-foreground"
                        : "border-border text-foreground hover:border-border-2 border"
                    }`}
                  >
                    {picked ? t("buy.selected") : t("buy.buyThis")}
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {!all && offers.length > FIRST && (
        <button
          type="button"
          onClick={() => {
            setAll(true);
          }}
          className="border-border mx-auto mt-4 block rounded-xl border px-6 py-2.5 text-[14px] font-semibold"
        >
          {t("loadMore")}
        </button>
      )}
    </>
  );
}
