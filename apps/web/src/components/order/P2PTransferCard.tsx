"use client";

import { Check, Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import type { P2PPaymentDetails } from "@/lib/orders-types";

import { formatUzs } from "@/lib/seo";

/**
 * Where to send a card transfer for a pending `p2p` payment (ADR-0097): the
 * owner's card and holder, the exact amount, and the time left on the hold.
 *
 * The amount is the one the server reserved, which may be a few soʻm above
 * the order total when the exact figure was held by someone else — so it is
 * printed from the payment, never recomputed from the order, and the copy
 * says «ровно». Both the card number and the amount copy with one tap: a
 * transfer is typed into a banking app, and a mistyped digit sends the money
 * to a stranger.
 */
export function P2PTransferCard({
  details,
  locale,
  nowMs,
}: {
  details: P2PPaymentDetails;
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

  const left = Math.max(0, Math.floor((Date.parse(details.expires_at) - tick) / 1000));
  const mm = String(Math.floor(left / 60)).padStart(2, "0");
  const ss = String(left % 60).padStart(2, "0");

  if (left === 0) {
    return (
      <div
        role="status"
        className="border-border bg-surface-1 rounded-xl border p-4 text-center text-sm"
      >
        {t("p2pExpired")}
      </div>
    );
  }

  return (
    <section
      aria-label={t("p2pTitle")}
      className="border-primary/40 bg-surface-1 space-y-4 rounded-xl border p-5"
    >
      <div>
        <h3 className="font-display text-lg font-bold tracking-[-0.02em]">{t("p2pTitle")}</h3>
        <p className="text-tx-mute mt-1 text-sm leading-relaxed">{t("p2pNote")}</p>
      </div>

      <Field label={`${t("p2pCard")} · ${details.network.toUpperCase()}`} value={details.pan}>
        <span className="font-mono text-xl tracking-[0.08em]">{details.pan}</span>
      </Field>

      <div>
        <p className="text-tx-dim text-xs">{t("p2pHolder")}</p>
        <p className="mt-0.5 font-medium">{details.holder_name}</p>
      </div>

      <Field label={`${t("p2pAmount")} · ${t("p2pExact")}`} value={String(details.amount_uzs)}>
        <span className="font-display text-2xl font-bold tabular-nums">
          {formatUzs(locale, details.amount_uzs)}
        </span>
      </Field>

      <div className="flex items-center justify-between">
        <span className="text-tx-dim text-xs">{t("p2pLeft")}</span>
        <span
          className="font-mono text-lg tabular-nums"
          aria-live="off"
          data-testid="p2p-countdown"
        >
          {mm}:{ss}
        </span>
      </div>
      <p className="text-tx-dim text-xs">{t("p2pWaiting")}</p>
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
  const t = useTranslations("web.orders");
  const [copied, setCopied] = useState(false);
  return (
    <div>
      <p className="text-tx-dim text-xs">{label}</p>
      <div className="mt-1 flex items-center justify-between gap-3">
        <div className="min-w-0 break-all">{children}</div>
        <button
          type="button"
          aria-label={`${t("p2pCopy")}: ${label}`}
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
          className="border-border hover:border-border-2 rounded-btn flex shrink-0 items-center gap-1.5 border px-3 py-2 text-xs font-semibold"
        >
          {copied ? <Check size={14} /> : <Copy size={14} />}
          {copied ? t("p2pCopied") : t("p2pCopy")}
        </button>
      </div>
    </div>
  );
}
