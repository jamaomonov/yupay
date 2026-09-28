"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import type { SkinQuery } from "@/lib/skins";

import { pathFor } from "@/lib/seo";
import { DEFAULT_SORT, skinQueryString } from "@/lib/skins";

/** Long enough to type a number, short enough not to feel like waiting. */
export const PRICE_APPLY_DELAY_MS = 500;

const PATH = "/skins";

/**
 * The price range, applied as the buyer types — half a second after they stop, no
 * «Применить» to press. Still a GET form, so Enter (or a page without JS) submits it.
 */
export function SkinPriceFilter({ query, locale }: { query: SkinQuery; locale: string }) {
  const t = useTranslations("web.skins");
  const router = useRouter();
  const base = pathFor(locale, PATH);
  const [min, setMin] = useState(query.minUzs?.toString() ?? "");
  const [max, setMax] = useState(query.maxUzs?.toString() ?? "");
  const typed = useRef(false);

  useEffect(() => {
    if (!typed.current) return;
    const timer = setTimeout(() => {
      const bound = (v: string) => (v.trim() === "" ? undefined : Math.max(0, Number(v)));
      router.replace(base + skinQueryString(query, { minUzs: bound(min), maxUzs: bound(max) }), {
        scroll: false,
      });
    }, PRICE_APPLY_DELAY_MS);
    return () => {
      clearTimeout(timer);
    };
    // `query` and `base` describe the page this box sits on; only typing re-arms it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [min, max]);

  const input = (
    name: "min" | "max",
    value: string,
    set: (v: string) => void,
    placeholder: string,
  ) => (
    <input
      type="number"
      name={name}
      min={0}
      inputMode="numeric"
      placeholder={placeholder}
      value={value}
      onChange={(e) => {
        typed.current = true;
        set(e.target.value);
      }}
      className="border-border bg-background w-full rounded-lg border px-2 py-1.5 text-[13px]"
    />
  );

  return (
    <form method="get" action={base}>
      <p className="text-tx-mute mb-2 text-[12px] font-semibold uppercase">{t("price")}</p>
      {query.category && <input type="hidden" name="category" value={query.category} />}
      {query.weapon && <input type="hidden" name="weapon" value={query.weapon} />}
      {query.exterior && <input type="hidden" name="exterior" value={query.exterior} />}
      {query.rarity && <input type="hidden" name="rarity" value={query.rarity} />}
      {query.stattrak && <input type="hidden" name="stattrak" value="1" />}
      {query.q && <input type="hidden" name="q" value={query.q} />}
      {query.sort !== DEFAULT_SORT && <input type="hidden" name="sort" value={query.sort} />}
      <div className="flex items-center gap-2">
        {input("min", min, setMin, t("from"))}
        <span className="text-tx-dim">—</span>
        {input("max", max, setMax, t("to"))}
      </div>
    </form>
  );
}
