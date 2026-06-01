import { ArrowRight, Clock, Percent } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import type { Brand } from "@/lib/catalog";

/**
 * Catalog tile — real key-art + localized name/eyebrow (from web.catalog.cards)
 * and two trust chips (commission-from, credit time). Links into the brand
 * top-up page. Server component; focus ring renders inset so it survives the
 * overflow-hidden clip.
 */
export async function BrandCard({ brand, locale }: { brand: Brand; locale: string }) {
  const tc = await getTranslations("web.catalog");
  const ts = await getTranslations("web.store");
  const prefix = `/${locale}`;

  return (
    <Link
      href={`${prefix}/store/${brand.slug}`}
      className="border-border hover:border-primary/30 focus-visible:ring-primary group relative isolate flex h-[240px] flex-col justify-end overflow-hidden rounded-xl border transition hover:-translate-y-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset"
    >
      <Image
        src={brand.art}
        alt=""
        fill
        sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 300px"
        className="object-cover transition duration-500 group-hover:scale-[1.04]"
      />
      <div className="absolute inset-0 bg-[linear-gradient(to_top,rgba(0,0,0,0.88)_0%,rgba(0,0,0,0.3)_55%,transparent_82%)]" />

      {brand.popular && (
        <span className="bg-primary text-primary-foreground absolute left-4 top-4 z-10 inline-flex rounded-md px-2 py-1 text-[10px] font-black uppercase tracking-[0.06em]">
          {ts("popular")}
        </span>
      )}
      {brand.icon && (
        <span className="absolute right-4 top-4 z-10 flex h-11 w-11 items-center justify-center overflow-hidden rounded-[12px] border border-white/15 bg-black/40 backdrop-blur">
          <Image
            src={brand.icon}
            alt=""
            width={28}
            height={28}
            className="h-7 w-7 object-contain"
          />
        </span>
      )}

      <div className="relative z-10 p-5">
        <div className="mb-1 text-[11px] font-bold uppercase tracking-[0.1em] text-white/65">
          {tc(`cards.${brand.slug}.eyebrow`)}
        </div>
        <div className="flex items-end justify-between gap-3">
          <div className="font-display whitespace-pre-line text-[24px] font-extrabold leading-none tracking-[-0.025em] text-white">
            {tc(`cards.${brand.slug}.name`)}
          </div>
          <div className="border-white/18 group-hover:bg-primary flex h-10 w-10 shrink-0 items-center justify-center rounded-[11px] border bg-black/45 backdrop-blur transition">
            <ArrowRight
              size={16}
              strokeWidth={2.4}
              className="group-hover:text-primary-foreground text-white transition"
            />
          </div>
        </div>
        <div className="mt-3 flex items-center gap-3 text-[11px] font-semibold text-white/75">
          <span className="inline-flex items-center gap-1">
            <Percent size={12} className="text-primary" />
            {ts("from")} {brand.commissionFrom}%
          </span>
          <span className="text-white/25">·</span>
          <span className="inline-flex items-center gap-1">
            <Clock size={12} className="text-primary" />
            {brand.etaMinutes} {ts("etaUnit")}
          </span>
        </div>
      </div>
    </Link>
  );
}
