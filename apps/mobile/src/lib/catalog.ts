import type { BrandOut, OrderItemOut } from "@yupay/api-client/types";

/**
 * Brands with a flow of their own, not built in the app yet: game gifts, skins, and the Steam
 * wallet (an amount the buyer types, not a denomination).
 */
const OWN_FLOW = new Set(["steam-gifts", "cs2-skins", "steam"]);

/**
 * Brands the app sells. Gift cards stay out of the first version (ADR-0100): they carry the
 * clearest store-billing risk.
 */
export function sellable(brands: readonly BrandOut[]): BrandOut[] {
  return brands.filter(
    (brand) => brand.category_slug !== "gift-cards" && !OWN_FLOW.has(brand.slug),
  );
}

/** Case-insensitive match on the brand name or slug. */
export function matches(brand: BrandOut, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q === "") return true;
  return brand.name.toLowerCase().includes(q) || brand.slug.includes(q);
}

/**
 * The picture for an order line: the SKU's, else the product's (the API already resolves those
 * two into `display.image_url`), else the brand's logo from the catalogue.
 */
export function orderImage(
  display: { image_url: string | null; brand_slug: string } | null | undefined,
  brands: readonly BrandOut[] | undefined,
): string | null {
  if (display == null) return null;
  if (display.image_url) return display.image_url;
  return brands?.find((b) => b.slug === display.brand_slug)?.logo_url ?? null;
}

/**
 * What an order line bought, in a few characters. A Steam top-up's denomination is the
 * «Любая сумма» placeholder, so it reads as the dollars credited (`unit_price_usd`); a Stars
 * line bought by count reads as the count. Everything else is its denomination.
 */
export function itemLabel(item: OrderItemOut | undefined): string {
  const display = item?.display;
  if (item === undefined || display == null) return "";
  if (display.variable_amount) {
    const cents = Math.round(Number(item.unit_price_usd) * 100) * item.qty;
    return `$${(cents / 100).toFixed(2).replace(/\.00$/, "")}`;
  }
  if (item.qty > 1) return item.qty.toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return display.denomination ?? display.product_name;
}
