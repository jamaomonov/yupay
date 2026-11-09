import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SkuRows } from "./SkuRows";

import type { Brand, Sku } from "@/lib/types";

const sku = (id: string, stock: number | null): Sku => ({
  sku_id: id,
  sku_code: id,
  name: id,
  kind: "fixed",
  price_usd: "1.61",
  retail_price_usd: null,
  unit_price_usd: null,
  unit: null,
  min_qty: null,
  max_qty: null,
  min_amount_usd: null,
  max_amount_usd: null,
  image_url: null,
  stock,
  updated_at: "2026-11-09T00:00:00Z",
});

const brand = (...skus: Sku[]): Brand => ({
  brand_id: "b",
  slug: "roblox",
  name: "Roblox",
  category_slug: null,
  category_name: null,
  logo_url: null,
  hero_image_url: null,
  products: [{ product_id: "p", slug: "p", name: "p", required_fields: [], skus }],
});

const messages = {
  merchant: {
    catalog: {
      inStock: "В наличии: {count}",
      outOfStock: "Нет в наличии",
      perHundred: "за 100",
      perDollar: "за $1",
      selected: "выбрано",
    },
  },
};

function render(b: Brand): string {
  return renderToStaticMarkup(
    <NextIntlClientProvider locale="ru" messages={messages}>
      <SkuRows brand={b} selected={null} onPick={() => undefined} />
    </NextIntlClientProvider>,
  );
}

/** The hourly supplier count is shown, and an empty line cannot be picked. */
describe("SkuRows stock", () => {
  it("shows the count and keeps a stocked line clickable", () => {
    const html = render(brand(sku("50 Robux", 127)));
    expect(html).toContain("В наличии: 127");
    expect(html).not.toContain('disabled=""');
  });

  it("marks an empty line and disables it", () => {
    const html = render(brand(sku("100 Robux", 0)));
    expect(html).toContain("Нет в наличии");
    expect(html).toContain('disabled=""');
  });

  it("says nothing for an uncounted top-up", () => {
    const html = render(brand(sku("60 UC", null)));
    expect(html).not.toContain("В наличии");
    expect(html).not.toContain("Нет в наличии");
  });
});
