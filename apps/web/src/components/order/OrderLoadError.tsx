"use client";

import { AlertCircle, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { buttonStyles } from "@/lib/button";
import { pathFor } from "@/lib/seo";

/**
 * Dead-end recovery for the order page.
 *
 * The order can fail to load for very different reasons — a flaky network, an
 * expired guest token, or a genuinely wrong link — and a single red line of
 * text left the customer with nowhere to go. Offer the three moves that
 * actually resolve each case: retry, their order list, or the catalog.
 */
interface OrderLoadErrorProps {
  locale: string;
  onRetry: () => void;
  /** The API answered 401/403/404: refreshing cannot help, so no retry button. */
  denied?: boolean;
}

export function OrderLoadError({ locale, onRetry, denied = false }: OrderLoadErrorProps) {
  const t = useTranslations("web.orders");

  return (
    <div
      role="alert"
      className="border-border bg-card space-y-4 rounded-2xl border p-6 text-center"
    >
      <span
        className="bg-[#FF6B6B]/12 mx-auto flex size-11 items-center justify-center rounded-xl ring-1 ring-inset ring-[#FF6B6B]/25"
        aria-hidden="true"
      >
        <AlertCircle size={22} className="text-[#FF6B6B]" strokeWidth={2.5} />
      </span>

      <div className="space-y-1.5">
        {/* The page's only heading in this state, so h1. */}
        <h1 className="font-display text-foreground text-lg font-bold">{t("notFound")}</h1>
        <p className="text-tx-mute mx-auto max-w-[36ch] text-sm leading-snug">
          {t(denied ? "notFoundDenied" : "notFoundHelp")}
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
        {!denied && (
          <button type="button" onClick={onRetry} className={buttonStyles({ size: "sm" })}>
            <RefreshCw size={14} />
            {t("retry")}
          </button>
        )}
        <Link
          href={pathFor(locale, "/account/orders")}
          className={buttonStyles({ variant: "ghost", size: "sm" })}
        >
          {t("backToOrders")}
        </Link>
        <Link
          href={pathFor(locale, "/store")}
          className={buttonStyles({ variant: "ghost", size: "sm" })}
        >
          {t("toCatalog")}
        </Link>
      </div>
    </div>
  );
}
