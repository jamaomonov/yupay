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
      {display.logo && (
        // A small square brand mark to the left of the text label — not a
        // replacement for it (unlike the old wordmark assets, these are icons).
        <span className="flex h-4 w-4 shrink-0 items-center justify-center overflow-hidden rounded-sm bg-white">
          <Image
            src={display.logo}
            alt=""
            width={display.logoWidth ?? 160}
            height={display.logoHeight ?? 160}
            className="h-full w-full object-contain"
          />
        </span>
      )}
      <span>{label}</span>
    </span>
  );
}
