import { motion } from "framer-motion";
import {
  ArrowLeft,
  Check,
  ChevronRight,
  Clock,
  ExternalLink,
  Package as PackageIcon,
  RotateCcw,
  Send,
  Settings,
  ShieldCheck,
  Wallet as WalletIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useParams } from "wouter";

import { DynamicFields } from "@/components/DynamicFields";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/use-toast";
import { ApiError } from "@/lib/api";
import { useMe } from "@/lib/auth";
import {
  useBrandSummary,
  useGames,
  useProductWithSkus,
  type Package as ApiPackage,
} from "@/lib/catalog";
import { useDisplayCurrency } from "@/lib/currency";
import { useT } from "@/lib/i18n";
import { getActiveLocale } from "@/lib/i18n/core";
import { SafeImage } from "@/components/ui/safe-image";
import { useAvailableProviders, useCheckout } from "@/lib/orders";
import { ACQUIRER_BY_METHOD, PAYMENT_METHODS, PROVIDER_BY_METHOD } from "@/lib/payment-methods";
import { getRecentFulfillment, rememberFulfillment } from "@/lib/recent-checkout";
import { isInsideTelegram, setClosingConfirmation } from "@/lib/telegram";
import { useDocumentTitle } from "@/lib/use-document-title";
import { cn } from "@/lib/utils";
import { amountError, parseAmount } from "@/lib/variable-amount";
import { formatBalance, groupBalancesByCurrency, useWallet } from "@/lib/wallet";
import { ensureBotCanWrite } from "@/lib/write-access";

// ─── Adapter: API Package → local Package ─────────────────────────────────────
// Keeps badge/bonus optional for future enrichment.
interface Package {
  id: string;
  label: string;
  region: string | null;
  price: number;
  priceCode: string;
  imageUrl: string | null;
  badge?: { label: string; color: string };
  // Variable-amount SKU (Steam wallet top-up): the customer types a dollar
  // amount instead of picking this card. ``price``/``priceCode`` above are
  // meaningless for these — see ``ratePerDollar``.
  variableAmount: boolean;
  minAmountUsd: number | null;
  maxAmountUsd: number | null;
  /** Localised price of one dollar. `null` means the FX trust gate rejected
   *  the live rate — not sellable right now, never a price of zero. */
  ratePerDollar: { amount: number; currency: string } | null;
}

function adaptPackage(api: ApiPackage): Package {
  return {
    id: api.id,
    label: api.label,
    region: api.region,
    price: api.displayPrice?.amount ?? api.priceUsd,
    priceCode: api.displayPrice?.currency ?? "USD",
    imageUrl: api.imageUrl,
    variableAmount: api.variableAmount,
    minAmountUsd: api.minAmountUsd,
    maxAmountUsd: api.maxAmountUsd,
    ratePerDollar: api.ratePerDollar,
  };
}

const DEFAULT_PAYMENT_METHOD = PAYMENT_METHODS[0]?.id ?? "click";

// When the user opens the miniapp in a plain browser we can't take payment
// (auth is bound to Telegram initData). Deep-link them back into the bot
// rather than letting them fill the whole form and bouncing at submit.
const BOT_USERNAME = (
  (import.meta.env.VITE_TELEGRAM_BOT_USERNAME as string | undefined) ?? ""
).replace(/^@/, "");
const TELEGRAM_DEEP_LINK = BOT_USERNAME ? `https://t.me/${BOT_USERNAME}` : null;

/** Sentinel for "pay from wallet balance" — handled by its own card, not part
 *  of the shared acquirer grid. The backend provider slug is ``wallet``. */
const WALLET_METHOD_ID = "wallet";

// The shared acquirer list carries the external providers; the wallet option is
// checkout-only, so we extend the provider map locally for resolution/availability.
const PROVIDER_BY_METHOD_FULL: Record<string, string> = {
  ...PROVIDER_BY_METHOD,
  [WALLET_METHOD_ID]: "wallet",
};

function formatMoney(value: number, code: string): string {
  const locale = getActiveLocale();
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency: code,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    // Non-ISO pseudocurrency (USDT) — format the number, suffix the code.
    return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value)} ${code}`;
  }
}

// ─── Step heading ──────────────────────────────────────────────────────────────
function Step({ n, title, sub }: { n: number; title: string; sub?: string }) {
  return (
    <div className="mb-3.5 flex items-start gap-3">
      <div
        className="mt-0.5 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full text-[11px] font-bold"
        style={{
          background: "hsl(var(--primary) / 0.15)",
          color: "hsl(var(--primary))",
          border: "1px solid hsl(var(--primary) / 0.4)",
        }}
      >
        {n}
      </div>
      <div>
        <p className="text-base font-bold leading-tight text-white">{title}</p>
        {sub && <p className="mt-0.5 text-xs text-white/40">{sub}</p>}
      </div>
    </div>
  );
}

// ─── Wallet payment option ────────────────────────────────────────────────────
function WalletPayOption({
  active,
  enough,
  loading,
  balance,
  shortfall,
  currency,
  onSelect,
}: {
  active: boolean;
  enough: boolean;
  loading: boolean;
  balance: number | null;
  shortfall: number;
  currency: string;
  onSelect: () => void;
}) {
  const { t } = useT();
  const disabled = !loading && !enough;
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
          {loading
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

// ─── Page ─────────────────────────────────────────────────────────────────────
export default function TopUp() {
  const { t, tn, locale } = useT();
  const { gameId } = useParams();
  const [, setLocation] = useLocation();
  const { toast } = useToast();

  const gamesQuery = useGames();
  const game = gamesQuery.data?.find((g) => g.id === gameId);
  const brandQuery = useBrandSummary(gameId);
  const products = brandQuery.data?.products ?? [];

  useDocumentTitle(game ? t("topup.docTitleNamed", { game: game.name }) : t("topup.docTitle"));

  // The currently picked product within the brand (PUBG UC vs Royale Pass …).
  const [selectedProductSlug, setSelectedProductSlug] = useState<string>("");
  useEffect(() => {
    if (!selectedProductSlug && products.length > 0) {
      setSelectedProductSlug(products[0]!.slug);
    }
  }, [products, selectedProductSlug]);

  const currency = useDisplayCurrency();
  const productQuery = useProductWithSkus(selectedProductSlug || undefined, currency);
  const requiredFields = productQuery.data?.product.required_fields ?? [];
  const productImage = productQuery.data?.product.image_url ?? null;
  const packages: Package[] = useMemo(
    () => (productQuery.data?.packages ?? []).map(adaptPackage),
    [productQuery.data],
  );
  // The Steam wallet top-up is the only variable-amount product today and it
  // has exactly one SKU (a fixed denomination doesn't apply — the customer
  // types the amount). Detected as "every SKU on this product is
  // variable-amount" rather than a product-level flag, since the flag lives
  // on the SKU.
  const isVariableProduct = packages.length > 0 && packages.every((p) => p.variableAmount);

  const me = useMe();
  const checkout = useCheckout();
  const isProcessing = checkout.isPending;
  // Backend tells us which gateways can actually accept a payment right now
  // (mock + whatever real acquirers have been wired). Until the response
  // lands we optimistically treat the catalogue as fully available so the UI
  // doesn't flash a "Скоро" badge across every method on first paint.
  const providersQuery = useAvailableProviders();
  const liveProviderSet = useMemo(() => {
    if (!providersQuery.data) return null;
    return new Set(providersQuery.data);
  }, [providersQuery.data]);
  const isMethodAvailable = (methodId: string): boolean => {
    // Wallet eligibility is computed below from the user's balance — the
    // payment-provider list on the server does not know about it.
    if (methodId === WALLET_METHOD_ID) return true;
    // Variable-amount SKUs (Steam wallet top-up) are priced in UZS only —
    // see catalog.service._resolve_variable_price. A non-UZS acquirer would
    // set an order currency the display price was never computed for, so it
    // must never be offered here, independent of the live-providers check
    // below (checked first so it applies even before that query resolves).
    if (isVariableProduct) {
      const method = PAYMENT_METHODS.find((m) => m.id === methodId);
      if (method && method.currency !== "UZS") return false;
    }
    if (liveProviderSet === null) return true;
    const provider = PROVIDER_BY_METHOD[methodId];
    return provider !== undefined && liveProviderSet.has(provider);
  };

  // Wallet balance in the SKU's display currency. ``finalPrice`` is set
  // further down, so the actual sufficiency check happens after that — we
  // only build the maps here.
  const walletQuery = useWallet();
  const walletByCurrency = useMemo(() => {
    const map = new Map<string, number>();
    for (const g of groupBalancesByCurrency(walletQuery.data ?? [])) {
      map.set(g.currency, g.amount);
    }
    return map;
  }, [walletQuery.data]);
  // Checkout requires Telegram initData. Detected once at mount — re-running
  // on every render would let an authenticated user navigate-and-render with
  // a stale answer if their session was just rebuilt.
  const insideTelegram = isInsideTelegram();

  const [fulfillment, setFulfillment] = useState<Record<string, string>>({});
  // Values from the customer's last checkout for this brand. Offered as a
  // per-field tap-to-fill suggestion (see DynamicFields) — never auto-applied,
  // so we don't carry a stale player_id into a fresh order by surprise.
  const [suggestions, setSuggestions] = useState<Record<string, string>>({});
  const [selectedPkg, setSelectedPkg] = useState<string>("");
  // The dollar amount typed for a variable-amount product. Raw string, not a
  // number — see ``@/lib/variable-amount`` for parsing/validation.
  const [amountInput, setAmountInput] = useState<string>("");
  const [paymentMethod, setPaymentMethod] = useState(DEFAULT_PAYMENT_METHOD);

  // If the user has a stale selection (e.g. "card" preserved across a session
  // where the live list now only has "mock", or a non-UZS method carried over
  // from a fixed-price product into a variable-amount one), bounce them to
  // the first live method instead of letting them tap a button that will
  // refuse.
  useEffect(() => {
    if (liveProviderSet === null) return;
    if (paymentMethod === "" || isMethodAvailable(paymentMethod)) return;
    // No live acquirer at all → deselect instead of leaving the highlight on
    // a method that renders with a «Скоро» badge (selected-but-disabled).
    const fallback = PAYMENT_METHODS.find((m) => isMethodAvailable(m.id));
    setPaymentMethod(fallback ? fallback.id : "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveProviderSet, paymentMethod, isVariableProduct]);

  // Don't pre-select a package — the customer chooses. A variable-amount
  // product is the exception: there's nothing to pick (one SKU, no
  // denominations), so it self-selects and the amount panel renders right
  // away instead of a one-card grid. On a product switch we otherwise only
  // clear a now-stale selection so the previous SKU doesn't stick around.
  useEffect(() => {
    if (isVariableProduct) {
      const only = packages[0];
      if (only && selectedPkg !== only.id) setSelectedPkg(only.id);
      return;
    }
    if (!selectedPkg) return;
    if (!packages.some((p) => p.id === selectedPkg)) {
      setSelectedPkg("");
    }
  }, [packages, selectedPkg, isVariableProduct]);

  // Typed amount is per-product — clear it on a product switch so a leftover
  // "10" from a previous variable-amount product never bleeds into the next.
  useEffect(() => {
    setAmountInput("");
  }, [selectedProductSlug]);

  // On every brand switch: start the form empty and load the last checkout's
  // fields as *suggestions* only. Clearing inputs here prevents PUBG's
  // player_id from bleeding into Steam's email when the user changes brand.
  useEffect(() => {
    setFulfillment({});
    if (!gameId) {
      setSuggestions({});
      return;
    }
    setSuggestions(getRecentFulfillment(gameId)?.fulfillment_data ?? {});
  }, [gameId]);

  if (gamesQuery.isLoading || brandQuery.isLoading) {
    return (
      <PageSkeleton
        onBack={() => {
          setLocation("/");
        }}
      />
    );
  }
  if (!game || brandQuery.isError) {
    return (
      <div className="space-y-4 p-4 pt-20 text-center">
        <h2 className="text-xl font-bold">{t("topup.notFound")}</h2>
        <button
          onClick={() => {
            setLocation("/");
          }}
          className="bg-primary rounded-2xl px-6 py-3 font-bold text-black"
        >
          {t("common.toHome")}
        </button>
      </div>
    );
  }
  // Brand is in maintenance — the tile is non-clickable on Home, but a direct
  // link (recent-orders strip, deep link) can still land here, so block the
  // purchase flow with a friendly notice instead of rendering the buy UI.
  if (game.maintenance || brandQuery.data?.maintenance) {
    return (
      <div className="flex flex-col items-center gap-4 p-6 pt-24 text-center">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-white/5">
          <Settings size={32} className="animate-spin text-white/70 [animation-duration:4s]" />
        </div>
        <h2 className="text-xl font-bold text-white">{t("topup.maintenance")}</h2>
        <p className="max-w-xs text-sm text-white/55">
          {t("topup.maintenanceBody", { game: game.name })}
        </p>
        <button
          onClick={() => {
            setLocation("/");
          }}
          className="bg-primary mt-2 rounded-2xl px-6 py-3 font-bold text-black"
        >
          {t("common.toHome")}
        </button>
      </div>
    );
  }

  const activePkg = packages.find((p) => p.id === selectedPkg);
  const isVariableSelected = activePkg?.variableAmount ?? false;
  // Parsed only for a variable-amount SKU — a fixed package has nothing to
  // parse. ``null`` covers both "nothing typed yet" and "unparseable".
  const parsedAmount = isVariableSelected ? parseAmount(amountInput) : null;
  const variableAmountErr =
    isVariableSelected && parsedAmount !== null
      ? amountError(parsedAmount, activePkg?.minAmountUsd ?? 0, activePkg?.maxAmountUsd ?? 0)
      : null;
  // Client-side total for display only — the server recomputes the
  // authoritative price from ``amount_usd`` at checkout.
  const variableTotal =
    isVariableSelected && parsedAmount !== null && activePkg?.ratePerDollar
      ? parsedAmount * activePkg.ratePerDollar.amount
      : null;
  const priceCode = isVariableSelected
    ? (activePkg?.ratePerDollar?.currency ?? currency)
    : (activePkg?.priceCode ?? currency);
  const finalPrice = isVariableSelected ? (variableTotal ?? 0) : (activePkg?.price ?? 0);
  // Gates the CTA for a variable-amount SKU: a live rate (the FX trust gate
  // didn't reject it) and a parsed, in-bounds, two-decimals-or-fewer amount.
  const variableAmountReady =
    !isVariableSelected ||
    (activePkg?.ratePerDollar !== null && parsedAmount !== null && variableAmountErr === null);
  // Human-readable reason the CTA is disabled — reused for both the toast
  // (belt-and-suspenders guard in handlePayment) and the button label itself,
  // so the customer sees *why* right on the button, same as the existing
  // "availableInTg" swap below.
  const variableAmountReason: string | null =
    isVariableSelected && !variableAmountReady && activePkg
      ? activePkg.ratePerDollar === null
        ? t("topup.priceUnavailable")
        : variableAmountErr === "below"
          ? t("topup.amountBelow", { min: formatMoney(activePkg.minAmountUsd ?? 0, "USD") })
          : variableAmountErr === "above"
            ? t("topup.amountAbove", { max: formatMoney(activePkg.maxAmountUsd ?? 0, "USD") })
            : variableAmountErr === "precision"
              ? t("topup.amountPrecision")
              : t("topup.amountRequired")
      : null;

  // Wallet sufficiency check + nicely-formatted shortfall message for the
  // disabled-state copy. ``walletBalance === null`` means we don't have
  // wallet data yet — render the option as enabled-but-uncertain so the
  // user doesn't see "недостаточно" while we're still loading the balance.
  const walletBalance = walletQuery.data ? (walletByCurrency.get(priceCode) ?? 0) : null;
  const walletEnough =
    walletBalance === null
      ? true // optimistic during load — submit will re-check
      : walletBalance >= finalPrice;
  const walletShortfall = walletBalance === null || walletEnough ? 0 : finalPrice - walletBalance;

  const accountRequired = requiredFields.length > 0;
  const missingFieldKey = requiredFields.find((f) => {
    if (!f.required) return false;
    const v = fulfillment[f.key];
    return !v || v.trim().length === 0;
  })?.key;
  const firstFieldLabel =
    requiredFields[0]?.label?.[locale] ?? requiredFields[0]?.label?.ru ?? t("topup.fieldFallback");
  const fillingHint = accountRequired
    ? t("topup.fillingHint", { field: firstFieldLabel })
    : t("topup.noAccount");

  const handlePayment = async () => {
    if (!activePkg) {
      toast({
        title: t("topup.pickPackageTitle"),
        description: t("topup.pickPackageBody"),
        variant: "destructive",
      });
      return;
    }
    // The pay button is already disabled while the amount is invalid — this
    // is a belt-and-suspenders guard against a stray Enter-key submit.
    if (!variableAmountReady) {
      toast({
        title: t("topup.amountInvalidTitle"),
        description: variableAmountReason ?? t("topup.amountRequired"),
        variant: "destructive",
      });
      return;
    }
    if (missingFieldKey) {
      const f = requiredFields.find((x) => x.key === missingFieldKey);
      toast({
        title: t("topup.fillFieldTitle"),
        description: f?.label?.[locale] ?? f?.label?.ru ?? missingFieldKey,
        variant: "destructive",
      });
      return;
    }
    if (!me.data) {
      toast({
        title: t("topup.openInTgTitle"),
        description: t("topup.openInTgBody"),
        variant: "destructive",
      });
      return;
    }
    // Preflight: never POST /orders if the selected gateway is unavailable —
    // the follow-up POST /payments/intents would fail and leave an orphan
    // ``pending_payment`` order until it expires.
    if (!isMethodAvailable(paymentMethod)) {
      toast({
        title: t("topup.methodUnavailableTitle"),
        description: t("topup.methodUnavailableBody"),
        variant: "destructive",
      });
      return;
    }
    if (paymentMethod === WALLET_METHOD_ID && !walletEnough) {
      // Client-side guard against a doomed POST. The backend
      // WalletGateway re-checks under a row-lock, so this is just UX —
      // the source of truth is server-side. Even if a stale balance
      // slipped past us, the gateway would fail safely and roll back.
      toast({
        title: t("topup.insufficientTitle"),
        description: t("topup.insufficientBody", {
          amount: formatBalance(walletShortfall, priceCode),
        }),
        variant: "destructive",
      });
      return;
    }
    const fulfillmentData: Record<string, string> = {};
    for (const f of requiredFields) {
      const v = (fulfillment[f.key] ?? "").trim();
      if (v) fulfillmentData[f.key] = v;
    }
    // Codes and status updates are delivered by the bot. Someone who opened
    // the Mini App from a link and never pressed /start can't be written to,
    // so ask once, here, where the reason is obvious.
    await ensureBotCanWrite();
    // Money is about to move and the next step may be a redirect to the
    // acquirer — a stray swipe-down here loses the customer mid-payment.
    setClosingConfirmation(true);
    try {
      const result = await checkout.mutateAsync({
        skuId: activePkg.id,
        fulfillmentData,
        currency,
        provider: PROVIDER_BY_METHOD_FULL[paymentMethod] ?? "click",
        // Sent as a fixed-2-decimal string so the server never has to
        // round-trip a client float — the server re-validates and re-prices
        // from it regardless.
        ...(isVariableSelected && parsedAmount !== null
          ? { amountUsd: parsedAmount.toFixed(2) }
          : {}),
      });
      // Remember the fulfilment payload only after the order was accepted by
      // the API — no point caching a half-typed player_id that came back
      // 400. Subsequent visits to this brand pick it back up automatically.
      if (gameId) rememberFulfillment(gameId, fulfillmentData);
      if (result.payment.intent_url && result.payment.provider !== "mock") {
        toast({
          title: t("topup.redirecting"),
          description: result.payment.provider,
        });
        window.location.href = result.payment.intent_url;
        return;
      }
      // Wallet ⇒ the gateway already debited and the saga already
      // walked the order toward delivered inside the create_intent
      // transaction. Pivot the toast wording so the user understands
      // the money has actually moved.
      if (result.payment.provider === "wallet") {
        toast({
          title: t("topup.paidFromBalance"),
          description: t("topup.processing", { game: game.name }),
        });
      } else {
        toast({
          title: t("topup.orderCreated"),
          description: t("topup.processing", { game: game.name }),
        });
      }
      setLocation(`/order/${result.order.id}`);
    } catch (exc) {
      const detail = exc instanceof ApiError ? exc.detail : t("topup.tryAgain");
      toast({
        title: t("topup.checkoutFailed"),
        description: detail,
        variant: "destructive",
      });
    } finally {
      // Checkout is over either way — stop nagging on close. Runs on the
      // redirect path too (`finally` fires on `return`), which is what we
      // want: we're navigating to the acquirer, not closing the app.
      setClosingConfirmation(false);
    }
  };

  return (
    <>
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.22 }}
        className="pb-32"
      >
        {/* ── Hero ── */}
        <div className="relative h-56 overflow-hidden">
          {game.bgUrl ? (
            <SafeImage
              src={game.bgUrl}
              className="absolute inset-0 h-full w-full object-cover"
              fallback={
                <div className="absolute inset-0 bg-gradient-to-br from-slate-800 to-slate-950" />
              }
            />
          ) : (
            <div className="absolute inset-0 bg-gradient-to-br from-slate-800 to-slate-950" />
          )}
          <div className="from-background via-background/40 absolute inset-0 bg-gradient-to-t to-black/20" />

          <div className="absolute bottom-0 left-0 right-0 z-10 flex items-end gap-3 px-4 pb-4">
            <div className="h-14 w-14 flex-shrink-0 overflow-hidden rounded-2xl border border-white/15 shadow-xl">
              {game.appIcon ? (
                <SafeImage
                  src={game.appIcon}
                  className="h-full w-full object-cover"
                  fallback={
                    <div
                      className="flex h-full w-full items-center justify-center text-xl font-bold text-white/80"
                      style={{ background: game.color }}
                    >
                      {game.name.charAt(0)}
                    </div>
                  }
                />
              ) : (
                <div
                  className="flex h-full w-full items-center justify-center text-xl font-bold text-white/80"
                  style={{ background: game.color }}
                >
                  {game.name.charAt(0)}
                </div>
              )}
            </div>
            <div className="min-w-0 flex-1">
              <p className="line-clamp-1 text-[11px] uppercase tracking-wide text-white/50">
                {game.publisher || "YuPay"}
              </p>
              <h1 className="line-clamp-1 text-lg font-bold leading-tight text-white">
                {game.name}
              </h1>
              <div className="mt-0.5 flex items-center gap-3">
                {/* Single honest signal: typical delivery time. The 4.9 star
                    rating that used to live here was hardcoded with no count
                    behind it — pulled per the audit ("trust gaps · present
                    but unearned"). When real review data lands, add a count
                    + tap-to-open reviews sheet. */}
                <div
                  className="flex items-center gap-1 rounded-full px-2 py-0.5"
                  style={{
                    background: "hsl(var(--primary) / 0.15)",
                    border: "1px solid hsl(var(--primary) / 0.3)",
                  }}
                >
                  <Clock size={10} className="text-primary" />
                  <span className="text-primary text-[10px] font-semibold">
                    {t("topup.deliveryTime")}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Telegram-only banner — surfaced at the top of the funnel, before
            the user invests time filling fulfilment fields and picking a
            package. */}
        {!insideTelegram && (
          <div className="px-4 pt-4">
            <div
              className="flex items-start gap-3 rounded-2xl p-4"
              style={{
                background: "hsl(var(--surface-1))",
                border: "1.5px solid hsl(var(--primary) / 0.4)",
              }}
              role="status"
            >
              <div
                className="flex size-9 flex-shrink-0 items-center justify-center rounded-xl"
                style={{
                  background: "hsl(var(--primary) / 0.15)",
                  color: "hsl(var(--primary))",
                }}
                aria-hidden="true"
              >
                <Send size={16} />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold leading-tight text-white">
                  {t("topup.openInTgTitle")}
                </p>
                <p className="mt-1 text-[12px] leading-relaxed text-white/55">
                  {t("topup.tgBannerBody")}
                </p>
                {TELEGRAM_DEEP_LINK && (
                  <a
                    href={TELEGRAM_DEEP_LINK}
                    className="mt-2.5 inline-flex items-center gap-1.5 text-[12px] font-semibold transition-opacity active:opacity-70"
                    style={{ color: "hsl(var(--primary))" }}
                  >
                    {t("common.openBot")}
                    <ExternalLink size={11} />
                  </a>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ── Form ── */}
        <div className="space-y-7 px-4 pt-5">
          {/* Step 0 — Product picker (only when there's more than one product) */}
          {products.length > 1 && (
            <div>
              <div className="mb-2.5 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <PackageIcon size={13} className="text-white/40" />
                  <span className="text-xs font-semibold uppercase tracking-wide text-white/50">
                    {t("topup.pickProduct")}
                  </span>
                </div>
                <span className="text-[10px] text-white/30">
                  {tn("topup.optionsCount", products.length)}
                </span>
              </div>
              <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4">
                {products.map((p) => {
                  const active = p.slug === selectedProductSlug;
                  return (
                    <button
                      key={p.id}
                      onClick={() => {
                        setSelectedProductSlug(p.slug);
                      }}
                      className="flex flex-shrink-0 items-center gap-2 rounded-2xl py-1.5 pl-2 pr-3 transition-all duration-150"
                      style={{
                        background: active ? "hsl(var(--surface-3))" : "hsl(var(--surface-2))",
                        border: active
                          ? "1.5px solid hsl(var(--primary) / 0.7)"
                          : "1px solid hsl(var(--border))",
                      }}
                    >
                      <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center overflow-hidden rounded-md bg-black/30">
                        {p.image_url ? (
                          <SafeImage
                            src={p.image_url}
                            className="h-full w-full object-cover"
                            fallback={<PackageIcon size={11} className="text-white/40" />}
                          />
                        ) : (
                          <PackageIcon size={11} className="text-white/40" />
                        )}
                      </div>
                      <span
                        className={cn(
                          "whitespace-nowrap text-xs font-semibold",
                          active ? "text-white" : "text-white/60",
                        )}
                      >
                        {p.name}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Step 1 — Dynamic account fields from product.required_fields */}
          {accountRequired && (
            <div>
              <Step
                n={1}
                title={
                  requiredFields.length === 1 ? t("topup.whereToCredit") : t("topup.credentials")
                }
                sub={fillingHint}
              />
              <DynamicFields
                productId={productQuery.data?.product.id ?? ""}
                fields={requiredFields}
                values={fulfillment}
                suggestions={suggestions}
                onChange={(key, value) => {
                  setFulfillment((prev) => ({ ...prev, [key]: value }));
                }}
              />
            </div>
          )}

          {/* Step 2 — Packages */}
          <div>
            <Step
              n={accountRequired ? 2 : 1}
              title={t("topup.howMuch")}
              sub={t("topup.creditWithinMinutes")}
            />

            {productQuery.isLoading && <PackagesSkeleton />}
            {!productQuery.isLoading && packages.length === 0 && (
              <p className="rounded-2xl border border-dashed border-white/10 p-6 text-center text-sm text-white/40">
                {t("topup.noPositions")}
              </p>
            )}
            {!productQuery.isLoading && isVariableProduct && activePkg && (
              <VariableAmountPanel
                pkg={activePkg}
                value={amountInput}
                onChange={setAmountInput}
                total={variableTotal}
                error={variableAmountErr}
              />
            )}
            {!isVariableProduct && packages.length > 0 && (
              <div className="grid grid-cols-2 gap-2.5">
                {packages.map((pkg) => (
                  <PackageCard
                    key={pkg.id}
                    pkg={pkg}
                    active={selectedPkg === pkg.id}
                    fallbackImage={productImage}
                    onSelect={() => {
                      setSelectedPkg(pkg.id);
                    }}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Step 3 — Payment */}
          <div>
            <Step
              n={accountRequired ? 3 : 2}
              title={t("topup.paymentMethod")}
              sub={t("topup.paymentSafe")}
            />

            {/* Wallet — separate full-width card on top because it's the
                cheapest option when funded, and because the disabled copy
                ("не хватает X") needs more room than a 4-col chip. */}
            <WalletPayOption
              active={paymentMethod === WALLET_METHOD_ID}
              enough={walletEnough}
              loading={walletQuery.isPending}
              balance={walletBalance}
              shortfall={walletShortfall}
              currency={priceCode}
              onSelect={() => {
                setPaymentMethod(WALLET_METHOD_ID);
              }}
            />

            <div className="mb-3 grid grid-cols-4 gap-2">
              {PAYMENT_METHODS.map((m) => {
                const available = isMethodAvailable(m.id);
                // An unavailable method can never look selected.
                const active = paymentMethod === m.id && available;
                return (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => {
                      if (!available) return;
                      setPaymentMethod(m.id);
                    }}
                    disabled={!available}
                    aria-disabled={!available}
                    title={available ? undefined : t("topup.soon")}
                    className="relative flex flex-col items-center gap-1 rounded-2xl py-3 transition-all duration-150 disabled:cursor-not-allowed"
                    style={{
                      background: active ? "hsl(var(--surface-3))" : "hsl(var(--surface-2))",
                      border: active
                        ? "1.5px solid hsl(var(--primary) / 0.8)"
                        : "1px solid hsl(var(--border))",
                      opacity: available ? 1 : 0.5,
                    }}
                    data-testid={`btn-pay-${m.id}`}
                  >
                    {active && available && (
                      <div
                        className="absolute right-1.5 top-1.5 flex h-4 w-4 items-center justify-center rounded-full"
                        style={{ background: "hsl(var(--primary))" }}
                      >
                        <Check size={9} strokeWidth={3} className="text-black" />
                      </div>
                    )}
                    {!available && (
                      <div
                        className="absolute right-1 top-1 rounded px-1 py-0.5 text-[8px] font-bold uppercase tracking-wide"
                        style={{
                          background: "hsl(var(--surface-3))",
                          color: "hsl(var(--muted-foreground))",
                        }}
                      >
                        {t("topup.soon")}
                      </div>
                    )}
                    <span className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-lg bg-white">
                      <img src={m.icon} alt={m.name} className="h-full w-full object-contain p-1" />
                    </span>
                    <span
                      className={cn(
                        "text-[11px] font-bold leading-none",
                        active && available ? "text-white" : "text-white/50",
                      )}
                    >
                      {m.name}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Trust items */}
          <div className="space-y-2.5 pt-1">
            {[
              {
                icon: ShieldCheck,
                text: accountRequired ? t("topup.trustNoPassword") : t("topup.trustEncrypted"),
              },
              {
                icon: RotateCcw,
                text: t("topup.trustRefund"),
              },
            ].map(({ icon: Icon, text }, i) => (
              <div key={i} className="flex items-center gap-2.5">
                <Icon size={14} className="flex-shrink-0 text-white/25" />
                <span className="text-xs text-white/35">{text}</span>
              </div>
            ))}
          </div>

          {/* Order summary */}
          {activePkg && (
            <motion.div
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex items-center gap-3 rounded-2xl p-3"
              style={{
                background: "hsl(var(--surface-2))",
                border: "1px solid hsl(var(--border))",
              }}
            >
              <PackageThumb pkg={activePkg} fallback={productImage ?? game.appIcon ?? null} />
              <div className="min-w-0 flex-1">
                <p className="line-clamp-1 text-sm font-bold text-white">
                  {activePkg.label} · {game.name}
                </p>
                <p className="mt-0.5 line-clamp-1 text-xs text-white/40">
                  {accountRequired
                    ? missingFieldKey
                      ? t("topup.fillAbove")
                      : t("topup.filled")
                    : t("topup.getCode")}
                </p>
              </div>
              <p className="flex-shrink-0 text-sm font-bold text-white">
                {isVariableSelected
                  ? variableTotal !== null
                    ? formatMoney(variableTotal, priceCode)
                    : "—"
                  : formatMoney(activePkg.price, activePkg.priceCode)}
              </p>
            </motion.div>
          )}
        </div>
      </motion.div>

      {/* ── Fixed CTA ── */}
      {/* 16px clear of the nav band — at 8px the two pills read as one stuck
          block on a real phone. */}
      <div className="fixed bottom-[calc(var(--app-nav-total)_+_16px)] left-1/2 z-40 w-full max-w-[430px] -translate-x-1/2 px-4">
        {/* Settlement disclaimer — only shown when the gateway will charge
            in a currency different from the displayed one. Keeps the CTA
            honest without forcing a live FX preview. */}
        {insideTelegram &&
          activePkg &&
          ACQUIRER_BY_METHOD[paymentMethod] &&
          ACQUIRER_BY_METHOD[paymentMethod].currency !== priceCode && (
            <p className="mb-2 text-center text-[11px] text-white/45" role="note">
              {t("topup.settlement", {
                currency: ACQUIRER_BY_METHOD[paymentMethod].currency,
                acquirer: ACQUIRER_BY_METHOD[paymentMethod].label,
              })}
            </p>
          )}
        {!insideTelegram && TELEGRAM_DEEP_LINK ? (
          <motion.a
            whileTap={{ scale: 0.97 }}
            href={TELEGRAM_DEEP_LINK}
            className="flex w-full items-center justify-center gap-2 rounded-2xl py-4 text-base font-bold tracking-wide transition-all"
            style={{
              background: "hsl(var(--primary))",
              color: "#000",
              boxShadow: "0 0 16px hsl(var(--primary) / 0.25)",
            }}
          >
            <Send size={16} />
            {t("topup.openInTgCta")}
          </motion.a>
        ) : activePkg ? (
          <motion.button
            whileTap={{ scale: 0.97 }}
            onClick={handlePayment}
            disabled={isProcessing || !insideTelegram || !variableAmountReady}
            className="flex w-full items-center justify-center gap-2 rounded-2xl py-4 text-base font-bold tracking-wide transition-all"
            style={{
              background:
                isProcessing || !insideTelegram || !variableAmountReady
                  ? "hsl(var(--primary) / 0.45)"
                  : "hsl(var(--primary))",
              color: "#000",
              boxShadow:
                isProcessing || !insideTelegram || !variableAmountReady
                  ? "none"
                  : "0 0 16px hsl(var(--primary) / 0.25)",
            }}
            data-testid="btn-pay"
          >
            {isProcessing
              ? t("topup.processingBtn")
              : !insideTelegram
                ? t("topup.availableInTg")
                : (variableAmountReason ?? (
                    <>
                      {t("topup.pay")}
                      <ChevronRight size={18} strokeWidth={2.5} />
                    </>
                  ))}
          </motion.button>
        ) : null}
      </div>
    </>
  );
}

// ─── Package card ─────────────────────────────────────────────────────────────
function PackageCard({
  pkg,
  active,
  fallbackImage,
  onSelect,
}: {
  pkg: Package;
  active: boolean;
  fallbackImage: string | null;
  onSelect: () => void;
}) {
  const { t } = useT();
  return (
    <button
      onClick={onSelect}
      className="relative rounded-2xl p-3.5 text-left transition-all duration-150"
      style={{
        background: active ? "hsl(var(--surface-3))" : "hsl(var(--surface-2))",
        border: active ? "1.5px solid hsl(var(--primary) / 0.8)" : "1px solid hsl(var(--border))",
        boxShadow: active ? "0 0 0 3px hsl(var(--primary) / 0.1)" : "none",
      }}
      data-testid={`btn-pkg-${pkg.id}`}
    >
      {pkg.badge && (
        <div
          className="absolute -top-2 left-3 rounded-md px-2 py-0.5 text-[9px] font-bold tracking-wider"
          style={{ background: pkg.badge.color, color: "#fff" }}
        >
          {pkg.badge.label}
        </div>
      )}

      {active && (
        <div
          className="absolute right-2.5 top-2.5 flex h-5 w-5 items-center justify-center rounded-full"
          style={{ background: "hsl(var(--primary))" }}
        >
          <Check size={11} strokeWidth={3} className="text-black" />
        </div>
      )}

      <div className="mb-1.5 flex items-center gap-2">
        <PackageThumb pkg={pkg} fallback={fallbackImage} />
        <span className="text-base font-bold leading-none text-white">{pkg.label}</span>
      </div>

      {pkg.region && pkg.region !== "GLOBAL" && (
        <p className="mb-2 text-[11px] text-white/40">
          {t("orders.region", { region: pkg.region })}
        </p>
      )}

      <p className="text-sm font-bold text-white">{formatMoney(pkg.price, pkg.priceCode)}</p>
    </button>
  );
}

function PackageThumb({ pkg, fallback }: { pkg: Package; fallback: string | null }) {
  const src = pkg.imageUrl ?? fallback;
  if (src) {
    return (
      <div className="h-9 w-9 flex-shrink-0 overflow-hidden rounded-xl bg-black/30">
        <SafeImage src={src} className="h-full w-full object-cover" />
      </div>
    );
  }
  // No image — show a small chip with whatever non-numeric part of the
  // denomination we have (e.g. "UC", "VP", "1 мес").
  const tag = pkg.label.replace(/^[\s\d.,]+/, "").trim() || "—";
  return (
    <div
      className="flex h-9 w-9 items-center justify-center rounded-xl text-[10px] font-bold text-black"
      style={{ background: "hsl(var(--primary))" }}
    >
      {tag.slice(0, 4).toUpperCase()}
    </div>
  );
}

// ─── Variable-amount panel (Steam wallet top-up) ──────────────────────────────
/**
 * Replaces the package grid for a variable-amount SKU: the customer types a
 * dollar amount instead of picking a denomination. `pkg.ratePerDollar` is the
 * localised price of ONE dollar (the SKU's `price_usd` is a `1`-placeholder) —
 * `null` means the FX trust gate rejected the live rate, so the product isn't
 * sellable right now and we render that instead of a price of zero.
 */
function VariableAmountPanel({
  pkg,
  value,
  onChange,
  total,
  error,
}: {
  pkg: Package;
  value: string;
  onChange: (v: string) => void;
  total: number | null;
  error: "below" | "above" | "precision" | null;
}) {
  const { t } = useT();
  const rate = pkg.ratePerDollar;

  if (!rate) {
    return (
      <p className="rounded-2xl border border-dashed border-white/10 p-6 text-center text-sm text-white/40">
        {t("topup.priceUnavailable")}
      </p>
    );
  }

  const errorMessage =
    error === "below"
      ? t("topup.amountBelow", { min: formatMoney(pkg.minAmountUsd ?? 0, "USD") })
      : error === "above"
        ? t("topup.amountAbove", { max: formatMoney(pkg.maxAmountUsd ?? 0, "USD") })
        : error === "precision"
          ? t("topup.amountPrecision")
          : null;

  return (
    <div
      className="rounded-2xl p-4"
      style={{ background: "hsl(var(--surface-2))", border: "1px solid hsl(var(--border))" }}
    >
      <label className="block">
        <span className="mb-1.5 block text-xs font-semibold text-white/50">
          {t("topup.amountLabel")}
        </span>
        <div className="relative">
          <span
            className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-base font-bold text-white/40"
            aria-hidden="true"
          >
            $
          </span>
          <input
            type="text"
            inputMode="decimal"
            value={value}
            onChange={(e) => {
              onChange(e.target.value);
            }}
            placeholder={t("topup.amountPlaceholder")}
            className="h-12 w-full rounded-xl border border-white/10 bg-black/20 pl-7 pr-3 text-lg font-bold text-white outline-none transition focus:border-white/25"
            data-testid="input-amount"
          />
        </div>
        {errorMessage && (
          <p className="mt-1.5 text-xs font-medium" style={{ color: "rgb(252, 165, 165)" }}>
            {errorMessage}
          </p>
        )}
      </label>

      <div className="mt-3 flex items-center justify-between rounded-xl bg-black/15 px-3 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-xs text-white/50">
            {t("topup.ratePerDollar", { rate: formatMoney(rate.amount, rate.currency) })}
          </span>
          <span
            className="flex-shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-bold"
            style={{ background: "hsl(var(--primary) / 0.15)", color: "hsl(var(--primary))" }}
          >
            {t("topup.zeroFee")}
          </span>
        </div>
        {total !== null && (
          <span className="flex-shrink-0 text-sm font-bold text-white">
            {formatMoney(total, rate.currency)}
          </span>
        )}
      </div>
    </div>
  );
}

// ─── Loading skeletons ────────────────────────────────────────────────────────
function PageSkeleton({ onBack }: { onBack: () => void }) {
  const { t } = useT();
  return (
    <div className="pb-32">
      <div className="relative h-56 overflow-hidden bg-gradient-to-br from-slate-800 to-slate-950">
        <div className="absolute left-4 top-12 z-10">
          <button
            onClick={onBack}
            className="flex h-9 w-9 items-center justify-center rounded-full border border-white/10 bg-black/50 backdrop-blur-md"
            aria-label={t("common.back")}
          >
            <ArrowLeft size={16} className="text-white" />
          </button>
        </div>
      </div>
      <div className="space-y-4 px-4 pt-5">
        <Skeleton className="h-12 w-full" />
        <PackagesSkeleton />
      </div>
    </div>
  );
}

function PackagesSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-2.5">
      {[0, 1, 2, 3].map((i) => (
        <Skeleton key={i} className="h-24 rounded-2xl" />
      ))}
    </div>
  );
}
