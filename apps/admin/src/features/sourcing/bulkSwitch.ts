/**
 * Chunked, idempotent bulk sourcing-rule switch.
 *
 * `PUT /admin/sourcing/rules:bulk` caps `sku_ids` at `MAX_BULK_SKU_IDS`
 * (100) and answers 422 above that — a brand can have more active SKUs
 * than that, so a "select all, switch" click must not hand the endpoint an
 * oversized array. This splits the selection into chunks of at most
 * `MAX_BULK_SKU_IDS` and sends one request per chunk, merging their
 * per-SKU results back into one report — the screen still shows one
 * outcome per SKU; chunk boundaries are invisible to it.
 *
 * **Idempotency-Key policy: one fresh key per HTTP attempt, never reused.**
 * The endpoint saves the replay body under whatever key is present,
 * including an all-failed body — reusing a key across a retry (operator
 * fixes the missing mapping, presses the button again) would silently
 * replay the stale failure and write nothing, and a reused key also pins
 * the *first* body it saw, so even a corrected selection would be
 * swallowed. `crypto.randomUUID()` is minted fresh for every chunk of
 * every call — never hoisted to a ref or generated once per selection.
 *
 * A chunk request that fails outright (network error, 5xx — not a
 * per-SKU business rejection, which the endpoint already reports inside a
 * 200) is turned into a per-SKU `ok: false` result for that chunk instead
 * of rejecting the whole operation, so one bad chunk in a multi-chunk
 * selection does not hide the chunks that already wrote successfully.
 */

import { MAX_BULK_SKU_IDS } from "./types";

import type {
  SourcingBulkRuleIn,
  SourcingBulkRuleOut,
  SourcingBulkRuleResultOut,
  SourcingMode,
} from "./types";

import { ApiError, apiPut, formatApiError } from "@/lib/api";

const BULK_RULES_URL = "/api/v1/admin/sourcing/rules:bulk";

export async function switchSkusChunked(
  skuIds: readonly string[],
  mode: SourcingMode,
  supplierSlug: string | null,
): Promise<SourcingBulkRuleOut> {
  const items: SourcingBulkRuleResultOut[] = [];
  for (let i = 0; i < skuIds.length; i += MAX_BULK_SKU_IDS) {
    const chunk = skuIds.slice(i, i + MAX_BULK_SKU_IDS);
    try {
      // Typed against SourcingBulkRuleIn so a renamed/misspelled field
      // fails tsc here instead of the backend's `extra="forbid"` 422 at
      // request time — apiPut's `body` parameter is `unknown` and checks
      // nothing on its own.
      const body: SourcingBulkRuleIn = { sku_ids: chunk, mode, supplier_slug: supplierSlug };
      // Sequential on purpose: each chunk mints and spends its own
      // Idempotency-Key, and firing them in parallel would gain nothing —
      // 100 SKUs per request is already the server's own cap on one unit
      // of work.
      const result = await apiPut<SourcingBulkRuleOut>(BULK_RULES_URL, body, {
        "Idempotency-Key": crypto.randomUUID(),
      });
      items.push(...result.items);
    } catch (err) {
      const message = err instanceof ApiError ? formatApiError(err) : "Сетевая ошибка";
      for (const skuId of chunk) {
        items.push({ sku_id: skuId, ok: false, error: message });
      }
    }
  }
  return { items };
}
