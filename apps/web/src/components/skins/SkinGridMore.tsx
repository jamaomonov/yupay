"use client";

import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import type { SkinItem, SkinQuery } from "@/lib/skins";

import { SkinCard } from "@/components/skins/SkinCard";
import { pathFor } from "@/lib/seo";
import { fetchSkinsPage, skinQueryString } from "@/lib/skins";

type Phase = "idle" | "loading" | "error";

interface SkinGridMoreProps {
  query: SkinQuery;
  /** The server page's `next_cursor`; the first batch this component fetches. */
  cursor: string;
  locale: string;
  /** Slugs already on the server page, so an overlapping batch never repeats a card. */
  shown: string[];
}

/**
 * The rest of the catalogue, appended under the server-rendered first page as the
 * reader nears the end — a spinner while a batch loads, a retry button if one fails.
 * Without JS the `<noscript>` link still walks the pages by cursor.
 */
export function SkinGridMore({ query, cursor: first, locale, shown }: SkinGridMoreProps) {
  const t = useTranslations("web.skins");
  const [items, setItems] = useState<SkinItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(first);
  const [phase, setPhase] = useState<Phase>("idle");
  const seen = useRef(new Set(shown));
  const busy = useRef(false);
  const sentinel = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    if (busy.current || cursor === null) return;
    busy.current = true;
    setPhase("loading");
    fetchSkinsPage(locale, { ...query, cursor })
      .then((page) => {
        const fresh = page.items.filter((i) => !seen.current.has(i.slug));
        for (const i of fresh) seen.current.add(i.slug);
        setItems((prev) => [...prev, ...fresh]);
        setCursor(page.next_cursor);
        setPhase("idle");
      })
      .catch(() => {
        setPhase("error");
      })
      .finally(() => {
        busy.current = false;
      });
  }, [cursor, locale, query]);

  useEffect(() => {
    const el = sentinel.current;
    if (!el || cursor === null || phase === "error") return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) load();
      },
      { rootMargin: "800px 0px" },
    );
    io.observe(el);
    return () => {
      io.disconnect();
    };
  }, [cursor, phase, load]);

  return (
    <>
      {items.length > 0 && (
        <ul className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {items.map((item) => (
            <li key={item.slug}>
              <SkinCard item={item} locale={locale} />
            </li>
          ))}
        </ul>
      )}
      <div ref={sentinel} aria-hidden className="h-px" />
      {phase === "loading" && (
        <div role="status" className="mt-6 flex justify-center">
          <Loader2 className="text-tx-dim h-6 w-6 animate-spin" aria-hidden />
          <span className="sr-only">{t("loading")}</span>
        </div>
      )}
      {phase === "error" && (
        <button
          type="button"
          onClick={load}
          className="border-border mx-auto mt-6 block w-fit rounded-xl border px-6 py-3 font-semibold"
        >
          {t("loadMore")}
        </button>
      )}
      <noscript>
        <Link
          href={pathFor(locale, "/skins") + skinQueryString(query, { cursor: first })}
          className="border-border mx-auto mt-6 block w-fit rounded-xl border px-6 py-3 font-semibold"
        >
          {t("loadMore")}
        </Link>
      </noscript>
    </>
  );
}
