import { Check } from "lucide-react";

import type { GiftPackage } from "@/lib/gifts";

import { formatMoney } from "@/lib/currency";
import { useT } from "@/lib/i18n";

/** `unavailable` is the caller's already-translated `gifts.priceUnavailable`
 *  string — this stays a plain function (not a component), so it can't call
 *  `useT()` itself. */
export function priceLabel(
  price: { price_usd: string; price_uzs: string | null } | null,
  unavailable: string,
): string {
  if (!price) return unavailable;
  return price.price_uzs != null
    ? formatMoney(Math.round(Number(price.price_uzs)), "UZS")
    : formatMoney(Number(price.price_usd), "USD");
}

/**
 * Edition (package) picker row — one selectable card per package, with its
 * price at the currently selected zone and a discount badge when the
 * package carries one.
 *
 * Extracted out of `GiftGame.tsx` (2026-09-03 review) purely to keep that
 * file near the repo's TS file-length budget — no behaviour change.
 */
export function PackageOption({
  pkg,
  price,
  active,
  onSelect,
}: {
  pkg: GiftPackage;
  price: { price_usd: string; price_uzs: string | null } | null;
  active: boolean;
  onSelect: () => void;
}) {
  const { t } = useT();
  const discount =
    pkg.discount_percent != null && pkg.discount_percent > 0 ? pkg.discount_percent : null;
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onSelect}
      className="relative rounded-2xl p-3.5 text-left transition-all duration-150"
      style={{
        background: active ? "hsl(var(--surface-3))" : "hsl(var(--surface-2))",
        border: active ? "1.5px solid hsl(var(--primary) / 0.8)" : "1px solid hsl(var(--border))",
      }}
    >
      {active && (
        <div
          className="absolute right-2.5 top-2.5 flex h-5 w-5 items-center justify-center rounded-full"
          style={{ background: "hsl(var(--primary))" }}
        >
          <Check size={11} strokeWidth={3} className="text-black" />
        </div>
      )}
      <div className="flex items-center justify-between gap-3 pr-6">
        <span className="text-sm font-bold text-white">{pkg.name}</span>
        <span className="font-mono text-sm font-bold tabular-nums text-white">
          {priceLabel(price, t("gifts.priceUnavailable"))}
        </span>
      </div>
      {discount !== null && (
        <span className="text-primary mt-1 inline-block text-[11px] font-bold">-{discount}%</span>
      )}
    </button>
  );
}
