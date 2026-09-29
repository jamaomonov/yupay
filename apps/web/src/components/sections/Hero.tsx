import { ArrowUpRight, Crosshair, Gamepad2, Gift, Send } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { HeroTopUp } from "./HeroTopUp";

import type { TopUpOffer } from "./QuickTopUpCard";
import type { ProductDetail } from "@/lib/catalog";

import { getProductDetail } from "@/lib/catalog";
import { skinsEnabled } from "@/lib/features";
import { TELEGRAM_MINIAPP_URL } from "@/lib/links";
import { pathFor } from "@/lib/seo";

async function product(slug: string, locale: string): Promise<ProductDetail | null> {
  return getProductDetail(slug, locale, "UZS").catch(() => null);
}

/** Steam: a dollar amount, priced per dollar. Falls back to a plain link without a rate. */
function steamOffer(locale: string, p: ProductDetail | null): TopUpOffer {
  const sku = p?.skus.find((s) => s.variable_amount ?? false);
  return {
    kind: "steam",
    href: pathFor(locale, "/store/steam"),
    fieldKey: "steam_login",
    pattern: p?.required_fields.find((f) => f.key === "steam_login")?.pattern ?? null,
    rateUzs: sku?.display_price ? Number(sku.display_price.amount) : null,
    min: sku?.min_amount_usd != null ? Number(sku.min_amount_usd) : 1,
    max: sku?.max_amount_usd != null ? Number(sku.max_amount_usd) : 300,
    initial: "10",
  };
}

/** Stars: a whole number of stars, priced per star. */
function starsOffer(locale: string, p: ProductDetail | null): TopUpOffer {
  const sku = p?.skus.find((s) => s.min_qty != null && s.max_qty != null);
  const min = sku?.min_qty ?? 50;
  return {
    kind: "stars",
    href: pathFor(locale, "/store/telegram-stars"),
    fieldKey: "username",
    pattern: p?.required_fields.find((f) => f.key === "username")?.pattern ?? null,
    rateUzs: sku?.display_price ? Number(sku.display_price.amount) : null,
    min,
    max: sku?.max_qty ?? 15000,
    initial: String(Math.max(min, 100)),
  };
}

/**
 * Storefront hero, led by what most visitors come for: topping up Steam, with
 * Telegram Stars one tab away. Copy on the left and the product forms on the right
 * (`HeroTopUp`, which switches both together), and the other
 * sections — CS2 skins, games, gift cards — as tiles under the copy. The mini app
 * is shown further down (`AppShowcase`); here it is one link, on phones only.
 */
export async function Hero({ locale }: { locale: string }) {
  const t = await getTranslations("web.hero");
  const [steam, stars] = await Promise.all([
    product("steam-wallet", locale),
    product("telegram-stars", locale),
  ]);
  const offers = [steamOffer(locale, steam), starsOffer(locale, stars)];
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
        <HeroTopUp offers={offers} locale={locale} />

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
