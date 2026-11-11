"use client";

import { CircleCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { type ReactNode, useRef } from "react";

import type { UsdtDeposit } from "@/lib/types";

import { useCabinet } from "@/components/CabinetContext";
import { CryptoLogo } from "@/components/CryptoLogo";
import { formatMoment } from "@/lib/datetime";
import { dollars, toCents } from "@/lib/money";
import { explorerTxLink, formatUsdt, networkLabel, shortHash, USDT_NETWORKS } from "@/lib/usdt";

interface UsdtPaidProps {
  deposit: UsdtDeposit;
  locale: string;
  /** "Top up again". */
  again: ReactNode;
}

/** The outcome: what arrived, over which chain, and the balance it made. */
export function UsdtPaid({ deposit, locale, again }: UsdtPaidProps) {
  const t = useTranslations("merchant.topUpUsdt");
  const { profile } = useCabinet();
  // The profile on screen when the payment landed is the one from before it.
  // The flow re-reads it on "paid"; a new object is that re-read, so only then
  // is its balance the one this top-up made. Nothing is computed by hand.
  const before = useRef(profile);
  const balance = profile !== null && profile !== before.current ? profile.balance_usd : null;

  return (
    <section className="border-border bg-card mt-5 max-w-md rounded-xl border p-6">
      <CircleCheck aria-hidden size={36} className="text-emerald-500" />
      <p className="mt-3 text-lg font-semibold">
        {t("paid", { amount: formatUsdt(deposit.amount, locale) })}
      </p>
      <p className="text-tx-mute text-sm">{t("credited")}</p>
      <dl className="mt-4 grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-1.5 text-sm">
        {balance !== null && (
          <>
            <dt className="text-tx-dim">{t("balance")}</dt>
            <dd className="font-mono font-semibold tabular-nums">{dollars(toCents(balance))}</dd>
          </>
        )}
        <dt className="text-tx-dim">{t("network")}</dt>
        <dd className="flex items-center gap-2">
          <CryptoLogo src={USDT_NETWORKS[deposit.network].logo} size={18} />
          {networkLabel(deposit.network)}
        </dd>
        {deposit.closed_at !== null && (
          <>
            <dt className="text-tx-dim">{t("paidAt")}</dt>
            <dd>{formatMoment(deposit.closed_at, locale)}</dd>
          </>
        )}
        {deposit.tx_id !== null && (
          <>
            <dt className="text-tx-dim">{t("tx")}</dt>
            <dd>
              <a
                href={explorerTxLink(deposit.network, deposit.tx_id)}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary-ink font-mono underline-offset-4 hover:underline"
              >
                {shortHash(deposit.tx_id)}
              </a>
            </dd>
          </>
        )}
      </dl>
      {again}
    </section>
  );
}
