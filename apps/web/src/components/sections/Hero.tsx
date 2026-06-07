import { ArrowRight, ChevronDown, Star } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { PhoneShowcase } from "./PhoneShowcase";

import { buttonStyles } from "@/lib/button";

/**
 * Storefront hero — type-led left column + a real product shot on the right:
 * two screenshots of the YuPay mini app layered into a floating device
 * cluster. Trust block underneath: avatar stack + counter + 5-star rating.
 */
export async function Hero({ locale }: { locale: string }) {
  const t = await getTranslations("web.hero");
  const prefix = `/${locale}`;

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

          <div className="mt-8 flex flex-wrap items-center gap-3.5">
            <Link
              href={`${prefix}/store`}
              className={buttonStyles({ size: "lg", className: "group" })}
            >
              {t("ctaPrimary")}
              <ArrowRight size={16} strokeWidth={2.6} />
            </Link>
            <a href="#how" className={buttonStyles({ variant: "ghost", size: "lg" })}>
              <span className="border-primary bg-primary/15 flex h-5 w-5 items-center justify-center rounded-full border">
                <ChevronDown size={12} strokeWidth={2.6} className="text-primary" />
              </span>
              {t("ctaSecondary")}
            </a>
          </div>

          {/* Trust strip — avatar stack + counter + stars */}
          <div className="mt-12 flex items-center gap-4">
            <div className="flex">
              {AVATARS.map((a, i) => (
                <div
                  key={i}
                  className="border-bg -ml-2.5 flex h-[38px] w-[38px] items-center justify-center rounded-full border-2 text-[13px] font-extrabold text-white first:ml-0"
                  style={{ background: a.bg }}
                >
                  {a.letter}
                </div>
              ))}
            </div>
            <div>
              <div className="text-foreground text-[14px] font-semibold">
                <span className="text-primary font-mono font-bold">{t("trustCount")}</span>{" "}
                {t("trustCountLabel")}
              </div>
              <div className="mt-1 flex items-center gap-2">
                <div className="flex gap-[1px]">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Star key={i} size={12} className="fill-gold text-gold" />
                  ))}
                </div>
                <span className="text-tx-mute text-[11px]">{t("rating")}</span>
              </div>
            </div>
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

const AVATARS = [
  { letter: "А", bg: "linear-gradient(135deg, #FFAA00, #1a1a1a)" },
  { letter: "М", bg: "linear-gradient(135deg, #5B2C82, #1a1a1a)" },
  { letter: "К", bg: "linear-gradient(135deg, #FF4655, #1a1a1a)" },
  { letter: "С", bg: "linear-gradient(135deg, #5BA8FF, #1a1a1a)" },
  { letter: "Д", bg: "linear-gradient(135deg, #1DB954, #1a1a1a)" },
];
