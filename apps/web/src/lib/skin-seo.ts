/**
 * What search engines read on a CS2 item page, built from the item's own numbers: the FAQ
 * (price in soʻm and offers, Steam's price when ours is lower, the wear's float range, how
 * to buy) and the Product JSON-LD with an AggregateOffer. Only facts the item has are
 * stated — no price, no price question; not cheaper than Steam, no Steam answer.
 */

import type { Exterior, SkinDetail } from "@yupay/utils";

import { displayPrice } from "@/lib/skins";

/** Steam's float bands per wear. */
const WEAR_BANDS: Record<Exterior, [number, number]> = {
  FN: [0, 0.07],
  MW: [0.07, 0.15],
  FT: [0.15, 0.38],
  WW: [0.38, 0.45],
  BS: [0.45, 1],
};

/** The float an item of this wear can have: the wear's band cut to the skin's range. */
export function wearFloatRange(
  item: Pick<SkinDetail, "exterior" | "min_float" | "max_float">,
): [string, string] | null {
  if (!item.exterior) return null;
  const [lo, hi] = WEAR_BANDS[item.exterior];
  const min = Math.max(lo, item.min_float === null ? lo : Number(item.min_float));
  const max = Math.min(hi, item.max_float === null ? hi : Number(item.max_float));
  if (!(min < max)) return null;
  return [min.toFixed(2), max.toFixed(2)];
}

/** The name as the page shows it, Doppler phase included. */
export function skinFullName(item: Pick<SkinDetail, "name" | "phase">): string {
  return item.phase ? `${item.name} ${item.phase}` : item.name;
}

export interface FaqEntry {
  question: string;
  answer: string;
}

/** The `web.skins` keys the FAQ reads. */
type FaqKey =
  | "faq.priceQ"
  | "faq.priceA"
  | "faq.steamQ"
  | "faq.steamA"
  | "faq.floatQ"
  | "faq.floatA"
  | "faq.buyQ"
  | "faq.buyA"
  | `exterior.${Exterior}`;

/** A `next-intl` translator scoped to `web.skins` — any that knows the FAQ's keys. */
export type SkinsT = (key: FaqKey, values?: Record<string, string | number>) => string;

export function skinFaq(item: SkinDetail, t: SkinsT, locale: string): FaqEntry[] {
  const name = skinFullName(item);
  const price = displayPrice(locale, item.price_uzs, item.price_usd);
  const out: FaqEntry[] = [];
  if (price !== null && item.count > 0) {
    out.push({
      question: t("faq.priceQ", { name }),
      answer: t("faq.priceA", { name, price, count: item.count }),
    });
  }
  if (item.steam_price_usd && item.discount_percent && item.discount_percent > 0) {
    out.push({
      question: t("faq.steamQ", { name }),
      answer: t("faq.steamA", { steam: item.steam_price_usd, percent: item.discount_percent }),
    });
  }
  const range = wearFloatRange(item);
  if (range && item.exterior) {
    out.push({
      question: t("faq.floatQ", { name }),
      answer: t("faq.floatA", {
        exterior: t(`exterior.${item.exterior}`),
        min: range[0],
        max: range[1],
      }),
    });
  }
  if (item.buy_sku_id) {
    out.push({ question: t("faq.buyQ", { name }), answer: t("faq.buyA") });
  }
  return out;
}

export type ProductLd = {
  "@context": "https://schema.org";
  "@type": "Product";
  name: string;
  image?: string;
  category: string;
  url: string;
  offers?: {
    "@type": "AggregateOffer";
    lowPrice: number;
    priceCurrency: "UZS";
    offerCount: number;
    availability: string;
    url: string;
  };
};

export function skinProductLd(item: SkinDetail, url: string): ProductLd {
  const uzs = item.price_uzs === null ? null : Math.round(Number(item.price_uzs));
  return {
    "@context": "https://schema.org",
    "@type": "Product",
    name: skinFullName(item),
    ...(item.image_url ? { image: item.image_url } : {}),
    category: `CS2 ${item.weapon ?? item.category}`,
    url,
    ...(uzs !== null && item.count > 0
      ? {
          offers: {
            "@type": "AggregateOffer" as const,
            lowPrice: uzs,
            priceCurrency: "UZS" as const,
            offerCount: item.count,
            availability: "https://schema.org/InStock",
            url,
          },
        }
      : {}),
  };
}
