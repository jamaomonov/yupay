"use client";

import { CheckCircle2, ExternalLink, Loader2, ShieldCheck, Wallet } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import type { SkinTradeOut } from "@/lib/orders-types";

import { buttonStyles } from "@/lib/button";
import { pathFor } from "@/lib/seo";

const SUPPORT_URL = "https://t.me/yupay_support";

/** Re-render once a minute so the accept-by line stays true. */
function useMinuteTick(active: boolean): void {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setTick((n) => n + 1), 60_000);
    return () => clearInterval(id);
  }, [active]);
}

/**
 * A CS2 skin line's Steam trade on the order page: buying → the offer (open it
 * in Steam, from whom, accept by when) → received, protected by Steam until
 * a date; or, failed, where the refund went (`refunded_to`, read off the
 * payment) — and support whenever no refund was made, so nothing is promised.
 */
export function SkinTradeCard({ trade, locale }: { trade: SkinTradeOut; locale: string }) {
  const t = useTranslations("web.skins.trade");
  useMinuteTick(trade.state === "offer_sent");
  const time = (iso: string) =>
    new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
  const date = (iso: string) =>
    new Intl.DateTimeFormat(locale, { day: "numeric", month: "long" }).format(new Date(iso));

  return (
    <section className="border-border bg-card space-y-3 rounded-xl border p-4">
      <p className="text-tx-dim text-[11px] font-semibold uppercase tracking-[0.08em]">
        {t("title")}
      </p>

      {trade.state === "buying" && (
        <p className="flex items-center gap-2 text-[14px]">
          <Loader2 className="text-primary h-4 w-4 animate-spin" aria-hidden />
          {t("buying")}
        </p>
      )}

      {trade.state === "offer_sent" && (
        <div className="space-y-3">
          <p className="text-[15px] font-semibold">{t("offer_sent")}</p>
          {trade.seller?.name && (
            <p className="flex items-center gap-2 text-[13px]">
              <span className="text-tx-dim">{t("seller")}</span>
              {trade.seller.avatar_url && (
                // A Steam avatar: next/image would need the host allowlisted for nothing.
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={trade.seller.avatar_url}
                  alt=""
                  width={20}
                  height={20}
                  className="h-5 w-5 rounded-full"
                />
              )}
              <span className="font-semibold">{trade.seller.name}</span>
            </p>
          )}
          {trade.offer_url && (
            <a
              href={trade.offer_url}
              target="_blank"
              rel="noopener noreferrer"
              className={`${buttonStyles({ size: "md" })} inline-flex items-center gap-2`}
            >
              {t("openOffer")}
              <ExternalLink className="h-4 w-4" aria-hidden />
            </a>
          )}
          {trade.send_until && (
            <p className="text-tx-dim text-[12px]">
              {t("acceptBy", { time: time(trade.send_until) })}
            </p>
          )}
        </div>
      )}

      {(trade.state === "accepted" || trade.state === "released") && (
        <div className="space-y-1">
          <p className="flex items-center gap-2 text-[15px] font-semibold text-emerald-400">
            <CheckCircle2 className="h-4 w-4" aria-hidden />
            {t(trade.state)}
          </p>
          {trade.state === "accepted" && trade.release_date && (
            <p className="text-tx-dim flex items-center gap-1.5 text-[12px]">
              <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
              {t("protectedUntil", { date: date(trade.release_date) })}
            </p>
          )}
        </div>
      )}

      {trade.state === "failed" && trade.refunded_to === "wallet" && (
        <div className="space-y-2">
          <p className="text-[14px]">
            {t(trade.reason_code === "try_later" ? "tryLater" : "refunded")}
          </p>
          <Link
            href={pathFor(locale, "/account/wallet")}
            className="text-primary inline-flex items-center gap-1.5 text-[13px] font-semibold"
          >
            <Wallet className="h-4 w-4" aria-hidden />
            {t("toWallet")}
          </Link>
        </div>
      )}

      {trade.state === "failed" && trade.refunded_to === "card" && (
        <p className="text-[14px]">{t("refundedCard")}</p>
      )}

      {trade.state === "failed" && trade.refunded_to === null && (
        <div className="space-y-2">
          <p className="text-[14px]">{t("support")}</p>
          <a
            href={SUPPORT_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary text-[13px] font-semibold"
          >
            {t("contactSupport")}
          </a>
        </div>
      )}
    </section>
  );
}
