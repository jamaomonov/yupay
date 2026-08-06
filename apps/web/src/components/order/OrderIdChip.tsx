"use client";

import { Check, Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { toast } from "@/store/useToast";

/**
 * The order number, copyable.
 *
 * Shows the short `#abcdef12` form the rest of the UI uses, but copies the
 * **full** id — that is what support needs when a customer asks about an order,
 * and re-typing a UUID off a phone screen is exactly the friction this removes.
 */
export function OrderIdChip({ orderId }: { orderId: string }) {
  const t = useTranslations("web.orders");
  const [copied, setCopied] = useState(false);

  const onCopy = () => {
    void navigator.clipboard
      .writeText(orderId)
      .then(() => {
        setCopied(true);
        toast.success(t("orderIdCopied"));
        setTimeout(() => {
          setCopied(false);
        }, 1500);
      })
      .catch(() => {
        toast.error(t("copyFailed"));
      });
  };

  return (
    <button
      type="button"
      onClick={onCopy}
      aria-label={`${t("copyOrderId")}: ${orderId}`}
      className="text-tx-dim hover:text-tx-mute focus-visible:ring-primary/60 group -mx-1 inline-flex items-center gap-1.5 rounded px-1 py-0.5 font-mono text-[11px] uppercase tracking-[0.14em] transition focus-visible:outline-none focus-visible:ring-2"
    >
      #{orderId.slice(0, 8)}
      {copied ? (
        <Check size={12} className="text-primary" aria-hidden="true" />
      ) : (
        <Copy
          size={12}
          className="opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
          aria-hidden="true"
        />
      )}
    </button>
  );
}
