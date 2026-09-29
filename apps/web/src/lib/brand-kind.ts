import type { ProductSummary } from "@/lib/catalog";

/**
 * A brand that sells only codes (Discord Nitro, Minecraft, gift cards): its page must say
 * «купить» and «активировать», never «пополнить» and «зачисление». A brand with any
 * top-up product, or none known, keeps the top-up copy.
 */
export function isVoucherBrand(brand: { products?: Pick<ProductSummary, "kind">[] }): boolean {
  const products = brand.products ?? [];
  return products.length > 0 && products.every((p) => p.kind === "voucher");
}
