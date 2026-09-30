import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

import { skinFaq, skinProductLd, wearFloatRange } from "./skin-seo";
import ru from "../../../../packages/i18n/locales/ru/web.json";

import type { SkinDetail } from "@yupay/utils";

const t = createTranslator({ locale: "ru", messages: { web: ru }, namespace: "web.skins" });

const ITEM: SkinDetail = {
  slug: "ak-47-slate-battle-scarred",
  name: "AK-47 | Slate (Battle-Scarred)",
  phase: null,
  category: "rifles",
  weapon: "AK-47",
  skin: "Slate",
  exterior: "BS",
  stattrak: false,
  souvenir: false,
  rarity: "Restricted",
  rarity_color: "#8847ff",
  image_url: "https://community.fastly.steamstatic.com/economy/image/x",
  price_usd: "3.40",
  price_uzs: "40000",
  steam_price_usd: "4.10",
  discount_percent: 17,
  count: 23,
  min_float: "0.00000",
  max_float: "1.00000",
  cheapest: [],
  family: [],
  buy_sku_id: "sku-1",
};

describe("wearFloatRange", () => {
  it("is the wear's band cut to the skin's own range", () => {
    expect(
      wearFloatRange({ ...ITEM, exterior: "FT", min_float: "0.10", max_float: "0.70" }),
    ).toEqual(["0.15", "0.38"]);
    expect(
      wearFloatRange({ ...ITEM, exterior: "FN", min_float: "0.02", max_float: "0.80" }),
    ).toEqual(["0.02", "0.07"]);
    expect(wearFloatRange({ ...ITEM, exterior: null })).toBeNull();
  });
});

describe("skinFaq", () => {
  it("answers price, Steam, float and how to buy from the item's own numbers", () => {
    const faq = skinFaq(ITEM, t, "ru");
    const text = faq.map((f) => `${f.question} ${f.answer}`).join("\n");
    expect(faq[0]?.question).toBe("Сколько стоит AK-47 | Slate (Battle-Scarred) в Узбекистане?");
    expect(faq[0]?.answer).toMatch(/40\s000 сум/);
    expect(faq[0]?.answer).toMatch(/23 предложений/);
    expect(text).toMatch(/\$4\.10/);
    expect(text).toMatch(/17\s?%/);
    expect(text).toMatch(/от 0\.45 до 1\.00/);
    expect(text).toMatch(/Click, Payme, Uzum/);
  });

  it("does not claim Steam is dearer when it is not, nor a price it does not have", () => {
    const faq = skinFaq(
      { ...ITEM, discount_percent: 0, price_usd: null, price_uzs: null },
      t,
      "ru",
    );
    const text = faq.map((f) => f.answer).join("\n");
    expect(text).not.toMatch(/дешевле/);
    expect(faq.some((f) => f.question.startsWith("Сколько стоит"))).toBe(false);
  });
});

describe("skinProductLd", () => {
  it("offers the cheapest price in soʻm as a single offer", () => {
    const ld = skinProductLd(ITEM, "https://yupay.uz/skins/ak-47-slate-battle-scarred");
    expect(ld?.["@type"]).toBe("Product");
    expect(ld?.name).toBe("AK-47 | Slate (Battle-Scarred)");
    // A single Offer, not an AggregateOffer: the page knows the cheapest price but
    // not the dearest, and Search Console flags an AggregateOffer without highPrice.
    expect(ld?.offers).toEqual(
      expect.objectContaining({
        "@type": "Offer",
        price: 40000,
        priceCurrency: "UZS",
        availability: "https://schema.org/InStock",
      }),
    );
  });

  it("keeps a priced item that sold out valid: an out-of-stock offer, never a bare Product", () => {
    const ld = skinProductLd({ ...ITEM, count: 0 }, "u");
    expect(ld?.offers).toEqual(
      expect.objectContaining({ price: 40000, availability: "https://schema.org/OutOfStock" }),
    );
  });

  it("emits no Product at all without a price", () => {
    expect(skinProductLd({ ...ITEM, price_uzs: null }, "u")).toBeNull();
  });
});
