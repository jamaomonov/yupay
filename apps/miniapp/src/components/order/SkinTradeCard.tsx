import { CheckCircle2, ExternalLink, Loader2, ShieldCheck, Wallet } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "wouter";

import type { SkinTradeOut } from "@/lib/orders";

import { useT } from "@/lib/i18n";
import { skinTradeView } from "@/lib/skin-trade";
import { openExternalLink } from "@/lib/telegram";

/** Re-render once a minute so the accept-by line stays true. */
function useMinuteTick(active: boolean): void {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => {
      setTick((n) => n + 1);
    }, 60_000);
    return () => {
      clearInterval(id);
    };
  }, [active]);
}

/**
 * A CS2 skin line's Steam trade on the order page: buying → the offer (open
 * it in Steam, from whom, accept by when) → received, protected by Steam
 * until a date; or the money back on the balance — or, for a purchase we
 * could not confirm, support (the status card above carries the link), with
 * no refund promised. Mirrors the web's `SkinTradeCard`.
 */
export function SkinTradeCard({ trade }: { trade: SkinTradeOut }) {
  const { t, locale } = useT();
  const view = skinTradeView(trade);
  useMinuteTick(view.kind === "offer");
  const time = (iso: string) =>
    new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
  const date = (iso: string) =>
    new Intl.DateTimeFormat(locale, { day: "numeric", month: "long" }).format(new Date(iso));

  return (
    <div className="mt-3 space-y-2 rounded-xl p-3" style={{ background: "hsl(var(--surface-2))" }}>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-white/50">
        {t("cs2.trade.title")}
      </p>

      {view.kind === "buying" && (
        <p className="flex items-center gap-2 text-[13px] text-white">
          <Loader2 className="text-primary h-4 w-4 shrink-0 animate-spin" aria-hidden="true" />
          {t("cs2.trade.buying")}
        </p>
      )}

      {view.kind === "offer" && (
        <div className="space-y-2">
          <p className="text-[14px] font-semibold text-white">{t("cs2.trade.offer_sent")}</p>
          {view.seller && (
            <p className="text-[12px] text-white/50">
              {t("cs2.trade.seller")}{" "}
              <span className="font-semibold text-white">{view.seller}</span>
            </p>
          )}
          {view.offerUrl && (
            <button
              type="button"
              onClick={() => {
                if (view.offerUrl) openExternalLink(view.offerUrl);
              }}
              className="bg-primary flex w-full items-center justify-center gap-2 rounded-xl py-3 text-[14px] font-bold text-black"
            >
              {t("cs2.trade.openOffer")}
              <ExternalLink className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
          {view.acceptBy && (
            <p className="text-[12px] text-white/50">
              {t("cs2.trade.acceptBy", { time: time(view.acceptBy) })}
            </p>
          )}
        </div>
      )}

      {view.kind === "received" && (
        <div className="space-y-1">
          <p className="flex items-center gap-2 text-[14px] font-semibold text-emerald-400">
            <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
            {t("cs2.trade.accepted")}
          </p>
          {view.protectedUntil && (
            <p className="flex items-center gap-1.5 text-[12px] text-white/50">
              <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
              {t("cs2.trade.protectedUntil", { date: date(view.protectedUntil) })}
            </p>
          )}
        </div>
      )}

      {view.kind === "refunded" && (
        <div className="space-y-2">
          <p className="text-[13px] text-white">{t("cs2.trade.refunded")}</p>
          <Link
            href="/wallet"
            className="text-primary inline-flex min-h-[32px] items-center gap-1.5 text-[13px] font-semibold"
          >
            <Wallet className="h-4 w-4" aria-hidden="true" />
            {t("cs2.trade.toWallet")}
          </Link>
        </div>
      )}

      {view.kind === "support" && (
        <p className="text-[13px] text-white">{t("cs2.trade.support")}</p>
      )}
    </div>
  );
}
