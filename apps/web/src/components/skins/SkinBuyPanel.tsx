"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useRef, useState } from "react";

import { useSelectedOffer, useSkinOffers } from "./SkinOffers";
import { SkinPaymentPicker } from "./SkinPaymentPicker";
import { SkinTradeLinkField } from "./SkinTradeLinkField";

import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { ApiError } from "@/lib/client";
import { isOrderNotAwaitingPaymentConflict } from "@/lib/gift-checkout";
import { withAutoOpen } from "@/lib/payment-return";
import {
  type OrderKey,
  buySkin,
  orderKeyFor,
  SkinListingGoneError,
  SkinPriceChangedError,
  SkinTradeLinkError,
} from "@/lib/skin-checkout";
import { displayPrice } from "@/lib/skins";
import { useLoginModal } from "@/store/useLoginModal";

/**
 * Buy the offer the customer picked (the cheapest until they pick another):
 * trade link, payment method, one button that says what it charges. A moved
 * price or a sold offer is shown, never charged silently; the next offer is
 * selected for the customer to confirm. Guests are asked to sign in — a skin
 * that falls through refunds to the YuPay balance.
 */
export function SkinBuyPanel({
  skuId,
  slug,
  locale,
}: {
  skuId: string;
  slug: string;
  locale: string;
}) {
  const t = useTranslations("web.skins.buy");
  const router = useRouter();
  const { user, isLoading } = useAuth();
  const openLogin = useLoginModal((s) => s.open);
  const { selected, select, reprice, drop } = useSelectedOffer();
  const offers = useSkinOffers();
  const [link, setLink] = useState({ url: "", usable: false });
  const [pay, setPay] = useState<{ provider: string | null; ready: boolean }>({
    provider: null,
    ready: false,
  });
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const orderKey = useRef<OrderKey | null>(null);
  const onLink = useCallback((s: { url: string; usable: boolean }) => {
    setLink(s);
  }, []);
  const onPay = useCallback((s: { provider: string | null; ready: boolean }) => {
    setPay(s);
  }, []);

  if (!selected) return null;
  const price = displayPrice(locale, selected.price_uzs, selected.price_usd) ?? "";
  const signedIn = user !== null;
  const hint = !link.usable ? t("payHintLink") : !pay.ready ? t("payHintMethod") : null;

  async function buy(): Promise<void> {
    const provider = pay.provider;
    if (!selected || !provider) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    const offer = selected;
    const attempt = (key: string) =>
      buySkin({
        locale,
        skuId,
        slug,
        listingId: offer.listing_id,
        tradelink: link.url,
        amountUsd: offer.price_usd,
        provider,
        orderKey: key,
      });
    orderKey.current = orderKeyFor(orderKey.current, offer.listing_id, link.url, () =>
      crypto.randomUUID(),
    );
    try {
      let result;
      try {
        result = await attempt(orderKey.current.key);
      } catch (err) {
        if (!isOrderNotAwaitingPaymentConflict(err)) throw err;
        // The replayed order expired before this retry: same offer, a fresh order, once.
        orderKey.current = { ...orderKey.current, key: crypto.randomUUID() };
        result = await attempt(orderKey.current.key);
      }
      orderKey.current = null;
      router.push(
        result.intentUrl && pay.provider !== "mock"
          ? withAutoOpen(result.trackHref)
          : result.trackHref,
      );
    } catch (err) {
      if (err instanceof SkinPriceChangedError) {
        // The button now says, and the next press sends, the server's price.
        // Pinned: at its new price it may no longer be the cheapest default.
        select(offer.listing_id);
        reprice(offer.listing_id, err.expectedAmountUsd);
        setNotice(t("priceChanged", { price: `$${err.expectedAmountUsd}` }));
      } else if (err instanceof SkinListingGoneError) {
        const rest = (offers ?? []).filter((o) => o.listing_id !== offer.listing_id);
        drop(offer.listing_id);
        const next =
          rest.find((o) => o.listing_id === err.nextOffer?.listing_id) ??
          rest.reduce<(typeof rest)[number] | null>(
            (a, b) => (a === null || Number(b.price_usd) < Number(a.price_usd) ? b : a),
            null,
          );
        if (next) {
          select(next.listing_id);
          setNotice(t("listingGone", { price: `$${next.price_usd}` }));
        } else {
          setNotice(t("noneLeft"));
        }
      } else if (err instanceof SkinTradeLinkError) {
        setError(
          t(err.reason === "tradelink_other_account" ? "verdict.other_account" : "verdict.invalid"),
        );
      } else if (err instanceof ApiError && err.detail) {
        setError(err.detail);
      } else {
        setError(t("buyError"));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div id="buy" className="border-border space-y-4 rounded-xl border p-4">
      {signedIn && <SkinTradeLinkField signedIn onChange={onLink} />}
      {signedIn && (
        <SkinPaymentPicker
          locale={locale}
          totalUzs={selected.price_uzs !== null ? Number(selected.price_uzs) : null}
          onChange={onPay}
        />
      )}
      {notice && <p className="text-[13px] font-semibold text-amber-400">{notice}</p>}
      {signedIn ? (
        <button
          type="button"
          disabled={hint !== null || busy}
          onClick={() => void buy()}
          className={`${buttonStyles({ size: "lg" })} w-full`}
        >
          {busy ? (
            <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
          ) : (
            (hint ?? t("pay", { price }))
          )}
        </button>
      ) : (
        <button
          type="button"
          disabled={isLoading}
          onClick={openLogin}
          className={`${buttonStyles({ size: "lg" })} w-full`}
        >
          {t("signIn")}
        </button>
      )}
      {error && <p className="text-[13px] text-[#FF6B6B]">{error}</p>}
    </div>
  );
}
