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

/** Gift cards fan from one corner, like a hand of cards. */
const CARD_FAN: readonly string[] = [
  "-rotate-[16deg]",
  "-rotate-[3deg] translate-x-[8%]",
  "rotate-[10deg] translate-x-[16%]",
];

type TileKey = "skins" | "games" | "giftCards";

/** One piece of a tile's art: the image, and for a skin its rarity colour. */
interface Art {
  src: string;
  tint?: string | null;
}

interface Tile {
  key: TileKey;
  href: string;
  Icon: LucideIcon;
  art: Art[];
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

const MOTION = "transition-transform duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]";

/** An app-icon square: game logos as they are, skins on their rarity colour. */
function IconFan({ art, skins }: { art: Art[]; skins: boolean }) {
  const pieces = art.slice(0, 3);
  return (
    <>
      {pieces.map((a, i) => (
        <span
          key={a.src}
          className={`absolute aspect-square w-[30%] overflow-hidden rounded-[22%] shadow-xl ring-1 group-hover:-translate-y-1 ${MOTION} ${
            FAN[pieces.length]?.[i] ?? MID
          } ${skins ? "" : "ring-white/15"}`}
          style={
            skins
              ? {
                  background: `radial-gradient(circle at 50% 70%, ${a.tint ?? "#8847ff"}aa, #11141d 78%)`,
                  boxShadow: `inset 0 0 0 1px ${a.tint ?? "#8847ff"}66`,
                }
              : undefined
          }
        >
          <Image
            src={a.src}
            alt=""
            fill
            sizes="96px"
            unoptimized={!isOptimizable(a.src)}
            className={
              skins
                ? "scale-[1.35] object-contain drop-shadow-[0_4px_8px_rgba(0,0,0,0.6)]"
                : "object-cover"
            }
          />
        </span>
      ))}
    </>
  );
}

/** Plastic gift cards: the brand's own colours as the face, its logo, a chip. */
function CardFan({ art }: { art: Art[] }) {
  const pieces = art.slice(0, 3);
  return (
    <>
      {pieces.map((a, i) => (
        <span
          key={a.src}
          className={`absolute left-[18%] top-[30%] aspect-[1.58/1] w-[48%] origin-bottom-left overflow-hidden rounded-[9%/14%] shadow-[0_10px_24px_rgba(0,0,0,0.55)] ring-1 ring-white/20 group-hover:-translate-y-1 ${MOTION} ${
            CARD_FAN[i] ?? ""
          }`}
          style={{ zIndex: i }}
        >
          {/* The logo blown up and blurred is the card's face — the brand's colour
              without a colour table to keep. */}
          <Image
            src={a.src}
            alt=""
            fill
            sizes="96px"
            unoptimized={!isOptimizable(a.src)}
            className="scale-[2.4] object-cover blur-md brightness-[0.7] saturate-200"
          />
          <span className="absolute inset-0 bg-[linear-gradient(135deg,rgba(255,255,255,0.18),transparent_40%,rgba(0,0,0,0.45))]" />
          <span className="absolute left-[8%] top-[12%] aspect-square h-[40%] overflow-hidden rounded-[22%] ring-1 ring-white/30">
            <Image
              src={a.src}
              alt=""
              fill
              sizes="32px"
              unoptimized={!isOptimizable(a.src)}
              className="object-cover"
            />
          </span>
          <span className="absolute right-[8%] top-[16%] h-[18%] w-[16%] rounded-[3px] bg-gradient-to-br from-amber-200 to-amber-500 opacity-90" />
          <span className="absolute bottom-[14%] left-[8%] h-[7%] w-[46%] rounded-full bg-white/60" />
          <span className="absolute bottom-[14%] right-[8%] h-[7%] w-[18%] rounded-full bg-white/35" />
        </span>
      ))}
    </>
  );
}

function TileArt({ tile }: { tile: Tile }) {
  const { art, key, Icon } = tile;
  if (art.length === 0) {
    return (
      <span className="bg-primary/10 text-primary absolute left-1/2 top-1/2 flex size-12 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-2xl">
        <Icon size={24} aria-hidden />
      </span>
    );
  }
  return key === "giftCards" ? (
    <CardFan art={art} />
  ) : (
    <IconFan art={art} skins={key === "skins"} />
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
              s.image_url
                ? [{ src: steamImageSize(s.image_url, "256fx256f"), tint: s.rarity_color }]
                : [],
            ),
            glow: "rgba(235,75,75,0.35)",
          },
        ]
      : []),
    {
      key: "games",
      href: categoryHref(locale, brands, "pubg-mobile", "games"),
      Icon: Gamepad2,
      art: logos(brands, GAME_BRANDS).map((src) => ({ src })),
      glow: "rgba(102,192,244,0.3)",
    },
    {
      key: "giftCards",
      href: categoryHref(locale, brands, "roblox", "gift-cards"),
      Icon: Gift,
      art: logos(brands, GIFT_BRANDS).map((src) => ({ src })),
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
            <TileArt tile={tile} />
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
