"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";

import { QuickTopUpCard, STAR_IMAGE, type TopUpOffer } from "./QuickTopUpCard";

/** A horizontal drag longer than this switches the card; shorter is a tap or a scroll. */
const SWIPE_PX = 48;

const TAB_MARK: Record<TopUpOffer["kind"], { src: string; invert: boolean }> = {
  steam: { src: "/brands/steam-mono.png", invert: true },
  stars: { src: STAR_IMAGE, invert: false },
};

/**
 * The hero's headline and its product forms, switched together: Steam in front,
 * Stars peeking from behind. Tabs above the stack switch them, as do a swipe on
 * the stack and the arrow keys on the tabs; the card behind slides forward and the
 * headline follows it. Renders two grid children — the copy and the stack — so the
 * server `Hero` places them in its own grid.
 */
export function HeroTopUp({ offers, locale }: { offers: TopUpOffer[]; locale: string }) {
  const t = useTranslations("web.hero");
  const [active, setActive] = useState(0);
  const start = useRef<{ x: number; y: number } | null>(null);
  const current = offers[active] ?? offers[0];
  if (!current) return null;

  const go = (i: number) => {
    setActive((i + offers.length) % offers.length);
  };

  return (
    <>
      <div className="md:self-end">
        <span className="border-primary/30 bg-primary/10 text-primary inline-flex items-center gap-2 rounded-full border px-3 py-1.5 font-mono text-[11px] font-bold uppercase tracking-[0.08em]">
          <span className="bg-primary relative inline-block h-1.5 w-1.5 rounded-full">
            <span className="bg-primary/60 absolute inset-0 animate-ping rounded-full" />
          </span>
          {t("badge")}
        </span>

        {/* Every product's headline sits in one grid cell, only the active one
            visible, so the block keeps the tallest one's height and nothing
            below it jumps on a switch. The visible one is keyed by product, so
            the swap replays its entrance. */}
        <div className="grid">
          {offers.map((o) => {
            const on = o.kind === current.kind;
            return (
              <div
                key={o.kind + (on ? "-on" : "")}
                aria-hidden={!on}
                className={`[grid-area:1/1] ${on ? "anim-hero-swap" : "invisible"}`}
              >
                {on ? (
                  <h1 className="font-display text-foreground mt-6 text-[clamp(2.6rem,6vw,4.4rem)] font-extrabold leading-[0.96] tracking-[-0.04em]">
                    <span className="block">{t(`offers.${o.kind}.titleLine1`)}</span>
                    <span className="text-primary block">{t(`offers.${o.kind}.titleLine2`)}</span>
                  </h1>
                ) : (
                  <p className="font-display mt-6 text-[clamp(2.6rem,6vw,4.4rem)] font-extrabold leading-[0.96] tracking-[-0.04em]">
                    <span className="block">{t(`offers.${o.kind}.titleLine1`)}</span>
                    <span className="block">{t(`offers.${o.kind}.titleLine2`)}</span>
                  </p>
                )}
                <p className="text-tx-mute mt-6 max-w-[440px] text-base sm:text-lg sm:leading-relaxed">
                  {t(`offers.${o.kind}.subtitle`)}
                </p>
              </div>
            );
          })}
        </div>
      </div>

      <div className="relative w-full md:col-start-2 md:row-span-2 md:row-start-1 md:self-center">
        <div
          aria-hidden
          className="pointer-events-none absolute -inset-10 -z-10 rounded-full opacity-60 blur-3xl transition-[background] duration-700"
          style={{
            background:
              current.kind === "stars"
                ? "radial-gradient(closest-side, rgba(245,184,46,0.3), rgba(245,184,46,0) 70%)"
                : "radial-gradient(closest-side, rgba(102,192,244,0.35), rgba(102,192,244,0) 70%)",
          }}
        />

        <div
          role="tablist"
          aria-label={t("switchLabel")}
          className="border-border bg-card/70 mb-4 grid grid-cols-2 gap-1 rounded-2xl border p-1 backdrop-blur"
          onKeyDown={(e) => {
            if (e.key === "ArrowRight") go(active + 1);
            if (e.key === "ArrowLeft") go(active - 1);
          }}
        >
          {offers.map((o, i) => (
            <button
              key={o.kind}
              type="button"
              role="tab"
              aria-selected={i === active}
              tabIndex={i === active ? 0 : -1}
              onClick={() => {
                go(i);
              }}
              className={`flex items-center justify-center gap-2 rounded-xl py-2 text-[14px] font-semibold transition ${
                i === active
                  ? "bg-bg text-foreground shadow-[0_2px_10px_rgba(0,0,0,0.35)]"
                  : "text-tx-mute hover:text-foreground"
              }`}
            >
              <Image
                src={TAB_MARK[o.kind].src}
                alt=""
                width={18}
                height={18}
                className={TAB_MARK[o.kind].invert ? "invert" : ""}
              />
              {t(`offers.${o.kind}.tab`)}
            </button>
          ))}
        </div>

        {/* The stack: every card in one grid cell; the one in front is whole, the
            rest sit behind it, smaller and dimmer, their top edge showing above it. */}
        <div
          className="grid touch-pan-y pt-5"
          onPointerDown={(e) => {
            start.current = { x: e.clientX, y: e.clientY };
          }}
          onPointerUp={(e) => {
            const from = start.current;
            start.current = null;
            if (!from) return;
            const dx = e.clientX - from.x;
            if (Math.abs(dx) > SWIPE_PX && Math.abs(dx) > Math.abs(e.clientY - from.y)) {
              go(active + (dx < 0 ? 1 : -1));
            }
          }}
        >
          {offers.map((o, i) => {
            const front = i === active;
            return (
              <div
                key={o.kind}
                inert={!front}
                aria-hidden={!front}
                className={`origin-top transition-all duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] [grid-area:1/1] ${
                  front
                    ? "z-20 translate-x-0 translate-y-0 scale-100 opacity-100"
                    : "z-10 -translate-y-5 scale-[0.92] opacity-50"
                }`}
              >
                <QuickTopUpCard offer={o} locale={locale} />
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
