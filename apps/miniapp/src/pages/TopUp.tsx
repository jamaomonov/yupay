import { motion } from "framer-motion";
import {
  ArrowLeft,
  Check,
  ChevronRight,
  ExternalLink,
  Package as PackageIcon,
  RotateCcw,
  Send,
  Settings,
  ShieldCheck,
  Star,
  Wallet as WalletIcon,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useParams } from "wouter";

import type { PlayerCheckResult } from "@/lib/player-check";

import { ConfirmPaymentDialog } from "@/components/ConfirmPaymentDialog";
import { DynamicFields, pickLocalized } from "@/components/DynamicFields";
import { ReviewsSheet } from "@/components/ReviewsSheet";
import { SafeImage } from "@/components/ui/safe-image";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/use-toast";
import { BOT_LINK } from "@/lib/bot-link";
import { getBrandShape, rememberBrandShape } from "@/lib/brand-shape";
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
import {
  methodVisibility,
  providerStatusMap,
  useAvailableProviders,
  useCheckout,
} from "@/lib/orders";
import { ACQUIRER_BY_METHOD, PAYMENT_METHODS, PROVIDER_BY_METHOD } from "@/lib/payment-methods";
import { mergeCheckResult } from "@/lib/player-check-state";
import { getRecentFulfillment, rememberFulfillment } from "@/lib/recent-checkout";
import { packagePrice, visibleStarPackages } from "@/lib/star-packages";
import { haptic, isInsideTelegram, openExternalLink, setClosingConfirmation } from "@/lib/telegram";
import { useDocumentTitle } from "@/lib/use-document-title";
import { cn } from "@/lib/utils";
import {
  amountError,
  boundToUnits,
  parseAmount,
  tierPrice,
  toUsd,
  unitAmountError,
  unitsPerUsd,
} from "@/lib/variable-amount";
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
  amountUnit: string | null;
  unitsPerUsd: number | null;
  units: number | null;
  minAmountUsd: number | null;
  maxAmountUsd: number | null;
  // Admin-configured quantity bounds for a unit SKU (Telegram Stars): the
  // customer types/taps a whole number of `amountUnit` directly — no dollar
  // conversion, unlike `minAmountUsd`/`maxAmountUsd` above. Both null means
  // this package isn't sold by typed quantity.
  minQty: number | null;
  maxQty: number | null;
  /** Localised price of one dollar. `null` means the FX trust gate rejected
   *  the live rate — not sellable right now, never a price of zero. */
  ratePerDollar: { amount: number; currency: string } | null;
  /** False only when the supplier has run out of codes. */
  inStock: boolean;
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
    amountUnit: api.amountUnit,
    unitsPerUsd: api.unitsPerUsd,
    units: api.units,
    minAmountUsd: api.minAmountUsd,
    maxAmountUsd: api.maxAmountUsd,
    minQty: api.minQty,
    maxQty: api.maxQty,
    ratePerDollar: api.ratePerDollar,
    inStock: api.inStock,
  };
}

/**
 * Sold as a typed (or tapped) integer quantity of `amountUnit` — Telegram
 * Stars — checked out as `{ sku_id, qty }` with no `amount_usd`. Mirrors
 * `yupay.modules.catalog.unit_sku.is_unit_sku` on the server. Until the Stars
 * seed lands (a later task), `tg-stars-any` is still `variableAmount`, so it
 * takes the old free-amount + package-tiers path below rather than this one —
 * the two are mutually exclusive by construction, same as on the server.
 */
function isUnitPackage(p: Package): boolean {
  return !p.variableAmount && p.amountUnit != null && p.minQty != null && p.maxQty != null;
}

const DEFAULT_PAYMENT_METHOD = PAYMENT_METHODS[0]?.id ?? "click";

// When the user opens the miniapp in a plain browser we can't take payment
// (auth is bound to Telegram initData). Deep-link them back into the bot
// rather than letting them fill the whole form and bouncing at submit.
const TELEGRAM_DEEP_LINK = BOT_LINK;

/** Sentinel for "pay from wallet balance" — handled by its own card, not part
 *  of the shared acquirer grid. The backend provider slug is ``wallet``. */
const WALLET_METHOD_ID = "wallet";

// The shared acquirer list carries the external providers (Click already
// resolves to the Mini App's own "click_miniapp" service — see
// payment-methods.ts); the wallet option is checkout-only, so we extend the
// provider map locally for resolution/availability.
const PROVIDER_BY_METHOD_FULL: Record<string, string> = {
  ...PROVIDER_BY_METHOD,
  [WALLET_METHOD_ID]: "wallet",
};

// ISO 4217 currencies YuPay handles that carry no practically-displayed minor
// unit — UZS technically has tiyin, but showing them just renders noisy
// ",00"/",79" suffixes on already-large sums. Mirrors packages/utils/money.ts.
const ZERO_DECIMAL_CURRENCIES = new Set(["UZS"]);

function formatMoney(value: number, code: string): string {
  const locale = getActiveLocale();
  const fractionDigits = ZERO_DECIMAL_CURRENCIES.has(code) ? 0 : 2;
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency: code,
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    }).format(value);
  } catch {
    // Non-ISO pseudocurrency (USDT) — format the number, suffix the code.
    return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value)} ${code}`;
  }
}

// ─── Step heading ──────────────────────────────────────────────────────────────
// `n` is omitted once a section is a standalone screen rather than one of
// several steps in a sequence (the review stage has only one section left to
// number — payment method — and a lone "3" read as "step 3 of 3" when the
// other two are a page away, on the previous screen).
function Step({ n, title, sub }: { n?: number; title: string; sub?: string }) {
  return (
    <div className="mb-3.5 flex items-start gap-3">
      {n !== undefined && (
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
      )}
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

  // The currently picked product within the brand (PUBG UC vs Royale Pass …).
  const [reviewsOpen, setReviewsOpen] = useState(false);
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
  // A gift card is a purchase, not a top-up: there's no account being
  // credited, only a code or activation link handed over after payment.
  // Drives every "пополнение/зачисление"-flavoured string on this page.
  const isVoucher = productQuery.data?.product.kind === "voucher";

  useDocumentTitle(
    game
      ? t(isVoucher ? "topup.docTitleNamedVoucher" : "topup.docTitleNamed", { game: game.name })
      : t("topup.docTitle"),
  );
  const packages: Package[] = useMemo(
    () => (productQuery.data?.packages ?? []).map(adaptPackage),
    [productQuery.data],
  );
  // The Steam wallet top-up is the only variable-amount product today and it
  // has exactly one SKU (a fixed denomination doesn't apply — the customer
  // types the amount). Detected as "every SKU on this product is
  // variable-amount" rather than a product-level flag, since the flag lives
  // on the SKU.
  // Telegram Stars sells eleven packages *and* a free amount, so the two
  // coexist rather than one replacing the other; Steam has only the amount.
  const variablePkg = packages.find((p) => p.variableAmount);
  // Telegram Stars sold as a genuine unit SKU (Task 8): dual-read with the
  // `variablePkg` shape above — a product carries at most one of the two,
  // never both, same as the server (`unit_sku.is_unit_sku`). No pack SKUs
  // sit alongside a unit package, unlike `variablePkg`+`fixedPackages`.
  const unitPkg = packages.find(isUnitPackage);
  const fixedPackages = packages.filter((p) => !p.variableAmount && p.id !== unitPkg?.id);
  const isVariableProduct = packages.length > 0 && fixedPackages.length === 0 && !!variablePkg;

  // Cache it so the next visit's skeleton promises the right form (see
  // lib/brand-shape.ts) — the flag only becomes knowable after the SKUs load,
  // which is after the placeholder has already been drawn.
  useEffect(() => {
    if (packages.length === 0) return;
    rememberBrandShape(gameId, isVariableProduct ? "amount" : "packages");
  }, [gameId, packages.length, isVariableProduct]);

  const me = useMe();
  const checkout = useCheckout();
  const isProcessing = checkout.isPending;
  // Backend tells us which gateways can actually accept a payment right now
  // (mock + whatever real acquirers have been wired). Until the response
  // lands we optimistically treat the catalogue as fully available so the UI
  // doesn't flash a "Скоро" badge across every method on first paint.
  const providersQuery = useAvailableProviders();
  const providerStatusBySlug = useMemo(() => {
    if (!providersQuery.data) return null;
    return providerStatusMap(providersQuery.data);
  }, [providersQuery.data]);
  // Admin-disabled methods are dropped entirely (not just greyed out like
  // `maintenance`), so the grid below sizes its columns to however many
  // remain — otherwise a hidden 4th method (e.g. crypto) leaves a blank
  // column-width gap on the right instead of letting the other three fill it.
  const visiblePaymentMethods = useMemo(
    () =>
      PAYMENT_METHODS.filter(
        (m) => methodVisibility(m.provider, providerStatusBySlug) !== "hidden",
      ),
    [providerStatusBySlug],
  );
  const isMethodAvailable = (methodId: string): boolean => {
    // Wallet eligibility is computed below from the user's balance — the
    // payment-provider list on the server does not know about it.
    if (methodId === WALLET_METHOD_ID) return true;
    // Variable-amount SKUs (Steam wallet top-up) are priced in UZS only —
    // see catalog.service._resolve_variable_price. A non-UZS acquirer would
    // set an order currency the display price was never computed for, so it
    // must never be offered here, independent of the live-providers check
    // below (checked first so it applies even before that query resolves).
    // Follows the selected line, not the product: a mixed product (Telegram
    // Stars) sells packages, which are fine in USD, alongside a free amount,
    // which the server refuses in USD. Gating on the product would let the
    // customer pick a currency checkout then rejects. `selectedPkg` is
    // declared below; this closure only ever runs after it exists.
    const variableChosen = variablePkg !== undefined && selectedPkg === variablePkg.id;
    if (variableChosen) {
      const method = PAYMENT_METHODS.find((m) => m.id === methodId);
      if (method && method.currency !== "UZS") return false;
    }
    // Resolve through the FULL map (not the shared base map) so the
    // availability check agrees with what checkout actually sends —
    // including the wallet sentinel, which only the FULL map carries.
    // Submittable only when the provider is present AND `"active"` —
    // `"maintenance"` and admin-disabled (absent) both fail this check.
    const provider = PROVIDER_BY_METHOD_FULL[methodId];
    return provider !== undefined && methodVisibility(provider, providerStatusBySlug) === "active";
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
  // Mirrors each checkable field's latest player-check result, reported by
  // DynamicFields. Lets "continue" require an actual verification instead of
  // a filled-in box — a mistyped id otherwise sails straight to checkout,
  // and the refund policy says a wrong id after payment is unrecoverable.
  const [checkResults, setCheckResults] = useState<Record<string, PlayerCheckResult | null>>({});
  const [selectedPkg, setSelectedPkg] = useState<string>("");
  // Confirmation before an irreversible payment. Declared here with the other
  // hooks — the component has early returns further down, and a `useState`
  // below one of them is a conditional hook.
  const [confirmOpen, setConfirmOpen] = useState(false);
  // The dollar amount typed for a variable-amount product. Raw string, not a
  // number — see ``@/lib/variable-amount`` for parsing/validation.
  const [amountInput, setAmountInput] = useState<string>("");
  const [paymentMethod, setPaymentMethod] = useState(DEFAULT_PAYMENT_METHOD);
  // The fixed CTA used to jump straight to the confirm dialog from the
  // denomination step, defaulting silently to whichever acquirer came first
  // — a first-time buyer who never scrolled past the packages had no idea
  // other payment methods existed. Splitting the flow into two screens
  // forces the payment-method grid onto the page the buyer actually lands
  // on after tapping the primary button. Kept as in-page state (not a
  // route) so the selected package/fields survive a back-and-forth for free.
  const [stage, setStage] = useState<"select" | "review">("select");

  // If the user has a stale selection (e.g. "card" preserved across a session
  // where the live list now only has "mock", or a non-UZS method carried over
  // from a fixed-price product into a variable-amount one), bounce them to
  // the first live method instead of letting them tap a button that will
  // refuse.
  useEffect(() => {
    if (providerStatusBySlug === null) return;
    if (paymentMethod === "" || isMethodAvailable(paymentMethod)) return;
    // No live acquirer at all → deselect instead of leaving the highlight on
    // a method that renders as maintenance/«Скоро» (selected-but-disabled).
    const fallback = PAYMENT_METHODS.find((m) => isMethodAvailable(m.id));
    setPaymentMethod(fallback ? fallback.id : "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providerStatusBySlug, paymentMethod, isVariableProduct, selectedPkg, variablePkg]);

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
    if (!selectedPkg) {
      // "Купить снова" arrives with ?sku=… — the one case where preselecting
      // is what the buyer asked for, rather than an anchor we chose for them.
      const wanted = new URLSearchParams(window.location.search).get("sku");
      if (wanted && packages.some((p) => p.id === wanted)) setSelectedPkg(wanted);
      return;
    }
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
    setCheckResults({});
    if (!gameId) {
      setSuggestions({});
      return;
    }
    setSuggestions(getRecentFulfillment(gameId)?.fulfillment_data ?? {});
  }, [gameId]);

  if (gamesQuery.isLoading || brandQuery.isLoading) {
    return (
      <PageSkeleton
        slug={gameId}
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
  // A genuine unit SKU (Telegram Stars, once the seed lands): mutually
  // exclusive with `isVariableSelected` by construction, same as the server.
  const isUnitSelected = unitPkg !== undefined && activePkg?.id === unitPkg.id;
  // Parsed only for a variable-amount SKU — a fixed package has nothing to
  // parse. ``null`` covers both "nothing typed yet" and "unparseable".
  const parsedAmount = isVariableSelected ? parseAmount(amountInput) : null;
  const perUsd = activePkg
    ? unitsPerUsd({
        amount_unit: activePkg.amountUnit,
        units_per_usd: activePkg.unitsPerUsd != null ? String(activePkg.unitsPerUsd) : null,
      })
    : null;
  const amountAsUsd =
    parsedAmount === null ? null : perUsd !== null ? toUsd(parsedAmount, perUsd) : parsedAmount;
  const variableAmountErr =
    isVariableSelected && parsedAmount !== null
      ? perUsd !== null
        ? unitAmountError(
            parsedAmount,
            boundToUnits(activePkg?.minAmountUsd ?? 0, perUsd, "min"),
            boundToUnits(activePkg?.maxAmountUsd ?? 0, perUsd, "max"),
          )
        : amountError(parsedAmount, activePkg?.minAmountUsd ?? 0, activePkg?.maxAmountUsd ?? 0)
      : null;
  // Client-side total for display only — the server recomputes the
  // authoritative price from ``amount_usd`` at checkout. While pack SKUs
  // still sit next to the variable line (dual-read until the Stars seed),
  // this must be `tierPrice` — the same rule as `orders.service.tier_price_usd`
  // — or the button shows a linear rate and checkout charges the pack band.
  const tierPacks = useMemo(
    () =>
      packages
        .filter((p) => !p.variableAmount && p.id !== unitPkg?.id && p.units != null && p.price > 0)
        .map((p) => ({ units: p.units ?? 0, price: p.price })),
    [packages, unitPkg?.id],
  );
  const variableTotal = !isVariableSelected
    ? null
    : parsedAmount === null
      ? null
      : tierPacks.length > 0
        ? tierPrice(parsedAmount, tierPacks)
        : amountAsUsd !== null && activePkg?.ratePerDollar
          ? amountAsUsd * activePkg.ratePerDollar.amount
          : null;

  // Same shape as the variable-amount block above, but for a genuine unit SKU
  // (Telegram Stars sold as `{ sku_id, qty }`, no `amount_usd`): the
  // typed/tapped number IS the quantity, `minQty`/`maxQty` are already whole
  // units, and there is no `unitsPerUsd`/`toUsd` conversion to run.
  const parsedQty = isUnitSelected ? parseAmount(amountInput) : null;
  const qtyMin = unitPkg?.minQty ?? 0;
  const qtyMax = unitPkg?.maxQty ?? 0;
  const qtyRate =
    isUnitSelected && unitPkg ? { amount: unitPkg.price, currency: unitPkg.priceCode } : null;
  const qtyErr =
    isUnitSelected && parsedQty !== null ? unitAmountError(parsedQty, qtyMin, qtyMax) : null;
  // `packagePrice` — a flat per-unit rate, never a guessed one.
  const qtyTotal =
    isUnitSelected && parsedQty !== null && qtyRate
      ? packagePrice(parsedQty, qtyRate.amount)
      : null;

  const priceCode = isVariableSelected
    ? (activePkg?.ratePerDollar?.currency ?? currency)
    : (activePkg?.priceCode ?? currency);
  const finalPrice = isVariableSelected
    ? (variableTotal ?? 0)
    : isUnitSelected
      ? (qtyTotal ?? 0)
      : (activePkg?.price ?? 0);
  // Gates the CTA: a variable-amount SKU needs a live rate (the FX trust gate
  // didn't reject it) and a parsed, in-bounds, two-decimals-or-fewer amount; a
  // unit SKU needs the same, but a whole in-bounds quantity instead.
  const variableAmountReady = isVariableSelected
    ? activePkg?.ratePerDollar !== null && parsedAmount !== null && variableAmountErr === null
    : isUnitSelected
      ? qtyRate !== null && parsedQty !== null && qtyErr === null
      : true;
  /** A dollar bound as the buyer reads it — a unit count for a unit-priced SKU,
   *  where quoting "$0.77" back at someone buying Stars is a non-answer. */
  const boundLabel = (usd: number, edge: "min" | "max"): string =>
    perUsd !== null
      ? `${boundToUnits(usd, perUsd, edge).toLocaleString(getActiveLocale())} ${activePkg?.amountUnit ?? ""}`
      : formatMoney(usd, "USD");
  /** Same idea as `boundLabel`, for a unit SKU's already-whole `minQty`/
   *  `maxQty` — no dollar bound to convert. */
  const qtyBoundLabel = (n: number): string =>
    `${n.toLocaleString(getActiveLocale())} ${unitPkg?.amountUnit ?? ""}`;
  // Human-readable reason the CTA is disabled — reused for both the toast
  // (belt-and-suspenders guard in handlePayment) and the button label itself,
  // so the customer sees *why* right on the button, same as the existing
  // "availableInTg" swap below.
  const variableAmountReason: string | null =
    isVariableSelected && !variableAmountReady && activePkg
      ? activePkg.ratePerDollar === null
        ? t("topup.priceUnavailable")
        : variableAmountErr === "below"
          ? t("topup.amountBelow", { min: boundLabel(activePkg.minAmountUsd ?? 0, "min") })
          : variableAmountErr === "above"
            ? t("topup.amountAbove", { max: boundLabel(activePkg.maxAmountUsd ?? 0, "max") })
            : variableAmountErr === "precision"
              ? // Half a star does not exist; a fraction of a dollar cent does.
                t(perUsd !== null ? "topup.amountWhole" : "topup.amountPrecision")
              : t("topup.amountRequired")
      : isUnitSelected && !variableAmountReady
        ? qtyRate === null
          ? t("topup.priceUnavailable")
          : qtyErr === "below"
            ? t("topup.amountBelow", { min: qtyBoundLabel(qtyMin) })
            : qtyErr === "above"
              ? t("topup.amountAbove", { max: qtyBoundLabel(qtyMax) })
              : qtyErr === "precision"
                ? // Half a star does not exist.
                  t("topup.amountWhole")
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
  // A checkable field (`f.check`) with something typed into it but no
  // successful "Проверить" behind that value yet — either it was never
  // pressed, it came back "not found"/errored, or an edit after a pass
  // reset the result to stale (see DynamicFields' `onCheckResult`). Checked
  // after `missingFieldKey` on purpose: an empty required field is "nothing
  // to verify yet", not "unverified".
  const uncheckedFieldKey = requiredFields.find((f) => {
    if (!f.check) return false;
    const v = (fulfillment[f.key] ?? "").trim();
    if (v.length === 0) return false;
    return checkResults[f.key]?.status !== "valid";
  })?.key;

  // One expression for the CTA's disabled state, used by both its styling and
  // its own `disabled` — spelled out three times, they drifted apart easily.
  // `missingFieldKey` belongs here: without it the button stayed lime and
  // enabled with no game id typed, opened the confirmation dialog on an
  // incomplete order, and only rejected it afterwards with a toast.
  const payDisabled =
    isProcessing ||
    !insideTelegram ||
    !variableAmountReady ||
    !activePkg ||
    Boolean(missingFieldKey) ||
    Boolean(uncheckedFieldKey);
  const firstFieldLabel =
    requiredFields[0]?.label?.[locale] ?? requiredFields[0]?.label?.ru ?? t("topup.fieldFallback");
  const fillingHint = accountRequired
    ? t("topup.fillingHint", { field: firstFieldLabel })
    : t("topup.noAccount");

  // A field the supplier can verify (`check`) has already resolved to a
  // nickname in place. Where none can be verified, the dialog is the only
  // place a typo is still catchable, so it asks for an explicit attestation.
  const hasVerifiableField = requiredFields.some((f) => Boolean(f.check));

  // Everything the buyer typed into step 1, for the review screen's order
  // details card — the nickname (once verified) rides along next to the raw
  // id, since that's the strongest "yes, this is the right account" signal
  // the buyer gets before paying.
  const filledAccountFields = requiredFields
    .filter((f) => (fulfillment[f.key] ?? "").trim() !== "")
    .map((f) => {
      const value = fulfillment[f.key] ?? "";
      const checked = f.check ? checkResults[f.key] : null;
      return {
        key: f.key,
        label: pickLocalized(f.label, locale, f.key),
        value,
        nickname: checked?.status === "valid" ? checked.name : null,
      };
    });

  const confirmRows = [
    {
      label: t("topup.confirmItem"),
      value: [game?.name, activePkg?.label].filter(Boolean).join(" · "),
    },
    ...requiredFields
      .filter((f) => (fulfillment[f.key] ?? "").trim() !== "")
      .map((f) => ({
        label: pickLocalized(f.label, locale, f.key),
        value: fulfillment[f.key] ?? "",
      })),
  ];

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
        provider: PROVIDER_BY_METHOD_FULL[paymentMethod] ?? "click_miniapp",
        // Sent as a fixed-2-decimal string so the server never has to
        // round-trip a client float — the server re-validates and re-prices
        // from it regardless.
        ...(isVariableSelected && parsedAmount !== null
          ? // Always dollars on the wire. Six decimals because one unit is
            // rarely a round cent; the server snaps it to a whole unit.
            { amountUsd: (amountAsUsd ?? parsedAmount).toFixed(perUsd !== null ? 6 : 2) }
          : {}),
        // A unit SKU (Telegram Stars) is bought as a real quantity, not the
        // usual single line + `amount_usd` — `variableAmountReady` (part of
        // `payDisabled`) already guarantees `parsedQty` is set by the time we
        // get here; the fallback is an unreachable sentinel.
        ...(isUnitSelected ? { qty: parsedQty ?? 1 } : {}),
      });
      // Remember the fulfilment payload only after the order was accepted by
      // the API — no point caching a half-typed player_id that came back
      // 400. Subsequent visits to this brand pick it back up automatically.
      if (gameId) {
        rememberFulfillment(
          gameId,
          fulfillmentData,
          activePkg ? { id: activePkg.id, label: activePkg.label } : undefined,
        );
      }
      if (result.payment.intent_url && result.payment.provider !== "mock") {
        toast({
          title: t("topup.redirecting"),
          description: result.payment.provider,
        });
        // Hand the acquirer URL to Telegram so it opens in the device browser
        // instead of replacing the Mini App's own WebView. The app itself then
        // moves to the order's status page, so when the customer finishes paying
        // and swipes back to Telegram they land on live order status (which
        // polls for the payment callback), not back on the checkout form.
        openExternalLink(result.payment.intent_url);
        setLocation(`/order/${result.order.id}`);
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

  const goToReview = () => {
    haptic("press");
    setStage("review");
    window.scrollTo({ top: 0 });
  };

  return (
    <>
      {reviewsOpen && gameId && (
        <ReviewsSheet
          brandSlug={gameId}
          onClose={() => {
            setReviewsOpen(false);
          }}
        />
      )}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.22 }}
        className="pb-32"
      >
        {/* ── Review header ── */}
        {/* Only the stage the fixed CTA below actually needs a back path
            for — the select stage still relies on Telegram's own
            BackButton (see PageSkeleton's comment on this route). */}
        {stage === "review" && (
          <div className="flex items-center gap-3 px-4 pb-1 pt-4">
            <button
              type="button"
              onClick={() => {
                setStage("select");
              }}
              className="bg-card border-border flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full border"
              aria-label={t("common.back")}
            >
              <ArrowLeft size={16} className="text-white/70" />
            </button>
            <div className="min-w-0 flex-1">
              <p className="text-base font-bold leading-tight text-white">
                {t("topup.reviewTitle")}
              </p>
              <p className="line-clamp-1 text-xs text-white/40">
                {[game.name, activePkg?.label].filter(Boolean).join(" · ")}
              </p>
            </div>
          </div>
        )}

        {/* ── Hero ── */}
        {stage === "select" && (
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

            {/* Back to the catalog. Telegram's own BackButton covers this
              inside the app, but outside it (a browser tab, a shared link)
              there was no way back at all — this one always works. */}
            <button
              type="button"
              onClick={() => {
                setLocation("/");
              }}
              aria-label={t("common.back")}
              className="absolute left-4 top-12 z-20 flex h-9 w-9 items-center justify-center rounded-full bg-black/40 backdrop-blur-sm"
            >
              <ArrowLeft size={16} className="text-white" />
            </button>

            <div className="absolute bottom-0 left-0 right-0 z-10 flex items-end gap-3 px-4 pb-4">
              <div className="h-14 w-14 flex-shrink-0 overflow-hidden rounded-2xl shadow-xl">
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
                  {/* Single honest signal: fulfilment is automated (supplier API
                    or the code warehouse), not a promised ETA. The 4.9 star
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
                    <Zap size={10} className="text-primary" />
                    <span className="text-primary text-[10px] font-semibold">
                      {t(isVoucher ? "topup.autoIssue" : "topup.autoCredit")}
                    </span>
                  </div>
                  {brandQuery.data?.rating && brandQuery.data.rating.count > 0 && (
                    <button
                      type="button"
                      onClick={() => {
                        setReviewsOpen(true);
                      }}
                      className="flex items-center gap-1 rounded-full px-2 py-0.5"
                      style={{ background: "rgba(255,255,255,0.08)" }}
                    >
                      <Star size={10} className="fill-amber-400 text-amber-400" />
                      <span className="text-[10px] font-semibold text-white">
                        {brandQuery.data.rating.avg.toFixed(1)}
                      </span>
                      <span className="text-[10px] text-white/50">
                        ({brandQuery.data.rating.count})
                      </span>
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Telegram-only banner — surfaced at the top of the funnel, before
            the user invests time filling fulfilment fields and picking a
            package. */}
        {stage === "select" && !insideTelegram && (
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
        {stage === "select" && (
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
                        <div
                          className={`flex h-6 w-6 flex-shrink-0 items-center justify-center overflow-hidden rounded-md ${
                            p.image_url ? "" : "bg-black/30"
                          }`}
                        >
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
                  onCheckResult={(key, result) => {
                    setCheckResults((prev) => mergeCheckResult(prev, key, result));
                  }}
                  knownResults={checkResults}
                />
              </div>
            )}

            {/* Step 2 — Packages */}
            <div>
              <Step
                n={accountRequired ? 2 : 1}
                // One heading over the whole choice. When a free amount and
                // packages are both on offer they are two ways of answering the
                // same question, so the step says so instead of naming only one.
                title={
                  variablePkg && fixedPackages.length > 0
                    ? t("topup.pickPackOrAmount")
                    : t(isVoucher ? "topup.pickDenomination" : "topup.howMuch")
                }
                sub={t(isVoucher ? "topup.voucherDeliveryNote" : "topup.creditWithinMinutes")}
              />

              {productQuery.isLoading && <PackagesSkeleton shape={getBrandShape(gameId)} />}
              {!productQuery.isLoading && packages.length === 0 && (
                <p className="rounded-2xl border border-dashed border-white/10 p-6 text-center text-sm text-white/40">
                  {t("topup.noPositions")}
                </p>
              )}
              {/* Packages and a free amount can coexist — Telegram Stars sells
                both. The field goes first and the packages read as its presets
                underneath; the other way round it looked like an afterthought
                below a wall of tiles. Tapping the field is what selects the
                variable line, the same gesture selecting a package is. */}
              {!productQuery.isLoading && variablePkg && (
                <div
                  onFocusCapture={() => {
                    if (selectedPkg !== variablePkg.id) setSelectedPkg(variablePkg.id);
                  }}
                >
                  <VariableAmountPanel
                    pkg={variablePkg}
                    value={selectedPkg === variablePkg.id ? amountInput : ""}
                    selected={selectedPkg === variablePkg.id}
                    onChange={(next) => {
                      if (selectedPkg !== variablePkg.id) setSelectedPkg(variablePkg.id);
                      setAmountInput(next);
                    }}
                    total={selectedPkg === variablePkg.id ? variableTotal : null}
                    error={selectedPkg === variablePkg.id ? variableAmountErr : null}
                  />
                </div>
              )}
              {!productQuery.isLoading && unitPkg && (
                <div
                  onFocusCapture={() => {
                    if (selectedPkg !== unitPkg.id) setSelectedPkg(unitPkg.id);
                  }}
                >
                  <UnitAmountPanel
                    pkg={unitPkg}
                    value={selectedPkg === unitPkg.id ? amountInput : ""}
                    selected={selectedPkg === unitPkg.id}
                    onChange={(next) => {
                      if (selectedPkg !== unitPkg.id) setSelectedPkg(unitPkg.id);
                      setAmountInput(next);
                    }}
                    total={selectedPkg === unitPkg.id ? qtyTotal : null}
                    error={selectedPkg === unitPkg.id ? qtyErr : null}
                  />
                  <UnitPackTiles
                    pkg={unitPkg}
                    qty={selectedPkg === unitPkg.id ? parseAmount(amountInput) : null}
                    fallbackImage={productImage}
                    onPick={(n) => {
                      haptic("select");
                      setSelectedPkg(unitPkg.id);
                      setAmountInput(String(n));
                    }}
                  />
                </div>
              )}
              {fixedPackages.length > 0 && (
                <div
                  className={cn("grid grid-cols-2 gap-2.5", (variablePkg ?? unitPkg) && "mt-2.5")}
                >
                  {fixedPackages.map((pkg) => (
                    <PackageCard
                      key={pkg.id}
                      pkg={pkg}
                      active={selectedPkg === pkg.id}
                      fallbackImage={productImage}
                      onSelect={() => {
                        haptic("select");
                        setSelectedPkg(pkg.id);
                        // A package and the free amount are two answers to one
                        // question. Dropping the typed number here keeps the
                        // field from resurrecting it when it is focused again.
                        setAmountInput("");
                      }}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {stage === "review" && (
          <div className="space-y-7 px-4 pt-2">
            {/* Order details — moved to the top of the review screen so the
              buyer sees what they're paying for (and to whom — the id and,
              once verified, the nickname behind it) before picking how, instead
              of scrolling past the payment grid to find it below. */}
            {activePkg && (
              <div>
                <p className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-white/50">
                  {t("topup.orderDetailsTitle")}
                </p>
                <motion.div
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="rounded-2xl p-3"
                  style={{
                    background: "hsl(var(--surface-2))",
                    border: "1px solid hsl(var(--border))",
                  }}
                >
                  <div className="flex items-center gap-3">
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
                        : isUnitSelected
                          ? qtyTotal !== null
                            ? formatMoney(qtyTotal, priceCode)
                            : "—"
                          : formatMoney(activePkg.price, activePkg.priceCode)}
                    </p>
                  </div>
                  {/* Every field the buyer typed on step 1 — with the resolved
                      nickname next to the raw id wherever "Проверить" confirmed
                      one, so this is the last look before the acquirer redirect
                      shows the account, not just that a box was non-empty. */}
                  {filledAccountFields.length > 0 && (
                    <div
                      className="mt-3 space-y-2 border-t pt-3"
                      style={{ borderColor: "hsl(var(--border))" }}
                    >
                      {filledAccountFields.map((f) => (
                        <div key={f.key} className="flex items-center justify-between gap-3">
                          <span className="text-xs text-white/40">{f.label}</span>
                          <span className="min-w-0 truncate text-right text-[13px] font-semibold text-white">
                            {f.nickname ? (
                              <>
                                {f.nickname}{" "}
                                <span className="font-mono text-white/45">· {f.value}</span>
                              </>
                            ) : (
                              f.value
                            )}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </motion.div>
              </div>
            )}

            {/* Payment method — its own screen now, so it no longer carries a
              step number ("3 of 3" read oddly once the other two steps live a
              page back). */}
            <div>
              <Step title={t("topup.paymentMethod")} sub={t("topup.paymentSafe")} />

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

              <div
                className="mb-3 grid gap-2"
                style={{
                  gridTemplateColumns: `repeat(${visiblePaymentMethods.length}, minmax(0, 1fr))`,
                }}
              >
                {visiblePaymentMethods.map((m) => {
                  const maintenance =
                    methodVisibility(m.provider, providerStatusBySlug) === "maintenance";
                  const available = isMethodAvailable(m.id);
                  // An unavailable method can never look selected.
                  const active = paymentMethod === m.id && available;
                  const unavailableLabel = maintenance ? t("payment.maintenance") : t("topup.soon");
                  const badgeLabel = maintenance ? t("payment.maintenanceShort") : t("topup.soon");
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
                      title={available ? undefined : unavailableLabel}
                      className="relative flex flex-col items-center gap-1 overflow-hidden rounded-2xl py-3 transition-all duration-150 disabled:cursor-not-allowed"
                      style={{
                        background: active ? "hsl(var(--surface-3))" : "hsl(var(--surface-2))",
                        border: active
                          ? "1.5px solid hsl(var(--primary) / 0.8)"
                          : "1px solid hsl(var(--border))",
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
                      {/* One strip for both unavailable reasons, pinned to the
                          top edge and out of the flow: "Технические работы" as
                          a third line under the name pushed this tile taller
                          than its neighbours. The strip keeps full contrast
                          while the mark and the name dim below it. */}
                      {!available && (
                        <span
                          className="absolute inset-x-0 top-0 z-10 py-[3px] text-center text-[9px] font-bold uppercase leading-none tracking-[0.06em]"
                          style={{
                            background: "hsl(var(--surface-3))",
                            borderBottom: "1px solid hsl(var(--border))",
                            color: "hsl(var(--muted-foreground))",
                          }}
                        >
                          {badgeLabel}
                        </span>
                      )}
                      <span
                        className={cn(
                          "flex h-8 w-8 items-center justify-center overflow-hidden rounded-md",
                          !available && "opacity-60 grayscale",
                        )}
                      >
                        <img src={m.icon} alt={m.name} className="h-full w-full object-cover" />
                      </span>
                      <span
                        className={cn(
                          "text-[11px] font-bold leading-none",
                          active && available
                            ? "text-white"
                            : available
                              ? "text-white/50"
                              : "text-white/35",
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
          </div>
        )}
      </motion.div>

      {/* ── Fixed CTA ── */}
      {/* 16px clear of the nav band — at 8px the two pills read as one stuck
          block on a real phone. */}
      <div className="fixed bottom-[calc(var(--app-nav-total)_+_16px)] left-1/2 z-40 w-full max-w-[430px] -translate-x-1/2 px-4">
        {/* Settlement disclaimer — only shown on the review screen, where a
            payment method is actually being chosen. Keeps the CTA honest
            without forcing a live FX preview. */}
        {stage === "review" &&
          insideTelegram &&
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
        ) : stage === "select" ? (
          /* "Далее" only — no acquirer, no total. Committing to a payment
             method (and finding out others exist) happens on its own screen
             right after this, not silently via whatever the grid defaulted
             to below the fold. Same disabled-with-the-reason pattern as the
             pay button used to carry alone. */
          <motion.button
            whileTap={{ scale: 0.97 }}
            onClick={goToReview}
            disabled={payDisabled}
            className="flex w-full items-center justify-center gap-2 rounded-2xl py-4 text-base font-bold tracking-wide transition-all"
            style={{
              background: payDisabled ? "hsl(var(--primary) / 0.45)" : "hsl(var(--primary))",
              color: "#000",
              boxShadow: payDisabled ? "none" : "0 0 16px hsl(var(--primary) / 0.25)",
            }}
            data-testid="btn-continue"
          >
            {!insideTelegram
              ? t("topup.availableInTg")
              : !activePkg
                ? t("topup.pickPackageBody")
                : missingFieldKey
                  ? t("topup.fillFieldCta", {
                      field: pickLocalized(
                        requiredFields.find((f) => f.key === missingFieldKey)?.label,
                        locale,
                        missingFieldKey,
                      ),
                    })
                  : uncheckedFieldKey
                    ? t("topup.verifyFieldCta", {
                        field: pickLocalized(
                          requiredFields.find((f) => f.key === uncheckedFieldKey)?.label,
                          locale,
                          uncheckedFieldKey,
                        ),
                      })
                    : (variableAmountReason ?? (
                        <>
                          {t("topup.continueCta")}
                          <ChevronRight size={18} strokeWidth={2.5} />
                        </>
                      ))}
          </motion.button>
        ) : (
          /* Review screen's own CTA — the only place money actually moves,
             now that a method has to be picked to get here at all. */
          <motion.button
            whileTap={{ scale: 0.97 }}
            onClick={() => {
              haptic("press");
              setConfirmOpen(true);
            }}
            disabled={payDisabled}
            className="flex w-full items-center justify-center gap-2 rounded-2xl py-4 text-base font-bold tracking-wide transition-all"
            style={{
              background: payDisabled ? "hsl(var(--primary) / 0.45)" : "hsl(var(--primary))",
              color: "#000",
              boxShadow: payDisabled ? "none" : "0 0 16px hsl(var(--primary) / 0.25)",
            }}
            data-testid="btn-pay"
          >
            {isProcessing
              ? t("topup.processingBtn")
              : !insideTelegram
                ? t("topup.availableInTg")
                : !activePkg
                  ? t("topup.pickPackageBody")
                  : missingFieldKey
                    ? // Name the field rather than a bare "заполните поле": with
                      // two fields (id + server) the buyer would have to guess
                      // which one is missing.
                      t("topup.fillFieldCta", {
                        field: pickLocalized(
                          requiredFields.find((f) => f.key === missingFieldKey)?.label,
                          locale,
                          missingFieldKey,
                        ),
                      })
                    : uncheckedFieldKey
                      ? t("topup.verifyFieldCta", {
                          field: pickLocalized(
                            requiredFields.find((f) => f.key === uncheckedFieldKey)?.label,
                            locale,
                            uncheckedFieldKey,
                          ),
                        })
                      : (variableAmountReason ?? (
                          <>
                            {t("topup.pay")} · {formatMoney(finalPrice, priceCode)}
                            <ChevronRight size={18} strokeWidth={2.5} />
                          </>
                        ))}
          </motion.button>
        )}
      </div>

      <ConfirmPaymentDialog
        open={confirmOpen}
        rows={confirmRows}
        total={formatMoney(finalPrice, priceCode)}
        warning={t(accountRequired ? "topup.confirmWarning" : "topup.confirmWarningVoucher")}
        // A field-less product (a gift card) has nothing to attest to — the
        // old `!hasVerifiableField` alone was true for it too (`.some()` on
        // an empty array), which blocked checkout on a checkbox that
        // referenced an account field the buyer never saw.
        needsAttestation={accountRequired && !hasVerifiableField}
        onOpenChange={setConfirmOpen}
        onConfirm={() => {
          setConfirmOpen(false);
          void handlePayment();
        }}
      />
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
  // Gift cards run out. A sold-out card stays on the grid rather than
  // disappearing — a denomination that vanishes between visits reads as a
  // pricing change, while a dimmed one reads as "come back later".
  const soldOut = !pkg.inStock;
  return (
    <button
      onClick={onSelect}
      disabled={soldOut}
      aria-disabled={soldOut}
      className={`relative rounded-2xl p-3.5 text-left transition-all duration-150 ${
        soldOut ? "cursor-not-allowed opacity-45" : ""
      }`}
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

      <p className="text-sm font-bold text-white">
        {soldOut ? t("topup.outOfStock") : formatMoney(pkg.price, pkg.priceCode)}
      </p>
    </button>
  );
}

function PackageThumb({ pkg, fallback }: { pkg: Package; fallback: string | null }) {
  const src = pkg.imageUrl ?? fallback;
  // No image — show a small chip with whatever non-numeric part of the
  // denomination we have (e.g. "UC", "VP", "1 мес"). Also doubles as the
  // SafeImage fallback below, so a broken URL degrades to this instead of a
  // blank square now that the wrapper no longer carries its own background.
  const tag = pkg.label.replace(/^[\s\d.,]+/, "").trim() || "—";
  const tagChip = (
    <div
      className="flex h-9 w-9 items-center justify-center rounded-xl text-[10px] font-bold text-black"
      style={{ background: "hsl(var(--primary))" }}
    >
      {tag.slice(0, 4).toUpperCase()}
    </div>
  );
  if (src) {
    return (
      <div className="h-9 w-9 flex-shrink-0 overflow-hidden rounded-xl">
        <SafeImage src={src} className="h-full w-full object-cover" fallback={tagChip} />
      </div>
    );
  }
  return tagChip;
}

// ─── Variable-amount panel (free amount) ──────────────────────────────────────
/**
 * The free-amount field of a product that carries a variable-amount SKU: the
 * customer types how much they want instead of picking a denomination.
 *
 * It sits ABOVE the package grid, and the two are mutually exclusive — tapping
 * a package clears the field, typing in the field selects this line. `selected`
 * is what makes that visible: the card takes the same lime border an active
 * `PackageCard` does.
 *
 * Everything on screen is denominated in the SKU's own `amountUnit` (Stars)
 * when it has one, and in dollars when it doesn't (the Steam wallet, where the
 * dollar IS the unit). Dollars stay internal for a unit-priced SKU: quoting a
 * rate at someone buying Stars answers a question they did not ask, which is
 * why there is no rate or fee row here — only what they typed, what it costs,
 * and how far the field can go.
 *
 * `pkg.ratePerDollar` is the localised price of ONE dollar (the SKU's
 * `price_usd` is a `1`-placeholder) — `null` means the FX trust gate rejected
 * the live rate, so the product isn't sellable right now and we render that
 * instead of a price of zero.
 */
function VariableAmountPanel({
  pkg,
  value,
  selected,
  onChange,
  total,
  error,
}: {
  pkg: Package;
  value: string;
  /** True while this line is the current selection — drives the active accent. */
  selected: boolean;
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

  // When the field is denominated in something else (stars), every number the
  // customer reads is in that unit — quoting dollars back at them would be
  // answering a question they did not ask.
  const perUsd = unitsPerUsd({
    amount_unit: pkg.amountUnit,
    units_per_usd: pkg.unitsPerUsd != null ? String(pkg.unitsPerUsd) : null,
  });
  const unit = perUsd !== null ? (pkg.amountUnit ?? "") : null;
  const minUsd = pkg.minAmountUsd ?? 0;
  const maxUsd = pkg.maxAmountUsd ?? 0;
  /** A dollar bound as a bare number the customer reads — a unit count, or a
   *  dollar sum. The unit word itself is appended only where it isn't already
   *  on the label. */
  const bound = (usd: number, edge: "min" | "max") =>
    perUsd !== null
      ? boundToUnits(usd, perUsd, edge).toLocaleString(getActiveLocale())
      : formatMoney(usd, "USD");
  const withUnit = (text: string) => (unit ? `${text} ${unit}` : text);
  const errorMessage =
    error === "below"
      ? t("topup.amountBelow", { min: withUnit(bound(minUsd, "min")) })
      : error === "above"
        ? t("topup.amountAbove", { max: withUnit(bound(maxUsd, "max")) })
        : error === "precision"
          ? unit
            ? t("topup.amountWhole")
            : t("topup.amountPrecision")
          : null;

  return (
    <div
      className="rounded-2xl p-4"
      style={{
        background: "hsl(var(--surface-2))",
        border: "1px solid hsl(var(--border))",
      }}
    >
      <label className="block">
        <span className="mb-1.5 block text-xs font-semibold text-white/50">
          {unit ? t("topup.amountUnitLabel", { unit }) : t("topup.amountLabel")}
        </span>
        <div className="relative">
          {/* The dollar SKU (Steam) carries its unit as a prefix, the way money
              is written; a named unit reads as a suffix after the count. Both
              are decorative — the label above already names the unit. */}
          {unit === null && (
            <span
              className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-base font-bold text-white/40"
              aria-hidden="true"
            >
              $
            </span>
          )}
          <input
            type="text"
            // Whole units only (half a star does not exist) → the numeric pad;
            // dollars take cents, so they keep the decimal one.
            inputMode={unit ? "numeric" : "decimal"}
            value={value}
            onChange={(e) => {
              onChange(e.target.value);
            }}
            // A plain number, not "e.g. 10": the placeholder doubles as the
            // smallest amount the field accepts. Dollars keep today's wording.
            placeholder={unit ? bound(minUsd, "min") : t("topup.amountPlaceholder")}
            // 48px tall and 18px of type: above the 44px tap target, and above
            // the 16px below which iOS Safari zooms the page on focus.
            className={cn(
              "h-12 w-full rounded-xl border text-lg font-bold text-white outline-none transition",
              // Lighter than the panel behind it: `bg-black/20` on a dark
              // surface read as a hole punched in the card rather than a field.
              "bg-white/[0.06]",
              selected
                ? "border-[hsl(var(--primary)/0.8)] shadow-[0_0_0_3px_hsl(var(--primary)/0.12)]"
                : "border-white/10 focus:border-white/25",
              unit ? "pl-3.5 pr-24" : "pl-7 pr-3",
            )}
            data-testid="input-amount"
          />
          {unit !== null && (
            <span
              className="pointer-events-none absolute right-3.5 top-1/2 max-w-[80px] -translate-y-1/2 truncate text-sm font-semibold text-white/40"
              aria-hidden="true"
            >
              {unit}
            </span>
          )}
        </div>
      </label>

      {/* The only two numbers under the field: how far it can go, and what the
          typed amount costs. No rate, no fee — see the component docstring. */}
      <div className="mt-2 flex items-center justify-between gap-3">
        <span className="min-w-0 truncate text-xs text-white/45">
          {t("topup.amountRange", { min: bound(minUsd, "min"), max: bound(maxUsd, "max") })}
        </span>
        {total !== null && (
          <span className="flex-shrink-0 text-sm font-bold text-white">
            {formatMoney(total, rate.currency)}
          </span>
        )}
      </div>

      {errorMessage && (
        <p className="mt-1.5 text-xs font-medium" style={{ color: "rgb(252, 165, 165)" }}>
          {errorMessage}
        </p>
      )}
    </div>
  );
}

// ─── Unit-quantity panel (Telegram Stars, checked out as {sku_id, qty}) ──────
/**
 * The free-typed-quantity field for a genuine unit SKU (`minQty`/`maxQty` set,
 * `variableAmount` false — see `isUnitPackage`) — the sibling of
 * `VariableAmountPanel` for a package whose bounds are already whole units,
 * not a USD range to convert. No `unitsPerUsd`/`toUsd` here: what's typed IS
 * the quantity, and `pkg.price` (the SKU's own `display_price`) prices it
 * directly via `packagePrice` (see `@/lib/star-packages` for why there's no
 * volume-discount band like `tierPrice`'s packages).
 *
 * Renders above the tap-to-fill tiles the same way `VariableAmountPanel`
 * renders above `fixedPackages` — typing and tapping a tile both just set
 * this package's selection and its quantity.
 */
function UnitAmountPanel({
  pkg,
  value,
  selected,
  onChange,
  total,
  error,
}: {
  pkg: Package;
  value: string;
  /** True while this line is the current selection — drives the active accent. */
  selected: boolean;
  onChange: (v: string) => void;
  total: number | null;
  error: "below" | "above" | "precision" | null;
}) {
  const { t } = useT();
  const rate = { amount: pkg.price, currency: pkg.priceCode };
  const unit = pkg.amountUnit ?? "";
  const min = pkg.minQty ?? 0;
  const max = pkg.maxQty ?? 0;

  const errorMessage =
    error === "below"
      ? t("topup.amountBelow", { min: `${min.toLocaleString(getActiveLocale())} ${unit}` })
      : error === "above"
        ? t("topup.amountAbove", { max: `${max.toLocaleString(getActiveLocale())} ${unit}` })
        : error === "precision"
          ? t("topup.amountWhole")
          : null;

  return (
    <div
      className="rounded-2xl p-4"
      style={{
        background: "hsl(var(--surface-2))",
        border: "1px solid hsl(var(--border))",
      }}
    >
      <label className="block">
        <span className="mb-1.5 block text-xs font-semibold text-white/50">
          {t("topup.amountUnitLabel", { unit })}
        </span>
        <div className="relative">
          <input
            type="text"
            // Whole units only — half a star does not exist.
            inputMode="numeric"
            value={value}
            onChange={(e) => {
              onChange(e.target.value);
            }}
            // A plain number, not "e.g. 50": the placeholder doubles as the
            // smallest amount the field accepts.
            placeholder={String(min)}
            // 48px tall and 18px of type: above the 44px tap target, and above
            // the 16px below which iOS Safari zooms the page on focus.
            className={cn(
              "h-12 w-full rounded-xl border pl-3.5 pr-24 text-lg font-bold text-white outline-none transition",
              // Lighter than the panel behind it: `bg-black/20` on a dark
              // surface read as a hole punched in the card rather than a field.
              "bg-white/[0.06]",
              selected
                ? "border-[hsl(var(--primary)/0.8)] shadow-[0_0_0_3px_hsl(var(--primary)/0.12)]"
                : "border-white/10 focus:border-white/25",
            )}
            data-testid="input-amount"
          />
          <span
            className="pointer-events-none absolute right-3.5 top-1/2 max-w-[80px] -translate-y-1/2 truncate text-sm font-semibold text-white/40"
            aria-hidden="true"
          >
            {unit}
          </span>
        </div>
      </label>

      {/* The only two numbers under the field: how far it can go, and what the
          typed amount costs. No rate, no fee — see the component docstring. */}
      <div className="mt-2 flex items-center justify-between gap-3">
        <span className="min-w-0 truncate text-xs text-white/45">
          {t("topup.amountRange", {
            min: min.toLocaleString(getActiveLocale()),
            max: max.toLocaleString(getActiveLocale()),
          })}
        </span>
        {total !== null && (
          <span className="flex-shrink-0 text-sm font-bold text-white">
            {formatMoney(total, rate.currency)}
          </span>
        )}
      </div>

      {errorMessage && (
        <p className="mt-1.5 text-xs font-medium" style={{ color: "rgb(252, 165, 165)" }}>
          {errorMessage}
        </p>
      )}
    </div>
  );
}

// ─── Unit-quantity quick-pick tiles ───────────────────────────────────────────
/**
 * Quick-pick tiles for a unit package, built from `visibleStarPackages` — not
 * separate SKUs (there are none): tapping one just sets `UnitAmountPanel`'s
 * quantity, the same field both render into.
 */
function UnitPackTiles({
  pkg,
  qty,
  onPick,
  fallbackImage,
}: {
  pkg: Package;
  /** The field's currently parsed quantity, or `null` — used only to mark a
   *  tile active when it matches what's typed. */
  qty: number | null;
  onPick: (n: number) => void;
  /** Product art when the unit SKU itself has no `imageUrl` — same fallback
   *  `PackageCard` uses for ordinary denominations. */
  fallbackImage: string | null;
}) {
  const packs = visibleStarPackages(pkg.minQty ?? 0, pkg.maxQty ?? 0);
  if (packs.length === 0) return null;
  const rate = { amount: pkg.price, currency: pkg.priceCode };
  return (
    <div className="mt-2.5 grid grid-cols-3 gap-2.5">
      {packs.map((n) => {
        const active = qty === n;
        const price = packagePrice(n, rate.amount);
        return (
          <button
            key={n}
            type="button"
            aria-pressed={active}
            onClick={() => {
              onPick(n);
            }}
            className="rounded-xl p-2.5 text-left transition-all duration-150"
            style={{
              background: active ? "hsl(var(--surface-3))" : "hsl(var(--surface-2))",
              border: active
                ? "1.5px solid hsl(var(--primary) / 0.8)"
                : "1px solid hsl(var(--border))",
            }}
            data-testid={`btn-pkg-unit-${n}`}
          >
            <div className="mb-1.5">
              <PackageThumb pkg={pkg} fallback={fallbackImage} />
            </div>
            <span className="block text-sm font-bold leading-none text-white">
              {n.toLocaleString(getActiveLocale())} {pkg.amountUnit}
            </span>
            <span className="mt-1 block text-xs font-semibold text-white/60">
              {formatMoney(price, rate.currency)}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// ─── Loading skeletons ────────────────────────────────────────────────────────
function PageSkeleton({ onBack, slug }: { onBack: () => void; slug: string | undefined }) {
  const { t } = useT();
  return (
    <div className="pb-32">
      <div className="relative h-56 overflow-hidden bg-gradient-to-br from-slate-800 to-slate-950">
        <button
          type="button"
          onClick={onBack}
          aria-label={t("common.back")}
          className="absolute left-4 top-12 z-20 flex h-9 w-9 items-center justify-center rounded-full bg-black/40 backdrop-blur-sm"
        >
          <ArrowLeft size={16} className="text-white" />
        </button>
      </div>
      <div className="space-y-4 px-4 pt-5">
        <Skeleton className="h-12 w-full" />
        <PackagesSkeleton shape={getBrandShape(slug)} />
      </div>
    </div>
  );
}

/**
 * Placeholder for the choice step.
 *
 * A skeleton is a promise about the form that is loading, so it follows the
 * brand's remembered shape: a grid of denomination cards, or the single amount
 * field a variable-amount product (Steam) resolves into. On a first visit
 * nothing is remembered and the grid is the safe default — six of seven brands
 * use it.
 */
function PackagesSkeleton({ shape }: { shape: "packages" | "amount" | null }) {
  if (shape === "amount") {
    return (
      <div className="space-y-2.5">
        <Skeleton className="h-16 w-full rounded-2xl" />
        <div className="grid grid-cols-3 gap-2.5">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-11 rounded-xl" />
          ))}
        </div>
      </div>
    );
  }
  return (
    <div className="grid grid-cols-2 gap-2.5">
      {[0, 1, 2, 3].map((i) => (
        <Skeleton key={i} className="h-24 rounded-2xl" />
      ))}
    </div>
  );
}
