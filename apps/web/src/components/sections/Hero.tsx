import { ArrowRight, Check, ChevronDown, Send } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { PhoneShowcase } from "./PhoneShowcase";

import { buttonStyles } from "@/lib/button";
import { TELEGRAM_MINIAPP_URL } from "@/lib/links";
import { pathFor } from "@/lib/seo";

/**
 * Storefront hero — type-led left column + a real product shot on the right:
 * two screenshots of the YuPay mini app layered into a floating device
 * cluster. Trust block underneath: avatar stack + counter + 5-star rating.
 */
export async function Hero({ locale }: { locale: string }) {
  const t = await getTranslations("web.hero");

  return (
    <header className="relative overflow-hidden pb-20 pt-28 sm:pb-[120px] sm:pt-[180px]">
      {/* Atmospheric layers behind the hero. Tuned to peek through the
          surrounding sections without distracting from the centred content. */}
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <div className="grid-cell absolute inset-0" />
        <div
          className="glow-lime anim-pulse-glow absolute"
          style={{
            width: 700,
            height: 700,
            left: "55%",
            top: "40%",
            transform: "translate(-50%, -50%)",
          }}
        />
        <div
          className="glow-blue absolute"
          style={{ width: 500, height: 500, right: 0, top: "10%" }}
        />
      </div>

      <div className="relative z-10 mx-auto grid max-w-[1200px] grid-cols-1 items-center gap-10 px-6 sm:px-10 md:grid-cols-2">
        {/* ── LEFT: copy + CTAs ── */}
        <div>
          <span className="border-primary/30 bg-primary/10 text-primary inline-flex items-center gap-2 rounded-full border px-3 py-1.5 font-mono text-[11px] font-bold uppercase tracking-[0.08em]">
            <span className="bg-primary relative inline-block h-1.5 w-1.5 rounded-full">
              <span className="bg-primary/60 absolute inset-0 animate-ping rounded-full" />
            </span>
            {t("badge")}
          </span>

          <h1 className="font-display text-foreground mt-6 text-[clamp(2.6rem,6vw,4.1rem)] font-extrabold leading-[0.96] tracking-[-0.04em]">
            <span className="block">{t("titleLine1")}</span>
            <span className="text-primary block">{t("titleLine2")}</span>
          </h1>

          <p className="text-tx-mute mt-6 max-w-[440px] text-base sm:text-lg sm:leading-relaxed">
            {t("subtitle")}
          </p>

          {/* Device-aware CTA priority. Telegram opens the Mini App (the
              lower-friction, higher-retention surface on phones, where a deep
              link is one tap) and is the bold primary on mobile. On desktop,
              opening Telegram is more friction than just browsing the web
              store, so the catalog leads and Telegram is the ghost secondary. */}
          <div className="mt-8">
            <div className="flex flex-col gap-3.5 sm:flex-row sm:items-center lg:hidden">
              <a
                href={TELEGRAM_MINIAPP_URL}
                target="_blank"
                rel="noreferrer noopener"
                className={buttonStyles({ size: "lg", className: "group" })}
              >
                <Send size={16} strokeWidth={2.4} />
                {t("ctaTelegram")}
                <ArrowRight
                  size={16}
                  strokeWidth={2.6}
                  className="transition group-hover:translate-x-0.5"
                />
              </a>
              <Link
                href={pathFor(locale, "/store")}
                className={buttonStyles({ variant: "ghost", size: "lg" })}
              >
                {t("ctaPrimary")}
              </Link>
            </div>
            <div className="hidden items-center gap-3.5 lg:flex">
              <Link
                href={pathFor(locale, "/store")}
                className={buttonStyles({ size: "lg", className: "group" })}
              >
                {t("ctaPrimary")}
                <ArrowRight
                  size={16}
                  strokeWidth={2.6}
                  className="transition group-hover:translate-x-0.5"
                />
              </Link>
              <a
                href={TELEGRAM_MINIAPP_URL}
                target="_blank"
                rel="noreferrer noopener"
                className={buttonStyles({ variant: "ghost", size: "lg" })}
              >
                <Send size={16} strokeWidth={2.4} />
                {t("ctaTelegram")}
              </a>
            </div>
            <a
              href="#how"
              className="text-tx-mute hover:text-foreground mt-4 inline-flex items-center gap-1.5 text-sm font-medium transition"
            >
              <ChevronDown size={14} strokeWidth={2.6} className="text-primary" />
              {t("ctaSecondary")}
            </a>
          </div>

          {/* Trust chips — honest, verifiable signals only (no review counts
              or invented totals): the Steam commission, local rails, refund
              window. */}
          <div className="mt-12 flex flex-wrap gap-2.5">
            {(["chip1", "chip2", "chip3"] as const).map((k) => (
              <span
                key={k}
                className="border-border bg-card/60 text-tx-mute inline-flex items-center gap-2 rounded-full border px-3.5 py-2 text-[13px] font-medium"
              >
                <Check size={14} strokeWidth={2.6} className="text-primary shrink-0" />
                {t(k)}
              </span>
            ))}
          </div>
        </div>

        {/* ── RIGHT: real product shot ── */}
        <div className="mt-6 md:mt-0">
          <PhoneShowcase />
        </div>
      </div>
    </header>
  );
}
