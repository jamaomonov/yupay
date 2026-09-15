"use client";

import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useState } from "react";

import type { Brand, Catalog } from "@/lib/types";

import { api } from "@/lib/api";
import { formatUsd, toCents } from "@/lib/money";

/** The cheapest thing in a brand, for the «from $X» on its card. */
function cheapest(brand: Brand): bigint | null {
  const prices = brand.products
    .flatMap((product) => product.skus)
    .map((sku) => (sku.kind === "fixed" ? sku.price_usd : sku.unit_price_usd))
    .filter((price): price is string => price !== null)
    .map(toCents);
  return prices.length > 0 ? prices.reduce((a, b) => (a < b ? a : b)) : null;
}

export default function CatalogPage() {
  const t = useTranslations("merchant.catalog");
  const { locale } = useParams<{ locale: string }>();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    void api<Catalog>("/catalog")
      .then(setCatalog)
      .catch(() => {
        setCatalog({ brands: [] });
      });
  }, []);

  const brands = useMemo(() => {
    const all = catalog?.brands ?? [];
    const needle = query.trim().toLowerCase();
    return needle ? all.filter((b) => b.name.toLowerCase().includes(needle)) : all;
  }, [catalog, query]);

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>

      <input
        type="search"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
        }}
        placeholder={t("searchPlaceholder")}
        aria-label={t("searchPlaceholder")}
        className="border-border bg-card rounded-btn mt-5 w-full border px-3.5 py-2.5 text-sm outline-none sm:max-w-sm"
      />

      {catalog !== null && brands.length === 0 && (
        <p className="text-tx-dim mt-8 text-sm">{t("empty")}</p>
      )}

      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {brands.map((brand) => {
          const from = cheapest(brand);
          return (
            <a
              key={brand.brand_id}
              href={`/${locale}/cabinet/catalog/${brand.slug}`}
              className="border-border bg-card rounded-xl border p-5"
            >
              <p className="font-semibold">{brand.name}</p>
              {from !== null && (
                <p className="text-tx-mute mt-1.5 font-mono text-sm">
                  {t("from", { price: `$${formatUsd(from)}` })}
                </p>
              )}
            </a>
          );
        })}
      </div>
    </div>
  );
}
