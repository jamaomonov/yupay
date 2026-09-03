"use client";

import { formatMoney } from "@yupay/utils";
import { Loader2 } from "lucide-react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useId, useState } from "react";

import { InviteGuide } from "./InviteGuide";

import type { GiftAppDetail, GiftPackage } from "@/lib/gifts";
import type { ProviderStatus, ProvidersOut } from "@/lib/payment-providers";

import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { getAccessToken, SURFACE } from "@/lib/client";
import { buyGift, GiftPriceChangedError } from "@/lib/gift-checkout";
import { methodVisibility, providerStatusMap, selectActiveMethodId } from "@/lib/payment-providers";
import { formatUzs } from "@/lib/seo";
import { toast } from "@/store/useToast";

const API = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** How many offered zones show as their own pill before the rest collapse
 *  behind a single "другой регион" toggle. */
const VISIBLE_ZONE_COUNT = 4;

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** In-scope acquirers for a gift purchase — same three UZ rails
 *  `PurchasePanel` offers, no wallet pay (a gift is always paid up front,
 *  not from the internal ledger — v1 scope cut). */
interface Method {
  id: string;
  name: string;
  provider: string;
  icon: string;
  w: number;
  h: number;
}
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
 * link field, a payment-method grid, and the Buy button. v1 scope cuts,
 * deliberate: no promo field, no wallet pay, no quantity — a gift order is
 * always exactly one package, in one region, `qty: 1`.
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
  const { user } = useAuth();

  const [packageId, setPackageId] = useState<number>(() => detail.packages[0]?.id ?? 0);
  const [zone, setZone] = useState<string>(detail.zone_default);

  const selectedPackage: GiftPackage | null =
    detail.packages.find((p) => p.id === packageId) ?? detail.packages[0] ?? null;
  const selectedPrice = selectedPackage?.prices.find((p) => p.zone === zone) ?? null;

  const visibleZones = detail.zones.slice(0, VISIBLE_ZONE_COUNT);
  const overflowZones = detail.zones.slice(VISIBLE_ZONE_COUNT);
  const [zoneExpanded, setZoneExpanded] = useState<boolean>(() => overflowZones.includes(zone));

  function selectPackage(pkg: GiftPackage): void {
    setPackageId(pkg.id);
    if (!pkg.prices.some((p) => p.zone === zone)) {
      const fallback = pkg.prices.find((p) => p.zone === detail.zone_default) ?? pkg.prices[0];
      if (fallback) setZone(fallback.zone);
    }
  }

  function selectZone(z: string): void {
    if (!selectedPackage?.prices.some((p) => p.zone === z)) return;
    setZone(z);
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
    setMethodId((current) => selectActiveMethodId(METHODS, current, providerStatus) ?? "");
  }, [providerStatus]);

  const selectedProvider = METHODS.find((m) => m.id === methodId)?.provider;
  const selectedMethodActive =
    selectedProvider !== undefined &&
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
          region: zone,
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
      // The dev `mock` provider returns a non-resolvable URL — go straight
      // to the order page, which already shows the pending timeline.
      router.push(result.trackHref);
    } catch (err) {
      if (err instanceof GiftPriceChangedError) {
        toast.info(tg("priceChanged"));
        // Re-fetches the game detail from the server; this client component
        // keeps its own state (package/zone/invite/email) across the
        // refresh, and the recomputed `selectedPrice` above picks up the
        // server's current figure automatically.
        router.refresh();
      } else {
        setError(t("buyError"));
      }
    } finally {
      setLoading(false);
    }
  }

  const inviteId = useId();
  const emailId = useId();

  return (
    <div className="border-border bg-card space-y-5 rounded-2xl border p-5 sm:p-6">
      <div>
        <p className="text-tx-dim text-[11px] font-semibold uppercase tracking-[0.08em]">
          {t("edition")}
        </p>
        <div className="mt-2 flex flex-col gap-2">
          {detail.packages.map((pkg) => {
            const price = pkg.prices.find((p) => p.zone === zone) ?? null;
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
        <p className="text-tx-dim text-[11px] font-semibold uppercase tracking-[0.08em]">
          {t("region")}
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          {visibleZones.map((z) => (
            <ZoneButton
              key={z}
              zone={z}
              active={z === zone}
              selectedPackage={selectedPackage}
              t={t}
              onSelect={selectZone}
            />
          ))}
          {overflowZones.length > 0 && !zoneExpanded && (
            <button
              type="button"
              onClick={() => {
                setZoneExpanded(true);
              }}
              className="border-border text-tx-mute hover:border-border-2 rounded-full border px-3 py-1.5 text-xs font-semibold transition"
            >
              {t("otherRegion")}
            </button>
          )}
          {zoneExpanded &&
            overflowZones.map((z) => (
              <ZoneButton
                key={z}
                zone={z}
                active={z === zone}
                selectedPackage={selectedPackage}
                t={t}
                onSelect={selectZone}
              />
            ))}
        </div>
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

/** One region pill: disabled (with a hint) when the currently selected
 *  package has no price in this zone. */
function ZoneButton({
  zone,
  active,
  selectedPackage,
  t,
  onSelect,
}: {
  zone: string;
  active: boolean;
  selectedPackage: GiftPackage | null;
  t: ReturnType<typeof useTranslations>;
  onSelect: (zone: string) => void;
}) {
  const available = selectedPackage?.prices.some((p) => p.zone === zone) ?? false;
  return (
    <button
      type="button"
      disabled={!available}
      title={available ? undefined : t("noPriceInRegion")}
      aria-pressed={active}
      onClick={() => {
        onSelect(zone);
      }}
      className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-40 ${
        active
          ? "border-primary bg-primary/10 text-primary"
          : "border-border text-tx-mute hover:border-border-2"
      }`}
    >
      {zone}
    </button>
  );
}
