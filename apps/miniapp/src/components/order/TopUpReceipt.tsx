import { motion } from "framer-motion";

import { isStringRecord, labelForField } from "./order-helpers";

import type { DeliveryOut } from "@/lib/orders";

import { useT } from "@/lib/i18n";
import { getActiveLocale } from "@/lib/i18n/core";

// For top-up products there is no code to deliver — the supplier credits the
// player's account directly. The receipt block surfaces:
//   * the fields the user entered at checkout (player_id, region, …) so they
//     can confirm we pushed UC to the right account;
//   * the supplier's order id, in case support needs it later.

/**
 * Extracted out of `OrderSuccess.tsx` (2026-09-03 review) purely to keep
 * that file near the repo's TS file-length budget — no behaviour change.
 */
export function TopUpReceipt({
  delivery,
  fulfillmentData,
  creditedUsd,
}: {
  delivery: DeliveryOut;
  fulfillmentData: Record<string, unknown>;
  /** The dollar amount credited, for a variable-amount SKU (Steam wallet).
   *  `null` for a fixed-denomination top-up — its package name already says
   *  what was bought, so repeating the USD unit price would just be noise. */
  creditedUsd: string | null;
}) {
  const { t } = useT();
  // Prefer the snapshot stored in the artifact (frozen at fulfilment time),
  // fall back to the live item.fulfillment_data if the supplier didn't echo
  // it back.
  const artifactSnapshot = isStringRecord(delivery.artifact.fulfillment_data)
    ? delivery.artifact.fulfillment_data
    : null;
  const fields = artifactSnapshot ?? fulfillmentData;

  const entries = Object.entries(fields).filter(
    ([, v]) => typeof v === "string" && v.trim().length > 0,
  ) as [string, string][];

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      className="mt-3 space-y-2"
    >
      <div className="flex items-center gap-1.5">
        <span
          className="text-[10px] font-semibold uppercase tracking-[0.08em]"
          style={{ color: "hsl(var(--primary))" }}
        >
          {t("success.credited")}
        </span>
        <span className="text-[10px] text-white/25">·</span>
        <span className="text-[10px] text-white/35">
          {new Date(delivery.delivered_at).toLocaleString(getActiveLocale(), {
            day: "2-digit",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>

      {(creditedUsd !== null || entries.length > 0) && (
        <div
          className="space-y-1.5 rounded-xl p-3"
          style={{
            background: "hsl(var(--surface-2))",
            border: "1px solid hsl(var(--border))",
          }}
        >
          {creditedUsd !== null && (
            <div className="flex items-baseline justify-between gap-3 text-xs">
              <span className="text-white/50">{t("success.creditedAmount")}</span>
              <span className="text-right font-mono font-semibold text-white">
                ${Number.parseFloat(creditedUsd).toFixed(2)}
              </span>
            </div>
          )}
          {entries.map(([key, value]) => (
            <div key={key} className="flex items-baseline justify-between gap-3 text-xs">
              <span className="text-white/50">{labelForField(key)}</span>
              <span className="max-w-[60%] truncate text-right font-mono text-white">{value}</span>
            </div>
          ))}
        </div>
      )}
      {/* The supplier's external_id is stored in the artifact for support
          / chargeback evidence, but isn't useful to the customer — and
          surfacing it invited "что значит этот номер?" support tickets.
          Admins still see it via /admin/fulfillment task details. */}
    </motion.div>
  );
}
