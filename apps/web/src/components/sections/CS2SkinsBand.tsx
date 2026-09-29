import { rarityGlow } from "@yupay/utils";
import { ArrowRight, Zap } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import type { SkinItem } from "@/lib/skins";

import { buttonStyles } from "@/lib/button";
import { skinsEnabled } from "@/lib/features";
import { isOptimizable } from "@/lib/image";
import { pathFor } from "@/lib/seo";
import { steamImageSize } from "@/lib/skin-float";
import { categoryPath, weaponPath } from "@/lib/skin-landing";
import { displayPrice, getSkinFacets, getSkinsPage } from "@/lib/skins";

/** The three showcase cards: the most wanted gloves, Karambit and AK-47 right now. */
export async function showcase(locale: string): Promise<SkinItem[]> {
  const pick = async (q: Parameters<typeof getSkinsPage>[1]) =>
    (await getSkinsPage(locale, q)).items.find((i) => i.image_url && i.price_usd) ?? null;
  const items = await Promise.all([
    pick({ sort: "popular", category: "gloves" }),
    pick({ sort: "popular", weapon: "Karambit" }),
    pick({ sort: "popular", weapon: "AK-47" }),
  ]);
  return items.filter((i): i is SkinItem => i !== null);
}

/** Cards in the collage: where each sits, how it tilts, how fast it drifts. */
const PLACES = [
  "left-0 top-14 -rotate-6 anim-float-slow",
  "left-1/2 top-0 z-10 -translate-x-1/2 rotate-1 anim-float",
  "right-0 top-24 rotate-6 anim-float-slow",
] as const;

function Card({ item, locale, place }: { item: SkinItem; locale: string; place: string }) {
  const glow = rarityGlow(item.rarity_color);
  const price = displayPrice(locale, item.price_uzs, item.price_usd);
  return (
    <Link
      href={pathFor(locale, `/skins/${item.slug}`)}
      className={`border-border bg-card/90 group absolute w-[38%] overflow-hidden rounded-2xl border shadow-2xl backdrop-blur transition hover:z-20 hover:scale-[1.04] ${place}`}
    >
      <div className="relative aspect-[4/3]">
        {glow && <span aria-hidden className="absolute inset-0" style={{ background: glow }} />}
        {item.image_url && (
          <Image
            src={steamImageSize(item.image_url, "256fx256f")}
            alt={item.name}
            fill
            unoptimized={!isOptimizable(item.image_url)}
            sizes="(min-width: 768px) 260px, 45vw"
            className="relative object-contain p-4 transition duration-500 group-hover:scale-110"
          />
        )}
      </div>
      <div className="p-3">
        <p className="text-tx-dim truncate text-[11px]">{item.weapon}</p>
        <p className="truncate text-[13px] font-semibold">{item.skin ?? item.name}</p>
        {price && <p className="text-primary mt-1 text-[14px] font-bold tabular-nums">{price}</p>}
      </div>
    </Link>
  );
}

/**
 * Home page band for the CS2 market: the claim, three facts, the way in, a few landing
 * links — and a floating collage of the most wanted knife, glove and rifle with their
 * rarity glow and live price. Nothing at all while skins are off or the catalogue is out.
 * RSC, zero client JS.
 */
export async function CS2SkinsBand({ locale }: { locale: string }) {
  if (!skinsEnabled()) return null;
  const [items, facets] = await Promise.all([showcase(locale), getSkinFacets(locale)]);
  if (items.length === 0 || !facets) return null;
  const t = await getTranslations("web.cs2Band");
  const tSkins = await getTranslations("web.skins");
  const total = facets.categories.reduce((n, c) => n + c.count, 0);
  const rounded = Math.floor(total / 1000) * 1000;
  const links = [
    {
      label: tSkins("landing.categoryH1", { name: tSkins("category.knives") }),
      path: categoryPath("knives"),
    },
    {
      label: tSkins("landing.categoryH1", { name: tSkins("category.gloves") }),
      path: categoryPath("gloves"),
    },
    { label: tSkins("landing.weaponH1", { weapon: "AK-47" }), path: weaponPath("AK-47") },
    { label: tSkins("landing.weaponH1", { weapon: "AWP" }), path: weaponPath("AWP") },
  ];

  return (
    <section className="border-border/60 relative isolate overflow-hidden border-y">
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <div
          className="absolute right-[10%] top-1/2 h-[520px] w-[520px] -translate-y-1/2 rounded-full opacity-60 blur-[90px]"
          style={{
            background:
              "radial-gradient(circle, rgba(235,75,75,0.35), rgba(136,71,255,0.25) 45%, transparent 70%)",
          }}
        />
        <div
          className="font-display absolute bottom-[-6%] left-[-1%] hidden select-none text-[clamp(8rem,20vw,17rem)] font-extrabold leading-none opacity-[0.08] md:block"
          style={{ WebkitTextStroke: "2px hsl(var(--primary))", color: "transparent" }}
        >
          CS2
        </div>
      </div>

      <div className="relative mx-auto grid max-w-[1200px] items-center gap-12 px-6 py-16 sm:px-10 sm:py-24 md:grid-cols-2">
        <div>
          <span className="border-primary/40 text-primary inline-block rounded-full border px-3 py-1 font-mono text-[11px] font-semibold uppercase tracking-[0.14em]">
            {t("eyebrow")}
          </span>
          <h2 className="font-display mt-5 text-[clamp(2.2rem,5vw,3.6rem)] font-extrabold leading-[1.05] tracking-tight">
            {t("title")}
          </h2>
          <p className="text-tx-mute mt-4 max-w-md text-[15px] leading-relaxed">{t("subtitle")}</p>

          <ul className="mt-6 flex flex-wrap gap-x-6 gap-y-2 text-[13px] font-semibold">
            <li className="text-foreground tabular-nums">
              {t("count", { count: new Intl.NumberFormat(locale).format(rounded) })}
            </li>
            <li className="text-tx-mute flex items-center gap-1.5">
              <Zap className="text-primary h-4 w-4" aria-hidden />
              {t("fast")}
            </li>
          </ul>

          <Link
            href={pathFor(locale, "/skins")}
            className={`${buttonStyles({ size: "lg" })} mt-8 inline-flex items-center gap-2`}
          >
            {t("cta")}
            <ArrowRight className="h-4 w-4" aria-hidden />
          </Link>

          <ul className="mt-6 flex flex-wrap gap-2">
            {links.map((l) => (
              <li key={l.path}>
                <Link
                  href={pathFor(locale, l.path)}
                  className="border-border hover:border-border-2 text-tx-mute hover:text-foreground inline-block rounded-full border px-3 py-1.5 text-[12px]"
                >
                  {l.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>

        <div className="relative h-[260px] sm:h-[360px]">
          {items.map((item, i) => (
            <Card key={item.slug} item={item} locale={locale} place={PLACES[i] ?? PLACES[0]} />
          ))}
        </div>
      </div>
    </section>
  );
}
