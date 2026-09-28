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
export function SkinListingsList({ items }: { items: SkinListing[] | null }) {
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
        {shown.map((l) => (
          <li
            key={l.listing_id}
            className="space-y-2 rounded-xl border p-3"
            style={{ borderColor: "hsl(var(--border))", background: "hsl(var(--surface-2))" }}
          >
            <div className="flex items-center gap-3">
              <span className="text-[14px] font-bold tabular-nums text-white">
                {skinPriceText(l.price_uzs, l.price_usd)}
              </span>
              {l.paint_seed !== null && (
                <span className="text-[11px] text-white/50">
                  {t("cs2.seed")} <span className="tabular-nums text-white/80">{l.paint_seed}</span>
                </span>
              )}
              {l.stickers.length > 0 && (
                <span className="ml-auto flex items-center gap-1">
                  {l.stickers.map((s, i) =>
                    s.image ? (
                      <img
                        key={`${String(i)}-${s.name}`}
                        src={s.image}
                        alt={s.name}
                        width={22}
                        height={16}
                        loading="lazy"
                        className="h-4 w-[22px] object-contain"
                      />
                    ) : null,
                  )}
                </span>
              )}
            </div>
            {l.float_value !== null && (
              <div>
                <div className="mb-1 flex justify-between text-[11px] text-white/50">
                  <span>{t("cs2.float")}</span>
                  <span className="tabular-nums">{l.float_value.toFixed(4)}</span>
                </div>
                <SkinFloatBar value={l.float_value} />
              </div>
            )}
          </li>
        ))}
      </ul>
      {!all && items.length > FIRST && (
        <button
          type="button"
          onClick={() => setAll(true)}
          className="mx-auto mt-4 block rounded-xl px-5 py-2 text-sm font-semibold text-white/70"
          style={{ background: "hsl(var(--surface-2))", border: "1px solid hsl(var(--border))" }}
        >
          {t("cs2.loadMore")}
        </button>
      )}
    </>
  );
}
