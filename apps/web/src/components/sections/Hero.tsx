import { ArrowUpRight, Crosshair, Gamepad2, Gift, Send } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { SteamQuickTopUp } from "./SteamQuickTopUp";

import { getProductDetail } from "@/lib/catalog";
import { skinsEnabled } from "@/lib/features";
import { TELEGRAM_MINIAPP_URL } from "@/lib/links";
import { pathFor } from "@/lib/seo";

/** The Steam wallet product — the hero's form prices and pre-fills it. */
const STEAM_PRODUCT = "steam-wallet";

/** The Steam SKU's rate and bounds, or nulls when the API could not say. */
async function steamQuote(locale: string) {
  const product = await getProductDetail(STEAM_PRODUCT, locale, "UZS").catch(() => null);
  const sku = product?.skus.find((s) => s.variable_amount ?? false);
  const login = product?.required_fields.find((f) => f.key === "steam_login");
  return {
    rateUzs: sku?.display_price ? Number(sku.display_price.amount) : null,
    minUsd: sku?.min_amount_usd != null ? Number(sku.min_amount_usd) : 1,
    maxUsd: sku?.max_amount_usd != null ? Number(sku.max_amount_usd) : 300,
    loginPattern: login?.pattern ?? null,
  };
}

/**
 * Storefront hero, led by what most visitors come for: topping up Steam. Copy on
 * the left, a working Steam form on the right (`SteamQuickTopUp`), and the other
 * sections — CS2 skins, games, gift cards — as tiles under the copy. The mini app
 * is shown further down (`AppShowcase`); here it is one link, on phones only.
 */
export async function Hero({ locale }: { locale: string }) {
  const t = await getTranslations("web.hero");
  const quote = await steamQuote(locale);
  const tiles = [
    ...(skinsEnabled()
      ? [{ key: "skins" as const, href: pathFor(locale, "/skins"), Icon: Crosshair }]
      : []),
    { key: "games" as const, href: `${pathFor(locale, "/store")}?cat=games`, Icon: Gamepad2 },
    { key: "giftCards" as const, href: `${pathFor(locale, "/store")}?cat=gift-cards`, Icon: Gift },
  ];

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

      {/* Three blocks, placed by the grid: on phones copy → form → the rest, so
          the form is on the first screen; on desktop the form spans the right
          column beside both. */}
      <div className="relative z-10 mx-auto grid max-w-[1200px] grid-cols-1 gap-x-14 gap-y-8 px-6 sm:px-10 md:grid-cols-[1fr_440px] md:grid-rows-[auto_1fr]">
        <div className="md:self-end">
          <span className="border-primary/30 bg-primary/10 text-primary inline-flex items-center gap-2 rounded-full border px-3 py-1.5 font-mono text-[11px] font-bold uppercase tracking-[0.08em]">
            <span className="bg-primary relative inline-block h-1.5 w-1.5 rounded-full">
              <span className="bg-primary/60 absolute inset-0 animate-ping rounded-full" />
            </span>
            {t("badge")}
          </span>

          <h1 className="font-display text-foreground mt-6 text-[clamp(2.6rem,6vw,4.4rem)] font-extrabold leading-[0.96] tracking-[-0.04em]">
            <span className="block">{t("titleLine1")}</span>
            <span className="text-primary block">{t("titleLine2")}</span>
          </h1>

          <p className="text-tx-mute mt-6 max-w-[440px] text-base sm:text-lg sm:leading-relaxed">
            {t("subtitle")}
          </p>
        </div>

        <div className="relative w-full md:col-start-2 md:row-span-2 md:row-start-1 md:self-center">
          {/* Steam-blue light behind the card. */}
          <div
            aria-hidden
            className="pointer-events-none absolute -inset-10 -z-10 rounded-full opacity-60 blur-3xl"
            style={{
              background:
                "radial-gradient(closest-side, rgba(102,192,244,0.35), rgba(102,192,244,0) 70%)",
            }}
          />
          <SteamQuickTopUp locale={locale} {...quote} />
        </div>

        {/* Everything that is not Steam, one tap away. */}
        <div className="md:self-start">
          <p className="text-tx-dim text-[12px] font-semibold uppercase tracking-[0.08em]">
            {t("moreTitle")}
          </p>
          <div className="mt-3 grid max-w-[520px] grid-cols-3 gap-2.5">
            {tiles.map(({ key, href, Icon }) => (
              <Link
                key={key}
                href={href}
                className="border-border bg-card/60 hover:border-primary/50 group flex flex-col gap-3 rounded-2xl border p-3.5 transition hover:-translate-y-0.5"
              >
                <span className="bg-primary/10 text-primary flex size-9 items-center justify-center rounded-xl">
                  <Icon size={18} aria-hidden />
                </span>
                <span className="flex items-center justify-between gap-1 text-[13px] font-semibold leading-tight sm:text-[14px]">
                  {t(`tiles.${key}`)}
                  <ArrowUpRight
                    size={14}
                    className="text-tx-dim group-hover:text-primary hidden shrink-0 transition sm:block"
                    aria-hidden
                  />
                </span>
              </Link>
            ))}
          </div>
          <a
            href={TELEGRAM_MINIAPP_URL}
            target="_blank"
            rel="noreferrer noopener"
            className="text-tx-mute hover:text-foreground mt-5 inline-flex items-center gap-1.5 text-sm font-medium transition md:hidden"
          >
            <Send size={14} strokeWidth={2.4} className="text-primary" />
            {t("ctaTelegram")}
          </a>
        </div>
      </div>
    </header>
  );
}
