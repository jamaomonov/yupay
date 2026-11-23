"use client";

import { Download } from "lucide-react";
import { useTranslations } from "next-intl";
import { toDataURL } from "qrcode";
import { useEffect, useState } from "react";

import type { UzqrPaymentDetails } from "@/lib/orders-types";

import { formatUzs } from "@/lib/seo";

/**
 * The QR to pay a pending `uzqr` payment (ADR-0106): drawn here from the
 * EMVCo text UzQR issued for this invoice, with the amount and the time left.
 *
 * Drawn as a PNG `data:` URL (the storefront CSP allows `img-src data:`), so
 * nothing about the payment leaves the page. A phone cannot scan its own
 * screen, so the same image can be saved and opened from the gallery in the
 * bank app's scanner. The order page's own polling moves
 * it to paid once the scheduler books the payment.
 */
export function UzqrPayCard({
  details,
  locale,
  nowMs,
}: {
  details: UzqrPaymentDetails;
  locale: string;
  /** Injected by tests; the component ticks itself otherwise. */
  nowMs?: number;
}) {
  const t = useTranslations("web.orders");
  const [tick, setTick] = useState(() => nowMs ?? Date.now());
  useEffect(() => {
    if (nowMs !== undefined) return;
    const id = setInterval(() => {
      setTick(Date.now());
    }, 1000);
    return () => {
      clearInterval(id);
    };
  }, [nowMs]);

  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    // PNG, not SVG: the picture is also what a phone saves, and a bank app's
    // scanner reads the gallery, which holds raster images only.
    void toDataURL(details.qr_text, { margin: 2, width: 512, errorCorrectionLevel: "M" }).then(
      (url) => {
        if (live) setSrc(url);
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [details.qr_text]);

  const left = Math.max(0, Math.floor((Date.parse(details.expires_at) - tick) / 1000));
  const mm = String(Math.floor(left / 60)).padStart(2, "0");
  const ss = String(left % 60).padStart(2, "0");

  if (left === 0) {
    return (
      <div
        role="status"
        className="border-border bg-surface-1 rounded-xl border p-4 text-center text-sm"
      >
        {t("uzqrExpired")}
      </div>
    );
  }

  return (
    <section
      aria-label={t("uzqrTitle")}
      className="border-primary/40 bg-surface-1 space-y-4 rounded-xl border p-5"
    >
      <div>
        <h3 className="font-display text-lg font-bold tracking-[-0.02em]">{t("uzqrTitle")}</h3>
        <p className="text-tx-mute mt-1 text-sm leading-relaxed">{t("uzqrNote")}</p>
      </div>

      <div className="flex flex-col items-center gap-3">
        <span className="flex h-60 w-60 items-center justify-center rounded-xl bg-white p-2">
          {src !== null && (
            // eslint-disable-next-line @next/next/no-img-element -- a data: URL, nothing to optimise
            <img
              src={src}
              alt={t("uzqrTitle")}
              width={224}
              height={224}
              className="h-56 w-56"
              data-testid="uzqr-code"
            />
          )}
        </span>
        <span className="font-display text-2xl font-bold tabular-nums">
          {formatUzs(locale, Math.round(Number(details.amount)))}
        </span>
        {src !== null && (
          <a
            href={src}
            download={`yupay-qr-${details.invoice_id}.png`}
            className="border-border hover:border-border-2 rounded-btn flex min-h-11 items-center gap-2 border px-4 py-2 text-sm font-semibold"
          >
            <Download size={16} aria-hidden />
            {t("uzqrSave")}
          </a>
        )}
        <p className="text-tx-dim text-center text-xs leading-relaxed">{t("uzqrPhone")}</p>
      </div>

      <div className="flex items-center justify-between">
        <span className="text-tx-dim text-xs">{t("uzqrLeft")}</span>
        <span
          className="font-mono text-lg tabular-nums"
          aria-live="off"
          data-testid="uzqr-countdown"
        >
          {mm}:{ss}
        </span>
      </div>
      <p className="text-tx-dim text-xs">{t("uzqrWaiting")}</p>
    </section>
  );
}
