import { steamImageSize, wearColor } from "@yupay/utils";
import { useState } from "react";

import type { SkinListing } from "@yupay/utils";

import { SkinFloatBar } from "@/components/skins/SkinFloatBar";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n";
import { skinPriceText } from "@/lib/skins";

const FIRST = 10;

/**
 * Live offers for one item, price first (loaded by the page, which also
 * headlines the cheapest). On the API's fallback the rows simply carry no
 * float/seed — nothing is said about it (owner rule: no service meta). Delivery
 * is instant for every offer we sell, so it is said once, by the price.
 */
export function SkinListingsList({
  items,
  selectedId = null,
  onSelect,
  image = null,
  exterior = null,
}: {
  items: SkinListing[] | null;
  /** The item's picture, shown on every row as a market row does. */
  image?: string | null;
  /** The item's wear code (FN…BS), coloured on every row. */
  exterior?: string | null;
  /** The offer the buy panel will charge; rows are tappable only with `onSelect`. */
  selectedId?: number | null;
  onSelect?: (listingId: number) => void;
}) {
  const { t } = useT();
  const [all, setAll] = useState(false);

  if (items === null) {
    return (
      <div className="space-y-2">
        {[0, 1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-[52px] rounded-xl" />
        ))}
      </div>
    );
  }
  if (items.length === 0) {
    return <p className="py-8 text-center text-sm text-white/50">{t("cs2.noOffers")}</p>;
  }

  const shown = all ? items : items.slice(0, FIRST);
  return (
    <>
      <ul className="space-y-2">
        {shown.map((l) => {
          const selected = onSelect !== undefined && l.listing_id === selectedId;
          return (
            <li
              key={l.listing_id}
              className="rounded-xl border p-2.5"
              style={{
                borderColor: selected ? "hsl(var(--primary))" : "hsl(var(--border))",
                background: "hsl(var(--surface-2))",
              }}
            >
              <div className="flex items-center gap-2.5">
                {image && (
                  <img
                    src={steamImageSize(image, "128fx96f")}
                    alt=""
                    width={48}
                    height={36}
                    loading="lazy"
                    className="h-9 w-12 shrink-0 object-contain"
                  />
                )}
                <div className="w-16 shrink-0 leading-tight">
                  {exterior && (
                    <span
                      className="block text-[12px] font-bold"
                      style={{ color: wearColor(exterior) ?? undefined }}
                    >
                      {exterior}
                    </span>
                  )}
                  {l.float_value !== null && (
                    <span className="block text-[11px] tabular-nums text-white/55">
                      {l.float_value.toFixed(4)}
                    </span>
                  )}
                  {l.paint_seed !== null && (
                    <span className="block text-[10px] text-white/40">
                      {t("cs2.seed")} <span className="tabular-nums">{l.paint_seed}</span>
                    </span>
                  )}
                </div>
                <span className="flex min-w-0 flex-1 items-center gap-1 overflow-hidden">
                  {l.stickers.map((s, i) =>
                    s.image ? (
                      <img
                        key={`${String(i)}-${s.name}`}
                        src={s.image}
                        alt={s.name}
                        width={24}
                        height={18}
                        loading="lazy"
                        className="h-[18px] w-6 shrink-0 object-contain"
                      />
                    ) : (
                      <span
                        key={`${String(i)}-${s.name}`}
                        role="img"
                        aria-label={s.name}
                        className="h-4 w-4 shrink-0 rounded-sm"
                        style={{ background: "hsl(var(--border))" }}
                      />
                    ),
                  )}
                </span>
                <div className="flex shrink-0 flex-col items-end gap-1.5">
                  <span className="whitespace-nowrap text-[14px] font-bold tabular-nums text-white">
                    {skinPriceText(l.price_uzs, l.price_usd)}
                  </span>
                  {onSelect && (
                    <button
                      type="button"
                      aria-pressed={selected}
                      onClick={() => {
                        onSelect(l.listing_id);
                      }}
                      className={`min-h-[30px] rounded-lg px-3 text-[12px] font-bold ${
                        selected ? "bg-primary text-black" : "text-white/80"
                      }`}
                      style={selected ? undefined : { border: "1px solid hsl(var(--border))" }}
                    >
                      {selected ? t("cs2.buy.selected") : t("cs2.buy.buyThis")}
                    </button>
                  )}
                </div>
              </div>
              {l.float_value !== null && (
                <div className="mt-2">
                  <SkinFloatBar value={l.float_value} />
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {!all && items.length > FIRST && (
        <button
          type="button"
          onClick={() => {
            setAll(true);
          }}
          className="mx-auto mt-4 block rounded-xl px-5 py-2 text-sm font-semibold text-white/70"
          style={{ background: "hsl(var(--surface-2))", border: "1px solid hsl(var(--border))" }}
        >
          {t("cs2.loadMore")}
        </button>
      )}
    </>
  );
}
