"use client";

import { Eye, Zap } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { SkinFloatBar } from "./SkinFloatBar";

import type { SkinListing } from "@/lib/skins";

import { displayPrice, fetchSkinListings } from "@/lib/skins";

type State = { phase: "loading" } | { phase: "ready"; items: SkinListing[] };

const FIRST = 10;

/**
 * Live offers for one item. Loaded in the browser: the listings read is the
 * one catalogue call that can reach the supplier, and a page render must not
 * wait on it. When the API answers from its fallback the rows simply carry no
 * float/seed/inspect — nothing is said about it (owner rule: no service meta).
 */
export function SkinListings({ slug, locale }: { slug: string; locale: string }) {
  const t = useTranslations("web.skins");
  const [state, setState] = useState<State>({ phase: "loading" });
  const [all, setAll] = useState(false);

  useEffect(() => {
    let live = true;
    fetchSkinListings(slug)
      .then((r) => {
        if (live) setState({ phase: "ready", items: r.items });
      })
      .catch(() => {
        if (live) setState({ phase: "ready", items: [] });
      });
    return () => {
      live = false;
    };
  }, [slug]);

  if (state.phase === "loading") {
    return (
      <ul className="space-y-2">
        {[0, 1, 2].map((i) => (
          <li key={i} className="bg-muted h-16 animate-pulse rounded-xl" />
        ))}
      </ul>
    );
  }
  if (state.items.length === 0) {
    return <p className="text-tx-mute py-8 text-center">{t("noOffers")}</p>;
  }

  const shown = all ? state.items : state.items.slice(0, FIRST);
  return (
    <>
      <ul className="space-y-2">
        {shown.map((l) => (
          <li
            key={l.listing_id}
            className="border-border bg-card flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border p-3"
          >
            <span className="inline-flex items-center gap-1 rounded-md bg-emerald-500/15 px-2 py-0.5 text-[11px] font-semibold text-emerald-400">
              <Zap className="h-3 w-3" />
              {t("ready")}
            </span>
            {l.float_value !== null && (
              <div className="w-40">
                <div className="text-tx-dim mb-1 flex justify-between text-[11px]">
                  <span>{t("float")}</span>
                  <span className="font-mono">{l.float_value.toFixed(4)}</span>
                </div>
                <SkinFloatBar value={l.float_value} />
              </div>
            )}
            {l.paint_seed !== null && (
              <div className="text-[12px]">
                <span className="text-tx-dim">{t("seed")} </span>
                <span className="font-mono">{l.paint_seed}</span>
              </div>
            )}
            {l.stickers.length > 0 && (
              <div
                className="text-tx-dim min-w-0 flex-1 truncate text-[12px]"
                title={t("stickers")}
              >
                {l.stickers.map((s) => s.name).join(", ")}
              </div>
            )}
            <div className="ml-auto flex items-center gap-3">
              {l.inspect_url?.startsWith("steam://") && (
                <a
                  href={l.inspect_url}
                  className="text-tx-mute hover:text-foreground inline-flex items-center gap-1 text-[12px]"
                >
                  <Eye className="h-3.5 w-3.5" />
                  {t("inspect")}
                </a>
              )}
              <span className="font-mono text-[14px] font-bold">
                {displayPrice(locale, l.price_uzs, l.price_usd)}
              </span>
            </div>
          </li>
        ))}
      </ul>
      {!all && state.items.length > FIRST && (
        <button
          type="button"
          onClick={() => {
            setAll(true);
          }}
          className="border-border mx-auto mt-4 block rounded-xl border px-6 py-2.5 text-[14px] font-semibold"
        >
          {t("loadMore")}
        </button>
      )}
    </>
  );
}
