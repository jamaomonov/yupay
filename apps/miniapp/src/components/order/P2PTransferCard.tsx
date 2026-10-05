import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";

import type { P2PPaymentDetails } from "@/lib/orders";

import { formatMoney } from "@/lib/currency";
import { useT } from "@/lib/i18n";

/**
 * Where to send a card transfer for a pending `p2p` payment (ADR-0097): the
 * owner's card and holder, the exact amount, and the time left on the hold.
 * The mini-app twin of the web's `P2PTransferCard`.
 *
 * The amount is the one the server reserved, which may sit a few soʻm above
 * the order total when the exact figure was held by someone else — printed
 * from the payment, never recomputed, and the copy says «ровно». Card number
 * and amount copy with one tap: a transfer is typed into a banking app, and
 * a mistyped digit sends the money to a stranger.
 */
export function P2PTransferCard({
  details,
  nowMs,
}: {
  details: P2PPaymentDetails;
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
        {t("success.p2p.expired")}
      </div>
    );
  }

  return (
    <section
      aria-label={t("success.p2p.title")}
      className="mx-4 space-y-4 rounded-2xl p-4"
      style={{
        background: "hsl(var(--surface-2))",
        border: "1.5px solid hsl(var(--primary) / 0.6)",
      }}
    >
      <div>
        <h3 className="text-base font-bold text-white">{t("success.p2p.title")}</h3>
        <p className="mt-1 text-[13px] leading-relaxed text-white/60">{t("success.p2p.note")}</p>
      </div>

      <Field
        label={`${t("success.p2p.card")} · ${details.network.toUpperCase()}`}
        value={details.pan}
      >
        <span className="whitespace-nowrap font-mono text-[15px] tracking-[0.05em] text-white">
          {details.pan}
        </span>
      </Field>

      <div>
        <p className="text-[11px] text-white/40">{t("success.p2p.holder")}</p>
        <p className="mt-0.5 text-sm font-medium text-white">{details.holder_name}</p>
      </div>

      <Field
        label={`${t("success.p2p.amount")} · ${t("success.p2p.exact")}`}
        value={String(details.amount_uzs)}
      >
        <span className="text-xl font-extrabold tabular-nums text-white">
          {formatMoney(details.amount_uzs, "UZS")}
        </span>
      </Field>

      <div className="flex items-center justify-between">
        <span className="text-[11px] text-white/40">{t("success.p2p.left")}</span>
        <span className="font-mono text-base tabular-nums text-white" data-testid="p2p-countdown">
          {mm}:{ss}
        </span>
      </div>
      <p className="text-[11px] text-white/40">{t("success.p2p.waiting")}</p>
    </section>
  );
}

/** A value with a copy button; `value` is the raw text that goes to the clipboard. */
function Field({
  label,
  value,
  children,
}: {
  label: string;
  value: string;
  children: React.ReactNode;
}) {
  const { t } = useT();
  const [copied, setCopied] = useState(false);
  return (
    <div>
      <p className="text-[11px] text-white/40">{label}</p>
      <div className="mt-1 flex items-center justify-between gap-3">
        <div className="min-w-0">{children}</div>
        <button
          type="button"
          aria-label={`${t("success.p2p.copy")}: ${label}`}
          onClick={() => {
            void navigator.clipboard
              .writeText(value.replace(/\s+/g, ""))
              .then(() => {
                setCopied(true);
                setTimeout(() => {
                  setCopied(false);
                }, 1500);
              })
              .catch(() => undefined);
          }}
          className="flex shrink-0 items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-semibold text-white"
          style={{ background: "hsl(var(--surface-3))", border: "1px solid hsl(var(--border))" }}
        >
          {copied ? <Check size={14} /> : <Copy size={14} />}
          {copied ? t("success.p2p.copied") : t("success.p2p.copy")}
        </button>
      </div>
    </div>
  );
}
