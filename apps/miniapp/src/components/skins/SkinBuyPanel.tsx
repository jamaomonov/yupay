import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "wouter";

import type { NextOffer, OrderKey } from "@/lib/skin-buy";
import type { SkinListing } from "@yupay/utils";

import { PaymentMethodGrid } from "@/components/gifts/PaymentMethodGrid";
import { SkinTradeLinkInput } from "@/components/skins/SkinTradeLinkInput";
import { WalletPayOption } from "@/components/WalletPayOption";
import { useToast } from "@/hooks/use-toast";
import { newIdempotencyKey } from "@/lib/api";
import {
  checkoutErrorMessage,
  isOrderNotAwaitingPaymentConflict,
  nextSelectedMethodId,
  PROVIDER_BY_METHOD_FULL,
  WALLET_METHOD_ID,
  walletPayState,
} from "@/lib/checkout-shared";
import { useT } from "@/lib/i18n";
import {
  methodVisibility,
  providerStatusMap,
  useAvailableProviders,
  useCheckout,
} from "@/lib/orders";
import { PAYMENT_METHODS } from "@/lib/payment-methods";
import { oneAtATime, orderKeyFor, skinBuyFailure } from "@/lib/skin-buy";
import { skinPriceText } from "@/lib/skins";
import { haptic, openExternalLink, setClosingConfirmation } from "@/lib/telegram";
import { groupBalancesByCurrency, useWallet } from "@/lib/wallet";
import { ensureBotCanWrite } from "@/lib/write-access";

/**
 * Buy the offer the customer picked (the cheapest until they tap another):
 * trade link, payment method, one fixed button that says what it charges. A
 * moved price or a sold offer is shown, never charged silently; the next
 * offer is handed back to the page to select. Mirrors the web's
 * `SkinBuyPanel`; the mini app is always signed in, so there is no guest path.
 */
export function SkinBuyPanel({
  skuId,
  slug,
  offer,
  onListingGone,
  onPriceChanged,
}: {
  skuId: string;
  slug: string;
  offer: SkinListing;
  /** Drops the sold offer and answers with the one now selected (`null`: none left). */
  onListingGone: (next: NextOffer | null) => SkinListing | null;
  /** The server's price for this offer: the button shows it and the next press sends it. */
  onPriceChanged: (expectedUsd: string) => void;
}) {
  const { t } = useT();
  const { toast } = useToast();
  const [, setLocation] = useLocation();
  const checkout = useCheckout();
  const [link, setLink] = useState({ url: "", usable: false });
  const onLink = useCallback((s: { url: string; usable: boolean }) => {
    setLink(s);
  }, []);
  const [notice, setNotice] = useState<string | null>(null);
  const orderKey = useRef<OrderKey | null>(null);
  const latestBuy = useRef<() => Promise<void>>(() => Promise.resolve());
  const tap = useMemo(() => oneAtATime(() => latestBuy.current()), []);

  const [methodId, setMethodId] = useState<string>(PAYMENT_METHODS[0]?.id ?? "click");
  const providersQuery = useAvailableProviders();
  const statusBySlug = useMemo(
    () => (providersQuery.data ? providerStatusMap(providersQuery.data) : null),
    [providersQuery.data],
  );
  useEffect(() => {
    setMethodId((current) =>
      nextSelectedMethodId({
        current,
        statusBySlug,
        providerByMethod: PROVIDER_BY_METHOD_FULL,
        methods: PAYMENT_METHODS,
      }),
    );
  }, [statusBySlug]);

  const walletQuery = useWallet();
  const balance = walletQuery.data
    ? (groupBalancesByCurrency(walletQuery.data).find((g) => g.currency === "UZS")?.amount ?? 0)
    : null;
  const walletVisibility = methodVisibility(WALLET_METHOD_ID, statusBySlug);
  const wallet = walletPayState({
    balance,
    total: offer.price_uzs !== null ? Number(offer.price_uzs) : null,
    loading: walletQuery.isPending,
    visibility: walletVisibility,
  });

  const provider = PROVIDER_BY_METHOD_FULL[methodId];
  const methodReady =
    provider !== undefined &&
    methodVisibility(provider, statusBySlug) === "active" &&
    (methodId !== WALLET_METHOD_ID || (!wallet.disabled && wallet.enough));
  const hint = !link.usable
    ? t("cs2.buy.payHintLink")
    : !methodReady
      ? t("cs2.buy.payHintMethod")
      : null;
  const price = skinPriceText(offer.price_uzs, offer.price_usd) ?? "";

  async function buy(): Promise<void> {
    if (hint !== null || !provider || checkout.isPending) return;
    setNotice(null);
    await ensureBotCanWrite();
    setClosingConfirmation(true);
    orderKey.current = orderKeyFor(orderKey.current, offer.listing_id, link.url, () =>
      newIdempotencyKey("order"),
    );
    const attempt = (key: string) =>
      checkout.mutateAsync({
        skuId,
        fulfillmentData: { slug, listing_id: offer.listing_id, tradelink: link.url },
        amountUsd: offer.price_usd,
        qty: 1,
        currency: "UZS",
        provider,
        orderIdempotencyKey: key,
      });
    try {
      let result;
      try {
        result = await attempt(orderKey.current.key);
      } catch (err) {
        if (!isOrderNotAwaitingPaymentConflict(err)) throw err;
        // The replayed order expired before this retry: same offer, a fresh order, once.
        orderKey.current = {
          listingId: offer.listing_id,
          tradelink: link.url,
          key: newIdempotencyKey("order"),
        };
        result = await attempt(orderKey.current.key);
      }
      orderKey.current = null;
      haptic("ok");
      if (result.payment.intent_url && result.payment.provider !== "mock") {
        toast({ title: t("topup.redirecting"), description: result.payment.provider });
        openExternalLink(result.payment.intent_url);
      } else if (result.payment.provider === "wallet") {
        toast({ title: t("topup.paidFromBalance") });
      }
      setLocation(`/order/${result.order.id}`);
    } catch (err) {
      haptic("error");
      const failure = skinBuyFailure(err);
      if (failure?.kind === "priceChanged") {
        onPriceChanged(failure.expectedUsd);
        setNotice(t("cs2.buy.priceChanged", { price: `$${failure.expectedUsd}` }));
      } else if (failure?.kind === "listingGone") {
        const now = onListingGone(failure.next);
        setNotice(
          now ? t("cs2.buy.listingGone", { price: `$${now.price_usd}` }) : t("cs2.buy.noneLeft"),
        );
      } else if (failure?.kind === "tradelink") {
        setNotice(
          t(
            failure.reason === "tradelink_other_account"
              ? "cs2.buy.verdict.other_account"
              : "cs2.buy.verdict.invalid",
          ),
        );
      } else {
        toast({
          title: t("topup.checkoutFailed"),
          description: checkoutErrorMessage(err),
          variant: "destructive",
        });
      }
    } finally {
      setClosingConfirmation(false);
    }
  }

  // The button calls the latest `buy`, and never twice at once (see `oneAtATime`).
  latestBuy.current = buy;

  return (
    <div className="space-y-4">
      <SkinTradeLinkInput onChange={onLink} />
      <div className="space-y-2">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-white/50">
          {t("topup.paymentMethod")}
        </p>
        <WalletPayOption
          active={methodId === WALLET_METHOD_ID}
          enough={wallet.enough}
          loading={walletQuery.isPending}
          balance={balance}
          shortfall={wallet.shortfall}
          currency="UZS"
          visibility={walletVisibility}
          unknownTotal={wallet.unknownTotal}
          onSelect={() => {
            setMethodId(WALLET_METHOD_ID);
          }}
        />
        <PaymentMethodGrid
          methods={PAYMENT_METHODS}
          activeId={methodId}
          providerStatusBySlug={statusBySlug}
          onSelect={setMethodId}
        />
      </div>
      {notice && (
        <p role="status" className="text-[13px] font-semibold text-amber-400">
          {notice}
        </p>
      )}
      <div className="fixed bottom-[calc(var(--app-nav-total)_+_16px)] left-1/2 z-40 w-full max-w-[430px] -translate-x-1/2 px-4">
        <button
          type="button"
          disabled={hint !== null || checkout.isPending}
          onClick={() => {
            haptic("press");
            void tap();
          }}
          className="bg-primary flex w-full items-center justify-center gap-2 rounded-2xl py-4 text-base font-bold tracking-wide text-black transition-all disabled:cursor-not-allowed disabled:opacity-45"
        >
          {checkout.isPending ? t("topup.processingBtn") : (hint ?? t("cs2.buy.pay", { price }))}
        </button>
      </div>
    </div>
  );
}
