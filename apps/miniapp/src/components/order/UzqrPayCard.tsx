import { Download } from "lucide-react";
import { toDataURL } from "qrcode";
import { useEffect, useState } from "react";

import type { UzqrPaymentDetails } from "@/lib/orders";

import { formatMoney } from "@/lib/currency";
import { useT } from "@/lib/i18n";

/**
 * The QR to pay a pending `uzqr` payment (ADR-0106), with the amount and the
 * time left. The mini-app twin of the web's `UzqrPayCard`.
 *
 * Drawn here from the EMVCo text UzQR issued, as a PNG `data:` URL (the CSP
 * allows `img-src data:`), so nothing about the payment leaves the page. A
 * phone cannot scan its own screen: the picture can be saved and opened from
 * the gallery in the bank app's scanner. The scheduler books the payment; the
 * order screen's own polling moves it to paid.
 */
export function UzqrPayCard({
  details,
  nowMs,
}: {
  details: UzqrPaymentDetails;
  /** Injected by tests; the component ticks itself otherwise. */
  nowMs?: number;
}) {
  const { t } = useT();
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
    // PNG, not SVG: a bank app's scanner reads the gallery, raster images only.
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
        className="mx-4 rounded-2xl p-4 text-center text-sm text-white/70"
        style={{ background: "hsl(var(--surface-2))", border: "1px solid hsl(var(--border))" }}
      >
        {t("success.uzqr.expired")}
      </div>
    );
  }

  return (
    <section
      aria-label={t("success.uzqr.title")}
      className="mx-4 space-y-4 rounded-2xl p-4"
      style={{
        background: "hsl(var(--surface-2))",
        border: "1.5px solid hsl(var(--primary) / 0.6)",
      }}
    >
      <div>
        <h3 className="text-base font-bold text-white">{t("success.uzqr.title")}</h3>
        <p className="mt-1 text-[13px] leading-relaxed text-white/60">{t("success.uzqr.note")}</p>
      </div>

      <div className="flex flex-col items-center gap-3">
        <span className="flex h-56 w-56 items-center justify-center rounded-xl bg-white p-2">
          {src !== null && (
            <img
              src={src}
              alt={t("success.uzqr.title")}
              width={208}
              height={208}
              className="h-52 w-52"
              data-testid="uzqr-code"
            />
          )}
        </span>
        <span className="text-xl font-extrabold tabular-nums text-white">
          {formatMoney(Number(details.amount), "UZS")}
        </span>
        {src !== null && (
          <a
            href={src}
            download={`yupay-qr-${details.invoice_id}.png`}
            className="flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-semibold text-white"
            style={{ background: "hsl(var(--surface-3))", border: "1px solid hsl(var(--border))" }}
          >
            <Download size={14} aria-hidden />
            {t("success.uzqr.save")}
          </a>
        )}
        <p className="text-center text-[11px] leading-relaxed text-white/40">
          {t("success.uzqr.phone")}
        </p>
      </div>

      <div className="flex items-center justify-between">
        <span className="text-[11px] text-white/40">{t("success.uzqr.left")}</span>
        <span className="font-mono text-base tabular-nums text-white" data-testid="uzqr-countdown">
          {mm}:{ss}
        </span>
      </div>
      <p className="text-[11px] text-white/40">{t("success.uzqr.waiting")}</p>
    </section>
  );
}
