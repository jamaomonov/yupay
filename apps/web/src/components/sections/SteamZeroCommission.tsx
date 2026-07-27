import { ArrowRight, RotateCcw, ShieldCheck, Zap } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { buttonStyles } from "@/lib/button";

/** Card networks (Uzcard, Humo) + the acquirer wordmarks customers actually
 * tap (Click, Payme, Uzum) — order matches the subtitle's "Click, Payme и
 * Uzum" flow with the two card brands leading. Uzcard's source is a portrait
 * icon-over-wordmark lockup and Humo's is full card art, wildly different
 * shapes from the flat Click/Payme/Uzum marks, so a bare `height: 22` render
 * (this component's old treatment) shrinks Uzcard to an illegible sliver and
 * leaves both colored marks with no ground to read against. Every mark now
 * sits in a uniform white chip instead — see the fixed-size box in the JSX
 * below, which lets `object-contain` letterbox each aspect ratio on its own
 * terms (portrait Uzcard fills the box height, wide Humo fills the box
 * width) while the row itself stays visually uniform. Intrinsic px
 * dimensions match the source files so aspect ratios never distort. */
const PAYMENTS = [
  { src: "/payment/uzcard.png", alt: "Uzcard", w: 461, h: 676 },
  { src: "/payment/humo.png", alt: "Humo", w: 600, h: 359 },
  // Dark wordmark, purpose-built for light/white grounds — unlike click.svg
  // (Footer.tsx / PurchasePanel.tsx), which is baked white-on-transparent for
  // the dark grounds those components render on and would vanish on this
  // white chip.
  { src: "/payment/click-dark.svg", alt: "Click", w: 157, h: 40 },
  { src: "/payment/payme.png", alt: "Payme", w: 454, h: 179 },
  { src: "/payment/uzum.png", alt: "Uzum", w: 506, h: 148 },
] as const;

/**
 * Accents every literal "0%" in `title` in the brand lime, leaving the rest
 * in the inherited foreground color. "0%" is the one substring shared by all
 * three locale titles (ru "0% комиссии…", en "0% fee…", uz "…0% komissiya…"),
 * so this is a locale-safe way to highlight the claim without hard-splitting
 * the string by word/character index — a future locale (or a copy tweak)
 * that drops the token still renders the title whole instead of crashing or
 * leaving a dangling empty span.
 */
function accentZero(title: string) {
  const token = "0%";
  const at = title.indexOf(token);
  if (at === -1) {
    return title;
  }
  return (
    <>
      {title.slice(0, at)}
      <span className="text-primary">{token}</span>
      {title.slice(at + token.length)}
    </>
  );
}

/**
 * Steam "0% commission, pay in so‘m" hero band — the storefront's sharpest
 * USP for the Uzbek market. Full-bleed, left-aligned editorial treatment:
 * giant type-led claim up top, a stat/CTA/payment-rail band along the
 * bottom. RSC, zero client JS.
 *
 * Business truth encoded in the copy (see i18n `web.steamZero`): 0% means no
 * service fee on top of the 1:1 amount — what the customer pays is what
 * lands on the Steam balance. Never claim an "official rate" here.
 */
export async function SteamZeroCommission({ locale }: { locale: string }) {
  const t = await getTranslations("web.steamZero");
  const stats = [
    { Icon: Zap, label: t("statSpeedLabel"), value: t("chipSpeed") },
    { Icon: ShieldCheck, label: t("statAccessLabel"), value: t("chipNoPassword") },
    { Icon: RotateCcw, label: t("statRiskLabel"), value: t("chipGuarantee") },
  ] as const;

  return (
    <section className="border-border/60 relative isolate overflow-hidden border-y">
      {/* `isolate` matters here, not just `relative`: a positioned element
          with z-index:auto does NOT create a stacking context on its own, so
          the `-z-10` atmosphere layer below would otherwise escape to the
          document root and paint behind the opaque <body> background —
          invisible. `isolate` scopes the negative z-index locally, the same
          fix CatalogBento.tsx uses for its card overlays. */}
      {/* Atmospheric ground: a SINGLE ghost Steam emblem on the right plus a
          giant outline "0%" — the only two background marks, both far too
          low-contrast to compete with the copy. No photographic key-art layer:
          the steam-bg.jpg photo is itself a Steam logo, so pairing it with the
          mono ghost rendered two overlapping emblems. */}
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <Image
          src="/brands/steam-mono.png"
          alt=""
          width={720}
          height={720}
          className="invert absolute right-[6%] top-1/2 hidden -translate-y-1/2 opacity-[0.06] sm:block"
        />
        <div
          className="font-display absolute bottom-[-8%] right-[-1%] hidden select-none text-[clamp(9rem,24vw,20rem)] font-extrabold leading-none opacity-[0.14] md:block"
          style={{ WebkitTextStroke: "2px hsl(var(--primary))", color: "transparent" }}
        >
          0%
        </div>
        <div
          className="glow-lime absolute"
          style={{ width: 560, height: 560, left: "8%", top: "24%", transform: "translate(-50%,-50%)" }}
        />
      </div>

      <div className="relative mx-auto max-w-[1200px] px-6 py-16 sm:px-10 sm:py-24">
        {/* Eyebrow pill, top-right — Steam mono mark + "STEAM · UZBEKISTAN". */}
        <div className="flex justify-end">
          <span className="border-primary/30 bg-primary/10 text-primary inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 font-mono text-[11px] font-bold uppercase tracking-[0.1em]">
            <Image
              src="/brands/steam-mono.png"
              alt=""
              width={14}
              height={14}
              className="invert shrink-0"
            />
            {t("eyebrow")}
          </span>
        </div>

        {/* Headline + subcopy — left-aligned, giant, "0%" accented in lime. */}
        <div className="mt-8 max-w-[960px] sm:mt-10">
          <h2 className="font-display text-balance text-[clamp(2.25rem,5.6vw,4.25rem)] font-extrabold leading-[0.96] tracking-[-0.035em] text-foreground">
            {accentZero(t("title"))}
          </h2>
          <p className="text-tx-mute mt-5 max-w-[54ch] text-[15px] leading-relaxed sm:text-base">
            {t("subtitle")}
          </p>
        </div>

        {/* Bottom band, two stacked rows (matches the reference): the stat
            columns on their own row, then the CTA + payment rail directly
            beneath — never side-by-side with the stats. */}
        <div className="border-border-2 mt-14 flex flex-col gap-8 border-t pt-8 sm:mt-16">
          {/* Row 1 — stat columns. Vertical list on mobile (no dividers, so a
              wrapped `border-l` can't strand itself); a single nowrap row with
              dividers from `sm` up, where the three short stats always fit. */}
          <div className="flex flex-col gap-5 sm:flex-row sm:flex-nowrap sm:items-center sm:gap-x-8">
            {stats.map((s, i) => (
              <div
                key={s.label}
                className={`flex items-center gap-3 ${i > 0 ? "sm:border-border-2 sm:border-l sm:pl-8" : ""}`}
              >
                <span className="border-primary/25 bg-primary/10 text-primary grid h-9 w-9 shrink-0 place-items-center rounded-lg border">
                  <s.Icon size={17} strokeWidth={2.2} />
                </span>
                <div>
                  <div className="text-tx-dim font-mono text-[10px] font-semibold uppercase tracking-[0.14em]">
                    {s.label}
                  </div>
                  <div className="mt-1 text-[15px] font-bold text-foreground">{s.value}</div>
                </div>
              </div>
            ))}
          </div>

          {/* Row 2 — CTA on the left, payment chips immediately to its right. */}
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:gap-5">
            <Link
              href={`/${locale}/store/steam`}
              className={buttonStyles({ size: "lg", className: "group shrink-0" })}
            >
              {t("cta")}
              <ArrowRight
                size={18}
                strokeWidth={2.6}
                className="transition group-hover:translate-x-0.5"
              />
            </Link>
            <div className="flex flex-wrap items-center gap-2">
              {PAYMENTS.map((p) => (
                <span
                  key={p.alt}
                  className="flex h-[52px] w-[74px] items-center justify-center rounded-btn bg-white p-2 shadow-[0_8px_18px_-8px_rgba(0,0,0,0.5)]"
                >
                  <Image
                    src={p.src}
                    alt={p.alt}
                    title={p.alt}
                    width={p.w}
                    height={p.h}
                    unoptimized
                    style={{ maxWidth: "100%", maxHeight: "100%", width: "auto", height: "auto" }}
                    className="object-contain"
                  />
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
