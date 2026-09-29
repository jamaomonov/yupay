"use client";

import { ArrowRight, ShieldCheck } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";

import { buttonStyles } from "@/lib/button";
import { formatUzs, pathFor } from "@/lib/seo";
import { amountError, parseAmount } from "@/lib/variable-amount";

const QUICK_AMOUNTS = [5, 10, 20, 50] as const;
/** The rails a buyer pays with on the Steam page, in its own order. */
const PAY_MARKS = [
  "/payment/payme-mark.png",
  "/payment/click-mark.png",
  "/payment/uzum-mark.png",
] as const;

interface SteamQuickTopUpProps {
  locale: string;
  /** One dollar in soʻm from the Steam SKU, or `null` when the rate is unavailable. */
  rateUzs: number | null;
  minUsd: number;
  maxUsd: number;
  /** The login field's pattern from the product, so both forms refuse the same input. */
  loginPattern: string | null;
}

/**
 * The home page's Steam top-up: login and dollar amount, the price in soʻm as it is
 * typed, then a hand-off to the Steam page with both filled in (`prefillFromQuery`),
 * where the login is checked and the order paid. Nothing is charged from here.
 */
export function SteamQuickTopUp({
  locale,
  rateUzs,
  minUsd,
  maxUsd,
  loginPattern,
}: SteamQuickTopUpProps) {
  const t = useTranslations("web.hero");
  const router = useRouter();
  const loginId = useId();
  const amountId = useId();
  const [login, setLogin] = useState("");
  const [amount, setAmount] = useState("10");
  const [touched, setTouched] = useState(false);
  const steamHref = pathFor(locale, "/store/steam");

  const loginOk = login.trim() !== "" && new RegExp(loginPattern ?? ".+").test(login.trim());
  const parsed = parseAmount(amount);
  const amountErr = parsed === null ? "below" : amountError(parsed, minUsd, maxUsd);
  const total = parsed !== null && amountErr === null && rateUzs !== null ? parsed * rateUzs : null;
  const usd = (n: number) => `$${n.toLocaleString("en-US")}`;

  function submit(): void {
    setTouched(true);
    if (!loginOk || total === null) return;
    const q = new URLSearchParams({ steam_login: login.trim(), amount: amount.trim() });
    router.push(`${steamHref}?${q.toString()}`);
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      noValidate
      className="border-border-2/80 relative overflow-hidden rounded-3xl border bg-[linear-gradient(180deg,#16283a_0%,hsl(var(--card))_38%)] p-5 shadow-[0_40px_100px_-40px_rgba(0,0,0,0.9)] sm:p-7"
    >
      {/* Ghost Steam emblem, top-right — identity without a second logo competing. */}
      <Image
        src="/brands/steam-mono.png"
        alt=""
        width={220}
        height={220}
        aria-hidden
        className="pointer-events-none absolute -right-16 -top-16 opacity-[0.05] invert"
      />

      <div className="relative flex items-center gap-3">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-[linear-gradient(135deg,#1b2838,#2a475e)] ring-1 ring-[#66c0f4]/40">
          <Image src="/brands/steam-mono.png" alt="" width={24} height={24} className="invert" />
        </span>
        <div className="min-w-0">
          <p className="font-display text-[19px] font-bold leading-tight">{t("form.title")}</p>
          <p className="text-primary mt-0.5 text-[12px] font-semibold">{t("chip1")}</p>
        </div>
      </div>

      <label htmlFor={loginId} className="text-tx-mute mt-6 block text-[13px] font-medium">
        {t("form.login")}
      </label>
      <input
        id={loginId}
        value={login}
        onChange={(e) => {
          setLogin(e.target.value);
        }}
        autoComplete="off"
        autoCapitalize="none"
        spellCheck={false}
        placeholder={t("form.loginPlaceholder")}
        aria-invalid={touched && !loginOk}
        className="border-border-2 bg-bg/70 focus:border-primary focus:ring-primary/20 mt-1.5 w-full rounded-xl border px-4 py-3 text-[15px] outline-none transition focus:ring-4"
      />
      <p className={`mt-1.5 text-[12px] ${touched && !loginOk ? "text-red-400" : "text-tx-dim"}`}>
        {touched && !loginOk ? t("form.loginInvalid") : t("form.loginHint")}
      </p>

      <label htmlFor={amountId} className="text-tx-mute mt-4 block text-[13px] font-medium">
        {t("form.amount")}
      </label>
      <div className="border-border-2 bg-bg/70 focus-within:border-primary focus-within:ring-primary/20 mt-1.5 flex items-center rounded-xl border px-4 transition focus-within:ring-4">
        <span className="text-tx-dim font-display text-2xl font-bold">$</span>
        <input
          id={amountId}
          value={amount}
          onChange={(e) => {
            setAmount(e.target.value);
          }}
          inputMode="decimal"
          aria-invalid={amountErr !== null}
          className="font-display w-full bg-transparent px-2 py-2.5 text-2xl font-bold outline-none"
        />
      </div>
      <div className="mt-2.5 grid grid-cols-4 gap-2">
        {QUICK_AMOUNTS.map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => {
              setAmount(String(n));
            }}
            aria-pressed={parsed === n}
            className={`rounded-full border py-1.5 text-[13px] font-semibold transition ${
              parsed === n
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-bg/40 text-tx-mute hover:border-border-2 hover:text-foreground"
            }`}
          >
            {usd(n)}
          </button>
        ))}
      </div>
      {amountErr !== null && amount.trim() !== "" && (
        <p className="mt-1.5 text-[12px] text-red-400">
          {t("form.range", { min: usd(minUsd), max: usd(maxUsd) })}
        </p>
      )}

      <div className="bg-primary/[0.07] ring-primary/15 mt-5 flex items-baseline justify-between rounded-2xl px-4 py-3.5 ring-1">
        <span className="text-tx-mute text-[14px]">{t("form.total")}</span>
        <span
          className="font-display text-primary text-2xl font-extrabold tabular-nums tracking-[-0.02em]"
          aria-live="polite"
        >
          {total !== null ? formatUzs(locale, Math.round(total)) : "—"}
        </span>
      </div>

      {rateUzs === null ? (
        <Link
          href={steamHref}
          className={buttonStyles({ size: "lg", className: "mt-4 w-full justify-center" })}
        >
          {t("form.open")}
          <ArrowRight size={16} strokeWidth={2.6} />
        </Link>
      ) : (
        <button
          type="submit"
          className={buttonStyles({ size: "lg", className: "group mt-4 w-full justify-center" })}
        >
          {t("form.submit")}
          <ArrowRight
            size={16}
            strokeWidth={2.6}
            className="transition group-hover:translate-x-0.5"
          />
        </button>
      )}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <span className="flex items-center gap-1.5">
          {PAY_MARKS.map((src) => (
            <Image
              key={src}
              src={src}
              alt=""
              width={24}
              height={24}
              className="rounded-md ring-1 ring-white/10"
            />
          ))}
        </span>
        <span className="text-tx-dim flex items-center gap-1.5 whitespace-nowrap text-[12px]">
          <ShieldCheck size={14} className="text-primary shrink-0" aria-hidden />
          {t("chip3")}
        </span>
      </div>
    </form>
  );
}
