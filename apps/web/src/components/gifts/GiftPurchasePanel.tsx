"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Check, ExternalLink, Loader2 } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";

import { InviteGuide } from "./InviteGuide";
import { RegionHintPanel, RegionHintToggle } from "./RegionHint";

import type { GiftAppDetail, GiftPackage, GiftProfileCheck } from "@/lib/gifts";
import type { ProviderStatus, ProvidersOut } from "@/lib/payment-providers";

import { WalletMark } from "@/components/icons/WalletMark";
import {
  ConfirmPurchaseModal,
  type ConfirmPurchaseRow,
} from "@/components/store/ConfirmPurchaseModal";
import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { ApiError, getAccessToken, SURFACE } from "@/lib/client";
import {
  buyGift,
  GiftPriceChangedError,
  isOrderNotAwaitingPaymentConflict,
  orderFingerprint,
} from "@/lib/gift-checkout";
import { checkGiftProfile, profileCheckBlocks } from "@/lib/gifts";
import { isOptimizable } from "@/lib/image";
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

/** How long the invite field waits, idle, before showing an error on its
 *  own — mirrors the catalog search debounces elsewhere in this module.
 *  Blurring the field shows the error immediately regardless. */
const INVITE_ERROR_DEBOUNCE_MS = 600;

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** The invite field's caption styling, shared by the `<label>` that owns the
 *  input and the plain caption that stands in for it once the field collapses
 *  into the confirmed-recipient card (a `<label>` whose `htmlFor` points at a
 *  control that is no longer rendered announces as a dangling label). */
const FIELD_LABEL_CLASS = "text-tx-dim text-[11px] font-semibold uppercase tracking-[0.08em]";

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

/** Turns whatever the buyer pasted into a `URL`, defaulting the scheme to
 *  `https://` the way a browser address bar would — shared by
 *  `isValidInviteUrl` (the accept/reject gate) and the "Открыть профиль"
 *  link (which needs the same normalized, absolute form to link to). */
function parseInviteUrl(raw: string): URL | null {
  const value = raw.trim();
  if (!value) return null;
  const candidate = value.includes("://") ? value : `https://${value}`;
  try {
    return new URL(candidate);
  } catch {
    return null;
  }
}

function isValidInviteUrl(raw: string): boolean {
  const url = parseInviteUrl(raw);
  if (!url) return false;
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

/** The "Открыть профиль получателя" link's `href` — the normalized,
 *  absolute form of the pasted invite, or `null` while it isn't a valid one
 *  yet. This is the free half of the deferred server-side profile checker:
 *  the buyer verifies the link resolves to the right person with their own
 *  eyes, in a new tab, before paying (2026-09-04 review). */
function inviteProfileHref(raw: string): string | null {
  if (!isValidInviteUrl(raw)) return null;
  return parseInviteUrl(raw)?.toString() ?? null;
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
  // `emailInvalid` ("Введите корректный email") is `AuthForm`'s established
  // wording for the same syntax check — reused rather than forking a third
  // translation of "that doesn't look like an email".
  const ta = useTranslations("web.auth");
  const router = useRouter();
  const { user, isLoading: authLoading } = useAuth();

  const [packageId, setPackageId] = useState<number>(() => detail.packages[0]?.id ?? 0);
  // `region_default`/`regions` are optional (see `GiftAppDetail` in
  // `lib/gifts.ts`): `apiGet` trusts the response shape with an
  // unchecked cast, so a version-skewed API response that predates these
  // fields resolves here truthy but without them — never throw on that,
  // degrade to the coming-soon state below instead.
  const [country, setCountry] = useState<string>(detail.region_default ?? "");
  // The country an edition switch just reassigned the buyer to, so the
  // shared "Это издание продаётся только для: {country}" notice can render
  // — and ONLY render — when `selectPackage` below actually moved it. `null`
  // on mount and after any manual country pick; never set except inside
  // `selectPackage`'s own reassignment branches.
  const [editionSwitchCountry, setEditionSwitchCountry] = useState<string | null>(null);

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
  // `price_uzs` legitimately comes back `null` when the FX trust gate
  // rejected the live rate — distinct from `selectedPrice === null` (no
  // price for this zone at all, which keeps its own `noPriceInRegion`
  // copy). Buying at `price_usd` here would charge the buyer an amount they
  // never saw in soum, so this gates both `canBuy` below and the wallet
  // tile's total.
  const priceUnavailable = selectedPrice !== null && selectedPrice.price_uzs == null;
  // The one formatted-price computation every call site used to repeat
  // verbatim (the Buy button, the confirm dialog's total, the main price
  // row, the sticky bar) — `null` covers both "nothing selected" and
  // "FX is down", so each site still decides its own wording for that case
  // (a dashed FX-down card here, a bare "—" there) the way `PurchasePanel`'s
  // `selectedPriceLabel` does at its own four call sites (2026-09-04 review,
  // round 2).
  const selectedPriceLabel =
    selectedPrice?.price_uzs != null
      ? formatUzs(locale, Math.round(Number(selectedPrice.price_uzs)))
      : null;

  const countries = (detail.regions ?? []).map((r) => r.country);
  // No offered country at all — an unlikely but real possibility once
  // `regions` is optional (version-skewed API, or a catalog entry with no
  // priced zone). Same posture as `page.tsx` omitting the Offer: degrade,
  // don't crash — rendered as the coming-soon state below, in place of a
  // form with nothing sellable in it.
  const hasRegions = countries.length > 0;

  /** Whether `c`'s zone has a price under the currently selected package —
   *  the same check `CountryButton` used to run for itself, centralized
   *  here so the visible/overflow split below can use it too. */
  function countryAvailable(c: string): boolean {
    const zone = countryZone.get(c);
    return zone !== undefined && (selectedPackage?.prices.some((p) => p.zone === zone) ?? false);
  }

  // Unpriced countries always fold into the overflow, never the visible row
  // — previously a country's *position* alone decided whether it showed
  // (positionally in the first `VISIBLE_COUNTRY_COUNT`), so an unpriced
  // country could sit right in the visible row, disabled, with its own
  // "нет цены…" caption. On a nine-country row that repeated the same
  // sentence under up to eight pills at 10px (2026-09-04 review) — see the
  // single row-level `noPriceInRegion` message below instead.
  const pricedCountries = countries.filter(countryAvailable);
  const visibleCountries = pricedCountries.slice(0, VISIBLE_COUNTRY_COUNT);
  const overflowCountries = countries.filter((c) => !visibleCountries.includes(c));
  const hasUnpricedCountry = countries.some((c) => !countryAvailable(c));
  // Sticky manual toggle only — the buyer's own tap on "другой регион".
  // Never auto-collapses; the auto-*expand* half lives in
  // `countryPanelExpanded` below, derived at render rather than synced here.
  const [countryExpanded, setCountryExpanded] = useState(false);

  // Whether the overflow panel actually renders open — either the buyer
  // toggled it manually (`countryExpanded`), or the current selection landed
  // behind it and needs to be forced open. Computed fresh every render, not
  // synced through a `useEffect` keyed on `country`: `selectPackage`'s first
  // branch (below) deliberately leaves `country` unchanged when the new
  // package still prices its zone — but that same switch can still reorder
  // `pricedCountries` above, pushing the still-selected country out of the
  // visible slice without `country` itself ever changing. An effect keyed on
  // `country` alone never fires for that path and leaves a selected country
  // hidden behind "другой регион" with nothing highlighted (2026-09-04
  // review, round 2). Deriving it here instead — from whatever
  // `overflowCountries` currently is — rules that whole bug class out, for
  // the price of nothing.
  const countryPanelExpanded = countryExpanded || overflowCountries.includes(country);

  // Whether the "Как узнать?" panel is open — lifted here (not owned inside
  // `RegionHint`) so the expanded panel can render as this row's sibling
  // instead of its child. See `RegionHintToggle`/`RegionHintPanel`.
  const [regionHintOpen, setRegionHintOpen] = useState(false);

  /** Selection reconciliation on a package switch: keeps the chosen
   *  country if its zone is still priced by the new package, else falls
   *  back to `region_default`, else falls back to a country covering
   *  whatever price the package does offer — a package with no prices at
   *  all, or a fallback zone no known country covers, leaves the country
   *  untouched. Mirrors `countryAfterPackageChange` on the miniapp
   *  (`GiftGame.tsx`) exactly: a package priced only in a zone neither the
   *  current nor the default country covers (e.g. a deluxe edition sold
   *  only in RU while the buyer sits on UZ) must still land on a priced
   *  country, not silently disable Buy.
   *
   *  Also tracks `editionSwitchCountry`: set exactly when a reassignment
   *  branch below actually fires, so the shared "this edition only sells
   *  for {country}" notice shows only on a real, silent move — never on a
   *  no-op reselect of the already-active package. */
  function selectPackage(pkg: GiftPackage): void {
    setPackageId(pkg.id);
    const zone = countryZone.get(country);
    if (zone !== undefined && pkg.prices.some((p) => p.zone === zone)) {
      // The current country still prices this edition — nothing moved.
      setEditionSwitchCountry(null);
      return;
    }

    const defaultCountry = detail.region_default ?? "";
    const defaultZone = countryZone.get(defaultCountry);
    if (defaultZone !== undefined && pkg.prices.some((p) => p.zone === defaultZone)) {
      setCountry(defaultCountry);
      setEditionSwitchCountry(defaultCountry);
      return;
    }

    const fallbackZone = pkg.prices[0]?.zone;
    if (fallbackZone === undefined) {
      setEditionSwitchCountry(null);
      return;
    }
    for (const [candidateCountry, candidateZone] of countryZone) {
      if (candidateZone === fallbackZone) {
        setCountry(candidateCountry);
        setEditionSwitchCountry(candidateCountry);
        return;
      }
    }
    setEditionSwitchCountry(null);
  }

  function selectCountry(c: string): void {
    if (!countryAvailable(c)) return;
    setCountry(c);
    // A manual pick supersedes whatever an earlier edition switch chose —
    // the notice explaining that switch is now stale.
    setEditionSwitchCountry(null);
  }

  const [inviteUrl, setInviteUrl] = useState("");
  const inviteValid = isValidInviteUrl(inviteUrl);
  const inviteHasValue = inviteUrl.trim() !== "";
  // Whether the current text *would* show an error, ignoring timing — the
  // gate the buy button and `payHint` reason off, unconditionally.
  const inviteWrong = inviteHasValue && !inviteValid;
  // Timing only, for the visible error paragraph below the field: it used to
  // fire on the very first keystroke, well before the buyer had finished
  // pasting or typing (2026-09-04 review). Shown once the field is blurred,
  // or after a short idle pause — whichever comes first — never live on
  // every change.
  const [inviteTouched, setInviteTouched] = useState(false);
  const [inviteIdle, setInviteIdle] = useState(false);
  useEffect(() => {
    setInviteIdle(false);
    if (!inviteWrong) return;
    const timer = setTimeout(() => {
      setInviteIdle(true);
    }, INVITE_ERROR_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [inviteUrl, inviteWrong]);
  const inviteInvalid = inviteWrong && (inviteTouched || inviteIdle);
  const inviteHref = inviteProfileHref(inviteUrl);

  // The pre-purchase recipient check («Проверить»). The verdict is stored
  // together with the link it was asked about and read back only while the
  // field still holds that same link — which buys two things at once: editing
  // the link resets the check with no effect to keep in sync, and an answer
  // that lands after the buyer has already corrected the link is discarded
  // rather than shown against a profile they no longer mean.
  const [profile, setProfile] = useState<{ url: string; check: GiftProfileCheck } | null>(null);
  const [profileChecking, setProfileChecking] = useState(false);
  // Set when «Проверить» is pressed on a field it cannot run against, so the
  // empty-field case can say what's missing. Only "you haven't pasted the
  // link yet" needs it — a *wrong* link already has its own visible error;
  // announcing the empty one before the buyer has tried would be noise.
  // Mirrors `CheckablePlayerField`'s `attempted`.
  const [checkAttempted, setCheckAttempted] = useState(false);
  const inviteRef = useRef<HTMLInputElement>(null);
  const editRef = useRef<HTMLButtonElement>(null);
  const profileCheck = profile !== null && profile.url === inviteUrl.trim() ? profile.check : null;
  const profileFound = profileCheck?.status === "found" ? profileCheck : null;
  // The single new condition on the purchase. `profileCheckBlocks` is `true`
  // for exactly one verdict — Steam's own "no such profile" — so an
  // unsupported link type, a Steam outage, and a link nobody checked all
  // leave the buyer free to pay: a check that fails on our side must never
  // cost a sale.
  const profileBlocks = profileCheckBlocks(profileCheck);

  async function runProfileCheck(): Promise<void> {
    const url = inviteUrl.trim();
    if (!isValidInviteUrl(url)) {
      // A dimmed control that swallows the click teaches nothing. Pressing it
      // answers either way: a *wrong* link gets the visible link error the
      // field would otherwise hold back until blur or the idle pause, and an
      // *empty* one gets the "paste the link first" note (`profileNote`
      // below) — which `inviteWrong` alone cannot produce, since it requires
      // the field to be non-empty.
      setInviteTouched(true);
      setCheckAttempted(true);
      return;
    }
    setProfileChecking(true);
    try {
      const check = await checkGiftProfile(url);
      setProfile({ url, check });
      if (check.status === "found") {
        // The «Проверить» button unmounts along with the field it sits next
        // to, dropping focus to <body> — a keyboard user's next Tab would
        // restart at the top of the page with no signal that anything
        // happened. Hand focus to the card's «Изменить», the mirror of what
        // `reopenInvite` does on the way back.
        requestAnimationFrame(() => editRef.current?.focus());
      }
    } catch {
      // `checkGiftProfile` never rejects (see its doc comment). This is here
      // so the component stays correct on its own if that ever changes —
      // with it, `runProfileCheck` itself cannot reject either, which is what
      // makes the bare `void runProfileCheck()` at the call site safe.
      setProfile({ url, check: { status: "unavailable" } });
    } finally {
      setProfileChecking(false);
    }
  }

  /** Reopen the collapsed field from the card's «Изменить» control. */
  function reopenInvite(): void {
    setProfile(null);
    // Belt-and-braces. The load-bearing reset is the input's own `onChange`
    // (see there): every route from "pressed «Проверить» on an empty field"
    // to a collapsed card runs through it, so the flag is already false by
    // the time this can be called. Kept so the flag cannot outlive its
    // meaning if another way of setting it is ever added.
    setCheckAttempted(false);
    requestAnimationFrame(() => inviteRef.current?.focus());
  }

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
  const payingFromBalance = methodId === WALLET_METHOD_ID;
  // The wallet rides the same admin lever as the acquirers (ADR-0056, an FX
  // drop can stop pay-from-balance too) — `methodVisibility` fails open
  // (`"active"`) while `providerStatus` is still `null`, same as everywhere
  // else it's consulted. Computed before `walletState` below, which needs it
  // to tell "under maintenance" apart from "FX is down"/"nothing chosen".
  const walletVisibility = methodVisibility(WALLET_METHOD_ID, providerStatus);
  const walletState = walletTile({
    // `isLoading` matters: the access token is memory-only, so a cold load
    // re-mints it and `user` is null for a beat — treating that as "guest"
    // would tell a signed-in buyer to sign in.
    isLoggedIn: user !== null || authLoading,
    balance: spendableBalance(walletQuery.data?.balances ?? null, WALLET_CURRENCY),
    total,
    // Without this, a chosen package with FX down reads as `total === null`
    // same as nothing chosen, and the tile said "Выберите пакет" — wrong,
    // the package IS chosen.
    fxDown: priceUnavailable,
    maintenance: walletVisibility === "maintenance",
  });

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

  // The sticky `Idempotency-Key` for `POST /orders`, kept alongside the
  // `orderFingerprint` it was minted for — a ref, not state, since neither
  // read nor write should trigger a render. A buy click reuses the stored
  // key exactly when the recomputed fingerprint still matches it (a failed
  // attempt with unchanged inputs), and mints a new one otherwise (changed
  // inputs, no prior attempt, or the previous purchase succeeded and
  // cleared this to `null`). Never reset from an individual input handler —
  // see `orderFingerprint`'s doc comment for why that would be a money bug.
  const orderKeyRef = useRef<{ fingerprint: string; key: string } | null>(null);

  const emailValid = user !== null || EMAIL_RE.test(email);
  // Only meaningful for the guest field (`user !== null` never renders it) —
  // blank stays silent (a required field the buyer hasn't reached yet is not
  // an error), a non-empty mistyped value gets the visible error below.
  const emailInvalid = user === null && email.trim() !== "" && !EMAIL_RE.test(email);
  const canBuy =
    selectedPrice !== null &&
    !priceUnavailable &&
    inviteValid &&
    !profileBlocks &&
    emailValid &&
    selectedMethodActive &&
    !loading;

  // What the Buy button says when it can't be pressed yet — mirrors
  // `canBuy`'s own checks, in the same order, so the reason always matches
  // the actual blocker. The button used to just grey out with no
  // explanation while the amount it would charge sat ~500px up the page
  // (2026-09-04 review, "ship this first") — this is read by both the
  // in-form button and the mobile sticky bar below.
  const payHint: string | null =
    selectedPrice === null
      ? t("noPriceInRegion")
      : priceUnavailable
        ? ts("priceUnavailable")
        : !inviteHasValue
          ? t("payHintInvite")
          : !inviteValid
            ? t("payHintInviteInvalid")
            : profileBlocks
              ? t("payHintProfileNotFound")
              : !emailValid
                ? ts("payHintEmail")
                : !selectedMethodActive
                  ? t("payHintMethod")
                  : null;

  const buyLabel = selectedPriceLabel != null ? `${t("buy")} · ${selectedPriceLabel}` : t("buy");

  // Last look before an irreversible payment — a mistyped invite link sends
  // a paid game to a stranger, with no way to undo it once the bot sends
  // the friend invite. Ordinary top-ups get `ConfirmPurchaseModal`
  // (`PurchasePanel`); this flow used to call `handleBuy()` straight from
  // the Buy button (2026-09-04 review).
  const [confirmOpen, setConfirmOpen] = useState(false);
  const confirmRows: ConfirmPurchaseRow[] = [
    { label: t("edition"), value: selectedPackage?.name ?? "" },
    { label: t("confirmRegion"), value: `${flagEmoji(country)} ${countryName(country, locale)}` },
    {
      label: t("confirmProfile"),
      // The modal's own warning says «Проверьте профиль получателя перед
      // оплатой» — so when the check has already answered that, the answer
      // belongs here, on the last screen before an irreversible gift, not
      // just up in the form. A URL the buyer has stopped reading is not
      // evidence; a name is. Falls back to the link alone when no check ran.
      //
      // Safe to join into one text node: the nickname is third-party text,
      // but `checkGiftProfile` has already stripped the bidi override
      // controls that would let it reorder the link it sits next to (see
      // `stripBidiControls`) — done once at that boundary rather than isolated
      // at each of the three places persona text renders.
      value:
        profileFound !== null ? `${profileFound.nickname} · ${inviteUrl.trim()}` : inviteUrl.trim(),
    },
  ];

  // The mobile sticky checkout bar auto-hides once the real form (this
  // panel) or the page footer is on screen — same reasoning and mechanism
  // as `PurchasePanel`'s bar.
  const panelRef = useRef<HTMLDivElement>(null);
  const [barHidden, setBarHidden] = useState(false);
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const footer = document.querySelector("footer");
    const targets: Element[] = [];
    if (panelRef.current) targets.push(panelRef.current);
    if (footer) targets.push(footer);
    if (targets.length === 0) return;
    const visible = new Set<Element>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) visible.add(e.target);
          else visible.delete(e.target);
        }
        setBarHidden(visible.size > 0);
      },
      { threshold: 0 },
    );
    targets.forEach((el) => {
      io.observe(el);
    });
    return () => {
      io.disconnect();
    };
  }, []);

  async function handleBuy(): Promise<void> {
    // `canBuy` already requires `selectedPrice !== null` — TS's aliased-
    // condition narrowing carries that through past this guard, so it isn't
    // re-checked here.
    if (!canBuy || !selectedPackage || !selectedProvider) return;
    setLoading(true);
    setError(null);
    const token = getAccessToken();
    const loggedIn = user !== null && token !== null;
    const fulfillmentData = {
      app_id: detail.app_id,
      package_id: selectedPackage.id,
      region: country,
      invite_url: inviteUrl.trim(),
    };
    // `loggedIn` aliases `user !== null` — `user` is narrowed non-null in
    // this branch, so no `?.` is needed here either.
    const resolvedEmail = loggedIn
      ? (user.delivery_email ?? user.email ?? "")
      : email.trim().toLowerCase();

    // Reuse the stored key only when it was minted for this exact order —
    // any other field (payment method included) never enters this hash, so
    // a bare method switch keeps replaying the same key on purpose.
    const fingerprint = orderFingerprint({
      skuId,
      amountUsd: selectedPrice.price_usd,
      fulfillmentData,
      email: resolvedEmail,
    });
    if (orderKeyRef.current?.fingerprint !== fingerprint) {
      orderKeyRef.current = { fingerprint, key: crypto.randomUUID() };
    }

    const attempt = (idempotencyKey: string) =>
      buyGift({
        locale,
        skuId,
        amountUsd: selectedPrice.price_usd,
        fulfillmentData,
        email: resolvedEmail,
        isLoggedIn: loggedIn,
        provider: selectedProvider,
        gameName: detail.name,
        idempotencyKey,
      });

    try {
      let result;
      try {
        result = await attempt(orderKeyRef.current.key);
      } catch (err) {
        if (!isOrderNotAwaitingPaymentConflict(err)) throw err;
        // The replayed order is no longer payable (typically expired past
        // `ORDER_EXPIRY_SECONDS` before this retry landed) — mint a fresh
        // key for the same order contents and retry exactly once. A second
        // failure here falls through to the outer `catch` untouched, so it
        // never loops.
        const freshKey = crypto.randomUUID();
        orderKeyRef.current = { fingerprint, key: freshKey };
        result = await attempt(freshKey);
      }
      // Success — the next purchase (even with identical inputs) must be a
      // new order, so the key does not survive to be replayed.
      orderKeyRef.current = null;
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
  const inviteErrorId = `${inviteId}-error`;
  const profileErrorId = `${inviteId}-profile-error`;
  const profileNoteId = `${inviteId}-profile`;
  const emailErrorId = `${emailId}-error`;

  // The one blocking verdict, kept apart from the notes below: it renders as
  // a `role="alert"`, which screen readers do announce on insertion.
  const profileAlert: string | null = profileBlocks ? t("profileNotFound") : null;
  // Everything else the check has to say about the link currently in the
  // field. `found` says it in the card instead, so it has no note. This text
  // lives in a live region that is always mounted (see the render), because
  // NVDA and JAWS commonly miss a `role="status"` node that is *inserted*
  // rather than updated in place — which would have made `unsupported` and
  // `unavailable` silent.
  const profileNote: string | null =
    checkAttempted && !inviteHasValue
      ? // «Проверить» pressed on an empty field: `inviteWrong` cannot speak
        // for this case (it requires a non-empty value), so without this the
        // button is a silent no-op. Reuses the Buy button's own wording for
        // the same missing thing rather than forking a fourth sentence.
        t("payHintInvite")
      : profileCheck === null || profileCheck.status === "found" || profileBlocks
        ? null
        : profileCheck.status === "unsupported"
          ? t("profileUnsupported")
          : t("profileUnavailable");
  // What the live region actually holds. A `found` verdict has no *visible*
  // note — the card says it — but it still has to be said out loud: the
  // sighted buyer gets an avatar and a name, while a screen-reader user
  // previously got focus moved to a button whose entire accessible name is
  // «Изменить». That is the one moment this whole feature exists for, so it
  // is announced — and only announced: the region goes `sr-only` whenever
  // `profileNote` is null, so this never renders as a second, redundant copy
  // of the card.
  const profileAnnounce: string =
    profileFound !== null
      ? t("profileFound", { nickname: profileFound.nickname })
      : (profileNote ?? "");
  // The shape error and the check verdict describe the same input, so they
  // are announced together rather than the later one hiding the earlier.
  const inviteDescribedBy =
    [
      inviteInvalid ? inviteErrorId : null,
      profileAlert !== null ? profileErrorId : null,
      profileNote !== null ? profileNoteId : null,
    ]
      .filter((id): id is string => id !== null)
      .join(" ") || undefined;

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
    <>
      <div ref={panelRef} className="border-border bg-card space-y-5 rounded-2xl border p-5 sm:p-6">
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
                      {/* Never the USD figure here, even as a fallback: a gift is
                        always billed in UZS, so a dollar amount next to a
                        package a buyer can still tap Buy on would look
                        payable without being the charged currency (2026-09-04
                        review). `price_uzs === null` (FX down for this
                        zone/package) degrades to the same dash as no price at
                        all. */}
                      {price?.price_uzs != null ? (
                        formatUzs(locale, Math.round(Number(price.price_uzs)))
                      ) : (
                        // A bare "—" read as nothing to a screen reader — the
                        // visible dash stays, but it now carries real text
                        // alongside it (2026-09-04 a11y review).
                        <span>
                          <span aria-hidden="true">—</span>
                          <span className="sr-only">{t("noPriceInRegion")}</span>
                        </span>
                      )}
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
          {editionSwitchCountry && (
            <p className="text-tx-dim mt-2 text-[12px] leading-snug">
              {t("editionSwitchNotice", { country: countryName(editionSwitchCountry, locale) })}
            </p>
          )}
        </div>

        <div>
          <div className="flex items-center gap-3">
            <p className="text-tx-dim text-[11px] font-semibold uppercase tracking-[0.08em]">
              {t("region")}
            </p>
            <RegionHintToggle
              open={regionHintOpen}
              onToggle={() => {
                setRegionHintOpen((o) => !o);
              }}
            />
          </div>
          {/* Rendered as the row's sibling, not its child — inside the label
            row above, the row's own `flex` layout squeezed this panel down
            to ~285px of the available 360px (2026-09-04 review). */}
          <RegionHintPanel open={regionHintOpen} />
          <div className="mt-2 flex flex-wrap gap-2">
            {visibleCountries.map((c) => (
              <CountryButton
                key={c}
                country={c}
                active={c === country}
                available={countryAvailable(c)}
                locale={locale}
                onSelect={selectCountry}
              />
            ))}
            {overflowCountries.length > 0 && !countryPanelExpanded && (
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
            {countryPanelExpanded &&
              overflowCountries.map((c) => (
                <CountryButton
                  key={c}
                  country={c}
                  active={c === country}
                  available={countryAvailable(c)}
                  locale={locale}
                  onSelect={selectCountry}
                />
              ))}
          </div>
          {/* Said once for the whole row instead of repeating under every
            disabled pill (up to eight of them, at 10px, on a nine-country
            row) — see `hasUnpricedCountry` above (2026-09-04 review). */}
          {hasUnpricedCountry && (
            <p className="text-tx-dim mt-2 text-[11px]">{t("noPriceInRegion")}</p>
          )}
        </div>

        {/* `aria-live`: a region/edition switch re-prices this silently
          otherwise — nothing told a screen-reader user the total just
          changed (2026-09-04 a11y review). */}
        <div className="border-border/70 border-t pt-4" aria-live="polite">
          {selectedPrice ? (
            selectedPriceLabel != null ? (
              // The only figure shown — the buyer is charged in UZS, always
              // (`buyGift` hardcodes `currency: "UZS"`), so a second, USD
              // number here answered a question nobody asked and left the
              // buyer guessing which one leaves their account (2026-09-04
              // review).
              <span className="font-display text-2xl font-bold tabular-nums">
                {selectedPriceLabel}
              </span>
            ) : (
              // FX is down for this zone — never fall back to `price_usd`
              // here: showing a dollar figure as if it were payable is exactly
              // what sent a buyer to the acquirer for an unknown soum amount.
              // Mirrors `PurchasePanel`'s `VariableAmountCard` FX-down card.
              <div className="border-border bg-card text-tx-mute rounded-lg border border-dashed p-6 text-center text-sm">
                {ts("priceUnavailable")}
              </div>
            )
          ) : (
            <p className="text-tx-mute text-sm">{t("noPriceInRegion")}</p>
          )}
        </div>

        <div className="space-y-2">
          {profileFound !== null ? (
            <p className={FIELD_LABEL_CLASS}>{t("inviteLabel")}</p>
          ) : (
            <label htmlFor={inviteId} className={FIELD_LABEL_CLASS}>
              {t("inviteLabel")}
            </label>
          )}
          {profileFound !== null ? (
            /* Confirmed recipient — the field collapses into who the link
              actually points to, so the last thing the buyer sees before
              paying is a face and a name rather than a URL they have already
              stopped reading. Mirrors `CheckablePlayerField`'s confirmation
              pill in `PurchasePanel`, plus the avatar gifts have and it
              doesn't. */
            <div className="rounded-btn flex items-center gap-2.5 border border-emerald-500/40 bg-emerald-500/[0.06] py-1.5 pl-1.5 pr-4">
              {profileFound.avatarUrl !== null ? (
                <Image
                  data-testid="gift-profile-avatar"
                  src={profileFound.avatarUrl}
                  // Decorative: the nickname it belongs to is right beside it,
                  // and an avatar has nothing of its own to announce.
                  alt=""
                  width={48}
                  height={48}
                  // `avatars.steamstatic.com` is a third-party host — see
                  // `lib/image.ts`: the optimizer 504s rather than degrading
                  // when such a host is slow, which would lose the whole card.
                  unoptimized={!isOptimizable(profileFound.avatarUrl)}
                  className="h-12 w-12 shrink-0 rounded-full object-cover"
                />
              ) : (
                <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400">
                  <Check size={20} strokeWidth={3} aria-hidden="true" />
                </span>
              )}
              <div className="min-w-0 flex-1 leading-tight">
                <div className="truncate text-[14px] font-bold">{profileFound.nickname}</div>
                {/* The link it resolved to, kept visible: the field it
                  replaced is gone, and the buyer should still be able to see
                  what they pasted. */}
                <div className="text-tx-dim truncate text-[12px]">{inviteUrl.trim()}</div>
              </div>
              <button
                type="button"
                ref={editRef}
                onClick={reopenInvite}
                // `min-h-[44px]` matching the «Открыть профиль» anchor below:
                // this is the only way back out of a confirmed-but-wrong
                // recipient, and on mobile it was a 13px word with no padding.
                className="text-tx-dim hover:text-tx-mute inline-flex min-h-[44px] shrink-0 items-center px-1 text-[13px] font-medium transition"
              >
                {ts("checkEdit")}
              </button>
            </div>
          ) : (
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <div className="min-w-0 flex-1">
                <input
                  id={inviteId}
                  ref={inviteRef}
                  type="text"
                  value={inviteUrl}
                  onChange={(e) => {
                    setInviteUrl(e.target.value);
                    // The flag means "«Проверить» was pressed with nothing to
                    // check", and any edit — including selecting all and
                    // deleting — makes that stale. Leaving it set meant the
                    // hint came back every later time the field went empty,
                    // with no press behind it: on a polite live region, spoken
                    // into the middle of the buyer's own retyping. Clearing
                    // here also covers "reset after a successful check", since
                    // a check can only run once an edit made the field
                    // non-empty.
                    setCheckAttempted(false);
                  }}
                  onBlur={() => {
                    setInviteTouched(true);
                  }}
                  placeholder={t("invitePlaceholder")}
                  aria-invalid={inviteInvalid || profileBlocks ? true : undefined}
                  aria-describedby={inviteDescribedBy}
                  className="border-border bg-bg rounded-btn h-11 w-full border px-3 text-sm"
                />
              </div>
              <button
                type="button"
                // `aria-disabled`, not `disabled`: a real `disabled` button
                // drops the click, leaving no moment at which to explain why
                // nothing happened. `runProfileCheck` answers with the link
                // error instead. Same posture as `CheckablePlayerField`.
                aria-disabled={!inviteValid}
                disabled={profileChecking}
                onClick={() => {
                  void runProfileCheck();
                }}
                // Neutral, not primary: the check is advisory — everything
                // except a definitive "no such profile" lets the buyer carry
                // on — and in lime it would compete with the real CTA.
                className={`border-border-2 text-tx-mute hover:border-tx-dim hover:text-foreground hover:bg-muted rounded-btn inline-flex h-11 shrink-0 items-center justify-center gap-2 border px-5 text-[14px] font-semibold transition disabled:pointer-events-none disabled:opacity-40 ${
                  inviteValid ? "" : "opacity-40"
                }`}
              >
                {profileChecking && (
                  <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                )}
                {profileChecking ? ts("checking") : ts("check")}
              </button>
            </div>
          )}
          {inviteInvalid && (
            <p id={inviteErrorId} className="text-[13px] text-[#FF6B6B]">
              {t("inviteError")}
            </p>
          )}
          {profileAlert !== null && (
            /* The only verdict that blocks Buy, and the only one that reads
              as an error. `role="alert"` announces on insertion, which is
              what this state needs. */
            <p id={profileErrorId} role="alert" className="text-[13px] text-[#FF6B6B]">
              {profileAlert}
            </p>
          )}
          {/* Always mounted, empty when there is nothing to say: NVDA and JAWS
            commonly miss a live region that is *inserted* into the page rather
            than updated in place, which would leave the non-blocking verdicts
            («нельзя проверить», «Steam не отвечает») announced to nobody.
            `sr-only` while empty rather than a plain empty block, so the
            parent's `space-y-2` doesn't reserve a gap for a node with nothing
            in it — it stays in the accessibility tree either way, which is
            the whole point of keeping it mounted. */}
          <div
            id={profileNoteId}
            data-testid="gift-profile-live"
            role="status"
            aria-live="polite"
            className={profileNote !== null ? "text-tx-dim text-[13px]" : "sr-only"}
          >
            {profileAnnounce}
          </div>
          {/* The free half of the deferred server-side profile checker
            (Task 6a): the buyer opens the pasted link themselves, in a new
            tab, and verifies it's the right person before paying
            (2026-09-04 review). */}
          {inviteHref && (
            <a
              href={inviteHref}
              target="_blank"
              rel="noreferrer noopener"
              className="text-primary inline-flex min-h-[44px] items-center gap-1 text-[13px] font-semibold hover:underline"
            >
              {t("openProfileLink")}
              <ExternalLink size={14} aria-hidden="true" />
            </a>
          )}
          {/* "Ссылка на профиль Steam получателя" reads, to a buyer purchasing
            for themselves, as though they're in the wrong place — this
            covers that case inline rather than leaving it unsaid
            (2026-09-04 review). Both this and the guide below tell the buyer
            what to put *in the field*, so both go away once the field has
            collapsed into a confirmed recipient — otherwise the most
            confident moment in the flow ends with instructions to fill in
            something that is no longer on screen. */}
          {profileFound === null && (
            <p className="text-tx-dim text-[12px] leading-snug">{t("inviteSelfNote")}</p>
          )}
          {/* The two sentences that explain the entire model used to sit
            *below* the Buy button, in 12px dim text — past the decision.
            Moved here, next to the field where the recipient first becomes
            a concept (2026-09-04 review). */}
          <div className="text-tx-dim space-y-1 text-[12px] leading-relaxed">
            <p>{t("timeline")}</p>
            <p>{t("accept")}</p>
          </div>
          {profileFound === null && <InviteGuide />}
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
              autoComplete="email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
              }}
              placeholder={ts("emailPlaceholder")}
              aria-invalid={emailInvalid ? true : undefined}
              aria-describedby={emailInvalid ? emailErrorId : undefined}
              className="border-border bg-bg rounded-btn h-11 w-full border px-3 text-sm"
            />
            {emailInvalid && (
              <p id={emailErrorId} className="text-[13px] text-[#FF6B6B]">
                {ta("emailInvalid")}
              </p>
            )}
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
                      : walletState.state === "maintenance"
                        ? ts("paymentMaintenance")
                        : walletState.state === "fxDown"
                          ? ts("priceUnavailable")
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
                const statusId = `gift-pay-method-status-${m.id}`;
                return (
                  <button
                    key={m.id}
                    type="button"
                    // Kept as the bare provider name: the status rides
                    // `aria-describedby` instead, so the accessible name of a
                    // tile doesn't change when an acquirer goes down.
                    aria-label={m.name}
                    aria-pressed={active}
                    aria-describedby={disabled ? statusId : undefined}
                    disabled={disabled}
                    onClick={() => {
                      setMethodId(m.id);
                    }}
                    className={`rounded-btn relative flex flex-col items-center justify-center gap-1 overflow-hidden border px-3 py-3 transition disabled:cursor-not-allowed disabled:opacity-60 ${
                      active
                        ? "border-primary bg-primary/10"
                        : "border-border bg-bg hover:border-border-2"
                    }`}
                  >
                    {/* Overlaid, not stacked — a third line of text inside the
                      tile would grow it taller than its neighbours. A strip
                      pinned to the top edge stays out of the flow and is
                      visible on touch, unlike a `title=` tooltip. */}
                    {disabled && (
                      <span
                        id={statusId}
                        className="border-border bg-bg/95 text-tx-dim absolute inset-x-0 top-0 z-10 border-b py-[3px] text-center text-[9px] font-bold uppercase leading-none tracking-[0.06em]"
                      >
                        {ts("paymentMaintenanceShort")}
                      </span>
                    )}
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

        {/* Carries its own state end to end: not payable → names the next
          required step (was a silently dimmed "Купить" with the reason, if
          any, only findable via `payHint` below); payable → the amount, so
          the buyer never has to scroll back up to the total; pending → the
          existing spinner. Mirrors `TopUp.tsx`'s disabled-label pattern
          (2026-09-04 review, "ship this first"). */}
        <button
          type="button"
          data-testid="gift-buy-cta"
          disabled={!canBuy}
          onClick={() => {
            setConfirmOpen(true);
          }}
          className={buttonStyles({ size: "lg", className: "w-full" })}
        >
          {loading ? (
            <Loader2 size={18} className="animate-spin" aria-hidden="true" />
          ) : canBuy ? (
            buyLabel
          ) : (
            (payHint ?? t("buy"))
          )}
        </button>
        {error && <p className="text-[13px] text-[#FF6B6B]">{error}</p>}
      </div>

      <ConfirmPurchaseModal
        open={confirmOpen}
        title={ts("confirmTitle")}
        rows={confirmRows}
        totalLabel={ts("confirmTotal")}
        totalValue={selectedPriceLabel ?? ""}
        warning={t("confirmWarning")}
        confirmLabel={ts("confirmCta")}
        cancelLabel={ts("confirmCancel")}
        onConfirm={() => {
          setConfirmOpen(false);
          void handleBuy();
        }}
        onClose={() => {
          setConfirmOpen(false);
        }}
      />

      {/* Mobile sticky checkout bar — mirrors `PurchasePanel`'s: total +
          blocking reason, primary when payable, a ghost that scrolls to the
          form when not. The gift page had none at all (2026-09-04 review):
          on mobile, the total sat a full screen above the fold by the time
          the buyer reached the fields that block Buy. */}
      <div
        className={`border-border bg-bg/95 fixed inset-x-0 bottom-0 z-40 border-t px-4 pt-3 backdrop-blur-xl transition-transform duration-200 [padding-bottom:calc(0.75rem+env(safe-area-inset-bottom))] lg:hidden ${
          barHidden ? "pointer-events-none translate-y-full" : "translate-y-0"
        }`}
      >
        <div className="mx-auto flex max-w-[1200px] items-center justify-between gap-4">
          <div className="min-w-0">
            <div className="text-tx-mute truncate text-[11px] font-semibold">
              {canBuy || !payHint ? t("buy") : payHint}
            </div>
            <div className="font-display truncate text-lg font-bold leading-tight">
              {priceUnavailable ? "—" : (selectedPriceLabel ?? "—")}
            </div>
          </div>
          <button
            type="button"
            data-testid="gift-buy-sticky"
            onClick={() => {
              if (canBuy) setConfirmOpen(true);
              else panelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
            }}
            className={buttonStyles({
              size: "lg",
              variant: canBuy ? "primary" : "ghost",
              className: "shrink-0",
            })}
          >
            {loading ? (
              <Loader2 size={18} className="animate-spin" aria-hidden="true" />
            ) : canBuy ? (
              t("buy")
            ) : (
              ts("goToPay")
            )}
          </button>
        </div>
      </div>
    </>
  );
}

/** One country pill: flag + localized name. `available` (whether the
 *  currently selected package prices this country's zone) comes from the
 *  parent's `countryAvailable` — a visible-row pill is always priced (see
 *  the visible/overflow split above), but an *overflow* pill can still be
 *  unpriced, disabled here without its own caption: the whole row explains
 *  that once via `hasUnpricedCountry`/`noPriceInRegion` instead of
 *  repeating "нет цены…" under every disabled pill (2026-09-04 review). */
function CountryButton({
  country,
  active,
  available,
  locale,
  onSelect,
}: {
  country: string;
  active: boolean;
  available: boolean;
  locale: string;
  onSelect: (country: string) => void;
}) {
  return (
    <button
      type="button"
      disabled={!available}
      aria-pressed={active}
      onClick={() => {
        onSelect(country);
      }}
      className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-left text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-60 ${
        active
          ? "border-primary bg-primary/10 text-primary"
          : "border-border text-tx-mute hover:border-border-2"
      }`}
    >
      <span aria-hidden="true">{flagEmoji(country)}</span>
      {countryName(country, locale)}
    </button>
  );
}
