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
        <Image
          src={display.logo}
          alt={label}
          width={16}
          height={16}
          className="h-4 w-4 object-contain"
        />
      ) : null}
      <span>{label}</span>
    </span>
  );
}
