"use client";

import { ExternalLink, TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import { toString as qrSvg } from "qrcode";
import { useEffect, useState } from "react";

import type { UsdtDeposit } from "@/lib/types";

import { CopyRow } from "@/components/CopyRow";
import { CryptoLogo } from "@/components/CryptoLogo";
import { formatClock, secondsLeft } from "@/lib/p2p";
import { groupUsdt, networkLabel, trustWalletLink, USDT_NETWORKS } from "@/lib/usdt";

interface UsdtDetailsProps {
  deposit: UsdtDeposit;
  nowMs: number;
  locale: string;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
}

interface AddressQrProps {
  address: string;
  alt: string;
}

/**
 * The address as a QR code, drawn here as SVG and shown through a `data:` URL
 * (the reseller CSP allows `img-src data:`) — no request leaves the page.
 */
function AddressQr({ address, alt }: AddressQrProps) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void qrSvg(address, { type: "svg", margin: 1, errorCorrectionLevel: "M" }).then(
      (svg) => {
        if (live) setSrc(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`);
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [address]);
  return (
    <span className="flex h-40 w-40 shrink-0 items-center justify-center rounded-lg bg-white p-2 lg:h-52 lg:w-52">
      {src !== null && (
        // eslint-disable-next-line @next/next/no-img-element -- a data: URL, nothing to optimise
        <img src={src} alt={alt} width={192} height={192} className="h-36 w-36 lg:h-48 lg:w-48" />
      )}
    </span>
  );
}

interface StatusBarProps {
  left: number;
}

/**
 * Pinned to the bottom of the card while it scrolls — above the phone's bottom
 * nav (3.5rem + safe area), at the very bottom from `md`, where that nav hides.
 */
function StatusBar({ left }: StatusBarProps) {
  const t = useTranslations("merchant.topUpUsdt");
  const time = formatClock(left).padStart(5, "0");
  return (
    <div className="border-border bg-card sticky bottom-[calc(3.5rem+env(safe-area-inset-bottom))] z-30 flex items-center gap-3 rounded-b-xl border-t px-4 py-3 sm:px-6 md:bottom-0">
      <span aria-hidden className="bg-primary h-2.5 w-2.5 shrink-0 animate-pulse rounded-full" />
      <p className="min-w-0 flex-1 leading-snug">
        <span className="block text-sm font-semibold">{t("waiting")}</span>
        <span className="text-tx-mute block text-xs">{t("waitingHint")}</span>
      </p>
      <span
        role="timer"
        aria-label={t("timeLeft", { time })}
        translate="no"
        className="bg-primary/15 text-primary-ink shrink-0 rounded-full px-3 py-1 font-mono text-base font-bold tabular-nums"
      >
        {time}
      </span>
    </div>
  );
}

/** The exact amount, the network, the address and the clock — everything to make the transfer. */
export function UsdtDetails({ deposit, nowMs, busy, error, onCancel }: UsdtDetailsProps) {
  const t = useTranslations("merchant.topUpUsdt");
  const left = secondsLeft(deposit.expires_at, nowMs);
  const address = deposit.address ?? "";
  const label = networkLabel(deposit.network);

  return (
    <div className="mt-5 max-w-md lg:max-w-[880px]">
      <section className="border-border bg-card rounded-xl border">
        <div className="p-6 lg:grid lg:grid-cols-[minmax(0,1fr)_13rem] lg:gap-10">
          <div className="min-w-0">
            <p className="text-tx-dim text-xs">{t("sendExactly")}</p>
            {/* Grouped for the eye, a point for the wallet: "1 000,50" pasted
                by eye into a send form is the wrong number. Copies raw. */}
            <CopyRow
              value={deposit.amount}
              label={t("copy")}
              done={t("copied")}
              className="text-primary-ink font-mono text-2xl font-extrabold tabular-nums sm:text-3xl"
            >
              {groupUsdt(deposit.amount)}{" "}
              <span className="text-tx-mute text-base font-semibold">USDT</span>
            </CopyRow>
            <p className="text-tx-mute mt-1.5 text-[13px] leading-relaxed">{t("exchangeFee")}</p>

            <p className="text-tx-dim mt-5 text-xs">{t("network")}</p>
            <p className="mt-1 flex items-center gap-2 text-sm font-semibold">
              <CryptoLogo src={USDT_NETWORKS[deposit.network].logo} size={20} />
              {label}
            </p>
            <p className="mt-2 flex gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-[13px] leading-relaxed">
              <TriangleAlert aria-hidden size={16} className="mt-0.5 shrink-0 text-amber-500" />
              <span>{t("networkWarning", { label })}</span>
            </p>

            {address !== "" && (
              <>
                <p className="text-tx-dim mt-5 text-xs">{t("address")}</p>
                <CopyRow
                  value={address}
                  label={t("copy")}
                  done={t("copied")}
                  className="break-all font-mono text-sm font-semibold"
                >
                  {address}
                </CopyRow>
              </>
            )}
          </div>

          {address !== "" && (
            <div className="mt-5 flex flex-col items-start gap-2 lg:mt-0 lg:items-center lg:text-center">
              <div className="order-1 lg:order-2 lg:mt-2 lg:w-full">
                <a
                  href={trustWalletLink(deposit.network, address, deposit.amount)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="bg-primary text-primary-foreground rounded-btn inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-semibold lg:w-full"
                >
                  {t("openWallet")}
                  <ExternalLink aria-hidden size={14} />
                </a>
                <p className="text-tx-mute mt-1.5 text-xs">{t("openWalletHint")}</p>
              </div>
              <div className="order-2 mt-3 lg:order-1 lg:mt-0">
                <AddressQr address={address} alt={t("qrAlt")} />
              </div>
              <p className="text-tx-mute order-3 text-xs">{t("qrHint")}</p>
            </div>
          )}

          {error !== null && (
            <p role="alert" className="mt-4 text-sm text-red-500 lg:col-span-2">
              {error}
            </p>
          )}
        </div>

        <StatusBar left={left} />
      </section>
      <button
        type="button"
        disabled={busy}
        onClick={onCancel}
        className="text-tx-mute hover:text-foreground mt-3 text-sm underline underline-offset-4 disabled:opacity-50"
      >
        {t("cancel")}
      </button>
    </div>
  );
}
