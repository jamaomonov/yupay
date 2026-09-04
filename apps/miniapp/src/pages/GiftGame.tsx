import { motion } from "framer-motion";
import { ArrowLeft } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useParams } from "wouter";

import type { GiftAppDetail, GiftPackage, GiftRegion } from "@/lib/gifts";
import type { MethodVisibility, ProviderAvailability } from "@/lib/orders";

import { DlcSheet } from "@/components/gifts/DlcSheet";
import { GiftBuyPanel } from "@/components/gifts/GiftBuyPanel";
import { InviteGuideSheet } from "@/components/gifts/InviteGuideSheet";
import { PackageOption, priceLabel } from "@/components/gifts/PackageOption";
import { RegionGuideSheet } from "@/components/gifts/RegionGuideSheet";
import { RegionPill } from "@/components/gifts/RegionPill";
import { SafeImage } from "@/components/ui/safe-image";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/use-toast";
import { ApiError, newIdempotencyKey } from "@/lib/api";
import {
  extractExpectedAmount,
  fetchGiftDetail,
  priceFor,
  useGiftSkuId,
  validateInviteUrl,
  zoneForCountry,
} from "@/lib/gifts";
import { useLocale, useT } from "@/lib/i18n";
import {
  methodVisibility,
  providerStatusMap,
  useAvailableProviders,
  useCheckout,
  type CheckoutResult,
} from "@/lib/orders";
import { PAYMENT_METHODS, PROVIDER_BY_METHOD } from "@/lib/payment-methods";
import { countryName } from "@/lib/regions";
import { haptic, openExternalLink, setClosingConfirmation } from "@/lib/telegram";
import { useDocumentTitle } from "@/lib/use-document-title";
import { formatBalance, groupBalancesByCurrency, useWallet } from "@/lib/wallet";
import { ensureBotCanWrite } from "@/lib/write-access";
import { checkoutErrorMessage } from "@/pages/TopUp";

/** How many offered countries show as their own pill before the rest
 *  collapse behind a single "другой регион" toggle — mirrors the web
 *  panel's `VISIBLE_COUNTRY_COUNT`; CIS alone is nine countries. */
const VISIBLE_COUNTRY_COUNT = 4;

/** Sentinel for "pay from wallet balance" — handled by its own card, not
 *  part of the shared acquirer grid. The backend provider slug is
 *  ``wallet``. Same sentinel `TopUp.tsx` uses. */
const WALLET_METHOD_ID = "wallet";

// The shared acquirer list carries only the external providers; the wallet
// option is checkout-only, so the provider map is extended locally for
// resolution/availability — mirrors `TopUp.tsx`'s `PROVIDER_BY_METHOD_FULL`.
const PROVIDER_BY_METHOD_FULL: Record<string, string> = {
  ...PROVIDER_BY_METHOD,
  [WALLET_METHOD_ID]: "wallet",
};

/** Resolves one representative country for a given zone from a `regions`
 *  list — the reverse of `zoneForCountry` (`@/lib/gifts`), used only for
 *  `countryAfterPackageChange`'s last-resort fallback below. Picks the
 *  first `regions` entry that covers the zone. */
function countryForZone(regions: GiftRegion[], zone: string): string | null {
  return regions.find((r) => r.zone === zone)?.country ?? null;
}

/**
 * Country kept after an edition/package switch: the current country if its
 * zone is still priced by the new package, else the app's default country,
 * else a country covering whatever price the package does offer, else — a
 * package with no prices at all, or a fallback zone no known country covers
 * — the country is left untouched. The country-keyed twin of the old
 * `zoneAfterPackageChange` (2026-09-03: the wire/pricing unit stays the
 * zone, but the buyer now picks a country); mirrors
 * `GiftPurchasePanel.tsx::selectPackage` on the web storefront exactly.
 */
export function countryAfterPackageChange(
  pkg: GiftPackage,
  currentCountry: string,
  defaultCountry: string,
  regions: GiftRegion[],
): string {
  const currentZone = zoneForCountry(regions, currentCountry);
  if (currentZone !== null && pkg.prices.some((p) => p.zone === currentZone)) {
    return currentCountry;
  }
  const defaultZone = zoneForCountry(regions, defaultCountry);
  if (defaultZone !== null && pkg.prices.some((p) => p.zone === defaultZone)) {
    return defaultCountry;
  }
  const fallback = pkg.prices[0];
  if (!fallback) return currentCountry;
  return countryForZone(regions, fallback.zone) ?? currentCountry;
}

/**
 * Whether an edition/package switch actually moved the buyer's selected
 * country — `selectPackage` below shows the shared "Это издание продаётся
 * только для: {country}" notice only when this is true, never merely
 * because a package was picked (re-selecting the current edition, or
 * switching to one still priced for the current country, must stay silent).
 * Pulled out pure so this decision has a name and a direct unit test
 * (2026-09-04 review), mirroring `walletPayState`/`nextSelectedMethodId`.
 */
export function countryMovedOnEditionSwitch(prevCountry: string, nextCountry: string): boolean {
  return nextCountry !== prevCountry;
}

/**
 * Which package/country stay selected after a detail refresh that must
 * preserve the buyer's picks — namely the price-drift reload in
 * `handleBuy`, where a fresh `load()` must NOT bounce the buyer back to
 * `packages[0]`/`region_default` the way an initial page load does. Keeps
 * `prevPackageId` when the refreshed detail still lists it, else falls back
 * to the first package (mirrors the initial-load default); resolves the
 * country through the existing `countryAfterPackageChange` rule so it stays
 * consistent with every other package/region transition on this page.
 */
export function reconcileSelection(
  detail: GiftAppDetail,
  prevPackageId: number | null,
  prevCountry: string | null,
): { packageId: number | null; country: string | null } {
  const pkg = detail.packages.find((p) => p.id === prevPackageId) ?? detail.packages[0] ?? null;
  if (!pkg) return { packageId: null, country: prevCountry ?? detail.region_default ?? null };
  return {
    packageId: pkg.id,
    country: countryAfterPackageChange(
      pkg,
      prevCountry ?? detail.region_default ?? "",
      detail.region_default ?? "",
      detail.regions ?? [],
    ),
  };
}

/** Splits an app's offered countries into the pills shown up front and the
 *  ones collapsed behind "другой регион". */
export function splitCountries(
  countries: string[],
  visibleCount: number,
): { visible: string[]; overflow: string[] } {
  return { visible: countries.slice(0, visibleCount), overflow: countries.slice(visibleCount) };
}

/** Whether a catalog entry is a DLC rather than a base game — the only DLC
 *  signal already on the wire (`GiftAppOut.type`, straight from the
 *  upstream Steam catalog). Drives the shared "this needs the base game"
 *  note on `GiftGame`'s own screen (2026-09-04 review): a DLC delivered
 *  without the base game is unusable, and the buyer had no warning. */
export function isDlcApp(type: string): boolean {
  return type === "dlc";
}

/**
 * The FX-down gate: `price_uzs` legitimately comes back `null` when FX is
 * unavailable, and this state must never be confused with "no price at all
 * for this edition/country" (a different, unrelated dead end) nor silently
 * priced in USD — a gift is always billed in UZS
 * (`GiftGame.tsx::handleBuy` hardcodes `currency: "UZS"`), so a buyer who
 * saw a dollar figure and pressed Buy would be sent to the acquirer for an
 * unknown sum in soum. `"unpriced"` renders `gifts.game.noPriceInRegion`;
 * `"fxDown"` renders the mature panels' dashed `topup.priceUnavailable` card
 * (`TopUp.tsx`'s `VariableAmountPanel`) instead of a guessed number;
 * `"priced"` is the only state `canBuy` accepts. Pulled out pure
 * (2026-09-04 review) so this decision is unit-tested directly, mirroring
 * `walletPayState`'s own `unknownTotal` distinction.
 */
export type GiftPriceAvailability = "unpriced" | "fxDown" | "priced";

export function giftPriceAvailability(
  price: { price_uzs: string | null } | null,
): GiftPriceAvailability {
  if (!price) return "unpriced";
  return price.price_uzs == null ? "fxDown" : "priced";
}

/** What the wallet ("pay from balance") tile should say and whether it's
 *  selectable — mirrors `TopUp.tsx`'s inline `walletEnough`/`walletShortfall`/
 *  `disabled` math exactly (see `WalletPayOption.tsx`), pulled out as a pure
 *  function so it's unit-testable under this app's node-env convention
 *  instead of only reachable by rendering. */
export interface WalletPayState {
  /** Whether the balance is known to cover `total`. Optimistically `true`
   *  while the balance is still loading (`balance === null`) — a submit
   *  re-checks server-side regardless, same belt-and-suspenders posture as
   *  `TopUp`. */
  enough: boolean;
  /** Non-selectable: an admin has the wallet in maintenance, the total
   *  isn't known yet (FX-unavailable `price_uzs`), or the balance is short
   *  and no longer loading. */
  disabled: boolean;
  /** UZS still needed to afford `total`. `0` unless genuinely short. */
  shortfall: number;
  /** `true` when there is nothing to weigh the balance against — the
   *  selected line's `price_uzs` was `null` (FX unavailable). Distinct from
   *  an insufficient balance: never compare against a guessed total. */
  unknownTotal: boolean;
}

export function walletPayState({
  balance,
  total,
  loading,
  visibility,
}: {
  balance: number | null;
  total: number | null;
  loading: boolean;
  visibility: MethodVisibility;
}): WalletPayState {
  if (total === null) {
    return { enough: false, disabled: true, shortfall: 0, unknownTotal: true };
  }
  const enough = balance === null ? true : balance >= total;
  const shortfall = balance === null || enough ? 0 : total - balance;
  const disabled = visibility === "maintenance" || (!loading && !enough);
  return { enough, disabled, shortfall, unknownTotal: false };
}

/**
 * Whether Buy may actually be submitted for the currently selected method —
 * the honest twin of `walletPayState.enough`'s optimistic display value.
 * Every non-wallet method is always ready (the acquirer path is untouched
 * by any of this). For the wallet, "ready" requires a balance that has
 * actually resolved (`balance !== null` — a still-loading balance is not a
 * known-sufficient one) AND a known total (`total !== null` — FX
 * unavailable must never be guessed past) AND that balance covering that
 * total. Pulled out as a pure function so this live-payment gate is
 * unit-tested directly rather than only reachable by rendering. Mirrors the
 * web panel, which only enables Buy once its wallet tile reaches the
 * genuine `"ready"` state (`canPayFromBalance(walletState)`), never a
 * loading or unknown one.
 */
export function walletSubmitReady({
  methodId,
  balance,
  total,
}: {
  methodId: string;
  balance: number | null;
  total: number | null;
}): boolean {
  if (methodId !== WALLET_METHOD_ID) return true;
  return balance !== null && total !== null && balance >= total;
}

/**
 * Decide the next selected method id when live provider status changes —
 * the reselect effect's own logic, pulled out pure so the wallet-stickiness
 * rule is unit-tested directly instead of only reachable by mounting the
 * page. `statusBySlug === null` (not yet loaded) leaves `current` alone,
 * same fail-open posture as `methodVisibility`. A wallet selection is NEVER
 * reassigned here, regardless of its own live status — its tile and
 * `walletSubmitReady`/`canBuy` are what decide whether it's usable, not
 * this reselection; reassigning it would silently swap the buyer onto a
 * card with no notice (mirrors `GiftPurchasePanel.tsx`'s identical guard on
 * web: `if (current === WALLET_METHOD_ID) return current;`). Otherwise:
 * keep `current` if it still resolves to an `"active"` provider, else fall
 * back to the first acquirer that does, else deselect entirely (`""`).
 */
export function nextSelectedMethodId({
  current,
  statusBySlug,
  providerByMethod,
  methods,
}: {
  current: string;
  statusBySlug: Map<string, ProviderAvailability> | null;
  providerByMethod: Record<string, string>;
  methods: { id: string }[];
}): string {
  if (statusBySlug === null || current === WALLET_METHOD_ID) return current;
  const isAvailable = (id: string): boolean => {
    const provider = providerByMethod[id];
    return provider !== undefined && methodVisibility(provider, statusBySlug) === "active";
  };
  if (current === "" || isAvailable(current)) return current;
  const fallback = methods.find((m) => isAvailable(m.id));
  return fallback ? fallback.id : "";
}

// ---------- sticky order idempotency key ----------
//
// A buyer who retries after a failed payment (most often "insufficient
// wallet balance", re-checked under a row lock server-side) must resume the
// SAME order instead of creating a second one. `create_order` already
// replays by `Idempotency-Key` (`_existing_idempotent_order` in
// `orders/service.py`) — the gap was purely that `handleBuy` minted a fresh
// key on every buy click. Mirrors `apps/web/src/lib/gift-checkout.ts`
// exactly, minus the delivery-email term this page doesn't collect (Telegram
// identity delivers the gift, not a typed email).

/** The subset of the buy inputs that determines the order body `handleBuy`
 *  sends to `POST /orders` — everything `orderFingerprint` hashes.
 *  Deliberately has no field for the payment method: switching card <->
 *  wallet is the same order, not a new one, so it must never be able to
 *  change the fingerprint. */
export interface OrderFingerprintInput {
  skuId: string;
  amountUsd: string;
  fulfillmentData: {
    app_id: number;
    package_id: number;
    region: string;
    invite_url: string;
  };
}

/**
 * A pure hash of exactly the fields that determine the order body
 * `handleBuy` sends to `POST /orders` for a gift purchase — `sku_id`, `qty`
 * (always 1 for a gift line), `amount_usd`, and every `fulfillment_data`
 * field.
 *
 * This is the correctness-by-construction half of the sticky order key:
 * `handleBuy` mints a new `Idempotency-Key` (via `nextOrderKeyState` below)
 * exactly when this string differs from the one it last used, rather than
 * resetting it from scattered input handlers — a forgotten one would replay
 * a stale key and charge the buyer for their OLD selection. Over-resetting
 * (two fingerprints treated as different when the order would actually be
 * identical) is safe — it's exactly today's "always mint a new key"
 * behaviour. Under-resetting is a money bug, so every field the server bills
 * from belongs here.
 */
export function orderFingerprint(input: OrderFingerprintInput): string {
  return JSON.stringify({
    sku_id: input.skuId,
    qty: 1,
    amount_usd: input.amountUsd,
    fulfillment_data: {
      app_id: input.fulfillmentData.app_id,
      package_id: input.fulfillmentData.package_id,
      region: input.fulfillmentData.region,
      invite_url: input.fulfillmentData.invite_url,
    },
  });
}

/** The sticky-key ref's shape: the `Idempotency-Key` last sent for
 *  `POST /orders`, alongside the `orderFingerprint` it was minted for. */
export interface OrderKeyState {
  fingerprint: string;
  key: string;
}

/**
 * The "should I mint a new key?" decision `handleBuy` applies on every buy
 * click: reuse `prev.key` when `fingerprint` still matches the one it was
 * minted for (a failed attempt retried with unchanged inputs, or a bare
 * payment-method switch — `orderFingerprint` never sees the method at all),
 * or mint a fresh key via `mintKey` when it's absent (no prior attempt, or a
 * prior success cleared it to `null`) or has changed (the buyer picked a
 * different region/edition/invite). Exported pure and `mintKey`-injected so
 * it's testable directly under this app's node-env convention — no jsdom, no
 * rendering `GiftGame` to click a button.
 */
export function nextOrderKeyState(
  prev: OrderKeyState | null,
  fingerprint: string,
  mintKey: () => string,
): OrderKeyState {
  if (prev?.fingerprint === fingerprint) return prev;
  return { fingerprint, key: mintKey() };
}

/**
 * True when `err` is the 409 `create_intent` raises for an order that has
 * walked past `pending_payment` (most commonly `ORDER_EXPIRY_SECONDS`
 * elapsing and the scheduler flipping it to `expired` before a retry
 * landed) — `ConflictError("order is not awaiting payment", extra=
 * {"status": order.status})` in `payments/service.py`. Matched structurally
 * on the 409 status plus the `extra.status` field that guard's `extra=`
 * keyword puts on the body (nested under `body.extra` — `app_error_handler`
 * merges `exc.extra` onto the response body), never by matching `detail`
 * text, which is shared prose with other 409s from the same endpoint (e.g.
 * the `extra.current_provider` conflict for a mismatched payment provider).
 * Mirrors `isOrderNotAwaitingPaymentConflict` in
 * `apps/web/src/lib/gift-checkout.ts`, adapted to this app's `ApiError`
 * shape, whose `body` is the raw parsed problem+json rather than a
 * pre-split `extra` field.
 */
export function isOrderNotAwaitingPaymentConflict(err: unknown): boolean {
  if (!(err instanceof ApiError) || err.status !== 409) return false;
  const body = err.body;
  if (!body || typeof body !== "object") return false;
  const extra = (body as Record<string, unknown>).extra;
  if (!extra || typeof extra !== "object") return false;
  return typeof (extra as Record<string, unknown>).status === "string";
}

// ─── Page ─────────────────────────────────────────────────────────────────────
type Phase = "loading" | "idle" | "error" | "notFound";

export default function GiftGame() {
  const { t } = useT();
  const locale = useLocale();
  const { appId } = useParams<{ appId: string }>();
  const [, setLocation] = useLocation();
  const { toast } = useToast();

  const numericAppId = Number(appId);
  const validAppId = Number.isInteger(numericAppId) && numericAppId > 0;

  const [detail, setDetail] = useState<GiftAppDetail | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [selectedPackageId, setSelectedPackageId] = useState<number | null>(null);
  const [selectedCountry, setSelectedCountry] = useState<string | null>(null);
  const [inviteUrl, setInviteUrl] = useState("");
  const [guideOpen, setGuideOpen] = useState(false);
  const [regionGuideOpen, setRegionGuideOpen] = useState(false);
  const [dlcOpen, setDlcOpen] = useState(false);
  const [countryExpanded, setCountryExpanded] = useState(false);
  // Non-null exactly while the edition-switch notice should show: the
  // country `selectPackage` just moved the buyer to, via
  // `countryMovedOnEditionSwitch`. Cleared on every load and on a manual
  // country pick — see `selectCountry` and `load` below — so it never
  // outlives the switch that produced it.
  const [editionCountryNotice, setEditionCountryNotice] = useState<string | null>(null);
  const seqRef = useRef(0);
  // The sticky `Idempotency-Key` for `POST /orders`, kept alongside the
  // `orderFingerprint` it was minted for — a ref, not state, since neither
  // read nor write should trigger a render. A buy click reuses the stored
  // key exactly when the recomputed fingerprint still matches it (a failed
  // attempt with unchanged inputs), and mints a new one otherwise (changed
  // inputs, no prior attempt, or the previous purchase succeeded and
  // cleared this to `null`). Never reset from an individual input handler —
  // see `orderFingerprint`'s doc comment for why that would be a money bug.
  const orderKeyRef = useRef<OrderKeyState | null>(null);

  // The steam-gift product's single purchasable SKU — resolved once, reused
  // by every game on this route. `status === "unavailable"` (flag off, or an
  // API that predates the seed) swaps the buy section for `gifts.comingSoon`
  // instead of rendering a Buy button checkout can never accept.
  const { skuId, status: skuStatus } = useGiftSkuId();

  // In-scope acquirers for a gift purchase — same rails `TopUp` offers, plus
  // its wallet ("pay from balance") option, wired in alongside them
  // (2026-09-03) — `WalletGateway` settles a `purpose="catalog"` order
  // synchronously, same as any other checkout here.
  const [methodId, setMethodId] = useState<string>(PAYMENT_METHODS[0]?.id ?? "click");
  const providersQuery = useAvailableProviders();
  const providerStatusBySlug = useMemo(
    () => (providersQuery.data ? providerStatusMap(providersQuery.data) : null),
    [providersQuery.data],
  );
  // Resolves through the FULL map (not the shared base map) so a wallet
  // selection is recognised as available too — an `isMethodAvailable` that
  // only knew the base map would treat "wallet" as always-unavailable and
  // the reselect effect below would silently swap it away the moment
  // provider status loaded.
  function isMethodAvailable(id: string): boolean {
    const provider = PROVIDER_BY_METHOD_FULL[id];
    return provider !== undefined && methodVisibility(provider, providerStatusBySlug) === "active";
  }
  // Once live provider status has loaded, bounce off a stale/now-unavailable
  // selection the same way `TopUp` does — never leave the highlight on a
  // method that renders as maintenance/hidden, and never reassign a chosen
  // wallet (see `nextSelectedMethodId`'s docstring — this is the CRITICAL
  // parity fix). A functional update reads the latest `methodId` from React
  // itself, so this doesn't need `methodId` in the dependency array.
  useEffect(() => {
    setMethodId((current) =>
      nextSelectedMethodId({
        current,
        statusBySlug: providerStatusBySlug,
        providerByMethod: PROVIDER_BY_METHOD_FULL,
        methods: PAYMENT_METHODS,
      }),
    );
  }, [providerStatusBySlug]);

  const checkout = useCheckout();

  // Wallet balance for the "pay from balance" tile. Gift orders are always
  // priced and charged in UZS (`handleBuy` below hardcodes `currency:
  // "UZS"`), so unlike `TopUp` — which reads the SKU's own display
  // currency — this always resolves against the "UZS" balance.
  const walletQuery = useWallet();
  const walletByCurrency = useMemo(() => {
    const map = new Map<string, number>();
    for (const g of groupBalancesByCurrency(walletQuery.data ?? [])) {
      map.set(g.currency, g.amount);
    }
    return map;
  }, [walletQuery.data]);

  /**
   * `keepSelection` distinguishes an initial/route-change load (reset to
   * `packages[0]`/`region_default`, the page's usual entry state) from the
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
    const prevCountry = selectedCountry;
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
          const { packageId, country } = reconcileSelection(d, prevPackageId, prevCountry);
          setSelectedPackageId(packageId);
          setSelectedCountry(country);
        } else {
          setSelectedPackageId(d.packages[0]?.id ?? null);
          setSelectedCountry(d.region_default ?? null);
        }
        setCountryExpanded(false);
        // A fresh detail resets the country picker outright (either branch
        // above) — any edition-switch notice from the previous load no
        // longer describes anything on screen.
        setEditionCountryNotice(null);
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
  const price = priceFor(detail, selectedPackage?.id ?? null, selectedCountry);
  // "unpriced" (nothing priced here at all) vs "fxDown" (priced, but the
  // UZS conversion is unavailable) vs "priced" — the price section below
  // renders each state distinctly, and `canBuy` accepts only "priced". See
  // `giftPriceAvailability`'s own docstring for why FX-down must never fall
  // back to a USD figure.
  const priceAvailability = giftPriceAvailability(price);

  // The UZS figure to weigh the wallet balance against. `price.price_usd`
  // is NOT it — that's what an acquirer charges, not what the wallet
  // debits. `price_uzs` is `null` only when FX is unavailable, which
  // `walletPayState` renders as a non-selectable "unknown total" instead of
  // guessing against the USD figure.
  const walletTotal = price?.price_uzs != null ? Number(price.price_uzs) : null;
  const walletBalance = walletQuery.data ? (walletByCurrency.get("UZS") ?? 0) : null;
  const walletVisibility = methodVisibility(WALLET_METHOD_ID, providerStatusBySlug);
  const walletPay = walletPayState({
    balance: walletBalance,
    total: walletTotal,
    loading: walletQuery.isPending,
    visibility: walletVisibility,
  });

  function selectPackage(pkg: GiftPackage): void {
    haptic("select");
    setSelectedPackageId(pkg.id);
    if (!detail) return;
    const prevCountry = selectedCountry ?? detail.region_default ?? "";
    const nextCountry = countryAfterPackageChange(
      pkg,
      prevCountry,
      detail.region_default ?? "",
      detail.regions ?? [],
    );
    setSelectedCountry(nextCountry);
    // Shown only when the switch actually moved the country — never merely
    // because a package was picked (see `countryMovedOnEditionSwitch`'s own
    // docstring for why an invisible auto-move is the bug being fixed here).
    setEditionCountryNotice(
      countryMovedOnEditionSwitch(prevCountry, nextCountry) ? nextCountry : null,
    );
  }

  function selectCountry(country: string): void {
    if (!detail) return;
    const zone = zoneForCountry(detail.regions ?? [], country);
    if (zone === null || !selectedPackage?.prices.some((p) => p.zone === zone)) return;
    haptic("select");
    setSelectedCountry(country);
    // A manual pick supersedes whatever the last edition switch explained.
    setEditionCountryNotice(null);
  }

  const canonicalInvite = validateInviteUrl(inviteUrl);
  const inviteTouched = inviteUrl.trim() !== "";
  // Resolved through the FULL map so a wallet selection resolves to the
  // `"wallet"` provider `performCheckout` expects instead of `undefined`
  // (which would silently block Buy — `PROVIDER_BY_METHOD` alone has no
  // entry for the wallet sentinel).
  const selectedProvider = PROVIDER_BY_METHOD_FULL[methodId];
  const methodReady = selectedProvider !== undefined && isMethodAvailable(methodId);
  // The submit gate must be honest even though the tile itself shows an
  // optimistic "enough" while the balance is still loading (`walletPay`
  // above) — see `walletSubmitReady`'s own docstring.
  const submitReady = walletSubmitReady({
    methodId,
    balance: walletBalance,
    total: walletTotal,
  });
  const canBuy =
    price !== null &&
    // FX down must block the sale, not guess: a `price` that exists but
    // whose `price_uzs` is `null` is exactly as unsellable as no price at
    // all (2026-09-04 review) — see `giftPriceAvailability`.
    priceAvailability === "priced" &&
    selectedCountry !== null &&
    canonicalInvite !== null &&
    skuId !== null &&
    methodReady &&
    submitReady &&
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
      !selectedCountry ||
      !canonicalInvite ||
      !skuId ||
      !selectedProvider
    ) {
      return;
    }
    // Preflight: never POST a wallet checkout the balance can't cover. The
    // tile is already disabled for this case (see `walletPayState`), so
    // this only matters for a stale selection (e.g. the balance dropped, or
    // the region/package changed the total, since either can happen while
    // "wallet" stays selected) — belt-and-suspenders, same as `TopUp`. The
    // backend `WalletGateway` re-checks under a row-lock regardless, so
    // this is UX only, not the source of truth.
    if (methodId === WALLET_METHOD_ID) {
      if (walletPay.unknownTotal) {
        toast({
          title: t("topup.insufficientTitle"),
          description: t("topup.priceUnavailable"),
          variant: "destructive",
        });
        return;
      }
      if (!walletPay.enough) {
        toast({
          title: t("topup.insufficientTitle"),
          description: t("topup.insufficientBody", {
            amount: formatBalance(walletPay.shortfall, "UZS"),
          }),
          variant: "destructive",
        });
        return;
      }
    }
    // Codes and status updates are delivered by the bot. Someone who opened
    // the Mini App from a link and never pressed /start can't be written to,
    // so ask once, here, where the reason is obvious — same as `TopUp`.
    await ensureBotCanWrite();
    // Money is about to move and the next step may be a redirect to the
    // acquirer — a stray swipe-down here loses the customer mid-payment.
    setClosingConfirmation(true);

    const fulfillmentData = {
      app_id: detail.app_id,
      package_id: selectedPackage.id,
      // The country the buyer picked, not the zone it prices from — the
      // server resolves country -> zone -> price itself and sends the
      // zone's own `region_code` to the supplier (2026-09-03, see
      // `apps/api/src/yupay/modules/gifts/schemas.py::GiftAppDetailOut`).
      region: selectedCountry,
      invite_url: canonicalInvite,
    };

    // Sticky `Idempotency-Key` for `POST /orders` — reuse the stored key
    // exactly when it was minted for this exact order (the payment method
    // never enters the fingerprint, so a bare method switch keeps replaying
    // the same key on purpose). See `orderFingerprint` / `nextOrderKeyState`.
    const fingerprint = orderFingerprint({ skuId, amountUsd: price.price_usd, fulfillmentData });
    orderKeyRef.current = nextOrderKeyState(orderKeyRef.current, fingerprint, () =>
      newIdempotencyKey("order"),
    );

    // `performCheckout` defaults to USD, but this SKU is variable-amount
    // and the server rejects USD for that shape before the gift hook
    // even runs (`_resolve_line_unit_price` in orders/service.py). Mirrors
    // `apps/web/src/lib/gift-checkout.ts`'s hardcoded `currency: "UZS"` —
    // required at both the orders layer and the Click/Payme/Uzum gateways.
    const attempt = (orderIdempotencyKey: string) =>
      checkout.mutateAsync({
        skuId,
        fulfillmentData,
        amountUsd: price.price_usd,
        qty: 1,
        currency: "UZS",
        provider: selectedProvider,
        orderIdempotencyKey,
      });

    try {
      let result: CheckoutResult;
      try {
        result = await attempt(orderKeyRef.current.key);
      } catch (err) {
        if (!isOrderNotAwaitingPaymentConflict(err)) throw err;
        // The replayed order is no longer payable (typically expired past
        // `ORDER_EXPIRY_SECONDS` before this retry landed) — mint a fresh
        // key for the same order contents and retry exactly once. A second
        // failure here falls through to the outer `catch` untouched, so it
        // never loops.
        const freshKey = newIdempotencyKey("order");
        orderKeyRef.current = { fingerprint, key: freshKey };
        result = await attempt(freshKey);
      }
      // Success — the next purchase (even with identical inputs) must be a
      // new order, so the key does not survive to be replayed.
      orderKeyRef.current = null;
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
      // Wallet ⇒ `WalletGateway` already debited and the saga already
      // walked the order toward delivered inside `create_intent` — pivot
      // the toast wording so the buyer understands the money has actually
      // moved, same as `TopUp`.
      if (result.payment.provider === "wallet") {
        toast({
          title: t("topup.paidFromBalance"),
          description: t("topup.processing", { game: detail.name }),
        });
      } else {
        toast({
          title: t("topup.orderCreated"),
          description: t("topup.processing", { game: detail.name }),
        });
      }
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

  // Captured as a local so `countryAvailable` below doesn't close over the
  // outer (nullable) `detail` state variable — TS narrows `detail` here
  // (past the `!detail` early return above) but that narrowing doesn't
  // survive into a nested function's body. `?? []`: `regions` is optional
  // on `GiftAppDetail` — a version-skewed API build predating the country
  // picker resolves `detail` truthy but without it (`lib/gifts.ts`'s
  // `apiGet`/`api()` casts the JSON response unchecked).
  const regions = detail.regions ?? [];
  const countries = regions.map((r) => r.country);

  // Nothing sellable at all — an unlikely but real possibility once
  // `regions` is optional. Same posture as the `notFound`/`error` phases
  // above: degrade, don't crash on `detail.regions.map(...)` mid-render.
  if (countries.length === 0) {
    return (
      <div className="flex flex-col items-center gap-4 p-6 pt-24 text-center">
        <p className="text-sm text-white/50">{t("gifts.comingSoon")}</p>
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

  const { visible: visibleCountries, overflow: overflowCountries } = splitCountries(
    countries,
    VISIBLE_COUNTRY_COUNT,
  );

  /** Whether the currently selected package still has a price in this
   *  country's zone — drives a pill's disabled state. */
  function countryAvailable(country: string): boolean {
    const zone = zoneForCountry(regions, country);
    return zone !== null && (selectedPackage?.prices.some((p) => p.zone === zone) ?? false);
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.22 }}
      className="pb-32"
    >
      <InviteGuideSheet open={guideOpen} onOpenChange={setGuideOpen} />
      <RegionGuideSheet open={regionGuideOpen} onOpenChange={setRegionGuideOpen} />
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

        {/* A DLC delivered with no note is unusable if the recipient lacks
            the base game — `type` is the only DLC signal already on the
            wire (2026-09-04 review), so no parent-game name is available to
            append here. */}
        {isDlcApp(detail.type) && (
          <p className="rounded-xl border border-dashed border-white/15 bg-white/5 p-3 text-[13px] leading-relaxed text-white/60">
            {t("gifts.game.dlcNote")}
          </p>
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
                price={selectedCountry ? (priceFor(detail, pkg.id, selectedCountry) ?? null) : null}
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
          <div className="mb-2 flex items-center gap-3">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-white/50">
              {t("gifts.game.region")}
            </p>
            <button
              type="button"
              onClick={() => {
                setRegionGuideOpen(true);
              }}
              className="text-primary text-[11px] font-semibold"
            >
              {t("gifts.game.regionHintCta")}
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {visibleCountries.map((country) => (
              <RegionPill
                key={country}
                country={country}
                active={country === selectedCountry}
                available={countryAvailable(country)}
                locale={locale}
                onSelect={() => {
                  selectCountry(country);
                }}
              />
            ))}
            {overflowCountries.length > 0 && !countryExpanded && (
              <button
                type="button"
                onClick={() => {
                  setCountryExpanded(true);
                }}
                className="rounded-full border px-3 py-1.5 text-xs font-semibold text-white/50"
                style={{ borderColor: "hsl(var(--border))" }}
              >
                {t("gifts.game.otherRegion")}
              </button>
            )}
            {countryExpanded &&
              overflowCountries.map((country) => (
                <RegionPill
                  key={country}
                  country={country}
                  active={country === selectedCountry}
                  available={countryAvailable(country)}
                  locale={locale}
                  onSelect={() => {
                    selectCountry(country);
                  }}
                />
              ))}
          </div>
          {/* Shown only when `selectPackage` actually moved the country
              (`countryMovedOnEditionSwitch`) — the old always-on
              `regionWarning` line explained your OWN Steam country, not the
              recipient's, and is deleted (2026-09-04 review): the relabeled
              step above plus the region hint sheet now carry that rule. */}
          {editionCountryNotice && (
            <p className="mt-2 text-[12px] leading-snug text-white/40">
              {t("gifts.game.editionCountryOnly", {
                country: countryName(editionCountryNotice, locale),
              })}
            </p>
          )}
        </div>

        {/* Price */}
        <div className="border-t pt-4" style={{ borderColor: "hsl(var(--border) / 0.7)" }}>
          {priceAvailability === "priced" && price ? (
            <p className="text-2xl font-bold tabular-nums text-white">
              {priceLabel(price, t("gifts.priceUnavailable"))}
            </p>
          ) : priceAvailability === "fxDown" ? (
            // FX down must block the sale, not guess (2026-09-04 review) —
            // the mature panels' own dashed placeholder
            // (`TopUp.tsx`'s `VariableAmountPanel`), never a USD figure.
            <p className="rounded-2xl border border-dashed border-white/10 p-4 text-center text-sm text-white/40">
              {t("topup.priceUnavailable")}
            </p>
          ) : (
            <p className="text-sm text-white/50">{t("gifts.game.noPriceInRegion")}</p>
          )}
        </div>

        <GiftBuyPanel
          inviteUrl={inviteUrl}
          onInviteUrlChange={setInviteUrl}
          showInviteError={inviteTouched && canonicalInvite === null}
          onOpenGuide={() => {
            setGuideOpen(true);
          }}
          skuStatus={skuStatus}
          methodId={methodId}
          providerStatusBySlug={providerStatusBySlug}
          onMethodChange={setMethodId}
          walletActive={methodId === WALLET_METHOD_ID}
          walletEnough={walletPay.enough}
          walletLoading={walletQuery.isPending}
          walletBalance={walletBalance}
          walletShortfall={walletPay.shortfall}
          walletVisibility={walletVisibility}
          walletUnknownTotal={walletPay.unknownTotal}
          onSelectWallet={() => {
            setMethodId(WALLET_METHOD_ID);
          }}
          canBuy={canBuy}
          isPending={checkout.isPending}
          onBuy={() => {
            void handleBuy();
          }}
        />

        <div className="space-y-1 text-[12px] leading-relaxed text-white/40">
          <p>{t("gifts.game.timeline")}</p>
          <p>{t("gifts.game.accept")}</p>
        </div>
      </div>
    </motion.div>
  );
}
