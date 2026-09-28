import { hasWear, isVanilla, offerHeadline, steamImageSize } from "@yupay/utils";
import { ExternalLink, Zap } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "wouter";

import type { SkinDetail, SkinListing } from "@yupay/utils";

import { SkinListingsList } from "@/components/skins/SkinListingsList";
import { SkinWearRow } from "@/components/skins/SkinWearRow";
import { SafeImage } from "@/components/ui/safe-image";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n";
import { fetchSkinDetail, fetchSkinListings, skinPriceText } from "@/lib/skins";
import { openExternalLink } from "@/lib/telegram";
import { useDocumentTitle } from "@/lib/use-document-title";

type State =
  | { phase: "loading" }
  | { phase: "error" }
  | { phase: "ready"; item: SkinDetail | null };

const steamMarketUrl = (name: string) =>
  `https://steamcommunity.com/market/listings/730/${encodeURIComponent(name)}`;

/** One skin: art, price, the other wears, and the live offers. Read-only until plan 3. */
export default function CS2Skin() {
  const { t } = useT();
  const { slug } = useParams<{ slug: string }>();
  const [state, setState] = useState<State>({ phase: "loading" });
  const [attempt, setAttempt] = useState(0);
  // Loaded here, not in the list: the cheapest offer is also the headline price.
  const [offers, setOffers] = useState<SkinListing[] | null>(null);
  const item = state.phase === "ready" ? state.item : null;
  useDocumentTitle(item ? item.name : t("cs2.docTitle"));

  useEffect(() => {
    let live = true;
    setState({ phase: "loading" });
    fetchSkinDetail(slug)
      .then((found) => {
        if (live) setState({ phase: "ready", item: found });
      })
      .catch(() => {
        if (live) setState({ phase: "error" });
      });
    return () => {
      live = false;
    };
  }, [slug, attempt]);

  useEffect(() => {
    let live = true;
    setOffers(null);
    fetchSkinListings(slug)
      .then((r) => {
        if (live) setOffers(r.items);
      })
      .catch(() => {
        if (live) setOffers([]);
      });
    return () => {
      live = false;
    };
  }, [slug]);

  if (state.phase === "loading") {
    return (
      <div className="space-y-4 px-4 pt-4">
        <Skeleton className="aspect-[4/3] w-full rounded-2xl" />
        <Skeleton className="h-6 w-3/4" />
        <Skeleton className="h-12 w-full rounded-xl" />
      </div>
    );
  }
  if (state.phase === "error") {
    return (
      <div className="flex flex-col items-center gap-3 py-20 text-center">
        <p className="text-sm text-white/50">{t("cs2.error")}</p>
        <button
          type="button"
          onClick={() => setAttempt((n) => n + 1)}
          className="text-primary text-sm font-semibold"
        >
          {t("common.retry")}
        </button>
      </div>
    );
  }
  if (item === null) {
    return <p className="py-20 text-center text-sm text-white/50">{t("cs2.notFound")}</p>;
  }

  const head = offerHeadline(item.price_uzs, item.price_usd, offers);
  const price = skinPriceText(head.uzs, head.usd);
  const worn = hasWear(item.category);
  return (
    <div className="yp-fade-in space-y-5 px-4 pb-4 pt-4">
      <div
        className="relative aspect-[4/3] w-full overflow-hidden rounded-2xl border border-b-[3px]"
        style={{
          borderColor: "hsl(var(--border))",
          background: "hsl(var(--surface-2))",
          ...(item.rarity_color ? { borderBottomColor: item.rarity_color } : {}),
        }}
      >
        {item.image_url && (
          <SafeImage
            src={steamImageSize(item.image_url, "512fx384f")}
            alt={item.name}
            className="h-full w-full object-contain p-5"
          />
        )}
      </div>

      <div>
        <p className="text-[13px] font-semibold text-white/60">
          {item.stattrak && <span className="text-orange-400">StatTrak™ </span>}
          {item.souvenir && <span className="text-yellow-400">Souvenir </span>}
          {item.weapon}
        </p>
        <h1 className="text-xl font-bold leading-tight tracking-tight text-white">
          {isVanilla(item) ? t("cs2.vanilla") : (item.skin ?? item.name)}
          {item.phase && <span className="text-white/50"> · {item.phase}</span>}
        </h1>
        <p className="mt-1 text-[13px] text-white/50">
          {item.exterior && t(`cs2.exterior.${item.exterior}`)}
          {item.rarity && (
            <span style={item.rarity_color ? { color: item.rarity_color } : undefined}>
              {item.exterior ? " · " : ""}
              {item.rarity}
            </span>
          )}
        </p>
      </div>

      <div className="space-y-3">
        <div>
          <p className="text-2xl font-bold tabular-nums text-white">
            {price === null ? t("cs2.soldOut") : head.from ? t("cs2.fromPrice", { price }) : price}
          </p>
          {price !== null && (
            <p className="mt-1 inline-flex items-center gap-1.5 text-[12px] font-semibold text-emerald-400">
              <Zap className="h-3.5 w-3.5" aria-hidden="true" />
              {t("cs2.instantDelivery")}
            </p>
          )}
        </div>
        {/* Purchase is plan 3; the button says so, and does not look clickable. */}
        <button
          type="button"
          disabled
          className="w-full cursor-not-allowed rounded-xl py-3.5 text-[15px] font-bold text-white/40"
          style={{ background: "hsl(var(--surface-2))" }}
        >
          {t("cs2.buySoon")}
        </button>
        <button
          type="button"
          onClick={() => openExternalLink(steamMarketUrl(item.name))}
          className="inline-flex items-center gap-1 text-[12px] text-white/50"
        >
          {t("cs2.steamPrice")}
          <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </div>

      {worn && item.family.length > 1 && (
        <section>
          <h2 className="mb-2 text-[15px] font-bold text-white">{t("cs2.otherWears")}</h2>
          <SkinWearRow family={item.family} current={item} currentPrice={price} />
        </section>
      )}

      {!worn && item.count > 0 && (
        <p className="text-sm text-white/60">{t("cs2.inStock", { count: item.count })}</p>
      )}

      {worn && (
        <section>
          <h2 className="mb-2 text-[15px] font-bold text-white">
            {t("cs2.offers")}{" "}
            <span className="font-mono text-[13px] text-white/50">{item.count}</span>
          </h2>
          <SkinListingsList key={item.slug} items={offers} />
        </section>
      )}
    </div>
  );
}
