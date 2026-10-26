"use client";

import { useTranslations } from "next-intl";
import { type ReactNode, useEffect, useState } from "react";

import { PurchasePanel } from "./PurchasePanel";

import type { ProductDetail } from "@/lib/catalog";

import { stashHandoff } from "@/lib/handoff";

/** One region of the game, with the products its own brand sells. */
export interface RegionOption {
  code: string;
  slug: string;
  products: ProductDetail[];
}

interface RegionPurchaseProps {
  /** Main brand first ("global"), in switcher order — as the API lists them. */
  regions: RegionOption[];
  locale: string;
  /** Server-rendered sections handed through to `PurchasePanel`'s left column. */
  children?: ReactNode;
}

const PARAM = "region";

/** True when the region asks for an account id but no field of it can be
 *  checked (ADR-0099: PH/MY/SG/ID are sold unchecked). A product with no
 *  fields at all (a code) has nothing to check, so it never counts. */
export function isRegionUnchecked(products: ProductDetail[]): boolean {
  const fields = products.flatMap((p) => p.required_fields);
  return fields.length > 0 && !fields.some((f) => Boolean(f.check));
}

/**
 * The game's region switcher over the purchase panel (ADR-0099): one page per
 * game, and each region is its own brand with its own products, player check
 * and orders. The picked region lives in `?region=` so a regional link
 * (`/store/<region slug>` redirects here) lands on it — read on the client,
 * because the page is ISR and reading `searchParams` on the server would make
 * it dynamic.
 */
export function RegionPurchase({ regions, locale, children }: RegionPurchaseProps) {
  const t = useTranslations("web.store");
  const first = regions[0];
  const [code, setCode] = useState<string>(first?.code ?? "");

  useEffect(() => {
    const wanted = new URLSearchParams(window.location.search).get(PARAM);
    if (wanted && regions.some((r) => r.code === wanted)) setCode(wanted);
    // Read once on mount: afterwards the switcher owns both state and URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function pick(next: string): void {
    setCode(next);
    const url = new URL(window.location.href);
    if (next === first?.code) url.searchParams.delete(PARAM);
    else url.searchParams.set(PARAM, next);
    window.history.replaceState(window.history.state, "", url);
  }

  // The game's main region is named after where our customers are —
  // «Узбекистан», «Узбекистан и СНГ» — and a plain global server is «Другие
  // страны»: «Глобальный (Узбекистан)» beside «Глобальный» on Free Fire left a
  // buyer two plausible chips for one account (design review 2026-10-26).
  function regionName(c: string): string {
    const home = `regionsHome.${c}`;
    if (c === first?.code && t.has(home)) return t(home);
    const key = `regions.${c}`;
    return t.has(key) ? t(key) : c.toUpperCase();
  }

  const current = regions.find((r) => r.code === code) ?? first;
  if (!current) return null;

  return (
    <>
      <div role="group" aria-label={t("regionTitle")} className="mb-6">
        <div className="text-tx-mute mb-3 text-sm font-semibold">{t("regionTitle")}</div>
        <div className="flex flex-wrap gap-2">
          {regions.map((r) => {
            const active = r.code === current.code;
            return (
              <button
                key={r.code}
                type="button"
                aria-pressed={active}
                onClick={() => {
                  pick(r.code);
                }}
                className={`focus-visible:ring-primary focus-visible:ring-offset-bg min-h-[44px] rounded-full border px-4 py-2 text-[13px] font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 ${
                  active
                    ? "border-primary bg-primary/10 text-foreground"
                    : "border-border bg-card text-tx-mute hover:border-border-2"
                }`}
              >
                {regionName(r.code)}
              </button>
            );
          })}
        </div>
        {isRegionUnchecked(current.products) && (
          <p className="mt-3 rounded-md border border-amber-400/40 bg-amber-400/[0.06] px-4 py-3 text-[13px] text-amber-200">
            {t("regionUnchecked", { region: regionName(current.code) })}
          </p>
        )}
      </div>
      {/* Keyed by the region's brand: a picked package, typed id or check
          verdict belongs to one region's products and must not carry over. */}
      <PurchasePanel
        key={current.slug}
        products={current.products}
        locale={locale}
        hasRegions
        regionSwitch={{
          name: regionName,
          available: regions.map((r) => r.code),
          // The id rides the hand-off the new region's panel reads on mount,
          // and is checked there by itself — no retyping.
          go: (next, carry) => {
            stashHandoff(window.location.pathname, new URLSearchParams(carry));
            pick(next);
          },
        }}
      >
        {children}
      </PurchasePanel>
    </>
  );
}
