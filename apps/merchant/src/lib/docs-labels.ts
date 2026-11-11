import { getTranslations } from "next-intl/server";

import type { Endpoint } from "./contract";

/**
 * Localised names for the API reference: one title per operation, one label
 * per tag.
 *
 * The contract's `summary` and tag names are English, and they were shown
 * as-is on the RU and UZ pages — «Place an order and settle it from the
 * deposit» as the title of a Russian page. The translations live in
 * `merchant.docs.ops` and `merchant.docs.tags`; an operation or tag added to
 * the contract without one falls back to the contract's own words, so a new
 * endpoint is never missing from the reference — only untranslated until
 * somebody adds the line.
 */

/** `get-orders-merchant-order-id` → `getOrdersMerchantOrderId`. */
export function opMessageKey(id: string): string {
  return id.replace(/-([a-z0-9])/g, (_, ch: string) => ch.toUpperCase());
}

export interface DocsLabels {
  /** The operation's title in the reader's language. */
  operation: (endpoint: Endpoint) => string;
  /** A sidebar group label for a contract tag. */
  tag: (name: string) => string;
}

export async function docsLabels(locale: string): Promise<DocsLabels> {
  const t = await getTranslations({ locale, namespace: "merchant.docs" });
  return {
    operation: (endpoint) => {
      const key = `ops.${opMessageKey(endpoint.id)}`;
      if (t.has(key)) return t(key);
      return endpoint.operation.summary ?? endpoint.path;
    },
    tag: (name) => {
      const key = `tags.${name}`;
      return t.has(key) ? t(key) : name;
    },
  };
}
