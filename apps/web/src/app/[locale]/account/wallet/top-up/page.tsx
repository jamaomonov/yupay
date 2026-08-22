"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Image from "next/image";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { use, useEffect, useId, useRef, useState } from "react";

import { amountValue, groupDigits, toDigits } from "@/lib/amount-input";
import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { ApiError, apiFetch } from "@/lib/client";
import {
  methodVisibility,
  providerStatusMap,
  selectActiveMethodId,
  type ProvidersOut,
} from "@/lib/payment-providers";
import { formatUzs, pathFor } from "@/lib/seo";
import {
  createWalletTopUp,
  QUICK_AMOUNTS,
  TOP_UP_LIMITS,
  topUpAttemptKey,
  WALLET_CURRENCY,
} from "@/lib/wallet";
import { useLoginModal } from "@/store/useLoginModal";

/** The acquirers that settle a soum deposit. `click_miniapp` is the mini app's
 *  own merchant service and must not appear here — see payment-methods. */
const METHODS = [
  { id: "click", provider: "click", name: "Click", icon: "/payment/click-mark.png" },
  { id: "payme", provider: "payme", name: "Payme", icon: "/payment/payme-mark.png" },
  { id: "uzum", provider: "uzum", name: "Uzum", icon: "/payment/uzum-mark.png" },
] as const;

export default function WalletTopUpPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = use(params);
  const t = useTranslations("web.wallet");
  const tNav = useTranslations("web.nav");
  const { user, isLoading: authLoading } = useAuth();

  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<string>(METHODS[0].id);
  const [error, setError] = useState<string | null>(null);
  // Survives re-renders so a second submit after a timed-out first one replays
  // that request instead of opening another top-up order.
  const attempt = useRef<{ signature: string; key: string } | null>(null);
  const boundsId = useId();
  const openLogin = useLoginModal((st) => st.open);

  // The same availability the checkout respects. Offering an acquirer that is
  // admin-disabled or in maintenance only buys the customer a refusal from
  // `_ensure_provider_accepting_intents` and a generic failure line.
  const providers = useQuery({
    queryKey: ["payment-providers"],
    queryFn: () => apiFetch<ProvidersOut>("/payments/providers", { anonymous: true }),
    staleTime: 60_000,
  });
  const providerStatus = providers.data ? providerStatusMap(providers.data) : null;

  // A hardcoded default can itself be down; move off it once status lands.
  useEffect(() => {
    if (!providerStatus) return;
    setMethod((current) => selectActiveMethodId([...METHODS], current, providerStatus) ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the map is rebuilt each render; the query data is the real dependency
  }, [providers.data]);

  const limits = TOP_UP_LIMITS[WALLET_CURRENCY];
  const typed = amountValue(amount);
  const belowMin = typed > 0 && limits !== undefined && typed < limits.min;
  const aboveMax = limits !== undefined && typed > limits.max;
  const amountOk = limits !== undefined && typed >= limits.min && typed <= limits.max;

  const topUp = useMutation({
    mutationFn: () =>
      createWalletTopUp(
        typed,
        method,
        topUpAttemptKey(attempt, `${typed.toString()}:${method}`),
        // Land the customer back on the balance they just changed. Without
        // this the server falls back to a generic return page.
        `${window.location.origin}${pathFor(locale, "/account/wallet")}`,
      ),
    onSuccess: (payment) => {
      if (payment.intent_url) {
        window.location.href = payment.intent_url;
        return;
      }
      // No hosted page (the dev `mock` acquirer) — the order view already
      // renders a deposit, so send them there rather than nowhere.
      window.location.href = pathFor(locale, `/orders/${payment.order_id}`);
    },
    onError: (err) => {
      // The server's reason is written for the customer (amount out of range,
      // provider not accepting). Collapsing every failure into one line hid
      // the half they could act on.
      setError(err instanceof ApiError && err.detail ? err.detail : t("topUpFailed"));
    },
  });

  if (authLoading) return <main className="pt-[120px]" />;

  if (!user) {
    return (
      <main className="mx-auto max-w-[640px] px-4 pb-24 pt-[120px]">
        <h1 className="font-display mb-6 text-3xl font-bold tracking-[-0.02em]">
          {t("topUpTitle")}
        </h1>
        <div className="border-border bg-card rounded-2xl border p-10 text-center">
          <p className="text-tx-mute mb-5">{t("guestBody")}</p>
          {/* Signing in is the action; the catalogue is the way out. Offering
              only "В каталог" left the customer nothing to do about it. */}
          <div className="flex flex-col gap-2 sm:flex-row sm:justify-center">
            <button type="button" onClick={openLogin} className={buttonStyles({ size: "md" })}>
              {tNav("login")}
            </button>
            <Link
              href={pathFor(locale, "/store")}
              className={buttonStyles({ variant: "ghost", size: "md" })}
            >
              {t("toCatalog")}
            </Link>
          </div>
        </div>
      </main>
    );
  }

  const quick = QUICK_AMOUNTS[WALLET_CURRENCY] ?? [];

  return (
    <main className="mx-auto max-w-[640px] px-4 pb-24 pt-[120px]">
      <Link
        href={pathFor(locale, "/account/wallet")}
        className="text-tx-mute hover:text-foreground mb-4 inline-block text-sm transition"
      >
        ← {t("title")}
      </Link>
      <h1 className="font-display mb-6 text-3xl font-bold tracking-[-0.02em]">{t("topUpTitle")}</h1>

      <section className="border-border bg-card mb-4 rounded-2xl border p-5">
        <label className="mb-2 block">
          <span className="text-tx-dim mb-2 block font-mono text-[11px] font-bold uppercase tracking-[0.16em]">
            {t("amountLabel")}
          </span>
          <input
            inputMode="numeric"
            // Grouped for reading: 100000 and 1000000 are one character apart
            // and ten times different, which in a bold 24px field is the same
            // shape. The stored value stays plain digits.
            value={groupDigits(amount, locale)}
            onChange={(e) => {
              setAmount(toDigits(e.target.value));
              setError(null);
            }}
            placeholder={limits ? formatUzs(locale, limits.min) : ""}
            aria-label={t("amountLabel")}
            aria-invalid={belowMin || aboveMax}
            aria-describedby={belowMin || aboveMax ? boundsId : undefined}
            className="border-border bg-card focus:border-primary rounded-btn h-14 w-full border px-4 text-2xl font-bold tabular-nums outline-none transition"
          />
        </label>

        <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-5">
          {quick.map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => {
                setAmount(String(v));
                setError(null);
              }}
              aria-pressed={typed === v}
              className={`rounded-btn h-11 border px-3 text-sm font-bold tabular-nums transition ${
                typed === v
                  ? "border-primary bg-primary/10"
                  : "border-border bg-card hover:border-primary"
              }`}
            >
              {/* The field above establishes the currency; repeating "UZS" on
                  every chip is what pushed them onto three rows at 360px. */}
              {v.toLocaleString(locale)}
            </button>
          ))}
        </div>

        {limits !== undefined && (
          <p
            id={boundsId}
            className={`mt-3 text-sm ${belowMin || aboveMax ? "text-[#FF6B6B]" : "text-tx-dim"}`}
          >
            {/* Shown from the start rather than only after they get it wrong. */}
            {t("amountRange", {
              min: formatUzs(locale, limits.min),
              max: formatUzs(locale, limits.max),
            })}
          </p>
        )}
      </section>

      <section className="border-border bg-card mb-4 rounded-2xl border p-5">
        <p className="text-tx-dim mb-3 font-mono text-[11px] font-bold uppercase tracking-[0.16em]">
          {t("methodLabel")}
        </p>
        <ul className="space-y-2">
          {METHODS.map((m) => {
            const visibility = methodVisibility(m.provider, providerStatus);
            if (visibility === "hidden") return null;
            const unavailable = visibility === "maintenance";
            const active = !unavailable && m.id === method;
            return (
              <li key={m.id}>
                <button
                  type="button"
                  disabled={unavailable}
                  onClick={() => {
                    setMethod(m.id);
                  }}
                  aria-pressed={active}
                  className={`rounded-btn flex w-full items-center gap-3 border p-3 text-left transition ${
                    active ? "border-primary bg-primary/10" : "border-border bg-card"
                  }`}
                >
                  <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center overflow-hidden rounded-md">
                    <Image
                      src={m.icon}
                      alt=""
                      width={40}
                      height={40}
                      className="h-full w-full object-cover"
                    />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-bold">{m.name}</span>
                    {unavailable && (
                      <span className="text-tx-dim block text-xs">{t("methodUnavailable")}</span>
                    )}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </section>

      {error && <p className="mb-3 text-sm text-red-400">{error}</p>}

      <button
        type="button"
        disabled={!amountOk || topUp.isPending}
        onClick={() => {
          setError(null);
          topUp.mutate();
        }}
        className={buttonStyles({ size: "lg", className: "w-full" })}
      >
        {topUp.isPending
          ? t("topUpPending")
          : amountOk
            ? t("topUpSubmit", { amount: formatUzs(locale, typed) })
            : aboveMax && limits !== undefined
              ? t("maxAmount", { amount: formatUzs(locale, limits.max) })
              : belowMin && limits !== undefined
                ? t("minAmount", { amount: formatUzs(locale, limits.min) })
                : t("topUpEnterAmount")}
      </button>

      <p className="text-tx-dim mt-3 text-center text-xs leading-relaxed">{t("topUpNote")}</p>
    </main>
  );
}
