"use client";

import { ExternalLink, TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import { toString as qrSvg } from "qrcode";
import { useEffect, useState } from "react";

import type { UsdtDeposit } from "@/lib/types";

import { CopyButton } from "@/components/CopyButton";
import { formatClock, secondsLeft } from "@/lib/p2p";
import { trustWalletLink } from "@/lib/usdt";

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
    <span className="flex h-40 w-40 shrink-0 items-center justify-center rounded-lg bg-white p-2">
      {/* eslint-disable-next-line @next/next/no-img-element -- a data: URL, nothing to optimise */}
      {src !== null && <img src={src} alt={alt} width={144} height={144} className="h-36 w-36" />}
    </span>
  );
}

/** The exact amount, the network, the address and the clock — everything to make the transfer. */
export function UsdtDetails({ deposit, nowMs, busy, error, onCancel }: UsdtDetailsProps) {
  const t = useTranslations("merchant.topUpUsdt");
  const left = secondsLeft(deposit.expires_at, nowMs);
  const address = deposit.address ?? "";

  return (
    <section className="border-border bg-card mt-5 max-w-md rounded-xl border">
      <div className="p-6">
        <p className="text-tx-dim text-xs">{t("sendExactly")}</p>
        <p className="mt-1 flex flex-wrap items-center gap-3">
          <span className="text-primary-ink font-mono text-3xl font-extrabold tabular-nums">
            {/* As a wallet takes it: a point, no grouping — "1 000,50" pasted
                by eye into a send form is the wrong number. */}
            {deposit.amount} USDT
          </span>
          <CopyButton value={deposit.amount} label={t("copy")} done={t("copied")} />
        </p>
        <p className="text-tx-mute mt-1.5 text-[13px] leading-relaxed">{t("exchangeFee")}</p>

        <p className="text-tx-dim mt-5 text-xs">{t("network")}</p>
        <p className="mt-0.5 text-sm font-semibold">{t("networkName")}</p>
        <p className="mt-2 flex gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-[13px] leading-relaxed">
          <TriangleAlert aria-hidden size={16} className="mt-0.5 shrink-0 text-amber-500" />
          <span>{t("networkWarning")}</span>
        </p>

        {address !== "" && (
          <>
            <p className="text-tx-dim mt-5 text-xs">{t("address")}</p>
            <p className="mt-1 flex items-start gap-3">
              <span className="min-w-0 flex-1 break-all font-mono text-sm font-semibold">
                {address}
              </span>
              <CopyButton value={address} label={t("copy")} done={t("copied")} />
            </p>

            <a
              href={trustWalletLink(address, deposit.amount)}
              target="_blank"
              rel="noopener noreferrer"
              className="bg-primary text-primary-foreground rounded-btn mt-5 inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold"
            >
              {t("openWallet")}
              <ExternalLink aria-hidden size={14} />
            </a>
            <p className="text-tx-mute mt-1.5 text-xs">{t("openWalletHint")}</p>

            <div className="mt-5 flex flex-col items-start gap-2">
              <AddressQr address={address} alt={t("qrAlt")} />
              <p className="text-tx-mute text-xs">{t("qrHint")}</p>
            </div>
          </>
        )}

        {error !== null && (
          <p role="alert" className="mt-4 text-sm text-red-500">
            {error}
          </p>
        )}
      </div>

      <div className="border-border bg-card sticky bottom-[calc(3.5rem+env(safe-area-inset-bottom))] z-30 flex items-center gap-3 rounded-b-xl border-t px-6 py-3 md:bottom-0">
        <span aria-hidden className="bg-primary h-2 w-2 shrink-0 animate-pulse rounded-full" />
        <p className="text-tx-mute min-w-0 flex-1 text-[13px] leading-snug">
          {t("waiting")}
          <span className="text-foreground block font-mono tabular-nums">
            {t("timeLeft", { time: formatClock(left).padStart(5, "0") })}
          </span>
        </p>
        <button
          type="button"
          disabled={busy}
          onClick={onCancel}
          className="border-border rounded-btn shrink-0 border px-4 py-2 text-sm font-semibold disabled:opacity-50"
        >
          {t("cancel")}
        </button>
      </div>
    </section>
  );
}
