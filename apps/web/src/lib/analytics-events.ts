import type { BrandSummary, ProductDetail, SkuOut } from "@/lib/catalog";
import type { OrderOut } from "@/lib/orders-types";

/**
 * GA4 e-commerce funnel events for the data layer — the shape GTM's GA4 tag
 * reads with «Send Ecommerce data: Data Layer», and that Metrika's
 * `ecommerce:"dataLayer"` understands for the events it maps (`view_item`,
 * `purchase`). `purchase` itself lives in `purchase-event.ts`, on the same
 * push helper. Setup on Google's side: `docs/runbooks/ga4-funnel.md`.
 *
 * Nothing here carries PII (AGENTS.md §9): no email, phone, player/game id,
 * nickname, Steam login, trade link or Telegram id — only catalogue codes,
 * prices, the provider code and a player check's verdict.
 */

/** A list longer than this is cut: GA4 caps a hit's size, and nobody scrolls 200 tiles. */
export const LIST_ITEMS_CAP = 50;

export interface EcommerceItem {
  item_id: string;
  item_name: string;
  item_brand: string;
  item_variant?: string;
  price?: number;
  quantity?: number;
  index?: number;
}

interface EcommerceEvent<E extends string, P extends object> {
  event: E;
  ecommerce: P & { items: EcommerceItem[] };
}

export type ViewItemListEvent = EcommerceEvent<
  "view_item_list",
  { item_list_id: string; item_list_name: string }
>;
export type ViewItemEvent = EcommerceEvent<"view_item", { currency?: string; value?: number }>;
export type SelectItemEvent = EcommerceEvent<"select_item", { currency?: string; value?: number }>;
export type BeginCheckoutEvent = EcommerceEvent<
  "begin_checkout",
  { currency: string; value: number }
>;
export type AddPaymentInfoEvent = EcommerceEvent<
  "add_payment_info",
  { currency: string; value: number; payment_type: string }
>;
export type PurchaseEvent = EcommerceEvent<
  "purchase",
  { transaction_id: string; currency: string; value: number }
>;

export type PlayerCheckOutcome = "valid" | "invalid" | "error" | "unsupported";

/** Custom, not GA4-recommended: a player-id check finished. The verdict and
 *  the brand only — never the id or the nickname it resolved to. */
export interface PlayerCheckEvent {
  event: "player_check";
  result: PlayerCheckOutcome;
  item_brand: string;
}

export type AnalyticsEvent =
  | ViewItemListEvent
  | ViewItemEvent
  | SelectItemEvent
  | PlayerCheckEvent
  | BeginCheckoutEvent
  | AddPaymentInfoEvent
  | PurchaseEvent;

/**
 * Push one event into `window.dataLayer`. An e-commerce event is preceded by
 * `{ecommerce: null}`, as GA4 asks, so its items never merge with the last
 * event's. A no-op on the server; never throws — analytics must not break a
 * checkout. Returns whether the event was pushed.
 */
export function pushAnalyticsEvent(event: AnalyticsEvent | null): boolean {
  if (event === null || typeof window === "undefined") return false;
  try {
    window.dataLayer = window.dataLayer ?? [];
    if ("ecommerce" in event) window.dataLayer.push({ ecommerce: null });
    window.dataLayer.push(event);
    return true;
  } catch {
    return false;
  }
}

/** `n` rounded to cents, or `undefined` when it is not a usable price. */
function money(n: number): number | undefined {
  return Number.isFinite(n) && n > 0 ? Math.round(n * 100) / 100 : undefined;
}

/**
 * An order's lines as GA4 items. Line prices are in USD; the charged total is
 * spread over them so the items add up to `value` in the order's own currency.
 */
export function orderItems(order: OrderOut): EcommerceItem[] {
  const value = Number(order.total_charged);
  const totalUsd = Number(order.total_usd);
  const rate = totalUsd > 0 && Number.isFinite(value) ? value / totalUsd : 0;
  return order.items.map((item) => ({
    item_id: item.display?.sku_code ?? item.sku_id,
    item_name: item.display?.product_name ?? "",
    item_brand: item.display?.brand_slug ?? "",
    price: Math.round(Number(item.unit_price_usd) * rate * 100) / 100,
    quantity: item.qty,
  }));
}

/** `value` and `currency` of an order, or `null` when it charges nothing usable. */
function orderValue(order: OrderOut): { currency: string; value: number } | null {
  const value = Number(order.total_charged);
  if (!Number.isFinite(value) || value <= 0) return null;
  return { currency: order.currency, value };
}

/** The catalogue (or one category of it) shown as a brand grid. */
export function viewItemListEvent(
  listId: string,
  listName: string,
  brands: readonly Pick<BrandSummary, "slug" | "name">[],
): ViewItemListEvent | null {
  if (brands.length === 0) return null;
  return {
    event: "view_item_list",
    ecommerce: {
      item_list_id: listId,
      item_list_name: listName,
      items: brands.slice(0, LIST_ITEMS_CAP).map((b, i) => ({
        item_id: b.slug,
        item_name: b.name,
        item_brand: b.slug,
        index: i,
      })),
    },
  };
}

/** A brand page opened. No price: nothing is chosen yet. */
export function viewItemEvent(brand: Pick<BrandSummary, "slug" | "name">): ViewItemEvent {
  return {
    event: "view_item",
    ecommerce: { items: [{ item_id: brand.slug, item_name: brand.name, item_brand: brand.slug }] },
  };
}

/**
 * A nominal picked. The price is the one on the tile — `display_price` (UZS)
 * when the API sent one, else `price_usd`. A variable-amount or per-unit SKU
 * has no price until the amount is typed, so it goes without one.
 */
export function selectItemEvent(
  sku: SkuOut,
  product: Pick<ProductDetail, "name">,
  brandSlug: string,
  priced: boolean,
): SelectItemEvent {
  const item: EcommerceItem = {
    item_id: sku.sku_code,
    item_name: product.name,
    item_brand: brandSlug,
    quantity: 1,
  };
  if (sku.denomination) item.item_variant = sku.denomination;
  if (!priced) return { event: "select_item", ecommerce: { items: [item] } };
  const price = money(Number(sku.display_price?.amount ?? sku.price_usd));
  if (price === undefined) return { event: "select_item", ecommerce: { items: [item] } };
  item.price = price;
  const currency = sku.display_price?.currency ?? "USD";
  return { event: "select_item", ecommerce: { currency, value: price, items: [item] } };
}

/** A player check's verdict, scoped to the brand. Never the id or the nickname. */
export function playerCheckEvent(result: PlayerCheckOutcome, brandSlug: string): PlayerCheckEvent {
  return { event: "player_check", result, item_brand: brandSlug };
}

/** An order was created — the start of checkout. */
export function beginCheckoutEvent(order: OrderOut): BeginCheckoutEvent | null {
  const v = orderValue(order);
  if (v === null) return null;
  return { event: "begin_checkout", ecommerce: { ...v, items: orderItems(order) } };
}

/** A payment was started for `order` on `provider` (click, payme, wallet, p2p, …). */
export function addPaymentInfoEvent(order: OrderOut, provider: string): AddPaymentInfoEvent | null {
  const v = orderValue(order);
  if (v === null) return null;
  return {
    event: "add_payment_info",
    ecommerce: { ...v, payment_type: provider, items: orderItems(order) },
  };
}

/** Build-and-push for a server response the type only promises: a builder
 *  that trips over a missing field must not fail the checkout around it. */
export function trackOrderEvent(
  build: (order: OrderOut) => AnalyticsEvent | null,
  order: OrderOut,
): void {
  try {
    pushAnalyticsEvent(build(order));
  } catch {
    // analytics never breaks checkout
  }
}

declare global {
  interface Window {
    dataLayer?: unknown[];
  }
}
