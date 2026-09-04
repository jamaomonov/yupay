import type { ProfileCheckState } from "@/lib/gift-profile";
import type { MethodVisibility, ProviderAvailability } from "@/lib/orders";

import { InviteField } from "@/components/gifts/InviteField";
import { PaymentMethodGrid } from "@/components/gifts/PaymentMethodGrid";
import { WalletPayOption } from "@/components/WalletPayOption";
import { useT } from "@/lib/i18n";
import { PAYMENT_METHODS } from "@/lib/payment-methods";

/**
 * Invite link input + payment method section of the gift checkout —
 * everything below the price that doesn't own `GiftGame`'s own state. Takes
 * only primitives and callbacks: the checkout mutation, the price-drift
 * reload, and the acquirer body it POSTs stay owned by the page
 * (`GiftGame.tsx::handleBuy`), which is why this panel has no `detail` /
 * `selectedPackage` / `price` prop at all. Same for the wallet tile: the
 * `wallet*` props below are `GiftGame.tsx`'s `walletPayState(...)` output
 * plus the selection primitives, not state this panel owns.
 *
 * The Buy button itself is NOT rendered here — it moved to `GiftGame.tsx`'s
 * own fixed CTA bar (2026-09-04 review, mirrors `TopUp.tsx`): a button
 * inline in the scroll flow greyed out with no explanation while the price
 * sat a screen above it. This panel only ever renders inputs, so it has no
 * `canBuy`/`isPending`/`onBuy` prop any more.
 *
 * The recipient field and its «Проверить» check live in `InviteField`, split
 * out for the same reason this panel was split out of `GiftGame.tsx`
 * (2026-09-03 review): the repo's 300-LOC soft limit for TS.
 */
export function GiftBuyPanel({
  inviteUrl,
  inviteValid,
  onInviteUrlChange,
  onInviteBlur,
  showInviteError,
  onOpenGuide,
  profile,
  profileChecking,
  onCheckProfile,
  onReopenInvite,
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
}: {
  inviteUrl: string;
  inviteValid: boolean;
  onInviteUrlChange: (value: string) => void;
  onInviteBlur: () => void;
  showInviteError: boolean;
  onOpenGuide: () => void;
  /** `GiftGame.tsx`'s `profileCheckState(...)` — the whole render decision
   *  for the pre-purchase recipient check. */
  profile: ProfileCheckState;
  profileChecking: boolean;
  onCheckProfile: () => void;
  onReopenInvite: () => void;
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
}) {
  const { t } = useT();
  return (
    <>
      <div className="space-y-2">
        <InviteField
          inviteUrl={inviteUrl}
          inviteValid={inviteValid}
          onInviteUrlChange={onInviteUrlChange}
          onInviteBlur={onInviteBlur}
          showInviteError={showInviteError}
          onOpenGuide={onOpenGuide}
          profile={profile}
          checking={profileChecking}
          onCheck={onCheckProfile}
          onReopen={onReopenInvite}
        />
        {/* The two sentences that explain the entire model used to sit
            *below* the payment section, past the decision, in 12px dim
            text. Moved here, next to the field where the recipient first
            becomes a concept (2026-09-04 review, mirrors
            `GiftPurchasePanel.tsx` on the web storefront). Unlike the guide
            link inside `InviteField`, these survive a confirmed recipient:
            what the gift *is* and how it arrives stays true after the check.
            Also the contrast fix for this caption: `white/40` measured
            3.68–3.81:1 on this app's surfaces, below the 4.5:1 floor for
            12px text. */}
        <div className="space-y-1 text-[12px] leading-relaxed text-white/50">
          <p>{t("gifts.game.timeline")}</p>
          <p>{t("gifts.game.accept")}</p>
        </div>
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
        </>
      )}
    </>
  );
}
