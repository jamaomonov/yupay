import { Check, Crosshair, Gamepad2, Gift, Send } from "lucide-react";
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

          {/* Everything that is not Steam, one tap away. */}
          <p className="text-tx-dim mt-8 text-[12px] font-semibold uppercase tracking-[0.08em]">
            {t("moreTitle")}
          </p>
          <div className="mt-3 flex flex-wrap gap-2.5">
            {tiles.map(({ key, href, Icon }) => (
              <Link
                key={key}
                href={href}
                className="border-border bg-card/60 hover:border-primary/60 hover:text-foreground text-tx-mute inline-flex items-center gap-2 rounded-xl border px-4 py-2.5 text-[14px] font-semibold transition"
              >
                <Icon size={16} className="text-primary" aria-hidden />
                {t(`tiles.${key}`)}
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

          {/* Trust chips — honest, verifiable signals only (no review counts
              or invented totals): the Steam commission, local rails, refund
              window. */}
          <div className="mt-8 flex flex-wrap gap-2.5">
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

        {/* ── RIGHT: the Steam form ── */}
        <div className="mx-auto w-full max-w-[440px] md:mr-0">
          <SteamQuickTopUp locale={locale} {...quote} />
        </div>
      </div>
    </header>
  );
}
