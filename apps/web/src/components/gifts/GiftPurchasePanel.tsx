"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { formatMoney } from "@yupay/utils";
import { ArrowUpRight, Loader2 } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useId, useState } from "react";

import { InviteGuide } from "./InviteGuide";
import { RegionHint } from "./RegionHint";

import type { GiftAppDetail, GiftPackage } from "@/lib/gifts";
import type { ProviderStatus, ProvidersOut } from "@/lib/payment-providers";

import { WalletMark } from "@/components/icons/WalletMark";
import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { ApiError, getAccessToken, SURFACE } from "@/lib/client";
import { buyGift, GiftPriceChangedError } from "@/lib/gift-checkout";
import { methodVisibility, providerStatusMap, selectActiveMethodId } from "@/lib/payment-providers";
import { countryName, flagEmoji } from "@/lib/regions";
import { formatUzs, pathFor } from "@/lib/seo";
import { getWallet, WALLET_CURRENCY } from "@/lib/wallet";
import { canPayFromBalance, spendableBalance, walletTile } from "@/lib/wallet-balance";
import { useLoginModal } from "@/store/useLoginModal";
import { toast } from "@/store/useToast";

const API = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** How many offered countries show as their own pill before the rest
 *  collapse behind a single "другой регион" toggle — CIS alone is nine
 *  countries. */
const VISIBLE_COUNTRY_COUNT = 4;

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** In-scope acquirers for a gift purchase — same three UZ rails
 *  `PurchasePanel` offers. The wallet is a separate tile (`WALLET_METHOD_ID`
 *  below), not one of these — see its own comment for why. */
interface Method {
  id: string;
  name: string;
  provider: string;
  icon: string;
  w: number;
  h: number;
}

/** Not an acquirer: the balance is our own ledger, and `WalletGateway`
 *  settles it synchronously inside `create_intent`. Kept out of `METHODS`
 *  so provider-availability logic, which is about upstream acquirers, never
 *  reasons about it — mirrors `PurchasePanel`'s `WALLET_METHOD_ID`. */
const WALLET_METHOD_ID = "wallet";

const METHODS: Method[] = [
  {
    id: "click",
    name: "Click",
    provider: "click",
    icon: "/payment/click-mark.png",
    w: 160,
    h: 160,
  },
  {
    id: "payme",
    name: "Payme",
    provider: "payme",
    icon: "/payment/payme-mark.png",
    w: 160,
    h: 160,
  },
  { id: "uzum", name: "Uzum", provider: "uzum", icon: "/payment/uzum-mark.png", w: 160, h: 160 },
];

//: Steam invite-link shapes, mirroring `checkout.py::parse_invite_url`'s
//: three accepted forms — this is only a client-side gate (the server is
//: the actual source of truth and canonicalizes on its own), so it doesn't
//: need to match byte-for-byte, just reject the same obviously-wrong input.
const STEAM_ID64_RE = /^\d{17}$/;
const STEAM_VANITY_RE = /^[A-Za-z0-9_-]{2,32}$/;
const S_TEAM_PATH_RE = /^[A-Za-z0-9/_-]{1,64}$/;

function isValidInviteUrl(raw: string): boolean {
  const value = raw.trim();
  if (!value) return false;
  const candidate = value.includes("://") ? value : `https://${value}`;
  let url: URL;
  try {
    url = new URL(candidate);
  } catch {
    return false;
  }
  if (url.protocol !== "https:") return false;
  const host = url.hostname.toLowerCase();
  const parts = url.pathname.replace(/\/+$/, "").split("/").filter(Boolean);
  if (host === "steamcommunity.com") {
    if (parts.length === 2 && parts[0] === "profiles") return STEAM_ID64_RE.test(parts[1] ?? "");
    if (parts.length === 2 && parts[0] === "id") return STEAM_VANITY_RE.test(parts[1] ?? "");
    return false;
  }
  if (host === "s.team") {
    if (parts.length >= 2 && parts[0] === "p") {
      return S_TEAM_PATH_RE.test(parts.slice(1).join("/"));
    }
    return false;
  }
  return false;
}

/**
 * The buy panel for one Steam gift: edition + region pickers, the invite
 * link field, a pay-from-balance tile plus a payment-method grid, and the
 * Buy button. v1 scope cuts, deliberate: no promo field, no quantity — a
 * gift order is always exactly one package, in one region, `qty: 1`.
 */
export function GiftPurchasePanel({
  detail,
  skuId,
  locale,
}: {
  detail: GiftAppDetail;
  skuId: string;
  locale: string;
}) {
  const t = useTranslations("web.gifts.game");
  const tg = useTranslations("web.gifts");
  // Payment-method chrome and the guest email field reuse `PurchasePanel`'s
  // existing copy (`emailLabel`/`paymentTitle`/...) rather than forking a
  // second translation of the same sentences into this namespace.
  const ts = useTranslations("web.store");
  const router = useRouter();
  const { user, isLoading: authLoading } = useAuth();

  const [packageId, setPackageId] = useState<number>(() => detail.packages[0]?.id ?? 0);
  // `region_default`/`regions` are optional (see `GiftAppDetail` in
  // `lib/gifts.ts`): `apiGet` trusts the response shape with an
  // unchecked cast, so a version-skewed API response that predates these
  // fields resolves here truthy but without them — never throw on that,
  // degrade to the coming-soon state below instead.
  const [country, setCountry] = useState<string>(detail.region_default ?? "");

  // The country picker's own unit is the country, but a package's prices
  // are keyed by zone (`GiftPackage.prices[].zone`) — every country a zone
  // covers shares that zone's price. `detail.regions` is the country ->
  // zone map the country picker renders from; resolving through it (rather
  // than the country's own `price_usd`, which reflects whichever package
  // first priced that zone) keeps this in sync with whatever package is
  // currently selected — see `zone_for_country` on the backend for the
  // server-side twin of this lookup.
  const countryZone = new Map((detail.regions ?? []).map((r) => [r.country, r.zone]));

  const selectedPackage: GiftPackage | null =
    detail.packages.find((p) => p.id === packageId) ?? detail.packages[0] ?? null;
  const selectedZone = countryZone.get(country);
  const selectedPrice =
    selectedZone !== undefined
      ? (selectedPackage?.prices.find((p) => p.zone === selectedZone) ?? null)
      : null;

  const countries = (detail.regions ?? []).map((r) => r.country);
  // No offered country at all — an unlikely but real possibility once
  // `regions` is optional (version-skewed API, or a catalog entry with no
  // priced zone). Same posture as `page.tsx` omitting the Offer: degrade,
  // don't crash — rendered as the coming-soon state below, in place of a
  // form with nothing sellable in it.
  const hasRegions = countries.length > 0;
  const visibleCountries = countries.slice(0, VISIBLE_COUNTRY_COUNT);
  const overflowCountries = countries.slice(VISIBLE_COUNTRY_COUNT);
  const [countryExpanded, setCountryExpanded] = useState<boolean>(() =>
    overflowCountries.includes(country),
  );

  /** Selection reconciliation on a package switch: keeps the chosen
   *  country if its zone is still priced by the new package, else falls
   *  back to `region_default`, else falls back to a country covering
   *  whatever price the package does offer — a package with no prices at
   *  all, or a fallback zone no known country covers, leaves the country
   *  untouched. Mirrors `countryAfterPackageChange` on the miniapp
   *  (`GiftGame.tsx`) exactly: a package priced only in a zone neither the
   *  current nor the default country covers (e.g. a deluxe edition sold
   *  only in RU while the buyer sits on UZ) must still land on a priced
   *  country, not silently disable Buy. */
  function selectPackage(pkg: GiftPackage): void {
    setPackageId(pkg.id);
    const zone = countryZone.get(country);
    if (zone !== undefined && pkg.prices.some((p) => p.zone === zone)) return;

    const defaultCountry = detail.region_default ?? "";
    const defaultZone = countryZone.get(defaultCountry);
    if (defaultZone !== undefined && pkg.prices.some((p) => p.zone === defaultZone)) {
      setCountry(defaultCountry);
      return;
    }

    const fallbackZone = pkg.prices[0]?.zone;
    if (fallbackZone === undefined) return;
    for (const [candidateCountry, candidateZone] of countryZone) {
      if (candidateZone === fallbackZone) {
        setCountry(candidateCountry);
        return;
      }
    }
  }

  function selectCountry(c: string): void {
    const zone = countryZone.get(c);
    if (zone === undefined || !selectedPackage?.prices.some((p) => p.zone === zone)) return;
    setCountry(c);
  }

  const [inviteUrl, setInviteUrl] = useState("");
  const inviteValid = isValidInviteUrl(inviteUrl);
  const [email, setEmail] = useState("");

  // Signed-in buyers get their account's delivery address pre-filled, the
  // same fallback `PurchasePanel` uses — a guest sees a blank field.
  useEffect(() => {
    if (email !== "") return;
    const fromAccount = user?.delivery_email ?? user?.email ?? "";
    if (fromAccount) setEmail(fromAccount);
  }, [user, email]);

  const [methodId, setMethodId] = useState<string>(METHODS[0]?.id ?? "click");
  const [providerStatus, setProviderStatus] = useState<Map<string, ProviderStatus> | null>(null);

  // Load provider availability once so the method grid can hide
  // admin-disabled acquirers and grey out ones under maintenance before the
  // customer ever tries to pay — same fetch `PurchasePanel` runs.
  useEffect(() => {
    let cancelled = false;
    fetch(`${API}/api/v1/payments/providers`, { headers: { "X-Yupay-Surface": SURFACE } })
      .then((r) => r.json() as Promise<ProvidersOut>)
      .then((data) => {
        if (!cancelled) setProviderStatus(providerStatusMap(data));
      })
      .catch(() => {
        // Leave `providerStatus` as `null` — fails open, see its declaration.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!providerStatus) return;
    setMethodId((current) => {
      // The wallet is not in METHODS, so `selectActiveMethodId` cannot find
      // it, falls past its "keep the current one" guard and answers with the
      // first active acquirer instead. A buyer who picked "pay from
      // balance" before this fetch landed would have had that swapped for a
      // card without being told — mirrors `PurchasePanel`'s same guard. Its
      // own readiness is `walletState`/`walletVisibility`, not this effect.
      if (current === WALLET_METHOD_ID) return current;
      return selectActiveMethodId(METHODS, current, providerStatus) ?? "";
    });
  }, [providerStatus]);

  // Only fetched for a signed-in buyer — a guest has no wallet, and asking
  // would 401.
  const walletQuery = useQuery({
    queryKey: ["wallet"],
    queryFn: getWallet,
    enabled: user !== null,
    staleTime: 30_000,
  });
  // Gift orders are always billed in UZS (`buyGift` hardcodes `currency:
  // "UZS"`), so the region's `price_uzs` is what the balance must cover —
  // never `price_usd`, which the FX-unavailable case leaves as the only
  // figure on the DTO.
  const total = selectedPrice?.price_uzs != null ? Number(selectedPrice.price_uzs) : null;
  const walletState = walletTile({
    // `isLoading` matters: the access token is memory-only, so a cold load
    // re-mints it and `user` is null for a beat — treating that as "guest"
    // would tell a signed-in buyer to sign in.
    isLoggedIn: user !== null || authLoading,
    balance: spendableBalance(walletQuery.data?.balances ?? null, WALLET_CURRENCY),
    total,
  });
  const payingFromBalance = methodId === WALLET_METHOD_ID;
  // The wallet rides the same admin lever as the acquirers (ADR-0056, an FX
  // drop can stop pay-from-balance too) — `methodVisibility` fails open
  // (`"active"`) while `providerStatus` is still `null`, same as everywhere
  // else it's consulted.
  const walletVisibility = methodVisibility(WALLET_METHOD_ID, providerStatus);

  const openLogin = useLoginModal((st) => st.open);
  const queryClient = useQueryClient();

  const selectedProvider = payingFromBalance
    ? WALLET_METHOD_ID
    : METHODS.find((m) => m.id === methodId)?.provider;
  const selectedMethodActive = payingFromBalance
    ? canPayFromBalance(walletState) && walletVisibility === "active"
    : selectedProvider !== undefined &&
      methodVisibility(selectedProvider, providerStatus) === "active";
  const anyMethodVisible = METHODS.some(
    (m) => methodVisibility(m.provider, providerStatus) !== "hidden",
  );

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const emailValid = user !== null || EMAIL_RE.test(email);
  const canBuy =
    selectedPrice !== null && inviteValid && emailValid && selectedMethodActive && !loading;

  async function handleBuy(): Promise<void> {
    // `canBuy` already requires `selectedPrice !== null` — TS's aliased-
    // condition narrowing carries that through past this guard, so it isn't
    // re-checked here.
    if (!canBuy || !selectedPackage || !selectedProvider) return;
    setLoading(true);
    setError(null);
    const token = getAccessToken();
    const loggedIn = user !== null && token !== null;
    try {
      const result = await buyGift({
        locale,
        skuId,
        amountUsd: selectedPrice.price_usd,
        fulfillmentData: {
          app_id: detail.app_id,
          package_id: selectedPackage.id,
          region: country,
          invite_url: inviteUrl.trim(),
        },
        // `loggedIn` aliases `user !== null` — `user` is narrowed non-null
        // in this branch, so no `?.` is needed here either.
        email: loggedIn ? (user.delivery_email ?? user.email ?? "") : email.trim().toLowerCase(),
        isLoggedIn: loggedIn,
        provider: selectedProvider,
        gameName: detail.name,
      });
      if (result.intentUrl && selectedProvider !== "mock") {
        // Real acquirer → its hosted payment page.
        window.location.href = result.intentUrl;
        return;
      }
      // Both the dev `mock` provider and a wallet payment (settled
      // synchronously inside `create_intent`) return a null/non-resolvable
      // `intent_url` — go straight to the order page, which already shows
      // the pending timeline, or in the wallet's case the paid one.
      router.push(result.trackHref);
    } catch (err) {
      if (err instanceof GiftPriceChangedError) {
        toast.info(tg("priceChanged"));
        // Re-fetches the game detail from the server; this client component
        // keeps its own state (package/country/invite/email) across the
        // refresh, and the recomputed `selectedPrice` above picks up the
        // server's current figure automatically.
        router.refresh();
      } else if (err instanceof ApiError && err.detail) {
        // Carries e.g. `create_intent`'s 409 "insufficient wallet balance:
        // have … need …" through to the buyer — the client-side `short`
        // check above is only a courtesy; `WalletGateway` re-checks under a
        // row lock, so a race can still land here. Matched structurally
        // (an `ApiError` with a `detail`), never by grepping the message.
        setError(err.detail);
      } else {
        setError(t("buyError"));
      }
    } finally {
      // Whatever happened, the balance we hold may no longer be the one the
      // ledger holds: a wallet payment just spent from it, and a failure may
      // have been the server refusing on a balance we had cached as
      // sufficient. Re-read rather than leave the tile promising a payment
      // that will be refused again.
      if (payingFromBalance) {
        void queryClient.invalidateQueries({ queryKey: ["wallet"] });
      }
      setLoading(false);
    }
  }

  const inviteId = useId();
  const emailId = useId();

  // No sellable country at all (see `hasRegions` above) — same posture the
  // page-level caller already uses when there's no purchasable SKU yet
  // (`GiftGamePage`'s `skuId ? <GiftPurchasePanel /> : <...comingSoon>`):
  // render the coming-soon placeholder instead of a form with nothing to
  // pick. All hooks above have already run unconditionally, so branching
  // here is safe.
  if (!hasRegions) {
    return (
      <div className="border-border bg-card rounded-2xl border p-6 text-center">
        <p className="text-tx-mute text-sm">{tg("comingSoon")}</p>
      </div>
    );
  }

  return (
    <div className="border-border bg-card space-y-5 rounded-2xl border p-5 sm:p-6">
      <div>
        <p className="text-tx-dim text-[11px] font-semibold uppercase tracking-[0.08em]">
          {t("edition")}
        </p>
        <div className="mt-2 flex flex-col gap-2">
          {detail.packages.map((pkg) => {
            const price =
              selectedZone !== undefined
                ? (pkg.prices.find((p) => p.zone === selectedZone) ?? null)
                : null;
            const active = pkg.id === selectedPackage?.id;
            const discount =
              pkg.discount_percent != null && pkg.discount_percent > 0
                ? pkg.discount_percent
                : null;
            return (
              <button
                key={pkg.id}
                type="button"
                aria-pressed={active}
                onClick={() => {
                  selectPackage(pkg);
                }}
                className={`rounded-lg border p-3 text-left transition ${
                  active
                    ? "border-primary bg-primary/[0.06]"
                    : "border-border hover:border-border-2"
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-foreground text-sm font-semibold">{pkg.name}</span>
                  <span className="font-mono text-sm font-bold tabular-nums">
                    {price
                      ? price.price_uzs != null
                        ? formatUzs(locale, Math.round(Number(price.price_uzs)))
                        : formatMoney(price.price_usd, "USD", locale)
                      : "—"}
                  </span>
                </div>
                {discount !== null && (
                  <span className="text-primary mt-1 inline-block text-[11px] font-bold">
                    -{discount}%
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      <div>
        <div className="flex items-center gap-3">
          <p className="text-tx-dim text-[11px] font-semibold uppercase tracking-[0.08em]">
            {t("region")}
          </p>
          <RegionHint />
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          {visibleCountries.map((c) => (
            <CountryButton
              key={c}
              country={c}
              active={c === country}
              selectedPackage={selectedPackage}
              countryZone={countryZone}
              locale={locale}
              t={t}
              onSelect={selectCountry}
            />
          ))}
          {overflowCountries.length > 0 && !countryExpanded && (
            <button
              type="button"
              onClick={() => {
                setCountryExpanded(true);
              }}
              className="border-border text-tx-mute hover:border-border-2 rounded-full border px-3 py-1.5 text-xs font-semibold transition"
            >
              {t("otherRegion")}
            </button>
          )}
          {countryExpanded &&
            overflowCountries.map((c) => (
              <CountryButton
                key={c}
                country={c}
                active={c === country}
                selectedPackage={selectedPackage}
                countryZone={countryZone}
                locale={locale}
                t={t}
                onSelect={selectCountry}
              />
            ))}
        </div>
        <p className="text-tx-dim mt-2 text-[12px] leading-snug">{t("regionWarning")}</p>
      </div>

      <div className="border-border/70 border-t pt-4">
        {selectedPrice ? (
          <div className="flex items-baseline gap-2.5">
            <span className="font-display text-2xl font-bold tabular-nums">
              {selectedPrice.price_uzs != null
                ? formatUzs(locale, Math.round(Number(selectedPrice.price_uzs)))
                : formatMoney(selectedPrice.price_usd, "USD", locale)}
            </span>
            {selectedPrice.price_uzs != null && (
              <span className="text-tx-dim text-sm">
                {formatMoney(selectedPrice.price_usd, "USD", locale)}
              </span>
            )}
          </div>
        ) : (
          <p className="text-tx-mute text-sm">{t("noPriceInRegion")}</p>
        )}
      </div>

      <div className="space-y-2">
        <label
          htmlFor={inviteId}
          className="text-tx-dim text-[11px] font-semibold uppercase tracking-[0.08em]"
        >
          {t("inviteLabel")}
        </label>
        <input
          id={inviteId}
          type="text"
          value={inviteUrl}
          onChange={(e) => {
            setInviteUrl(e.target.value);
          }}
          placeholder={t("invitePlaceholder")}
          className="border-border bg-bg rounded-btn h-11 w-full border px-3 text-sm"
        />
        {inviteUrl.trim() !== "" && !inviteValid && (
          <p className="text-[13px] text-[#FF6B6B]">{t("inviteError")}</p>
        )}
        <InviteGuide />
      </div>

      {!user && (
        <div className="space-y-1.5">
          <label
            htmlFor={emailId}
            className="text-tx-dim text-[11px] font-semibold uppercase tracking-[0.08em]"
          >
            {ts("emailLabel")}
          </label>
          <input
            id={emailId}
            type="email"
            required
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
            }}
            placeholder={ts("emailPlaceholder")}
            className="border-border bg-bg rounded-btn h-11 w-full border px-3 text-sm"
          />
        </div>
      )}

      <div>
        <p className="text-tx-dim mb-2 text-[11px] font-semibold uppercase tracking-[0.08em]">
          {ts("paymentTitle")}
        </p>
        {/* Full width, above the acquirer grid — mirrors `PurchasePanel`'s
            wallet tile. Hidden outright when an admin disables the wallet
            entirely; kept visible but unselectable under maintenance, same
            as an acquirer tile. */}
        {walletVisibility !== "hidden" && (
          <>
            <button
              type="button"
              // Only a toggle when there is something to toggle: in the
              // guest state this button signs you in, and announcing it as
              // "not pressed" describes a choice that is not on offer.
              aria-pressed={walletState.state === "guest" ? undefined : payingFromBalance}
              disabled={
                walletVisibility !== "active" ||
                (walletState.state !== "ready" && walletState.state !== "guest")
              }
              title={walletVisibility === "maintenance" ? ts("paymentMaintenance") : undefined}
              onClick={() => {
                if (walletState.state === "guest") {
                  openLogin();
                  return;
                }
                setMethodId(WALLET_METHOD_ID);
              }}
              className={`rounded-btn mb-2 flex w-full items-center gap-3 border px-3 py-3 text-left transition disabled:cursor-not-allowed ${
                payingFromBalance && walletState.state === "ready"
                  ? "border-primary bg-primary/10"
                  : "border-border bg-bg hover:border-border-2"
              }`}
            >
              <span
                className={`bg-muted flex h-9 w-9 shrink-0 items-center justify-center rounded-md ${
                  walletState.state === "ready" || walletState.state === "guest"
                    ? "text-primary"
                    : "text-tx-dim"
                }`}
              >
                <WalletMark size={18} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[13px] font-semibold">{ts("payFromBalance")}</span>
                <span className="text-tx-dim block text-[12px]">
                  {walletState.state === "guest"
                    ? ts("payFromBalanceGuest")
                    : walletState.state === "short"
                      ? ts("payFromBalanceShort", {
                          amount: formatUzs(locale, walletState.missing),
                        })
                      : walletState.state === "ready"
                        ? formatUzs(locale, Math.round(walletState.balance))
                        : walletState.state === "noTotal"
                          ? ts("payFromBalanceUnknown")
                          : ts("payFromBalanceLoading")}
                </span>
              </span>
            </button>

            {/* "Не хватает 45 000" is a fact; this is what to do about it. A
                new tab so the invite link and picked package survive the
                trip. */}
            {walletState.state === "short" && (
              <Link
                href={pathFor(locale, "/account/wallet/top-up")}
                target="_blank"
                rel="noreferrer"
                className="text-primary hover:text-primary-2 mb-2 inline-flex items-center gap-1 text-[13px] font-semibold"
              >
                {ts("payFromBalanceTopUp")}
                <ArrowUpRight size={14} />
              </Link>
            )}
          </>
        )}
        {anyMethodVisible ? (
          <div className="grid grid-cols-3 gap-2">
            {METHODS.map((m) => {
              const visibility = methodVisibility(m.provider, providerStatus);
              if (visibility === "hidden") return null;
              const disabled = visibility === "maintenance";
              const active = !disabled && m.id === methodId;
              return (
                <button
                  key={m.id}
                  type="button"
                  aria-label={m.name}
                  aria-pressed={active}
                  title={disabled ? ts("paymentMaintenance") : undefined}
                  disabled={disabled}
                  onClick={() => {
                    setMethodId(m.id);
                  }}
                  className={`rounded-btn flex flex-col items-center justify-center gap-1 border px-3 py-3 transition disabled:cursor-not-allowed disabled:opacity-60 ${
                    active
                      ? "border-primary bg-primary/10"
                      : "border-border bg-bg hover:border-border-2"
                  }`}
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-md">
                    <Image
                      src={m.icon}
                      alt=""
                      width={m.w}
                      height={m.h}
                      className="h-full w-full object-cover"
                    />
                  </span>
                  <span className="text-foreground text-[13px] font-semibold">{m.name}</span>
                </button>
              );
            })}
          </div>
        ) : (
          <p className="text-tx-mute text-sm">{ts("paymentNone")}</p>
        )}
      </div>

      <button
        type="button"
        disabled={!canBuy}
        onClick={() => void handleBuy()}
        className={buttonStyles({ size: "lg", className: "w-full" })}
      >
        {loading ? <Loader2 size={18} className="animate-spin" aria-hidden="true" /> : t("buy")}
      </button>
      {error && <p className="text-[13px] text-[#FF6B6B]">{error}</p>}

      <div className="text-tx-dim space-y-1 text-[12px] leading-relaxed">
        <p>{t("timeline")}</p>
        <p>{t("accept")}</p>
      </div>
    </div>
  );
}

/** One country pill: flag + localized name, priced from the zone that
 *  covers it. Disabled *with visible text* (not a `title=` tooltip, which
 *  is invisible on mobile) when the currently selected package has no
 *  price in that zone. */
function CountryButton({
  country,
  active,
  selectedPackage,
  countryZone,
  locale,
  t,
  onSelect,
}: {
  country: string;
  active: boolean;
  selectedPackage: GiftPackage | null;
  countryZone: Map<string, string>;
  locale: string;
  t: ReturnType<typeof useTranslations>;
  onSelect: (country: string) => void;
}) {
  const zone = countryZone.get(country);
  const available =
    zone !== undefined && (selectedPackage?.prices.some((p) => p.zone === zone) ?? false);
  return (
    <button
      type="button"
      disabled={!available}
      aria-pressed={active}
      onClick={() => {
        onSelect(country);
      }}
      className={`flex flex-col items-start gap-0.5 rounded-lg border px-3 py-1.5 text-left text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-60 ${
        active
          ? "border-primary bg-primary/10 text-primary"
          : "border-border text-tx-mute hover:border-border-2"
      }`}
    >
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden="true">{flagEmoji(country)}</span>
        {countryName(country, locale)}
      </span>
      {!available && (
        <span className="text-tx-dim text-[10px] font-normal normal-case">
          {t("noPriceInRegion")}
        </span>
      )}
    </button>
  );
}
