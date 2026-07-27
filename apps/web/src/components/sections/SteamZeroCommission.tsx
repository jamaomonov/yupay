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
  // Icon-only mark, not the click.svg wordmark used elsewhere (Footer.tsx /
  // PurchasePanel.tsx): that SVG's "click" wordmark is baked white-on-
  // transparent for the dark grounds it was designed for, so it vanishes on
  // this white chip. We don't recolor a partner's logo file — its squircle
  // icon alone is a highly recognized standalone mark in this market.
  { src: "/payment/click.png", alt: "Click", w: 225, h: 225 },
  { src: "/payment/payme.png", alt: "Payme", w: 454, h: 179 },
  { src: "/payment/uzum.png", alt: "Uzum", w: 506, h: 148 },
] as const;

/**
 * Steam "0% commission, pay in so‘m" value band — the storefront's sharpest
 * USP for the Uzbek market. Type-led claim + payment rail + trust chips +
 * a single CTA into the real product page (/store/steam). RSC, zero client JS.
 *
 * Business truth encoded in the copy (see i18n `web.steamZero`): 0% means no
 * service fee on top of the 1:1 amount — what the customer pays is what
 * lands on the Steam balance. Never claim an "official rate" here.
 */
export async function SteamZeroCommission({ locale }: { locale: string }) {
  const t = await getTranslations("web.steamZero");
  const chips = [
    { Icon: Zap, label: t("chipSpeed") },
    { Icon: ShieldCheck, label: t("chipNoPassword") },
    { Icon: RotateCcw, label: t("chipGuarantee") },
  ] as const;

  return (
    <section className="relative isolate overflow-hidden">
      {/* `isolate` matters here, not just `relative`: a positioned element
          with z-index:auto does NOT create a stacking context on its own, so
          the `-z-10` atmosphere layer below would otherwise escape to the
          document root and paint behind the opaque <body> background —
          invisible. `isolate` scopes the negative z-index locally, the same
          fix CatalogBento.tsx uses for its card overlays. */}
      {/* Atmospheric ground: Steam key-art, darkened to a near-solid navy so
          the section reads as its own "room" rather than a photo with text
          over it — the claim stays the hero, not the artwork. */}
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <Image
          src="/brands/steam-bg.jpg"
          alt=""
          fill
          sizes="100vw"
          className="object-cover object-center opacity-70"
        />
        <div className="absolute inset-0 bg-[radial-gradient(120%_120%_at_50%_0%,hsl(var(--card)/0.55)_0%,hsl(var(--card)/0.88)_55%,hsl(var(--bg))_100%)]" />
        <div
          className="glow-lime absolute"
          style={{ width: 560, height: 560, left: "50%", top: "8%", transform: "translate(-50%,-50%)" }}
        />
      </div>

      <div className="mx-auto max-w-[900px] px-6 py-20 sm:px-10 sm:py-28">
        <div className="flex flex-col items-center text-center">
          {/* Steam mono mark: source is a black disc + white glyph, so
              `invert` flips it to a white disc + black glyph — a clean,
              self-contained badge that reads on the dark ground without
              needing its own background fill. */}
          <span className="border-border-2 bg-card-2/60 relative mb-6 grid h-16 w-16 place-items-center rounded-2xl border backdrop-blur">
            <Image
              src="/brands/steam-mono.png"
              alt={t("logoAlt")}
              width={44}
              height={44}
              className="invert"
            />
          </span>

          <div className="text-primary mb-3 font-mono text-[12px] font-semibold uppercase tracking-[0.14em]">
            {t("eyebrow")}
          </div>
          <h2 className="font-display max-w-[15ch] text-balance text-[clamp(2rem,5vw,3.4rem)] font-extrabold leading-[0.98] tracking-[-0.03em] text-foreground">
            {t("title")}
          </h2>
          <p className="text-tx-mute mt-5 max-w-[54ch] text-[15px] leading-relaxed sm:text-base">
            {t("subtitle")}
          </p>

          <div className="mt-8 flex flex-wrap items-center justify-center gap-2.5">
            {chips.map(({ Icon, label }) => (
              <span
                key={label}
                className="border-border-2 bg-card/70 inline-flex items-center gap-1.5 rounded-full border px-3.5 py-2 text-[13px] font-semibold text-foreground backdrop-blur"
              >
                <Icon size={14} className="text-primary shrink-0" />
                {label}
              </span>
            ))}
          </div>

          <div className="mt-10 flex flex-col items-center gap-3.5">
            <span className="text-tx-dim font-mono text-[11px] uppercase tracking-[0.12em]">
              {t("payLabel")}
            </span>
            <div className="flex flex-wrap items-center justify-center gap-3">
              {PAYMENTS.map((p) => (
                <span
                  key={p.alt}
                  className="flex h-[72px] w-24 items-center justify-center rounded-btn bg-white p-2.5 shadow-[0_10px_24px_-10px_rgba(0,0,0,0.55)]"
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

          <Link
            href={`/${locale}/store/steam`}
            className={buttonStyles({ size: "lg", className: "group mt-10" })}
          >
            {t("cta")}
            <ArrowRight
              size={18}
              strokeWidth={2.6}
              className="transition group-hover:translate-x-0.5"
            />
          </Link>
        </div>
      </div>
    </section>
  );
}
