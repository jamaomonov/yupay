import { Check, Wallet as WalletIcon } from "lucide-react";

import type { MethodVisibility } from "@/lib/orders";

import { useT } from "@/lib/i18n";
import { formatBalance } from "@/lib/wallet";

/**
 * "Pay from balance" tile — a full-width card rendered above the acquirer
 * grid on checkout. Not one of the acquirer picker's tiles (`TopUp`'s own
 * grid, `PaymentMethodGrid` on the Steam Gifts checkout) because the wallet
 * is our own ledger, not an upstream provider: `WalletGateway` settles it
 * synchronously inside `create_intent` instead of redirecting anywhere.
 *
 * Extracted out of `TopUp.tsx` (2026-09-03, Steam Gifts wallet-pay task) so
 * the gift checkout (`GiftBuyPanel`) can reuse it instead of forking a
 * second copy — no behaviour change for `TopUp` itself.
 */
export function WalletPayOption({
  active,
  enough,
  loading,
  balance,
  shortfall,
  currency,
  visibility,
  onSelect,
  unknownTotal = false,
}: {
  active: boolean;
  enough: boolean;
  loading: boolean;
  balance: number | null;
  shortfall: number;
  currency: string;
  visibility: MethodVisibility;
  onSelect: () => void;
  /** True when there is nothing to weigh the balance against yet — e.g. a
   *  Steam Gifts line whose UZS price is FX-unavailable (`price_uzs ===
   *  null`, see `walletPayState` in `GiftGame.tsx`). Forces the tile into a
   *  disabled "price unavailable" state instead of a shortfall computed
   *  against a guessed total. `TopUp` always has a concrete total, so it
   *  never passes this — the default keeps its rendering unchanged. */
  unknownTotal?: boolean;
}) {
  const { t } = useT();
  if (visibility === "hidden") return null;
  const maintenance = visibility === "maintenance";
  const disabled = maintenance || unknownTotal || (!loading && !enough);
  return (
    <button
      type="button"
      onClick={disabled ? undefined : onSelect}
      disabled={disabled}
      aria-disabled={disabled}
      className="mb-2 flex w-full items-center gap-3 rounded-2xl p-3.5 transition-all duration-150 disabled:cursor-not-allowed"
      style={{
        background: active ? "hsl(var(--surface-3))" : "hsl(var(--surface-2))",
        border: active ? "1.5px solid hsl(var(--primary) / 0.8)" : "1px solid hsl(var(--border))",
        opacity: disabled ? 0.6 : 1,
      }}
      data-testid="btn-pay-wallet"
    >
      <span
        className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl"
        style={{
          background: active ? "hsl(var(--primary) / 0.18)" : "hsl(var(--surface-3))",
          color: active ? "hsl(var(--primary))" : "rgba(255,255,255,0.6)",
        }}
        aria-hidden="true"
      >
        <WalletIcon size={18} />
      </span>
      <span className="min-w-0 flex-1 text-left">
        <span className="block text-sm font-bold text-white">{t("topup.walletPay")}</span>
        <span
          className="mt-0.5 block text-[12px]"
          style={{
            color: disabled ? "rgb(252, 165, 165)" : "rgba(255,255,255,0.55)",
          }}
        >
          {maintenance
            ? t("payment.maintenance")
            : unknownTotal
              ? t("topup.priceUnavailable")
              : loading
                ? t("topup.walletLoading")
                : disabled
                  ? t("topup.walletShort", { amount: formatBalance(shortfall, currency) })
                  : t("topup.walletBalance", { amount: formatBalance(balance ?? 0, currency) })}
        </span>
      </span>
      {active && !disabled && (
        <span
          className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full"
          style={{ background: "hsl(var(--primary))" }}
          aria-hidden="true"
        >
          <Check size={11} strokeWidth={3} className="text-black" />
        </span>
      )}
    </button>
  );
}
