"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";

import { buttonStyles } from "@/lib/button";
import { formatUzs, pathFor } from "@/lib/seo";
import { amountError, parseAmount } from "@/lib/variable-amount";

const QUICK_AMOUNTS = [5, 10, 20, 50] as const;

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
  const t = useTranslations("web.hero.form");
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
      className="border-border bg-card/80 rounded-2xl border p-5 shadow-[0_30px_80px_-30px_rgba(0,0,0,0.7)] backdrop-blur sm:p-6"
    >
      <p className="font-display text-lg font-bold">{t("title")}</p>

      <label htmlFor={loginId} className="text-tx-mute mt-5 block text-[13px] font-medium">
        {t("login")}
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
        placeholder={t("loginPlaceholder")}
        aria-invalid={touched && !loginOk}
        className="border-border-2 bg-bg focus:border-primary mt-1.5 w-full rounded-xl border px-4 py-3 text-[15px] outline-none transition"
      />
      <p className={`mt-1.5 text-[12px] ${touched && !loginOk ? "text-red-400" : "text-tx-dim"}`}>
        {touched && !loginOk ? t("loginInvalid") : t("loginHint")}
      </p>

      <label htmlFor={amountId} className="text-tx-mute mt-4 block text-[13px] font-medium">
        {t("amount")}
      </label>
      <div className="border-border-2 bg-bg focus-within:border-primary mt-1.5 flex items-center rounded-xl border px-4 transition">
        <span className="text-tx-dim text-[15px]">$</span>
        <input
          id={amountId}
          value={amount}
          onChange={(e) => {
            setAmount(e.target.value);
          }}
          inputMode="decimal"
          aria-invalid={amountErr !== null}
          className="w-full bg-transparent px-2 py-3 text-[15px] outline-none"
        />
      </div>
      <div className="mt-2 flex gap-2">
        {QUICK_AMOUNTS.map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => {
              setAmount(String(n));
            }}
            aria-pressed={parsed === n}
            className={`flex-1 rounded-lg border py-1.5 text-[13px] font-semibold transition ${
              parsed === n
                ? "border-primary bg-primary/10 text-primary"
                : "border-border text-tx-mute hover:border-border-2"
            }`}
          >
            {usd(n)}
          </button>
        ))}
      </div>
      {amountErr !== null && amount.trim() !== "" && (
        <p className="mt-1.5 text-[12px] text-red-400">
          {t("range", { min: usd(minUsd), max: usd(maxUsd) })}
        </p>
      )}

      <div className="border-border mt-5 flex items-baseline justify-between border-t pt-4">
        <span className="text-tx-mute text-[14px]">{t("total")}</span>
        <span className="font-mono text-xl font-bold" aria-live="polite">
          {total !== null ? formatUzs(locale, Math.round(total)) : "—"}
        </span>
      </div>

      {rateUzs === null ? (
        <Link
          href={steamHref}
          className={buttonStyles({ size: "lg", className: "mt-4 w-full justify-center" })}
        >
          {t("open")}
          <ArrowRight size={16} strokeWidth={2.6} />
        </Link>
      ) : (
        <button
          type="submit"
          className={buttonStyles({ size: "lg", className: "group mt-4 w-full justify-center" })}
        >
          {t("submit")}
          <ArrowRight
            size={16}
            strokeWidth={2.6}
            className="transition group-hover:translate-x-0.5"
          />
        </button>
      )}
    </form>
  );
}
