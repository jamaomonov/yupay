"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import type { ProviderStatus, ProvidersOut } from "@/lib/payment-providers";

import { WalletMark } from "@/components/icons/WalletMark";
import { apiFetch } from "@/lib/client";
import { methodVisibility, providerStatusMap, selectActiveMethodId } from "@/lib/payment-providers";
import { formatUzs, pathFor } from "@/lib/seo";
import { usePreferBalance } from "@/lib/prefer-balance";
import { getWallet, WALLET_CURRENCY } from "@/lib/wallet";
import { canPayFromBalance, spendableBalance, walletTile } from "@/lib/wallet-balance";

export const WALLET_METHOD_ID = "wallet";

/** The same four UZ rails, in the same order, as the gift and top-up panels. */
const METHODS = [
  { id: "payme", name: "Payme", icon: "/payment/payme-mark.png" },
  { id: "click", name: "Click", icon: "/payment/click-mark.png" },
  { id: "uzum", name: "Uzum", icon: "/payment/uzum-mark.png" },
  { id: "paynet", name: "Paynet", icon: "/payment/paynet-mark.png" },
] as const;

/**
 * Balance tile + acquirer tiles for a skin purchase. Availability and the
 * balance rules come from the shared libraries the gift panel uses
 * (`payment-providers`, `wallet-balance`); reports the chosen provider and
 * whether it can be paid with right now.
 */
export function SkinPaymentPicker({
  locale,
  totalUzs,
  onChange,
}: {
  locale: string;
  /** What the balance must cover; `null` while FX is down. */
  totalUzs: number | null;
  onChange: (state: { provider: string | null; ready: boolean }) => void;
}) {
  const ts = useTranslations("web.store");
  const [status, setStatus] = useState<Map<string, ProviderStatus> | null>(null);
  const [methodId, setMethodId] = useState<string>("payme");

  useEffect(() => {
    let live = true;
    apiFetch<ProvidersOut>("/payments/providers", { anonymous: true })
      .then((data) => {
        if (live) setStatus(providerStatusMap(data));
      })
      .catch(() => undefined); // fails open, as everywhere
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    if (!status) return;
    setMethodId((current) =>
      current === WALLET_METHOD_ID
        ? current
        : (selectActiveMethodId(
            [...METHODS].map((m) => ({ ...m, provider: m.id })),
            current,
            status,
          ) ?? ""),
    );
  }, [status]);

  const wallet = useQuery({ queryKey: ["wallet"], queryFn: getWallet, staleTime: 30_000 });
  const walletVisibility = methodVisibility(WALLET_METHOD_ID, status);
  const tile = walletTile({
    isLoggedIn: true,
    balance: spendableBalance(wallet.data?.balances ?? null, WALLET_CURRENCY),
    total: totalUzs,
    fxDown: totalUzs === null,
    maintenance: walletVisibility === "maintenance",
  });
  const fromBalance = methodId === WALLET_METHOD_ID;
  const ready = fromBalance
    ? canPayFromBalance(tile) && walletVisibility === "active"
    : methodId !== "" && methodVisibility(methodId, status) === "active";
  // A balance that covers the order is the default method until the buyer picks one.
  const markPicked = usePreferBalance(
    canPayFromBalance(tile) && walletVisibility === "active",
    setMethodId,
    status
      ? (selectActiveMethodId(
          [...METHODS].map((m) => ({ ...m, provider: m.id })),
          "",
          status,
        ) ?? "")
      : "payme",
  );

  useEffect(() => {
    onChange({ provider: methodId || null, ready });
    // `onChange` is the parent's setter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [methodId, ready]);

  const balanceLine =
    tile.state === "ready"
      ? formatUzs(locale, Math.round(tile.balance))
      : tile.state === "short"
        ? ts("payFromBalanceShort", { amount: formatUzs(locale, tile.missing) })
        : tile.state === "maintenance"
          ? ts("paymentMaintenance")
          : tile.state === "fxDown"
            ? ts("priceUnavailable")
            : ts("payFromBalanceLoading");

  return (
    <div>
      <p className="text-tx-dim mb-2 text-[11px] font-semibold uppercase tracking-[0.08em]">
        {ts("paymentTitle")}
      </p>
      {walletVisibility !== "hidden" && (
        <button
          type="button"
          aria-pressed={fromBalance}
          disabled={walletVisibility !== "active" || tile.state !== "ready"}
          onClick={() => {
            markPicked();
            setMethodId(WALLET_METHOD_ID);
          }}
          className={`rounded-btn mb-2 flex w-full items-center gap-3 border px-3 py-3 text-left transition disabled:cursor-not-allowed ${
            fromBalance && tile.state === "ready"
              ? "border-primary bg-primary/10"
              : "border-border bg-bg hover:border-border-2"
          }`}
        >
          <span className="bg-muted text-primary flex h-9 w-9 shrink-0 items-center justify-center rounded-md">
            <WalletMark size={18} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[13px] font-semibold">{ts("payFromBalance")}</span>
            <span className="text-tx-dim block text-[12px]">{balanceLine}</span>
          </span>
        </button>
      )}
      {tile.state === "short" && (
        <Link
          href={pathFor(locale, "/account/wallet/top-up")}
          target="_blank"
          rel="noreferrer"
          className="text-primary mb-2 inline-flex items-center gap-1 text-[13px] font-semibold"
        >
          {ts("payFromBalanceTopUp")}
          <ArrowUpRight size={14} />
        </Link>
      )}
      <div className="grid grid-cols-4 gap-2">
        {METHODS.map((m) => {
          const visibility = methodVisibility(m.id, status);
          if (visibility === "hidden") return null;
          const disabled = visibility === "maintenance";
          const active = !disabled && m.id === methodId;
          return (
            <button
              key={m.id}
              type="button"
              aria-label={m.name}
              aria-pressed={active}
              disabled={disabled}
              onClick={() => {
                markPicked();
                setMethodId(m.id);
              }}
              className={`rounded-btn flex items-center justify-center border px-3 py-3 transition disabled:cursor-not-allowed disabled:opacity-60 ${
                active
                  ? "border-primary bg-primary/10"
                  : "border-border bg-bg hover:border-border-2"
              }`}
            >
              <Image src={m.icon} alt="" width={36} height={36} className="h-9 w-9 rounded-md" />
            </button>
          );
        })}
      </div>
    </div>
  );
}
