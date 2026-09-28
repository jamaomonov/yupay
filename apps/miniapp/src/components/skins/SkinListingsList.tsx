import { Eye, Zap } from "lucide-react";
import { useEffect, useState } from "react";

import type { SkinListing } from "@yupay/utils";

import { SkinFloatBar } from "@/components/skins/SkinFloatBar";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n";
import { fetchSkinListings, skinPriceText } from "@/lib/skins";
import { openExternalLink } from "@/lib/telegram";

const FIRST = 10;

/**
 * Live offers for one item. When the API answers from its fallback the rows
 * simply carry no float/seed/inspect — nothing is said about it (owner rule:
 * no service meta in copy).
 */
export function SkinListingsList({ slug }: { slug: string }) {
  const { t } = useT();
  const [items, setItems] = useState<SkinListing[] | null>(null);
  const [all, setAll] = useState(false);

  useEffect(() => {
    let live = true;
    setItems(null);
    setAll(false);
    fetchSkinListings(slug)
      .then((r) => {
        if (live) setItems(r.items);
      })
      .catch(() => {
        if (live) setItems([]);
      });
    return () => {
      live = false;
    };
  }, [slug]);

  if (items === null) {
    return (
      <div className="space-y-2">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-16 rounded-xl" />
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
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1 rounded-md bg-emerald-500/15 px-2 py-0.5 text-[11px] font-semibold text-emerald-400">
                <Zap className="h-3 w-3" aria-hidden="true" />
                {t("cs2.ready")}
              </span>
              {l.paint_seed !== null && (
                <span className="text-[11px] text-white/50">
                  {t("cs2.seed")} <span className="font-mono text-white/80">{l.paint_seed}</span>
                </span>
              )}
              <span className="ml-auto font-mono text-[14px] font-bold text-white">
                {skinPriceText(l.price_uzs, l.price_usd)}
              </span>
            </div>
            {l.float_value !== null && (
              <div>
                <div className="mb-1 flex justify-between text-[11px] text-white/50">
                  <span>{t("cs2.float")}</span>
                  <span className="font-mono">{l.float_value.toFixed(4)}</span>
                </div>
                <SkinFloatBar value={l.float_value} />
              </div>
            )}
            {(l.stickers.length > 0 || l.inspect_url?.startsWith("steam://")) && (
              <div className="flex items-center gap-3">
                {l.stickers.length > 0 && (
                  <p className="min-w-0 flex-1 truncate text-[11px] text-white/50">
                    {t("cs2.stickers")}: {l.stickers.map((s) => s.name).join(", ")}
                  </p>
                )}
                {l.inspect_url?.startsWith("steam://") && (
                  <button
                    type="button"
                    onClick={() => openExternalLink(l.inspect_url ?? "")}
                    className="ml-auto inline-flex shrink-0 items-center gap-1 text-[11px] text-white/60"
                  >
                    <Eye className="h-3.5 w-3.5" aria-hidden="true" />
                    {t("cs2.inspect")}
                  </button>
                )}
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
