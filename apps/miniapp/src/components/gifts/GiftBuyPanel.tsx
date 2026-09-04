import { useId } from "react";

import type { MethodVisibility, ProviderAvailability } from "@/lib/orders";

import { PaymentMethodGrid } from "@/components/gifts/PaymentMethodGrid";
import { WalletPayOption } from "@/components/WalletPayOption";
import { useT } from "@/lib/i18n";
import { PAYMENT_METHODS } from "@/lib/payment-methods";

/**
 * Invite link input + payment method / buy button section of the gift
 * checkout — everything below the price that doesn't own `GiftGame`'s own
 * state. Takes only primitives and callbacks: the checkout mutation, the
 * price-drift reload, and the acquirer body it POSTs stay owned by the page
 * (`GiftGame.tsx::handleBuy`), which is why this panel has no `detail` /
 * `selectedPackage` / `price` prop at all. Same for the wallet tile: the
 * `wallet*` props below are `GiftGame.tsx`'s `walletPayState(...)` output
 * plus the selection primitives, not state this panel owns.
 *
 * Extracted out of `GiftGame.tsx` (2026-09-03 review) purely to keep that
 * file near the repo's TS file-length budget — no behaviour change.
 */
export function GiftBuyPanel({
  inviteUrl,
  onInviteUrlChange,
  showInviteError,
  onOpenGuide,
  skuStatus,
  methodId,
  providerStatusBySlug,
  onMethodChange,
  walletActive,
  walletEnough,
  walletLoading,
  walletBalance,
  walletShortfall,
  walletVisibility,
  walletUnknownTotal,
  onSelectWallet,
  canBuy,
  isPending,
  onBuy,
}: {
  inviteUrl: string;
  onInviteUrlChange: (value: string) => void;
  showInviteError: boolean;
  onOpenGuide: () => void;
  skuStatus: "loading" | "ready" | "unavailable";
  methodId: string;
  providerStatusBySlug: Map<string, ProviderAvailability> | null;
  onMethodChange: (id: string) => void;
  walletActive: boolean;
  walletEnough: boolean;
  walletLoading: boolean;
  walletBalance: number | null;
  walletShortfall: number;
  walletVisibility: MethodVisibility;
  walletUnknownTotal: boolean;
  onSelectWallet: () => void;
  canBuy: boolean;
  isPending: boolean;
  onBuy: () => void;
}) {
  const { t } = useT();
  // The single required field in the whole checkout, and previously the
  // one with NO label association at all — a `<label>` with no `htmlFor`
  // next to an `<input>` with no `id` (2026-09-04 accessibility audit): a
  // screen reader announced only "text field". `useId()` mirrors the web
  // storefront sibling (`GiftPurchasePanel.tsx`), which already does this
  // correctly.
  const inviteId = useId();
  const inviteErrorId = useId();
  return (
    <>
      {/* Invite link */}
      <div className="space-y-2">
        <label
          htmlFor={inviteId}
          className="text-[11px] font-semibold uppercase tracking-wide text-white/50"
        >
          {t("gifts.game.inviteLabel")}
        </label>
        <input
          id={inviteId}
          type="text"
          value={inviteUrl}
          onChange={(e) => {
            onInviteUrlChange(e.target.value);
          }}
          placeholder={t("gifts.game.invitePlaceholder")}
          aria-invalid={showInviteError}
          aria-describedby={showInviteError ? inviteErrorId : undefined}
          className="h-11 w-full rounded-xl border bg-transparent px-3 text-sm text-white outline-none"
          style={{ borderColor: "hsl(var(--border))" }}
        />
        {showInviteError && (
          <p id={inviteErrorId} className="text-[13px] text-red-400">
            {t("gifts.game.inviteError")}
          </p>
        )}
        <button
          type="button"
          onClick={onOpenGuide}
          className="text-primary text-[13px] font-semibold"
        >
          {t("gifts.game.inviteGuideCta")}
        </button>
      </div>

      {skuStatus === "unavailable" ? (
        <p className="rounded-2xl border border-dashed border-white/10 p-4 text-center text-sm text-white/40">
          {t("gifts.comingSoon")}
        </p>
      ) : (
        <>
          {/* Payment method */}
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-white/50">
              {t("topup.paymentMethod")}
            </p>
            {/* Wallet — own full-width card above the acquirer grid, same
              placement `TopUp` uses. Gift orders are always billed in UZS
              (`GiftGame.tsx::handleBuy` hardcodes it), so unlike `TopUp`
              this never needs a per-product display currency. */}
            <WalletPayOption
              active={walletActive}
              enough={walletEnough}
              loading={walletLoading}
              balance={walletBalance}
              shortfall={walletShortfall}
              currency="UZS"
              visibility={walletVisibility}
              unknownTotal={walletUnknownTotal}
              onSelect={onSelectWallet}
            />
            <PaymentMethodGrid
              methods={PAYMENT_METHODS}
              activeId={methodId}
              providerStatusBySlug={providerStatusBySlug}
              onSelect={onMethodChange}
            />
          </div>

          <button
            type="button"
            disabled={!canBuy}
            onClick={onBuy}
            className="bg-primary w-full rounded-2xl py-3.5 text-base font-bold text-black disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isPending ? t("topup.processingBtn") : t("gifts.game.buy")}
          </button>
        </>
      )}
    </>
  );
}
