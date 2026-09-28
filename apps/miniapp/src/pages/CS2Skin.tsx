import { hasWear, isVanilla, offerHeadline, repriceOffer, steamDiscount } from "@yupay/utils";
import { ExternalLink, Zap } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "wouter";

import type { SkinDetail, SkinListing } from "@yupay/utils";

import { SkinFixedCta } from "@/components/skins/SkinFixedCta";
import { SkinHeroCard } from "@/components/skins/SkinHeroCard";
import { SkinListingsList } from "@/components/skins/SkinListingsList";
import { SkinPayStep } from "@/components/skins/SkinPayStep";
import { SkinTradeLinkInput } from "@/components/skins/SkinTradeLinkInput";
import { SkinWearRow } from "@/components/skins/SkinWearRow";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n";
import { afterListingGone, cheapestOffer } from "@/lib/skin-buy";
import { fetchSkinDetail, fetchSkinListings, skinPriceText } from "@/lib/skins";
import { haptic, openExternalLink } from "@/lib/telegram";
import { useDocumentTitle } from "@/lib/use-document-title";

type State =
  | { phase: "loading" }
  | { phase: "error" }
  | { phase: "ready"; item: SkinDetail | null };

const steamMarketUrl = (name: string) =>
  `https://steamcommunity.com/market/listings/730/${encodeURIComponent(name)}`;

/**
 * One skin, top to bottom in the order a buyer decides: art and price, the other wears,
 * the live offers (pick one), then the trade link and payment for the picked offer.
 */
export default function CS2Skin() {
  const { t } = useT();
  const { slug } = useParams<{ slug: string }>();
  const [state, setState] = useState<State>({ phase: "loading" });
  const [attempt, setAttempt] = useState(0);
  // Loaded here, not in the list: the cheapest offer is also the headline price.
  const [offers, setOffers] = useState<SkinListing[] | null>(null);
  // The offer the buy panel charges: the one tapped, else the cheapest.
  const [pickedId, setPickedId] = useState<number | null>(null);
  // Two steps, as for every other brand: pick (wear, offer, trade link), then review
  // and pay. The link survives going back and forth.
  const [stage, setStage] = useState<"select" | "review">("select");
  const [link, setLink] = useState({ url: "", usable: false });
  const onLink = useCallback((s: { url: string; usable: boolean }) => {
    setLink(s);
  }, []);
  const linkRef = useRef<HTMLInputElement>(null);
  const topRef = useRef<HTMLDivElement>(null);
  // Picking an offer glides back up to the picture, which now shows that offer's
  // float and stickers, and to its price.
  const pickOffer = (listingId: number) => {
    haptic("select");
    setPickedId(listingId);
    topRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
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
    setPickedId(null);
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
          onClick={() => {
            setAttempt((n) => n + 1);
          }}
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

  const worn = hasWear(item.category);
  const selected =
    offers?.find((o) => o.listing_id === pickedId) ?? (offers ? cheapestOffer(offers) : null);
  // The picked offer is what «Далее» buys; before offers load, the stored «от» price.
  const head = selected
    ? { uzs: selected.price_uzs, usd: selected.price_usd, from: false }
    : offerHeadline(item.price_uzs, item.price_usd, offers);
  const price = skinPriceText(head.uzs, head.usd);
  const off = head.usd !== null ? steamDiscount(head.usd, item.steam_price_usd) : null;
  const buySku = item.buy_sku_id ?? null;
  const buyable = buySku !== null && selected !== null;

  if (buyable && stage === "review") {
    return (
      <SkinPayStep
        skuId={buySku}
        item={item}
        offer={selected}
        tradelink={link.url}
        onBack={() => {
          setStage("select");
        }}
        onListingGone={(next) => {
          const after = afterListingGone(offers ?? [], selected.listing_id, next);
          setOffers(after.offers);
          setPickedId(after.selected?.listing_id ?? null);
          return after.selected;
        }}
        onPriceChanged={(usd) => {
          // Pinned: at its new price it may no longer be the cheapest default.
          setPickedId(selected.listing_id);
          setOffers(
            (all) =>
              all?.map((o) => (o.listing_id === selected.listing_id ? repriceOffer(o, usd) : o)) ??
              null,
          );
        }}
      />
    );
  }

  return (
    <div className={`yp-fade-in space-y-5 px-4 pt-4 ${buyable ? "pb-28" : "pb-4"}`}>
      <div ref={topRef} className="scroll-mt-[calc(var(--app-header-total)_+_8px)]">
        <SkinHeroCard item={item} offer={selected} />
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
          <p className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
            <span className="text-2xl font-bold tabular-nums text-white">
              {price === null
                ? t("cs2.soldOut")
                : head.from
                  ? t("cs2.fromPrice", { price })
                  : price}
            </span>
            {off !== null && (
              <span className="rounded-md bg-emerald-500/15 px-1.5 py-0.5 text-[12px] font-bold text-emerald-400">
                {t("cs2.belowSteam", { percent: off })}
              </span>
            )}
          </p>
          {price !== null && (
            <p className="mt-1 inline-flex items-center gap-1.5 text-[12px] font-semibold text-emerald-400">
              <Zap className="h-3.5 w-3.5" aria-hidden="true" />
              {t("cs2.instantDelivery")}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => {
            openExternalLink(steamMarketUrl(item.name));
          }}
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

      {/* Above the offers: with forty of them, the link would be forty rows down. */}
      {buyable && <SkinTradeLinkInput onChange={onLink} inputRef={linkRef} initial={link.url} />}

      {worn && (
        <section>
          <h2 className="mb-2 text-[15px] font-bold text-white">
            {t("cs2.offers")}{" "}
            <span className="font-mono text-[13px] text-white/50">{item.count}</span>
          </h2>
          <SkinListingsList
            key={item.slug}
            items={offers}
            image={item.image_url}
            exterior={item.exterior}
            {...(buyable ? { selectedId: selected.listing_id, onSelect: pickOffer } : {})}
          />
        </section>
      )}
      {buyable && (
        <>
          <SkinFixedCta
            muted={!link.usable}
            onPress={() => {
              haptic("press");
              if (!link.usable) {
                // The link is the step left: take the buyer to it.
                linkRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
                linkRef.current?.focus({ preventScroll: true });
                return;
              }
              setStage("review");
              window.scrollTo({ top: 0 });
              document.querySelector("main")?.scrollTo({ top: 0 });
            }}
            label={link.usable ? t("topup.continueCta") : t("cs2.buy.payHintLink")}
          />
        </>
      )}
    </div>
  );
}
