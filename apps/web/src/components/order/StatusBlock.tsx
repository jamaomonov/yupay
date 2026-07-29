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
 */
export function StatusBlock({ status }: { status: string }) {
  const t = useTranslations("web.orders");
  const known = KNOWN.has(status);
  return (
    <div className="space-y-1">
      <h2 className="font-display text-xl font-bold">
        {known ? t(`status.${status}`) : status}
      </h2>
      {known ? <p className="text-tx-mute text-sm">{t(`body.${status}`)}</p> : null}
    </div>
  );
}
