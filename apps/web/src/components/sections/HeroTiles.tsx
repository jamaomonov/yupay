import { ArrowUpRight, Crosshair, Gamepad2, Gift, type LucideIcon } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { showcase } from "./CS2SkinsBand";

import type { BrandSummary } from "@/lib/catalog";

import { getBrands } from "@/lib/catalog";
import { skinsEnabled } from "@/lib/features";
import { isOptimizable } from "@/lib/image";
import { pathFor } from "@/lib/seo";
import { steamImageSize } from "@/lib/skin-float";

/** The brands whose art fronts each tile, most recognisable first. */
const GAME_BRANDS = ["pubg-mobile", "genshin-impact", "free-fire", "mobile-legends"];
const GIFT_BRANDS = ["roblox", "discord", "minecraft"];

/** A fan: where each piece of art sits, by how many there are, back to front. */
const LEFT = "left-[10%] top-[28%] -rotate-[14deg]";
const MID = "left-1/2 top-[14%] z-10 -translate-x-1/2";
const RIGHT = "right-[10%] top-[28%] rotate-[14deg]";
const FAN: Record<number, readonly string[]> = {
  1: [MID],
  2: [LEFT, RIGHT],
  3: [LEFT, MID, RIGHT],
};

/** Skins are wide and transparent, so they fan wider and overlap less. */
const SKIN_FAN: readonly string[] = [
  "-left-[6%] top-[34%] -rotate-[18deg]",
  "left-1/2 top-[4%] z-10 -translate-x-1/2",
  "-right-[6%] top-[34%] rotate-[18deg]",
];

type TileKey = "skins" | "games" | "giftCards";

interface Tile {
  key: TileKey;
  href: string;
  Icon: LucideIcon;
  art: string[];
  /** Light behind the art, in the section's own colour. */
  glow: string;
}

export function logos(brands: BrandSummary[], slugs: string[]): string[] {
  return slugs
    .map((s) => brands.find((b) => b.slug === s)?.logo_url ?? null)
    .filter((u): u is string => u !== null);
}

/** Where a tile's category lives in the catalogue, read off a brand known to be in it. */
export function categoryHref(
  locale: string,
  brands: BrandSummary[],
  slug: string,
  fallback: string,
) {
  const cat = brands.find((b) => b.slug === slug)?.category_slug ?? fallback;
  return `${pathFor(locale, "/store")}?cat=${encodeURIComponent(cat)}`;
}

function Art({ tile }: { tile: Tile }) {
  const { art, key, Icon } = tile;
  if (art.length === 0) {
    return (
      <span className="bg-primary/10 text-primary absolute left-1/2 top-1/2 flex size-12 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-2xl">
        <Icon size={24} aria-hidden />
      </span>
    );
  }
  const pieces = art.slice(0, 3);
  const skins = key === "skins";
  const cards = key === "giftCards";
  return (
    <>
      {pieces.map((src, i) => (
        <span
          key={src}
          className={`absolute transition-transform duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] ${
            (skins && pieces.length === 3 ? SKIN_FAN[i] : FAN[pieces.length]?.[i]) ?? MID
          } ${
            skins
              ? "aspect-[4/3] w-[54%] group-hover:scale-110"
              : cards
                ? "aspect-[3/4] w-[28%] overflow-hidden rounded-lg shadow-xl ring-1 ring-white/15 group-hover:-translate-y-1"
                : "aspect-square w-[30%] overflow-hidden rounded-[22%] shadow-xl ring-1 ring-white/15 group-hover:-translate-y-1"
          }`}
        >
          <Image
            src={src}
            alt=""
            fill
            sizes="96px"
            unoptimized={!isOptimizable(src)}
            className={
              skins ? "object-contain drop-shadow-[0_8px_16px_rgba(0,0,0,0.6)]" : "object-cover"
            }
          />
        </span>
      ))}
    </>
  );
}

/**
 * The hero's "also here" row: CS2 skins, games and gift cards, each fronted by its own
 * art — real skins fanned out, game icons, gift cards — pulled from the catalogue, so
 * the row stays true as the catalogue changes. A tile with no art shows its icon.
 */
export async function HeroTiles({ locale }: { locale: string }) {
  const t = await getTranslations("web.hero");
  const skinsOn = skinsEnabled();
  const [brands, skins] = await Promise.all([
    getBrands(locale).catch(() => [] as BrandSummary[]),
    skinsOn ? showcase(locale).catch(() => []) : Promise.resolve([]),
  ]);

  const tiles: Tile[] = [
    ...(skinsOn
      ? [
          {
            key: "skins" as const,
            href: pathFor(locale, "/skins"),
            Icon: Crosshair,
            art: skins.flatMap((s) =>
              s.image_url ? [steamImageSize(s.image_url, "256fx256f")] : [],
            ),
            glow: "rgba(235,75,75,0.35)",
          },
        ]
      : []),
    {
      key: "games",
      href: categoryHref(locale, brands, "pubg-mobile", "games"),
      Icon: Gamepad2,
      art: logos(brands, GAME_BRANDS),
      glow: "rgba(102,192,244,0.3)",
    },
    {
      key: "giftCards",
      href: categoryHref(locale, brands, "roblox", "gift-cards"),
      Icon: Gift,
      art: logos(brands, GIFT_BRANDS),
      glow: "rgba(168,85,247,0.32)",
    },
  ];

  return (
    <div className="mt-3 grid max-w-[560px] grid-cols-3 gap-2.5 sm:gap-3">
      {tiles.map((tile) => (
        <Link
          key={tile.key}
          href={tile.href}
          className="border-border bg-card/60 hover:border-primary/50 group relative flex flex-col overflow-hidden rounded-2xl border transition hover:-translate-y-0.5"
        >
          <div className="relative h-24 sm:h-28">
            <span
              aria-hidden
              className="absolute inset-0 opacity-80 transition-opacity group-hover:opacity-100"
              style={{
                background: `radial-gradient(70% 80% at 50% 45%, ${tile.glow}, transparent 70%)`,
              }}
            />
            <Art tile={tile} />
          </div>
          <span className="flex items-center justify-between gap-1 px-3 pb-3 text-[13px] font-semibold leading-tight sm:px-3.5 sm:text-[14px]">
            {t(`tiles.${tile.key}`)}
            <ArrowUpRight
              size={14}
              className="text-tx-dim group-hover:text-primary hidden shrink-0 transition sm:block"
              aria-hidden
            />
          </span>
        </Link>
      ))}
    </div>
  );
}
