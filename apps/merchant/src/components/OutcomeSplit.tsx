"use client";

import { useTranslations } from "next-intl";

interface OutcomeSplitProps {
  delivered: number;
  failed: number;
  /** Still moving — paid, fulfilling. Hidden at zero, like the other two. */
  inFlight?: number;
  className?: string;
}

/**
 * «✓ 7 · ✕ 1 · 1 в работе» under an order count, so a reseller tells a busy
 * day from a broken one without opening the list. Colour and a glyph both
 * carry the meaning — the glyph is the fact, the colour a hint about it.
 */
export function OutcomeSplit({ delivered, failed, inFlight = 0, className }: OutcomeSplitProps) {
  const t = useTranslations("merchant.outcome");
  if (delivered + failed + inFlight === 0) return null;
  return (
    <span className={`flex flex-wrap gap-x-2.5 gap-y-0.5 text-xs font-medium ${className ?? ""}`}>
      <span className="text-primary-ink" title={t("deliveredHint")}>
        ✓ {t("delivered", { count: delivered })}
      </span>
      {failed > 0 && (
        <span className="text-danger" title={t("failedHint")}>
          ✕ {t("failed", { count: failed })}
        </span>
      )}
      {inFlight > 0 && <span className="text-tx-dim">{t("inFlight", { count: inFlight })}</span>}
    </span>
  );
}
