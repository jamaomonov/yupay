"use client";

import { ArrowRight } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";

import { buttonStyles } from "@/lib/button";
import { formatUzs } from "@/lib/seo";
import { amountError, parseAmount, unitAmountError } from "@/lib/variable-amount";

/** The two products the home hero sells from its own form. */
export type OfferKind = "steam" | "stars";

/** One product the hero form can price and hand off — built on the server from the catalogue. */
export interface TopUpOffer {
  kind: OfferKind;
  /** The product page the form hands off to, pre-filled (`prefillFromQuery`). */
  href: string;
  /** The recipient field's key on that product (`steam_login`, `username`). */
  fieldKey: string;
  /** That field's pattern, so both forms refuse the same input. */
  pattern: string | null;
  /** One unit — a dollar for Steam, a star for Stars — in soʻm; `null` without a rate. */
  rateUzs: number | null;
  min: number;
  max: number;
  /** What the amount field opens with. */
  initial: string;
}

/** The rails a buyer pays with on the product page, in its own order. */
const PAY_MARKS = [
  { src: "/payment/payme-mark.png", name: "Payme" },
  { src: "/payment/click-mark.png", name: "Click" },
  { src: "/payment/uzum-mark.png", name: "Uzum" },
] as const;

export const STAR_IMAGE = "/brands/telegram-star.png";

/** Per-product look: the header mark, the card's top wash, the ghost emblem. */
const THEME: Record<OfferKind, { mark: string; markBg: string; wash: string; invert: boolean }> = {
  steam: {
    mark: "/brands/steam-mono.png",
    markBg: "bg-[linear-gradient(135deg,#1b2838,#2a475e)] ring-[#66c0f4]/40",
    wash: "bg-[linear-gradient(180deg,#16283a_0%,hsl(var(--card))_38%)]",
    invert: true,
  },
  stars: {
    mark: STAR_IMAGE,
    markBg: "bg-[linear-gradient(135deg,#3a2a08,#5a3f0a)] ring-[#f5b82e]/40",
    wash: "bg-[linear-gradient(180deg,#2e2410_0%,hsl(var(--card))_38%)]",
    invert: false,
  },
};

/**
 * One product's quick form on the home page: the recipient, the amount, the
 * price in soʻm as it is typed, then a hand-off to the product page with both
 * filled in, where the recipient is checked and the order paid. Nothing is
 * charged from here.
 */
export function QuickTopUpCard({ offer, locale }: { offer: TopUpOffer; locale: string }) {
  const t = useTranslations("web.hero");
  const router = useRouter();
  const fieldId = useId();
  const amountId = useId();
  const [who, setWho] = useState("");
  const [amount, setAmount] = useState(offer.initial);
  const [touched, setTouched] = useState(false);
  const theme = THEME[offer.kind];
  const k = `offers.${offer.kind}` as const;

  const whoOk = who.trim() !== "" && new RegExp(offer.pattern ?? ".+").test(who.trim());
  const parsed = parseAmount(amount);
  const amountErr =
    parsed === null
      ? "below"
      : offer.kind === "stars"
        ? unitAmountError(parsed, offer.min, offer.max)
        : amountError(parsed, offer.min, offer.max);
  const total =
    parsed !== null && amountErr === null && offer.rateUzs !== null ? parsed * offer.rateUzs : null;
  const bound = (n: number) =>
    offer.kind === "stars" ? n.toLocaleString(locale) : `$${n.toLocaleString("en-US")}`;

  function submit(): void {
    setTouched(true);
    if (!whoOk || total === null) return;
    const q = new URLSearchParams({ [offer.fieldKey]: who.trim(), amount: amount.trim() });
    router.push(`${offer.href}?${q.toString()}`);
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      noValidate
      aria-label={t(`${k}.title`)}
      className={`border-border-2/80 relative h-full overflow-hidden rounded-3xl border p-5 shadow-[0_40px_100px_-40px_rgba(0,0,0,0.9)] sm:p-7 ${theme.wash}`}
    >
      <Image
        src={theme.mark}
        alt=""
        width={220}
        height={220}
        aria-hidden
        className={`pointer-events-none absolute -right-16 -top-16 opacity-[0.06] ${theme.invert ? "invert" : "grayscale"}`}
      />

      <div className="relative flex items-center gap-3">
        <span
          className={`flex size-11 shrink-0 items-center justify-center rounded-2xl ring-1 ${theme.markBg}`}
        >
          <Image
            src={theme.mark}
            alt=""
            width={26}
            height={26}
            className={theme.invert ? "invert" : ""}
          />
        </span>
        <div className="min-w-0">
          <p className="font-display text-[19px] font-bold leading-tight">{t(`${k}.title`)}</p>
          <p className="text-primary mt-0.5 text-[12px] font-semibold">{t(`${k}.note`)}</p>
        </div>
      </div>

      <label htmlFor={fieldId} className="text-tx-mute mt-6 block text-[13px] font-medium">
        {t(`${k}.field`)}
      </label>
      <input
        id={fieldId}
        value={who}
        onChange={(e) => {
          setWho(e.target.value);
        }}
        autoComplete="off"
        autoCapitalize="none"
        spellCheck={false}
        placeholder={t(`${k}.placeholder`)}
        aria-invalid={touched && !whoOk}
        className="border-border-2 bg-bg/70 focus:border-primary focus:ring-primary/20 mt-1.5 w-full rounded-xl border px-4 py-3 text-[15px] outline-none transition focus:ring-4"
      />
      {touched && !whoOk && <p className="mt-1.5 text-[12px] text-red-400">{t(`${k}.invalid`)}</p>}

      <label htmlFor={amountId} className="text-tx-mute mt-4 block text-[13px] font-medium">
        {t(`${k}.amount`)}
      </label>
      <div className="border-border-2 bg-bg/70 focus-within:border-primary focus-within:ring-primary/20 mt-1.5 flex items-center rounded-xl border px-4 transition focus-within:ring-4">
        {offer.kind === "stars" ? (
          <Image src={STAR_IMAGE} alt="" width={24} height={24} className="shrink-0" />
        ) : (
          <span className="text-tx-dim font-display text-2xl font-bold">$</span>
        )}
        <input
          id={amountId}
          value={amount}
          onChange={(e) => {
            setAmount(e.target.value);
          }}
          inputMode={offer.kind === "stars" ? "numeric" : "decimal"}
          aria-invalid={amountErr !== null}
          className="font-display w-full bg-transparent px-2 py-2.5 text-2xl font-bold outline-none"
        />
      </div>
      {amountErr !== null && amount.trim() !== "" && (
        <p className="mt-1.5 text-[12px] text-red-400">
          {t(`${k}.range`, { min: bound(offer.min), max: bound(offer.max) })}
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

      {offer.rateUzs === null ? (
        <Link
          href={offer.href}
          className={buttonStyles({ size: "lg", className: "mt-4 w-full justify-center" })}
        >
          {t(`${k}.open`)}
          <ArrowRight size={16} strokeWidth={2.6} />
        </Link>
      ) : (
        <button
          type="submit"
          className={buttonStyles({ size: "lg", className: "group mt-4 w-full justify-center" })}
        >
          {t(`${k}.submit`)}
          <ArrowRight
            size={16}
            strokeWidth={2.6}
            className="transition group-hover:translate-x-0.5"
          />
        </button>
      )}

      <div className="mt-4 flex items-center justify-center gap-2.5">
        <span className="text-tx-dim text-[12px]">{t("form.weAccept")}</span>
        {PAY_MARKS.map(({ src, name }) => (
          <Image
            key={src}
            src={src}
            alt={name}
            width={24}
            height={24}
            className="rounded-md ring-1 ring-white/10"
          />
        ))}
      </div>
    </form>
  );
}
