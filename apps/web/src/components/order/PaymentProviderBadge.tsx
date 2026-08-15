"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";

import { paymentProviderDisplay } from "@/lib/payment-providers";

export function PaymentProviderBadge({ provider }: { provider: string | null }) {
  const t = useTranslations("web.orders");
  const display = paymentProviderDisplay(provider);
  if (!display) return null;
  const label = display.nameKey ? t(display.nameKey) : (display.name ?? "");
  return (
    <span className="border-border-2 bg-muted text-foreground rounded-btn inline-flex items-center gap-1.5 border px-2 py-1 text-[13px] font-medium">
      {display.logo ? (
        // The logo IS the name — every acquirer's asset is a wordmark, so
        // pairing it with the text spelled "Click" twice. Scaled by height with
        // the width left to the intrinsic ratio: these assets run from 3.9:1 to
        // 2.5:1, and the old fixed 16x16 box squashed the wordmark into an
        // illegible smudge. `alt` keeps the name available to screen readers,
        // which is the only reason dropping the visible text is safe.
        <Image
          src={display.logo}
          alt={label}
          title={label}
          width={display.logoWidth ?? 16}
          height={display.logoHeight ?? 16}
          style={{ width: "auto", height: 16 }}
          className="object-contain"
        />
      ) : (
        // No asset (wallet, Octo, an unrecognised slug) — the text is all there
        // is, so it has to stay or the badge renders empty.
        <span>{label}</span>
      )}
    </span>
  );
}
