"use client";

import { Eye } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { SkinFloatBar } from "./SkinFloatBar";
import { useSelectedOffer, useSkinOffers } from "./SkinOffers";

import { displayPrice } from "@/lib/skins";

const FIRST = 10;

/**
 * The live offers, price first. When the API answers from its fallback the rows
 * simply carry no float/seed/inspect — nothing is said about it (owner rule: no
 * service meta). Delivery is instant for every offer we sell, so it is said once
 * by the headline price, not on each row.
 */
export function SkinListings({ locale, buyable = false }: { locale: string; buyable?: boolean }) {
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
        {shown.map((l) => (
          <li
            key={l.listing_id}
            className="border-border bg-card flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl border px-4 py-3"
          >
            <span className="w-32 shrink-0 text-[15px] font-bold tabular-nums">
              {displayPrice(locale, l.price_uzs, l.price_usd)}
            </span>
            {l.float_value !== null && (
              <div className="w-40">
                <div className="text-tx-dim mb-1 flex justify-between text-[11px]">
                  <span>{t("float")}</span>
                  <span className="tabular-nums">{l.float_value.toFixed(4)}</span>
                </div>
                <SkinFloatBar value={l.float_value} />
              </div>
            )}
            {l.paint_seed !== null && (
              <span className="text-[12px]">
                <span className="text-tx-dim">{t("seed")} </span>
                <span className="tabular-nums">{l.paint_seed}</span>
              </span>
            )}
            {l.stickers.length > 0 && (
              <span className="flex items-center gap-1" title={t("stickers")}>
                {l.stickers.map((s, i) =>
                  s.image ? (
                    // Steam CDN thumbnails at 20 px: next/image adds nothing here.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      key={`${String(i)}-${s.name}`}
                      src={s.image}
                      alt={s.name}
                      title={s.name}
                      width={24}
                      height={18}
                      loading="lazy"
                      className="h-[18px] w-6 object-contain"
                    />
                  ) : (
                    <span
                      key={`${String(i)}-${s.name}`}
                      title={s.name}
                      className="bg-muted size-[18px] rounded-sm"
                    />
                  ),
                )}
              </span>
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
                className={`rounded-btn border px-3 py-1.5 text-[12px] font-semibold ${
                  selected?.listing_id === l.listing_id
                    ? "border-primary bg-primary/10 text-foreground"
                    : "border-border text-tx-mute hover:border-border-2"
                }`}
              >
                {selected?.listing_id === l.listing_id ? t("buy.selected") : t("buy.buyThis")}
              </button>
            )}
            {l.inspect_url?.startsWith("steam://") && (
              <a
                href={l.inspect_url}
                className="text-tx-mute hover:text-foreground ml-auto inline-flex items-center gap-1 text-[12px]"
              >
                <Eye className="h-3.5 w-3.5" aria-hidden />
                {t("inspect")}
              </a>
            )}
          </li>
        ))}
      </ul>
      {!all && offers.length > FIRST && (
        <button
          type="button"
          onClick={() => setAll(true)}
          className="border-border mx-auto mt-4 block rounded-xl border px-6 py-2.5 text-[14px] font-semibold"
        >
          {t("loadMore")}
        </button>
      )}
    </>
  );
}
