import { steamImageSize } from "@yupay/utils";
import { ArrowLeft } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "wouter";

import type { NextOffer, OrderKey } from "@/lib/skin-buy";
import type { SkinDetail, SkinListing } from "@yupay/utils";

import { PaymentMethodGrid } from "@/components/gifts/PaymentMethodGrid";
import { SkinFixedCta } from "@/components/skins/SkinFixedCta";
import { SkinHowItWorks } from "@/components/skins/SkinHowItWorks";
import { SafeImage } from "@/components/ui/safe-image";
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
import { oneAtATime, orderKeyFor, skinBuyFailure, tradeLinkAccount } from "@/lib/skin-buy";
import { skinPriceText } from "@/lib/skins";
import { haptic, openExternalLink, setClosingConfirmation } from "@/lib/telegram";
import { groupBalancesByCurrency, useWallet } from "@/lib/wallet";
import { ensureBotCanWrite } from "@/lib/write-access";

/**
 * The skin page's second step, as for every other brand (`TopUp`'s review stage): what
 * is being bought — the skin, its wear, the picked offer's float and seed, the Steam
 * account the trade goes to, the price — then how to pay, and one button that says what
 * it charges. A moved price or a sold offer is shown, never charged silently; the next
 * offer is handed back to the page to select. The mini app is always signed in.
 */
export function SkinPayStep({
  skuId,
  item,
  offer,
  tradelink,
  onBack,
  onListingGone,
  onPriceChanged,
}: {
  skuId: string;
  item: SkinDetail;
  offer: SkinListing;
  /** Checked on the first step. */
  tradelink: string;
  onBack: () => void;
  /** Drops the sold offer and answers with the one now selected (`null`: none left). */
  onListingGone: (next: NextOffer | null) => SkinListing | null;
  /** The server's price for this offer: the button shows it and the next press sends it. */
  onPriceChanged: (expectedUsd: string) => void;
}) {
  const { t } = useT();
  const { toast } = useToast();
  const [, setLocation] = useLocation();
  const checkout = useCheckout();
  const slug = item.slug;
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
  const hint = !methodReady ? t("cs2.buy.payHintMethod") : null;
  const price = skinPriceText(offer.price_uzs, offer.price_usd) ?? "";

  async function buy(): Promise<void> {
    if (hint !== null || !provider || checkout.isPending) return;
    setNotice(null);
    await ensureBotCanWrite();
    setClosingConfirmation(true);
    orderKey.current = orderKeyFor(orderKey.current, offer.listing_id, tradelink, () =>
      newIdempotencyKey("order"),
    );
    const attempt = (key: string) =>
      checkout.mutateAsync({
        skuId,
        fulfillmentData: { slug, listing_id: offer.listing_id, tradelink: tradelink },
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
          tradelink: tradelink,
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

  const account = tradeLinkAccount(tradelink);
  const details: { label: string; value: string }[] = [
    ...(item.exterior
      ? [{ label: t("cs2.buy.wear"), value: t(`cs2.exterior.${item.exterior}`) }]
      : []),
    ...(offer.float_value !== null
      ? [{ label: t("cs2.float"), value: offer.float_value.toFixed(4) }]
      : []),
    ...(offer.paint_seed !== null
      ? [{ label: t("cs2.seed"), value: String(offer.paint_seed) }]
      : []),
    ...(account
      ? [{ label: t("cs2.buy.tradeTo"), value: t("cs2.buy.steamAccount", { id: account }) }]
      : []),
  ];

  return (
    <div className="yp-fade-in space-y-6 px-4 pb-28 pt-4">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onBack}
          aria-label={t("common.back")}
          className="bg-card border-border flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full border"
        >
          <ArrowLeft size={16} className="text-white/70" />
        </button>
        <div className="min-w-0 flex-1">
          <p className="text-base font-bold leading-tight text-white">{t("topup.reviewTitle")}</p>
          <p className="line-clamp-1 text-xs text-white/40">{item.name}</p>
        </div>
      </div>

      <section>
        <p className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-white/50">
          {t("topup.orderDetailsTitle")}
        </p>
        <div
          className="rounded-2xl p-3"
          style={{ background: "hsl(var(--surface-2))", border: "1px solid hsl(var(--border))" }}
        >
          <div className="flex items-center gap-3">
            {item.image_url && (
              <SafeImage
                src={steamImageSize(item.image_url, "256fx256f")}
                alt=""
                className="h-12 w-16 flex-shrink-0 object-contain"
              />
            )}
            <div className="min-w-0 flex-1">
              <p className="line-clamp-2 text-sm font-bold text-white">
                {item.stattrak && <span className="text-orange-400">StatTrak™ </span>}
                {item.weapon} | {item.skin ?? item.name}
                {item.phase && <span className="text-white/50"> · {item.phase}</span>}
              </p>
            </div>
            <p className="flex-shrink-0 text-sm font-bold tabular-nums text-white">{price}</p>
          </div>
          {details.length > 0 && (
            <div
              className="mt-3 space-y-2 border-t pt-3"
              style={{ borderColor: "hsl(var(--border))" }}
            >
              {details.map((d) => (
                <div key={d.label} className="flex items-center justify-between gap-3">
                  <span className="text-xs text-white/40">{d.label}</span>
                  <span className="min-w-0 truncate text-right text-[13px] font-semibold text-white">
                    {d.value}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="space-y-2">
        <div className="px-1">
          <p className="text-xs font-semibold uppercase tracking-wide text-white/50">
            {t("topup.paymentMethod")}
          </p>
          <p className="text-[11px] text-white/35">{t("topup.paymentSafe")}</p>
        </div>
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
      </section>

      <SkinHowItWorks />

      {notice && (
        <p role="status" className="text-[13px] font-semibold text-amber-400">
          {notice}
        </p>
      )}

      <SkinFixedCta
        disabled={hint !== null || checkout.isPending}
        onPress={() => {
          haptic("press");
          void tap();
        }}
        label={
          checkout.isPending ? t("topup.processingBtn") : (hint ?? t("cs2.buy.pay", { price }))
        }
      />
    </div>
  );
}
