import { ArrowRight } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { getBrands, type BrandSummary } from "@/lib/catalog";

/**
 * Bento-grid catalog teaser on the landing — a featured brand (2×2) plus
 * smaller brand cards, backed by the live catalog API. Adaptive to any brand
 * count: the feature occupies cols 1–2 / rows 1–2, leaving col 3 for two cards
 * and every further row holding three — so we render the largest multiple of
 * three (capped at 9) and the grid always fills cleanly, however many brands
 * production ends up with. The rest live behind "Весь каталог".
 */
const MAX = 9;

function BentoCard({
  brand,
  locale,
  featured,
  maintenanceLabel,
}: {
  brand: BrandSummary;
  locale: string;
  featured: boolean;
  maintenanceLabel: string;
}) {
  const img = brand.hero_image_url ?? brand.logo_url;
  const accent = brand.accent_color ?? "#AAFF33";
  return (
    <Link
      href={`/${locale}/store/${brand.slug}`}
      className={`border-border hover:border-primary/30 focus-visible:ring-primary group relative isolate overflow-hidden rounded-xl border transition hover:-translate-y-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset ${
        featured ? "h-[300px] md:col-span-2 md:row-span-2 md:h-auto" : "h-[240px] md:h-auto"
      }`}
    >
      {img ? (
        <Image
          src={img}
          alt=""
          fill
          unoptimized
          sizes={featured ? "(max-width: 768px) 100vw, 540px" : "(max-width: 768px) 100vw, 270px"}
          className="object-cover transition duration-500 group-hover:scale-[1.04]"
        />
      ) : (
        <div
          aria-hidden
          className="absolute inset-0"
          style={{ background: `linear-gradient(135deg, ${accent}55, #0A0D1A)` }}
        />
      )}
      <div className="absolute inset-0 bg-[linear-gradient(to_top,rgba(0,0,0,0.85)_0%,rgba(0,0,0,0.25)_55%,transparent_82%)]" />

      {brand.maintenance && (
        <span className="absolute left-4 top-4 z-10 inline-flex rounded-md bg-black/60 px-2 py-1 text-[10px] font-black uppercase tracking-[0.06em] text-white backdrop-blur">
          {maintenanceLabel}
        </span>
      )}

      <div className="absolute inset-x-5 bottom-5 z-10">
        {brand.short_description && (
          <div className="mb-1.5 line-clamp-1 text-[11px] font-bold uppercase tracking-[0.1em] text-white/65">
            {brand.short_description}
          </div>
        )}
        <div className="flex items-end justify-between gap-3">
          <div
            className="font-display font-extrabold leading-none tracking-[-0.025em] text-white"
            style={{ fontSize: featured ? 48 : 26 }}
          >
            {brand.name}
          </div>
          <div className="border-white/18 group-hover:bg-primary flex h-10 w-10 shrink-0 items-center justify-center rounded-[11px] border bg-black/45 backdrop-blur transition">
            <ArrowRight
              size={16}
              strokeWidth={2.4}
              className="group-hover:text-primary-foreground text-white transition"
            />
          </div>
        </div>
      </div>
    </Link>
  );
}

export async function CatalogBento({ locale }: { locale: string }) {
  const t = await getTranslations("web.catalog");
  const ts = await getTranslations("web.store");
  const prefix = `/${locale}`;

  let all: BrandSummary[] = [];
  try {
    all = await getBrands(locale);
  } catch {
    // API unreachable → skip the teaser rather than break the page.
  }
  if (all.length === 0) return null;

  // Render the largest multiple of three (capped) so the bento fills cleanly;
  // fall back to whatever exists when there are fewer than three brands.
  const clean = all.length >= 3 ? Math.min(Math.floor(all.length / 3) * 3, MAX) : all.length;
  const brands = all.slice(0, clean);
  const [feature, ...rest] = brands;
  if (!feature) return null;

  return (
    <section id="catalog" className="relative py-28">
      <div className="mx-auto max-w-[1200px] px-6 sm:px-10">
        <div className="mb-14 flex items-end justify-between gap-6">
          <div>
            <div className="text-primary font-mono text-xs font-semibold uppercase tracking-[0.16em]">
              [ 01 / {t("eyebrow")} ]
            </div>
            <h2 className="font-display mt-3 text-[clamp(2.2rem,4vw,3.4rem)] font-extrabold leading-[0.98] tracking-[-0.04em]">
              <span className="block">{t("titleLine1")}</span>
              <span className="text-tx-mute block">{t("titleLine2")}</span>
            </h2>
          </div>
          <Link
            href={`${prefix}/store`}
            className="border-border-2 text-foreground hover:border-tx-dim hover:bg-muted hidden h-[44px] items-center gap-2 rounded-[12px] border px-5 text-sm font-semibold transition sm:inline-flex"
          >
            {t("viewAll")}
            <ArrowRight size={14} strokeWidth={2.4} />
          </Link>
        </div>

        <div className="grid grid-cols-1 gap-4 md:auto-rows-[300px] md:grid-cols-3">
          <BentoCard
            brand={feature}
            locale={locale}
            featured
            maintenanceLabel={ts("maintenance")}
          />
          {rest.map((brand) => (
            <BentoCard
              key={brand.slug}
              brand={brand}
              locale={locale}
              featured={false}
              maintenanceLabel={ts("maintenance")}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
