import { ArrowRight } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import type { BrandSummary } from "@/lib/catalog";

/**
 * Catalog tile backed by live API data — brand key-art (hero, falling back to
 * logo or an accent gradient), localised name + short description, and a
 * maintenance badge when the brand is temporarily paused. Links into the brand
 * top-up page. Focus ring renders inset so it survives the overflow clip.
 */
export async function BrandCard({ brand, locale }: { brand: BrandSummary; locale: string }) {
  const ts = await getTranslations("web.store");
  const prefix = `/${locale}`;
  const img = brand.hero_image_url ?? brand.logo_url;
  const accent = brand.accent_color ?? "#AAFF33";

  return (
    <Link
      href={`${prefix}/store/${brand.slug}`}
      className="border-border hover:border-primary/30 focus-visible:ring-primary group relative isolate flex h-[240px] flex-col justify-end overflow-hidden rounded-xl border transition hover:-translate-y-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset"
    >
      {img ? (
        <Image
          src={img}
          alt=""
          fill
          unoptimized
          sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 300px"
          className="object-cover transition duration-500 group-hover:scale-[1.04]"
        />
      ) : (
        <div
          aria-hidden
          className="absolute inset-0"
          style={{ background: `linear-gradient(135deg, ${accent}55, #0A0D1A)` }}
        />
      )}
      <div className="absolute inset-0 bg-[linear-gradient(to_top,rgba(0,0,0,0.88)_0%,rgba(0,0,0,0.3)_55%,transparent_82%)]" />

      {brand.maintenance && (
        <span className="absolute left-4 top-4 z-10 inline-flex rounded-md bg-black/60 px-2 py-1 text-[10px] font-black uppercase tracking-[0.06em] text-white backdrop-blur">
          {ts("maintenance")}
        </span>
      )}

      <div className="relative z-10 p-5">
        {brand.short_description && (
          <div className="mb-1 line-clamp-1 text-[11px] font-bold uppercase tracking-[0.1em] text-white/65">
            {brand.short_description}
          </div>
        )}
        <div className="flex items-end justify-between gap-3">
          <div className="font-display text-[24px] font-extrabold leading-none tracking-[-0.025em] text-white">
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
