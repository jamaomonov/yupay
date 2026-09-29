import { rarityGlow } from "@yupay/utils";
import { ArrowRight } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import type { SkinItem } from "@/lib/skins";

import { skinsEnabled } from "@/lib/features";
import { isOptimizable } from "@/lib/image";
import { pathFor } from "@/lib/seo";
import { steamImageSize } from "@/lib/skin-float";
import { displayPrice, getSkinsPage } from "@/lib/skins";

/** Three live examples: the most wanted Karambit, gloves and AK-47. */
async function picks(locale: string): Promise<SkinItem[]> {
  const pick = async (q: Parameters<typeof getSkinsPage>[1]) =>
    (await getSkinsPage(locale, q)).items.find((i) => i.image_url && i.price_usd) ?? null;
  const items = await Promise.all([
    pick({ sort: "popular", weapon: "Karambit" }),
    pick({ sort: "popular", category: "gloves" }),
    pick({ sort: "popular", weapon: "AK-47" }),
  ]);
  return items.filter((i): i is SkinItem => i !== null);
}

/**
 * On the Steam top-up page, where most buyers play CS2: the skins market, with three live
 * examples and the way in.
 * Nothing while skins are off or the catalogue is out. RSC.
 */
export async function SteamSkinsPromo({ locale }: { locale: string }) {
  if (!skinsEnabled()) return null;
  const items = await picks(locale);
  if (items.length === 0) return null;
  const t = await getTranslations("web.skinsPromo");

  return (
    <section className="border-border bg-card relative isolate mt-14 overflow-hidden rounded-2xl border p-6 sm:p-8">
      <div
        aria-hidden
        className="absolute -right-24 -top-24 -z-10 h-80 w-80 rounded-full opacity-60 blur-[80px]"
        style={{
          background:
            "radial-gradient(circle, rgba(235,75,75,0.35), rgba(136,71,255,0.25) 50%, transparent 72%)",
        }}
      />
      <span className="border-primary/40 text-primary inline-block rounded-full border px-3 py-1 font-mono text-[11px] font-semibold uppercase tracking-[0.14em]">
        {t("eyebrow")}
      </span>
      <h2 className="font-display mt-4 text-[clamp(1.5rem,3vw,2rem)] font-bold leading-tight tracking-[-0.02em]">
        {t("title")}
      </h2>
      <p className="text-tx-mute mt-2 max-w-[52ch] text-[15px] leading-relaxed">{t("body")}</p>

      <ul className="mt-6 grid grid-cols-3 gap-3">
        {items.map((item) => {
          const glow = rarityGlow(item.rarity_color);
          const price = displayPrice(locale, item.price_uzs, item.price_usd);
          return (
            <li key={item.slug}>
              <Link
                href={pathFor(locale, `/skins/${item.slug}`)}
                className="border-border group block overflow-hidden rounded-xl border bg-black/20 transition hover:-translate-y-1"
              >
                <div className="relative aspect-[4/3]">
                  {glow && (
                    <span aria-hidden className="absolute inset-0" style={{ background: glow }} />
                  )}
                  {item.image_url && (
                    <Image
                      src={steamImageSize(item.image_url, "256fx256f")}
                      alt={item.name}
                      fill
                      unoptimized={!isOptimizable(item.image_url)}
                      sizes="(min-width: 768px) 200px, 30vw"
                      className="relative object-contain p-3 transition duration-500 group-hover:scale-110"
                    />
                  )}
                </div>
                <div className="p-2.5">
                  <p className="text-tx-dim truncate text-[11px]">{item.weapon}</p>
                  <p className="truncate text-[12px] font-semibold sm:text-[13px]">
                    {item.skin ?? item.name}
                  </p>
                  {price && (
                    <p className="text-primary mt-0.5 text-[12px] font-bold tabular-nums sm:text-[13px]">
                      {price}
                    </p>
                  )}
                </div>
              </Link>
            </li>
          );
        })}
      </ul>

      <Link
        href={pathFor(locale, "/skins")}
        className="text-primary mt-5 inline-flex items-center gap-1.5 text-[15px] font-semibold hover:underline"
      >
        {t("cta")}
        <ArrowRight className="h-4 w-4" aria-hidden />
      </Link>
    </section>
  );
}
