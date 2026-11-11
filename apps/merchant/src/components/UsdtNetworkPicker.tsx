"use client";

import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import type { UsdtNetwork } from "@/lib/types";
import type { UsdtFlow } from "@/lib/useUsdtDeposit";

import { formatUsdt, USDT_NETWORKS } from "@/lib/usdt";

/** A letter disc in the chain's colour — drawn inline, no image asset to load. */
const MARK: Readonly<Record<UsdtNetwork, string>> = {
  trc20: "bg-[#eb0029] text-white",
  bep20: "bg-[#f0b90b] text-black",
  erc20: "bg-[#627eea] text-white",
};

interface UsdtNetworkPickerProps {
  flow: UsdtFlow;
  locale: string;
}

/** The second step: which chain the USDT goes over. A tap reserves the amount on it. */
export function UsdtNetworkPicker({ flow, locale }: UsdtNetworkPickerProps) {
  const t = useTranslations("merchant.topUpUsdt");

  return (
    <section className="mt-5 max-w-md">
      <button
        type="button"
        onClick={flow.backToAmount}
        className="text-tx-mute mb-3 text-sm underline-offset-4 hover:underline"
      >
        ← {t("changeAmount")}
      </button>
      <p className="flex items-baseline justify-between gap-3">
        <span className="font-semibold">{t("networkTitle")}</span>
        <span className="text-tx-mute font-mono text-sm tabular-nums">
          {formatUsdt(flow.amount, locale)} USDT
        </span>
      </p>
      <p className="text-tx-mute mt-1 text-sm">{t("networkHint")}</p>
      {flow.networks.map((network) => {
        const spec = USDT_NETWORKS[network];
        return (
          <button
            key={network}
            type="button"
            disabled={flow.busy}
            onClick={() => {
              void flow.pickNetwork(network);
            }}
            className="border-border bg-card hover:border-primary mt-2 flex w-full items-center gap-4 rounded-xl border p-4 text-left transition-colors disabled:opacity-50"
          >
            <span
              aria-hidden
              className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-bold ${MARK[network]}`}
            >
              {spec.name.charAt(0)}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block font-semibold">{spec.name}</span>
              <span className="text-tx-mute block text-sm">
                {spec.standard}
                {spec.costly && <span className="text-tx-dim"> · {t("networkCostly")}</span>}
              </span>
            </span>
            <ChevronRight aria-hidden size={18} className="text-tx-dim shrink-0" />
          </button>
        );
      })}
      {flow.error !== null && (
        <p role="alert" className="mt-3 text-sm text-red-500">
          {flow.error}
        </p>
      )}
    </section>
  );
}
