"use client";

import { LayoutGrid } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, useMemo } from "react";

import type { Brand } from "@/lib/types";

import { sectionsOf, useCabinet, useSearch } from "@/components/CabinetContext";
import { EmptyState } from "@/components/EmptyState";
import { PageHeading } from "@/components/PageHeading";
import { downloadFile } from "@/lib/api";
import { pathFor } from "@/lib/locale-href";
import { formatUsd, toCents } from "@/lib/money";

/**
 * A tint per brand, stable across renders and sessions.
 *
 * Every brand in the dev catalog has `logo_url: null`, and a grid of twenty
 * identical grey rectangles is harder to scan than a grid of twenty different
 * ones. The tint is derived from the slug, so a brand keeps its colour — it
 * reads as identity rather than as decoration, right up until real artwork
 * replaces it.
 */
const TINTS = [
  "from-orange-500/25",
  "from-blue-500/25",
  "from-violet-500/25",
  "from-rose-500/25",
  "from-cyan-500/25",
  "from-lime-500/20",
] as const;

function tintOf(slug: string): string {
  let hash = 0;
  for (const char of slug) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  // `noUncheckedIndexedAccess` types a computed index as possibly undefined
  // even when the modulo makes that impossible; `as const` above is what
  // makes the fallback a known literal rather than a second maybe-undefined.
  return TINTS[hash % TINTS.length] ?? TINTS[0];
}

/** The cheapest SKU in a brand, and the product it belongs to. */
function cheapest(brand: Brand): { cents: bigint; product: string } | null {
  let best: { cents: bigint; product: string } | null = null;
  for (const product of brand.products) {
    for (const sku of product.skus) {
      const price = sku.kind === "fixed" ? sku.price_usd : sku.unit_price_usd;
      if (price === null) continue;
      const cents = toCents(price);
      if (best === null || cents < best.cents) best = { cents, product: product.name };
    }
  }
  return best;
}

function CatalogGrid() {
  const t = useTranslations("merchant.catalog");
  const tCommon = useTranslations("merchant.common");
  const { locale } = useParams<{ locale: string }>();
  const { catalog } = useCabinet();
  const query = useSearch(t("searchPlaceholder"));
  const section = useSearchParams().get("section");

  const sectionName = useMemo(
    () => sectionsOf(catalog).find((entry) => entry.slug === section)?.name ?? null,
    [catalog, section],
  );

  const brands = useMemo(() => {
    const all = catalog?.brands ?? [];
    const inSection = section === null ? all : all.filter((b) => b.category_slug === section);
    const needle = query.trim().toLowerCase();
    if (needle === "") return inSection;
    // Brand name or any product under it: a reseller looking for "robux"
    // is looking for Roblox, and typing the currency is the natural way in.
    return inSection.filter(
      (brand) =>
        brand.name.toLowerCase().includes(needle) ||
        brand.products.some((product) => product.name.toLowerCase().includes(needle)),
    );
  }, [catalog, section, query]);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <PageHeading icon={LayoutGrid} title={sectionName ?? t("title")} />
        <button
          type="button"
          onClick={() => {
            void downloadFile("/catalog.csv").catch(() => undefined);
          }}
          className="border-border bg-card rounded-btn text-tx-mute border px-3 py-1.5 text-xs font-semibold"
        >
          {tCommon("exportCsv")}
        </button>
      </div>

      {catalog !== null && brands.length === 0 && (
        <EmptyState icon={LayoutGrid} title={t("empty")} />
      )}

      <div className="mt-5 grid grid-cols-2 gap-3.5 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
        {brands.map((brand) => {
          const from = cheapest(brand);
          return (
            <Link
              key={brand.brand_id}
              href={pathFor(locale, `/cabinet/catalog/${brand.slug}`)}
              className="border-border bg-card overflow-hidden rounded-xl border"
            >
              <div
                className={`bg-card-2 relative flex aspect-[4/3] items-end bg-gradient-to-tr to-transparent p-2.5 ${tintOf(
                  brand.slug,
                )}`}
              >
                {brand.logo_url !== null && (
                  /* eslint-disable-next-line @next/next/no-img-element --
                     the URL is an operator-entered absolute one on a host we
                     do not control, so `next/image` would need every one of
                     them allowlisted in the config and would fail the page on
                     the first that is not. */
                  <img
                    src={brand.logo_url}
                    alt=""
                    className="absolute inset-0 h-full w-full object-cover"
                  />
                )}
              </div>
              <div className="px-3 pb-3 pt-2.5">
                <p className="truncate text-[13.5px] font-bold">{brand.name}</p>
                {/* Price first, and only the product name truncates. It used
                    to read "<product> · from $X" inside one `truncate`, so on
                    most cards the price — the only reason a reseller opens
                    this screen — was the half that got cut. */}
                <p className="text-tx-dim mt-0.5 flex min-w-0 items-baseline gap-1.5 text-[11.5px]">
                  {from === null ? (
                    "—"
                  ) : (
                    <>
                      <span className="text-primary-ink shrink-0 font-mono">
                        {t("from", { price: `$${formatUsd(from.cents)}` })}
                      </span>
                      <span className="min-w-0 truncate">{from.product}</span>
                    </>
                  )}
                </p>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

export default function CatalogPage() {
  return (
    <Suspense fallback={null}>
      <CatalogGrid />
    </Suspense>
  );
}
