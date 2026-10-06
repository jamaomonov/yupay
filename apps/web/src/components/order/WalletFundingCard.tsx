"use client";

import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock, Loader2, XCircle, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect } from "react";

import { OrderPayNow } from "./OrderPayNow";

import type { OrderOut } from "@/lib/orders-types";

import { buttonStyles } from "@/lib/button";
import { formatUzs, pathFor } from "@/lib/seo";

const FAILED = new Set(["failed", "cancelled", "expired", "refunded"]);

type Phase = "waiting" | "crediting" | "credited" | "failed";

const PHASE: Record<Phase, { Icon: LucideIcon; tile: string; spin: boolean }> = {
  waiting: { Icon: Clock, tile: "bg-gold/12 text-gold ring-gold/25", spin: false },
  crediting: { Icon: Loader2, tile: "bg-blue/12 text-blue ring-blue/25", spin: true },
  credited: { Icon: CheckCircle2, tile: "bg-primary/12 text-primary ring-primary/25", spin: false },
  failed: { Icon: XCircle, tile: "bg-[#FF6B6B]/12 text-[#FF6B6B] ring-[#FF6B6B]/25", spin: false },
};

function phaseFor(status: string): Phase {
  if (status === "delivered") return "credited";
  if (FAILED.has(status)) return "failed";
  if (status === "pending_payment") return "waiting";
  return "crediting";
}

/**
 * The order page for a wallet deposit: one card that says where the money
 * is. A deposit is an order with no lines, so the ordinary layout would
 * render a purchase of nothing — and until 2026-10-06 this card said
 * «Баланс обновится, когда банк подтвердит платёж» whatever the status,
 * which read as "still waiting" on a deposit that had already landed.
 *
 * Four phases: waiting for the payment (the pay-now block — a card transfer's
 * instructions or the acquirer link), crediting (paid, the ledger entry is on
 * its way), credited, and failed. Credited also invalidates the wallet
 * query, so the balance in the header moves at the same moment as the card.
 */
export function WalletFundingCard({ order, locale }: { order: OrderOut; locale: string }) {
  const t = useTranslations("web.orders");
  const qc = useQueryClient();
  const phase = phaseFor(order.status);
  const { Icon, tile, spin } = PHASE[phase];

  useEffect(() => {
    if (phase === "credited") void qc.invalidateQueries({ queryKey: ["wallet"] });
  }, [phase, qc]);

  const walletHref = pathFor(locale, "/account/wallet");

  return (
    <div
      className="border-border bg-surface-1 rounded-2xl border p-6 text-center"
      data-testid="wallet-funding"
      data-phase={phase}
    >
      <span
        className={`mx-auto flex h-14 w-14 items-center justify-center rounded-full ring-1 ${tile}`}
        aria-hidden
      >
        <Icon size={28} strokeWidth={2.4} className={spin ? "animate-spin" : undefined} />
      </span>
      <p className="font-display mt-4 text-xl font-bold tracking-[-0.02em]">
        {t(`walletTopUp.${phase}.title`)}
      </p>
      <p className="font-display mt-2 text-3xl font-bold tabular-nums">
        {formatUzs(locale, Math.round(Number(order.total_charged)))}
      </p>
      <p className="text-tx-mute mt-2 text-sm">{t(`walletTopUp.${phase}.body`)}</p>

      {phase === "waiting" && (
        <div className="mt-5 text-left">
          {/* A deposit is always made signed in, so there is no guest email to send. */}
          <OrderPayNow
            orderId={order.id}
            awaitingPayment
            locale={locale}
            email={undefined}
            auth={undefined}
          />
        </div>
      )}

      <div className="mt-5 flex flex-col items-center gap-2 sm:flex-row sm:justify-center">
        {phase === "failed" && (
          <Link
            href={pathFor(locale, "/account/wallet/top-up")}
            className={buttonStyles({ size: "md" })}
          >
            {t("walletTopUp.retry")}
          </Link>
        )}
        <Link
          href={walletHref}
          className={buttonStyles({
            size: "md",
            variant: phase === "credited" ? "primary" : "ghost",
          })}
        >
          {t("walletTopUpCta")}
        </Link>
      </div>
    </div>
  );
}
