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
    <span className="inline-flex items-center gap-1.5">
      {display.logo ? (
        <Image
          src={display.logo}
          alt={label}
          width={20}
          height={20}
          className="h-5 w-5 object-contain"
        />
      ) : null}
      <span>{label}</span>
    </span>
  );
}
