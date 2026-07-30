"use client";

import { useTranslations } from "next-intl";

/** Statuses with both a ``web.orders.status.*`` label and a ``web.orders.body.*``
 *  explanation; anything else falls back to the raw status code with no body. */
const KNOWN = new Set([
  "pending_payment",
  "paid",
  "fulfilling",
  "fulfilled",
  "delivered",
  "failed",
  "cancelled",
  "expired",
  "refunded",
  "partially_refunded",
]);

/**
 * Order status heading + real explanatory copy for every status — most
 * notably `fulfilling`, which previously showed only the bare status word
 * ("Processing") with no context for what's actually happening.
 *
 * `isTopUp` swaps the `delivered` copy for top-up-flavored wording
 * ("Credited" instead of "Delivered") to match the Mini App's phrasing —
 * a top-up never gets "delivered", it gets credited to the account.
 */
export function StatusBlock({ status, isTopUp }: { status: string; isTopUp?: boolean }) {
  const t = useTranslations("web.orders");
  const known = KNOWN.has(status);
  const isDeliveredTopUp = status === "delivered" && Boolean(isTopUp);
  return (
    <div className="space-y-1">
      <h2 className="font-display text-xl font-bold">
        {isDeliveredTopUp ? t("status.deliveredTopup") : known ? t(`status.${status}`) : status}
      </h2>
      {isDeliveredTopUp ? (
        <p className="text-tx-mute text-sm">{t("body.deliveredTopup")}</p>
      ) : known ? (
        <p className="text-tx-mute text-sm">{t(`body.${status}`)}</p>
      ) : null}
    </div>
  );
}
