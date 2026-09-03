import { motion } from "framer-motion";
import { ArrowLeft, Check } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useParams } from "wouter";

import type { GiftAppDetail, GiftPackage } from "@/lib/gifts";

import { DlcSheet } from "@/components/gifts/DlcSheet";
import { InviteGuideSheet } from "@/components/gifts/InviteGuideSheet";
import { PaymentMethodGrid } from "@/components/gifts/PaymentMethodGrid";
import { SafeImage } from "@/components/ui/safe-image";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/use-toast";
import { ApiError } from "@/lib/api";
import { formatMoney } from "@/lib/currency";
import {
  extractExpectedAmount,
  fetchGiftDetail,
  priceFor,
  useGiftSkuId,
  validateInviteUrl,
} from "@/lib/gifts";
import { useT } from "@/lib/i18n";
import {
  methodVisibility,
  providerStatusMap,
  selectActiveMethodId,
  useAvailableProviders,
  useCheckout,
} from "@/lib/orders";
import { PAYMENT_METHODS, PROVIDER_BY_METHOD } from "@/lib/payment-methods";
import { haptic, openExternalLink, setClosingConfirmation } from "@/lib/telegram";
import { useDocumentTitle } from "@/lib/use-document-title";
import { ensureBotCanWrite } from "@/lib/write-access";
import { checkoutErrorMessage } from "@/pages/TopUp";

/** How many offered zones show as their own pill before the rest collapse
 *  behind a single "другой регион" toggle — mirrors the web panel's
 *  `VISIBLE_ZONE_COUNT`. */
const VISIBLE_ZONE_COUNT = 4;

/**
 * Region kept after an edition/package switch: the current zone if the new
 * package still prices it, else the app's default zone, else whatever price
 * the package does offer, else — a package with no prices at all — the zone
 * is left untouched. Mirrors `GiftPurchasePanel.tsx::selectPackage` on the
 * web storefront exactly.
 */
export function zoneAfterPackageChange(
  pkg: GiftPackage,
  currentZone: string,
  defaultZone: string,
): string {
  if (pkg.prices.some((p) => p.zone === currentZone)) return currentZone;
  const fallback = pkg.prices.find((p) => p.zone === defaultZone) ?? pkg.prices[0];
  return fallback ? fallback.zone : currentZone;
}

/**
 * Which package/zone stay selected after a detail refresh that must
 * preserve the buyer's picks — namely the price-drift reload in
 * `handleBuy`, where a fresh `load()` must NOT bounce the buyer back to
 * `packages[0]`/`zone_default` the way an initial page load does. Keeps
 * `prevPackageId` when the refreshed detail still lists it, else falls back
 * to the first package (mirrors the initial-load default); resolves the
 * zone through the existing `zoneAfterPackageChange` rule so it stays
 * consistent with every other package/zone transition on this page.
 */
export function reconcileSelection(
  detail: GiftAppDetail,
  prevPackageId: number | null,
  prevZone: string | null,
): { packageId: number | null; zone: string | null } {
  const pkg = detail.packages.find((p) => p.id === prevPackageId) ?? detail.packages[0] ?? null;
  if (!pkg) return { packageId: null, zone: prevZone ?? detail.zone_default };
  return {
    packageId: pkg.id,
    zone: zoneAfterPackageChange(pkg, prevZone ?? detail.zone_default, detail.zone_default),
  };
}

/** Splits an app's offered zones into the pills shown up front and the ones
 *  collapsed behind "другой регион". */
export function splitZones(
  zones: string[],
  visibleCount: number,
): { visible: string[]; overflow: string[] } {
  return { visible: zones.slice(0, visibleCount), overflow: zones.slice(visibleCount) };
}

/** `unavailable` is the caller's already-translated `gifts.priceUnavailable`
 *  string — this stays a plain function (not a component), so it can't call
 *  `useT()` itself. */
function priceLabel(
  price: { price_usd: string; price_uzs: string | null } | null,
  unavailable: string,
): string {
  if (!price) return unavailable;
  return price.price_uzs != null
    ? formatMoney(Math.round(Number(price.price_uzs)), "UZS")
    : formatMoney(Number(price.price_usd), "USD");
}

// ─── Edition (package) picker ───────────────────────────────────────────────
function PackageOption({
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

// ─── Region pill ─────────────────────────────────────────────────────────────
function ZonePill({
  zone,
  active,
  available,
  onSelect,
}: {
  zone: string;
  active: boolean;
  available: boolean;
  onSelect: () => void;
}) {
  const { t } = useT();
  return (
    <button
      type="button"
      disabled={!available}
      title={available ? undefined : t("gifts.game.noPriceInRegion")}
      aria-pressed={active}
      onClick={onSelect}
      className="rounded-full border px-3 py-1.5 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-40"
      style={{
        borderColor: active ? "hsl(var(--primary))" : "hsl(var(--border))",
        background: active ? "hsl(var(--primary) / 0.12)" : "transparent",
        color: active ? "hsl(var(--primary))" : "rgba(255,255,255,0.6)",
      }}
    >
      {zone}
    </button>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────
type Phase = "loading" | "idle" | "error" | "notFound";

export default function GiftGame() {
  const { t } = useT();
  const { appId } = useParams<{ appId: string }>();
  const [, setLocation] = useLocation();
  const { toast } = useToast();

  const numericAppId = Number(appId);
  const validAppId = Number.isInteger(numericAppId) && numericAppId > 0;

  const [detail, setDetail] = useState<GiftAppDetail | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [selectedPackageId, setSelectedPackageId] = useState<number | null>(null);
  const [selectedZone, setSelectedZone] = useState<string | null>(null);
  const [inviteUrl, setInviteUrl] = useState("");
  const [guideOpen, setGuideOpen] = useState(false);
  const [dlcOpen, setDlcOpen] = useState(false);
  const [zoneExpanded, setZoneExpanded] = useState(false);
  const seqRef = useRef(0);

  // The steam-gift product's single purchasable SKU — resolved once, reused
  // by every game on this route. `status === "unavailable"` (flag off, or an
  // API that predates the seed) swaps the buy section for `gifts.comingSoon`
  // instead of rendering a Buy button checkout can never accept.
  const { skuId, status: skuStatus } = useGiftSkuId();

  // In-scope acquirers for a gift purchase — same rails `TopUp` offers, no
  // wallet pay (a gift is always paid up front, not from the internal
  // ledger, mirroring `GiftPurchasePanel.tsx` on the web storefront).
  const [methodId, setMethodId] = useState<string>(PAYMENT_METHODS[0]?.id ?? "click");
  const providersQuery = useAvailableProviders();
  const providerStatusBySlug = useMemo(
    () => (providersQuery.data ? providerStatusMap(providersQuery.data) : null),
    [providersQuery.data],
  );
  // Once live provider status has loaded, bounce off a stale/now-unavailable
  // selection the same way `TopUp` does — never leave the highlight on a
  // method that renders as maintenance/hidden.
  useEffect(() => {
    if (providerStatusBySlug === null) return;
    setMethodId(
      (current) => selectActiveMethodId(PAYMENT_METHODS, current, providerStatusBySlug) ?? "",
    );
  }, [providerStatusBySlug]);
  function isMethodAvailable(id: string): boolean {
    const provider = PROVIDER_BY_METHOD[id];
    return provider !== undefined && methodVisibility(provider, providerStatusBySlug) === "active";
  }

  const checkout = useCheckout();

  /**
   * `keepSelection` distinguishes an initial/route-change load (reset to
   * `packages[0]`/`zone_default`, the page's usual entry state) from the
   * price-drift reload in `handleBuy` (reapply whatever the buyer had
   * picked, via `reconcileSelection`, so a 422 doesn't silently swap their
   * edition/region out from under them while they re-confirm).
   */
  function load(keepSelection = false): void {
    if (!validAppId) {
      setPhase("notFound");
      return;
    }
    const seq = ++seqRef.current;
    const prevPackageId = selectedPackageId;
    const prevZone = selectedZone;
    setPhase("loading");
    fetchGiftDetail(numericAppId)
      .then((d) => {
        if (seq !== seqRef.current) return;
        if (!d) {
          setDetail(null);
          setPhase("notFound");
          return;
        }
        setDetail(d);
        if (keepSelection) {
          const { packageId, zone } = reconcileSelection(d, prevPackageId, prevZone);
          setSelectedPackageId(packageId);
          setSelectedZone(zone);
        } else {
          setSelectedPackageId(d.packages[0]?.id ?? null);
          setSelectedZone(d.zone_default);
        }
        setZoneExpanded(false);
        setPhase("idle");
      })
      .catch(() => {
        if (seq !== seqRef.current) return;
        setPhase("error");
      });
  }

  useEffect(() => {
    load();
    // Re-fetch whenever the route's appId changes (a DLC link navigates
    // in-place, this page doesn't unmount/remount for it).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appId]);

  useDocumentTitle(
    detail ? t("gifts.game.docTitleNamed", { name: detail.name }) : t("gifts.docTitle"),
  );

  const selectedPackage =
    detail?.packages.find((p) => p.id === selectedPackageId) ?? detail?.packages[0] ?? null;
  const price = priceFor(detail, selectedPackage?.id ?? null, selectedZone);

  function selectPackage(pkg: GiftPackage): void {
    haptic("select");
    setSelectedPackageId(pkg.id);
    if (!detail) return;
    setSelectedZone((current) =>
      zoneAfterPackageChange(pkg, current ?? detail.zone_default, detail.zone_default),
    );
  }

  function selectZone(zone: string): void {
    if (!selectedPackage?.prices.some((p) => p.zone === zone)) return;
    haptic("select");
    setSelectedZone(zone);
  }

  const canonicalInvite = validateInviteUrl(inviteUrl);
  const inviteTouched = inviteUrl.trim() !== "";
  const selectedProvider = PROVIDER_BY_METHOD[methodId];
  const methodReady = selectedProvider !== undefined && isMethodAvailable(methodId);
  const canBuy =
    price !== null &&
    canonicalInvite !== null &&
    skuId !== null &&
    methodReady &&
    !checkout.isPending;

  /**
   * Checkout with the frozen body (`{sku_id, qty:1, amount_usd, fulfillment_data}`)
   * — mirrors `buyGift` on the web storefront. A price-drift 422
   * (`extra.expected_amount_usd`, `price_gift_line`'s ±2% tolerance) refetches
   * this game's detail and lets the buyer re-confirm at the server's own
   * figure rather than retrying blind with the same amount; every other
   * failure falls back to the shared `checkoutErrorMessage` path.
   */
  async function handleBuy(): Promise<void> {
    // `canBuy` already requires `price !== null` — TS's aliased-condition
    // narrowing carries that through past this guard (same pattern
    // `GiftPurchasePanel.tsx` documents on the web storefront), which is why
    // `!price` alone reads as redundant to the linter. Kept spelled out
    // anyway, alongside `detail`/`selectedPackage` (which `canBuy` does NOT
    // cover), so every field this function reads below is narrowed non-null
    // in one place rather than trusting an alias silently.
    if (
      !canBuy ||
      !detail ||
      !selectedPackage ||
      !price ||
      !canonicalInvite ||
      !skuId ||
      !selectedProvider
    ) {
      return;
    }
    // Codes and status updates are delivered by the bot. Someone who opened
    // the Mini App from a link and never pressed /start can't be written to,
    // so ask once, here, where the reason is obvious — same as `TopUp`.
    await ensureBotCanWrite();
    // Money is about to move and the next step may be a redirect to the
    // acquirer — a stray swipe-down here loses the customer mid-payment.
    setClosingConfirmation(true);
    try {
      const result = await checkout.mutateAsync({
        skuId,
        fulfillmentData: {
          app_id: detail.app_id,
          package_id: selectedPackage.id,
          region: price.zone,
          invite_url: canonicalInvite,
        },
        amountUsd: price.price_usd,
        qty: 1,
        // `performCheckout` defaults to USD, but this SKU is variable-amount
        // and the server rejects USD for that shape before the gift hook
        // even runs (`_resolve_line_unit_price` in orders/service.py). Mirrors
        // `apps/web/src/lib/gift-checkout.ts`'s hardcoded `currency: "UZS"` —
        // required at both the orders layer and the Click/Payme/Uzum gateways.
        currency: "UZS",
        provider: selectedProvider,
      });
      haptic("ok");
      if (result.payment.intent_url && result.payment.provider !== "mock") {
        // Hand the acquirer URL to Telegram so it opens in the device browser
        // instead of replacing the Mini App's own WebView, then move to the
        // order's status page — same handoff `TopUp` uses.
        toast({ title: t("topup.redirecting"), description: result.payment.provider });
        openExternalLink(result.payment.intent_url);
        setLocation(`/order/${result.order.id}`);
        return;
      }
      toast({
        title: t("topup.orderCreated"),
        description: t("topup.processing", { game: detail.name }),
      });
      setLocation(`/order/${result.order.id}`);
    } catch (exc) {
      if (exc instanceof ApiError && exc.status === 422) {
        const expected = extractExpectedAmount(exc.body);
        if (expected !== null) {
          toast({ title: t("gifts.checkout.priceChanged"), variant: "destructive" });
          load(/* keepSelection */ true);
          return;
        }
      }
      haptic("error");
      toast({
        title: t("topup.checkoutFailed"),
        description: checkoutErrorMessage(exc),
        variant: "destructive",
      });
    } finally {
      // Checkout is over either way — stop nagging on close. Runs on the
      // redirect path too (`finally` fires on `return`), which is what we
      // want: we're navigating to the acquirer, not closing the app.
      setClosingConfirmation(false);
    }
  }

  if (phase === "loading") {
    return (
      <div className="pb-32">
        <Skeleton className="h-56 w-full" />
        <div className="space-y-4 px-4 pt-5">
          <Skeleton className="h-6 w-2/3" />
          <Skeleton className="h-16 w-full rounded-2xl" />
          <div className="grid grid-cols-2 gap-2.5">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-16 rounded-2xl" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (phase === "notFound" || !detail) {
    return (
      <div className="flex flex-col items-center gap-4 p-6 pt-24 text-center">
        <h2 className="text-xl font-bold text-white">{t("gifts.game.notFound")}</h2>
        <button
          type="button"
          onClick={() => {
            setLocation("/gifts");
          }}
          className="bg-primary rounded-2xl px-6 py-3 font-bold text-black"
        >
          {t("common.toHome")}
        </button>
      </div>
    );
  }

  if (phase === "error") {
    return (
      <div className="flex flex-col items-center gap-4 p-6 pt-24 text-center">
        <p className="text-sm text-white/50">{t("gifts.search.error")}</p>
        <button
          type="button"
          onClick={() => {
            load();
          }}
          className="bg-primary rounded-2xl px-6 py-3 font-bold text-black"
        >
          {t("common.retry")}
        </button>
      </div>
    );
  }

  const { visible: visibleZones, overflow: overflowZones } = splitZones(
    detail.zones,
    VISIBLE_ZONE_COUNT,
  );

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.22 }}
      className="pb-32"
    >
      <InviteGuideSheet open={guideOpen} onOpenChange={setGuideOpen} />
      <DlcSheet
        open={dlcOpen}
        onOpenChange={setDlcOpen}
        appId={detail.app_id}
        total={detail.dlc_total}
      />

      {/* ── Hero ── */}
      <div className="relative h-56 overflow-hidden">
        {detail.image ? (
          <SafeImage
            src={detail.image}
            className="absolute inset-0 h-full w-full object-cover"
            fallback={
              <div className="absolute inset-0 bg-gradient-to-br from-slate-800 to-slate-950" />
            }
          />
        ) : (
          <div className="absolute inset-0 bg-gradient-to-br from-slate-800 to-slate-950" />
        )}
        <div className="from-background via-background/40 absolute inset-0 bg-gradient-to-t to-black/20" />
        <button
          type="button"
          onClick={() => {
            setLocation("/gifts");
          }}
          aria-label={t("common.back")}
          className="absolute left-4 top-12 z-20 flex h-9 w-9 items-center justify-center rounded-full bg-black/40 backdrop-blur-sm"
        >
          <ArrowLeft size={16} className="text-white" />
        </button>
        <div className="absolute bottom-0 left-0 right-0 z-10 px-4 pb-4">
          <h1 className="line-clamp-2 text-lg font-bold leading-tight text-white">{detail.name}</h1>
        </div>
      </div>

      <div className="space-y-6 px-4 pt-5">
        {detail.description && (
          <p className="text-sm leading-relaxed text-white/55">{detail.description}</p>
        )}

        {detail.dlc_total > 0 && (
          <button
            type="button"
            onClick={() => {
              setDlcOpen(true);
            }}
            className="text-primary text-sm font-semibold"
          >
            {t("gifts.dlc.toggle", { count: detail.dlc_total })}
          </button>
        )}

        {/* Step: edition */}
        <div>
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-white/50">
            {t("gifts.game.edition")}
          </p>
          <div className="flex flex-col gap-2">
            {detail.packages.map((pkg) => (
              <PackageOption
                key={pkg.id}
                pkg={pkg}
                price={selectedZone ? (priceFor(detail, pkg.id, selectedZone) ?? null) : null}
                active={pkg.id === selectedPackage?.id}
                onSelect={() => {
                  selectPackage(pkg);
                }}
              />
            ))}
          </div>
        </div>

        {/* Step: region */}
        <div>
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-white/50">
            {t("gifts.game.region")}
          </p>
          <div className="flex flex-wrap gap-2">
            {visibleZones.map((zone) => (
              <ZonePill
                key={zone}
                zone={zone}
                active={zone === selectedZone}
                available={selectedPackage?.prices.some((p) => p.zone === zone) ?? false}
                onSelect={() => {
                  selectZone(zone);
                }}
              />
            ))}
            {overflowZones.length > 0 && !zoneExpanded && (
              <button
                type="button"
                onClick={() => {
                  setZoneExpanded(true);
                }}
                className="rounded-full border px-3 py-1.5 text-xs font-semibold text-white/50"
                style={{ borderColor: "hsl(var(--border))" }}
              >
                {t("gifts.game.otherRegion")}
              </button>
            )}
            {zoneExpanded &&
              overflowZones.map((zone) => (
                <ZonePill
                  key={zone}
                  zone={zone}
                  active={zone === selectedZone}
                  available={selectedPackage?.prices.some((p) => p.zone === zone) ?? false}
                  onSelect={() => {
                    selectZone(zone);
                  }}
                />
              ))}
          </div>
        </div>

        {/* Price */}
        <div className="border-t pt-4" style={{ borderColor: "hsl(var(--border) / 0.7)" }}>
          {price ? (
            <p className="text-2xl font-bold tabular-nums text-white">
              {priceLabel(price, t("gifts.priceUnavailable"))}
            </p>
          ) : (
            <p className="text-sm text-white/50">{t("gifts.game.noPriceInRegion")}</p>
          )}
        </div>

        {/* Invite link */}
        <div className="space-y-2">
          <label className="text-[11px] font-semibold uppercase tracking-wide text-white/50">
            {t("gifts.game.inviteLabel")}
          </label>
          <input
            type="text"
            value={inviteUrl}
            onChange={(e) => {
              setInviteUrl(e.target.value);
            }}
            placeholder={t("gifts.game.invitePlaceholder")}
            className="h-11 w-full rounded-xl border bg-transparent px-3 text-sm text-white outline-none"
            style={{ borderColor: "hsl(var(--border))" }}
          />
          {inviteTouched && canonicalInvite === null && (
            <p className="text-[13px] text-red-400">{t("gifts.game.inviteError")}</p>
          )}
          <button
            type="button"
            onClick={() => {
              setGuideOpen(true);
            }}
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
              <PaymentMethodGrid
                methods={PAYMENT_METHODS}
                activeId={methodId}
                providerStatusBySlug={providerStatusBySlug}
                onSelect={setMethodId}
              />
            </div>

            <button
              type="button"
              disabled={!canBuy}
              onClick={() => {
                void handleBuy();
              }}
              className="bg-primary w-full rounded-2xl py-3.5 text-base font-bold text-black disabled:cursor-not-allowed disabled:opacity-50"
            >
              {checkout.isPending ? t("topup.processingBtn") : t("gifts.game.buy")}
            </button>
          </>
        )}

        <div className="space-y-1 text-[12px] leading-relaxed text-white/40">
          <p>{t("gifts.game.timeline")}</p>
          <p>{t("gifts.game.accept")}</p>
        </div>
      </div>
    </motion.div>
  );
}
